"""Incident storage using ClickHouse (replaces S3 JSON + DuckDB)."""

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone

from clickhouse_driver import Client

APP_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$|^[a-z0-9]$")


def _safe_json_loads(value: str, default):
    """Parse JSON with fallback to default on error."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _validate_app_id(app_id: str) -> bool:
    """Validate app_id format to prevent SQL injection."""
    if not app_id:
        return False
    return bool(APP_ID_PATTERN.match(app_id))


log = logging.getLogger("trace-rca-service")

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "clickhouse-cluster-client.clickhouse.svc.cluster.local")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "9000"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "default")

_thread_local = threading.local()


def _get_clickhouse() -> Client:
    """Get or create ClickHouse client (thread-local, safe for concurrent requests)."""
    if not hasattr(_thread_local, 'client'):
        _thread_local.client = Client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            user=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            database=CLICKHOUSE_DATABASE,
        )
    return _thread_local.client


def init_incidents_table():
    """Create incidents table if not exists."""
    client = _get_clickhouse()
    client.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            incident_id String,
            app_id String,
            created_at DateTime,
            time_window_start DateTime,
            time_window_end DateTime,
            stage1_ranking String,
            root_cause String,
            confidence_level String,
            analysis_summary String,
            total_traces UInt32,
            anomalous_traces UInt32,
            services Array(String),
            log_evidence String,
            status String
        )
        ENGINE = MergeTree()
        ORDER BY (created_at, app_id)
        TTL created_at + INTERVAL 90 DAY DELETE
        SETTINGS storage_policy = 'hot_cold'
    """)
    log.info("Incidents table initialized")


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
    """Save incident to ClickHouse. Returns incident_id."""
    incident_id = incident["incident_id"]
    app_id = incident.get("app_id") or ""
    time_window = incident.get("time_window", {})
    stage2 = incident.get("stage2_result") or {}
    trace_summary = incident.get("trace_summary", {})

    created_at = datetime.fromisoformat(incident["created_at"].replace("Z", "+00:00"))
    time_start = datetime.fromisoformat(time_window.get("start", created_at.isoformat()).replace("Z", "+00:00"))
    time_end = datetime.fromisoformat(time_window.get("end", created_at.isoformat()).replace("Z", "+00:00"))

    data = [(
        incident_id,
        app_id,
        created_at,
        time_start,
        time_end,
        json.dumps(incident.get("stage1_ranking", [])),
        json.dumps(stage2.get("root_cause", {})) if isinstance(stage2.get("root_cause"), dict) else str(stage2.get("root_cause", "")),
        stage2.get("confidence_level", ""),
        json.dumps(stage2.get("analysis", [])),
        trace_summary.get("total_traces", 0),
        trace_summary.get("anomalous_traces", 0),
        trace_summary.get("services", []),
        json.dumps(incident.get("log_evidence", [])),
        incident.get("status", "completed"),
    )]

    client = _get_clickhouse()
    client.execute("""
        INSERT INTO incidents (
            incident_id, app_id, created_at, time_window_start, time_window_end,
            stage1_ranking, root_cause, confidence_level, analysis_summary,
            total_traces, anomalous_traces, services, log_evidence, status
        ) VALUES
    """, data)

    log.info("Saved incident %s to ClickHouse", incident_id)
    return incident_id


def _row_to_incident(row: tuple, columns: list[str]) -> dict:
    """Convert ClickHouse row to incident dict."""
    data = dict(zip(columns, row))
    return {
        "incident_id": data["incident_id"],
        "app_id": data["app_id"] or None,
        "created_at": data["created_at"].isoformat() if data["created_at"] else None,
        "time_window": {
            "start": data["time_window_start"].isoformat() if data["time_window_start"] else None,
            "end": data["time_window_end"].isoformat() if data["time_window_end"] else None,
        },
        "stage1_ranking": _safe_json_loads(data["stage1_ranking"], []),
        "stage2_result": {
            "root_cause": _safe_json_loads(data["root_cause"], {}),
            "confidence_level": data["confidence_level"],
            "analysis": _safe_json_loads(data["analysis_summary"], []),
        },
        "trace_summary": {
            "total_traces": data["total_traces"],
            "anomalous_traces": data["anomalous_traces"],
            "services": list(data["services"]) if data["services"] else [],
        },
        "log_evidence": _safe_json_loads(data["log_evidence"], []),
        "status": data["status"],
    }


def list_incidents(app_id: str = None, app_ids: list[str] = None, limit: int = 100) -> list[dict]:
    """List incidents from ClickHouse (summary fields only).

    Args:
        app_id: Filter by single app_id (optional)
        app_ids: Filter by multiple app_ids (optional)
        limit: Max number of incidents to return (default 100)
    """
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

    limit = min(max(1, limit), 1000)

    query = f"""
        SELECT
            incident_id,
            app_id,
            created_at,
            time_window_start,
            time_window_end,
            stage1_ranking,
            root_cause,
            confidence_level,
            analysis_summary,
            total_traces,
            anomalous_traces,
            services,
            log_evidence,
            status
        FROM incidents
        {where_clause}
        ORDER BY created_at DESC
        LIMIT {limit}
    """

    client = _get_clickhouse()
    result, columns = client.execute(query, with_column_types=True)
    col_names = [c[0] for c in columns]

    return [_row_to_incident(row, col_names) for row in result]


def list_applications() -> list[str]:
    """List all unique app_ids from incidents."""
    query = """
        SELECT DISTINCT app_id
        FROM incidents
        WHERE app_id != ''
        ORDER BY app_id
    """
    client = _get_clickhouse()
    result = client.execute(query)
    return [row[0] for row in result]


def get_incident(incident_id: str, app_id: str = None) -> dict | None:
    """Get a single incident from ClickHouse."""
    where_parts = [f"incident_id = '{incident_id}'"]
    if app_id and _validate_app_id(app_id):
        where_parts.append(f"app_id = '{app_id}'")

    query = f"""
        SELECT
            incident_id,
            app_id,
            created_at,
            time_window_start,
            time_window_end,
            stage1_ranking,
            root_cause,
            confidence_level,
            analysis_summary,
            total_traces,
            anomalous_traces,
            services,
            log_evidence,
            status
        FROM incidents
        WHERE {' AND '.join(where_parts)}
        LIMIT 1
    """

    client = _get_clickhouse()
    result, columns = client.execute(query, with_column_types=True)

    if not result:
        return None

    col_names = [c[0] for c in columns]
    return _row_to_incident(result[0], col_names)
