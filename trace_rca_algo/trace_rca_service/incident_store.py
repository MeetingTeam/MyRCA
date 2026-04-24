"""Incident storage using S3 JSON files, queryable via DuckDB."""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import boto3


# Validate app_id format: lowercase alphanumeric with hyphens, max 63 chars
APP_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$|^[a-z0-9]$")


def _validate_app_id(app_id: str) -> bool:
    """Validate app_id format to prevent SQL injection."""
    if not app_id:
        return False
    return bool(APP_ID_PATTERN.match(app_id))

log = logging.getLogger("trace-rca-service")

S3_BUCKET = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
RCA_RESULTS_PREFIX = "rca-results"

_s3_client = None


def _get_s3():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            region_name=S3_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        )
    return _s3_client


def build_incident(ranking, llm_result, logs, traces, start_dt, end_dt, app_id: str = None):
    """Assemble an incident dict from RCA pipeline outputs."""
    anomalous = [t for t in traces if t.get("label") == 1]
    all_services = set()
    for t in traces:
        all_services.update(t.get("services", []))

    return {
        "incident_id": str(uuid.uuid4()),
        "app_id": app_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "time_window": {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
        },
        "stage1_ranking": [
            {"service": svc, "score": round(score, 4)}
            for svc, score in ranking
        ],
        "stage2_result": llm_result,
        "log_evidence": logs,
        "trace_summary": {
            "total_traces": len(traces),
            "anomalous_traces": len(anomalous),
            "services": sorted(all_services),
        },
        "status": "completed",
    }


def save_incident(incident: dict) -> str:
    """Upload incident JSON to S3. Returns incident_id.

    Storage path: rca-results/app_id={id}/{incident_id}.json
    For incidents without app_id, stores at rca-results/{incident_id}.json (legacy)
    """
    incident_id = incident["incident_id"]
    app_id = incident.get("app_id")

    if app_id:
        key = f"{RCA_RESULTS_PREFIX}/app_id={app_id}/{incident_id}.json"
    else:
        key = f"{RCA_RESULTS_PREFIX}/{incident_id}.json"

    _get_s3().put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(incident, default=str).encode("utf-8"),
        ContentType="application/json",
    )
    log.info("Saved incident %s to s3://%s/%s", incident_id, S3_BUCKET, key)
    return incident_id


def list_incidents(db_con, app_id: str = None, app_ids: list[str] = None, limit: int = 100) -> list[dict]:
    """List incidents from S3 via DuckDB (summary fields only).

    Args:
        db_con: DuckDB connection
        app_id: Filter by single app_id (optional)
        app_ids: Filter by multiple app_ids (optional)
        limit: Max number of incidents to return (default 100)
    """
    try:
        # Use list of glob patterns to match both legacy (root-level) and app-partitioned paths
        legacy_glob = f"s3://{S3_BUCKET}/{RCA_RESULTS_PREFIX}/*.json"
        partitioned_glob = f"s3://{S3_BUCKET}/{RCA_RESULTS_PREFIX}/app_id=*/*.json"
        glob_pattern = f"['{legacy_glob}', '{partitioned_glob}']"

        # Build WHERE clause for app_id filtering (with validation to prevent SQL injection)
        where_clause = ""
        if app_id:
            if not _validate_app_id(app_id):
                log.warning("Invalid app_id format: %s", app_id)
                return []
            where_clause = f"WHERE app_id = '{app_id}'"
        elif app_ids:
            valid_ids = [a for a in app_ids if _validate_app_id(a)]
            if not valid_ids:
                log.warning("No valid app_ids provided")
                return []
            app_ids_str = ", ".join(f"'{a}'" for a in valid_ids)
            where_clause = f"WHERE app_id IN ({app_ids_str})"

        # Clamp limit to prevent abuse
        limit = min(max(1, limit), 1000)

        query = f"""
            SELECT
                incident_id::VARCHAR AS incident_id,
                app_id,
                created_at,
                time_window,
                stage2_result.root_cause AS root_cause,
                stage2_result.confidence_level AS confidence_level,
                stage1_ranking[1].service AS top_service,
                stage1_ranking[1].score AS top_score,
                trace_summary,
                status
            FROM read_json_auto('{glob_pattern}')
            {where_clause}
            ORDER BY created_at DESC
            LIMIT {limit}
        """
        df = db_con.cursor().execute(query).fetchdf()
        return json.loads(df.to_json(orient="records"))
    except Exception as e:
        log.warning("Failed to list incidents: %s", e)
        return []


def list_applications(db_con) -> list[str]:
    """List all unique app_ids from incidents."""
    try:
        legacy_glob = f"s3://{S3_BUCKET}/{RCA_RESULTS_PREFIX}/*.json"
        partitioned_glob = f"s3://{S3_BUCKET}/{RCA_RESULTS_PREFIX}/app_id=*/*.json"
        glob_pattern = f"['{legacy_glob}', '{partitioned_glob}']"
        query = f"""
            SELECT DISTINCT app_id
            FROM read_json_auto('{glob_pattern}')
            WHERE app_id IS NOT NULL
            ORDER BY app_id
        """
        df = db_con.cursor().execute(query).fetchdf()
        return df["app_id"].tolist()
    except Exception as e:
        log.warning("Failed to list applications: %s", e)
        return []


def get_incident(db_con, incident_id: str, app_id: str = None) -> dict | None:
    """Read a single incident from S3.

    Searches:
    1. If app_id provided: rca-results/app_id={app_id}/{incident_id}.json
    2. New path pattern: rca-results/app_id=*/{incident_id}.json (via S3 list)
    3. Legacy path: rca-results/{incident_id}.json
    """
    s3 = _get_s3()

    # Try app_id-specific path first if provided
    if app_id and _validate_app_id(app_id):
        try:
            key = f"{RCA_RESULTS_PREFIX}/app_id={app_id}/{incident_id}.json"
            obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
            return json.loads(obj["Body"].read())
        except s3.exceptions.NoSuchKey:
            pass

    # Search for incident in app-partitioned paths
    try:
        prefix = f"{RCA_RESULTS_PREFIX}/app_id="
        response = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
        for obj_meta in response.get("Contents", []):
            if obj_meta["Key"].endswith(f"/{incident_id}.json"):
                obj = s3.get_object(Bucket=S3_BUCKET, Key=obj_meta["Key"])
                return json.loads(obj["Body"].read())
    except Exception as e:
        log.warning("Error searching app-partitioned incidents: %s", e)

    # Try legacy path
    try:
        key = f"{RCA_RESULTS_PREFIX}/{incident_id}.json"
        obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
        return json.loads(obj["Body"].read())
    except s3.exceptions.NoSuchKey:
        return None
    except Exception as e:
        log.warning("Failed to get incident %s: %s", incident_id, e)
        return None
