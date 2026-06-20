"""
Step 1: Drift Detection
───────────────────────
Checks for data drift between current inference span data and the previous
training snapshot using PSI (Population Stability Index) on duration_ns,
and detects new API endpoints (service × operation combos).

Writes drift report to S3 and outputs XCom for downstream tasks.
Starts parent MLflow pipeline run when drift is detected.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

from tasks.s3_utils import (
    S3_BUCKET,
    DRIFT_WINDOW_MINUTES,
    read_parquet_from_s3,
    s3_path,
    list_s3_versions,
    write_json_to_s3,
)
from tasks.clickhouse_utils import load_recent_anomaly_data
from tasks.mlflow_utils import start_pipeline_run
from tasks.evidently_monitoring import SpanMonitoring, WorkspaceManager
from tasks.evidently_strategies import DriftTestSuiteStrategy, DataDriftStrategy, DataQualityStrategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("drift-detection")

PSI_THRESHOLD = float(os.getenv("PSI_THRESHOLD", "0.2"))
MIN_SAMPLE_COUNT = int(os.getenv("MIN_DRIFT_SAMPLES", "100"))
FORCE_DRIFT = os.getenv("FORCE_DRIFT", "false").lower() == "true"
NUM_BINS = 10

# Evidently feature flag and configuration
USE_EVIDENTLY = os.getenv("USE_EVIDENTLY", "true").lower() == "true"
RUN_DATA_QUALITY = os.getenv("RUN_DATA_QUALITY", "true").lower() == "true"
NUMERIC_FEATURES = ["duration_ns", "duration"]
CATEGORICAL_FEATURES = ["service", "operation"]
KNOWN_APPS = ["microservices-demo", "k8s-repo-application"]


def compute_psi(reference: np.ndarray, current: np.ndarray, bins: int = NUM_BINS) -> float:
    """Compute Population Stability Index between reference and current distributions."""
    breakpoints = np.quantile(reference, np.linspace(0, 1, bins + 1))
    breakpoints[0] = -np.inf
    breakpoints[-1] = np.inf

    ref_counts = np.histogram(reference, bins=breakpoints)[0].astype(float)
    cur_counts = np.histogram(current, bins=breakpoints)[0].astype(float)

    eps = 1e-6
    ref_pct = ref_counts / ref_counts.sum() + eps
    cur_pct = cur_counts / cur_counts.sum() + eps

    psi = np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct))
    return float(psi)


def find_latest_training_version() -> str | None:
    """Find the latest training data version in S3 using boto3."""
    versions = list_s3_versions("mlops/training-data/")
    version_names = []
    for v in versions:
        parts = v.rstrip("/").split("/")
        name = parts[-1]
        if name.startswith("v"):
            version_names.append(name)
    if not version_names:
        return None
    version_names.sort(reverse=True)
    return version_names[0]


def find_production_training_version() -> str | None:
    """Get training version from Production model in MLflow Registry.

    Tries in order:
    1. Model alias 'champion' (MLflow 2.9+ recommended)
    2. Model alias 'production' (alternative alias)
    3. Stage 'Production' (deprecated but backwards compatible)
    4. Fall back to latest S3 version
    """
    try:
        from mlflow.tracking import MlflowClient
        from tasks.mlflow_utils import setup_mlflow

        setup_mlflow()
        client = MlflowClient()
        model_name = "transformer-ae"
        prod_version = None

        # Try aliases first (MLflow 2.9+ recommended)
        for alias in ["champion", "production"]:
            try:
                prod_version = client.get_model_version_by_alias(model_name, alias)
                log.info("Found model via alias '%s'", alias)
                break
            except Exception:
                continue

        # Fall back to deprecated stages
        if prod_version is None:
            try:
                versions = client.get_latest_versions(model_name, stages=["Production"])
                if versions:
                    prod_version = versions[0]
                    log.info("Found model via stage 'Production'")
            except Exception:
                pass

        if prod_version is None:
            log.warning("No Production model found, falling back to latest")
            return find_latest_training_version()

        run = client.get_run(prod_version.run_id)
        version_id = run.data.tags.get("version_id") or run.data.params.get("version_id")

        if not version_id:
            log.warning("Production model has no version_id tag, falling back")
            return find_latest_training_version()

        log.info("Production baseline version_id: %s", version_id)
        return version_id

    except Exception as e:
        log.warning("Failed to get Production model: %s", e)
        return find_latest_training_version()


def write_xcom_and_return(version_id: str, drift_detected: bool,
                          mlflow_run_id: str | None, decision: str) -> str:
    """Write XCom to file AND return decision string for BranchPythonOperator."""
    xcom = {
        "version_id": version_id,
        "drift_detected": drift_detected,
        "mlflow_run_id": mlflow_run_id,
    }
    xcom_dir = "/airflow/xcom"
    os.makedirs(xcom_dir, exist_ok=True)
    with open(os.path.join(xcom_dir, "return.json"), "w") as f:
        json.dump(xcom, f)
    return decision


def load_app_baseline(app_id: str, version: str) -> pd.DataFrame:
    """Load baseline training data filtered by app_id."""
    full_df = read_parquet_from_s3(
        s3_path(f"mlops/training-data/{version}/train.parquet")
    )
    app_df = full_df[full_df["app_id"] == app_id]

    if app_df.empty:
        raise ValueError(f"No baseline data for app: {app_id}")

    return app_df


def compute_psi_for_app(ref_df: pd.DataFrame, cur_df: pd.DataFrame) -> float:
    """Compute PSI for single app (fallback when Evidently fails)."""
    ref_col = "duration_ns" if "duration_ns" in ref_df.columns else "duration"
    cur_col = "duration_ns" if "duration_ns" in cur_df.columns else "duration"
    return compute_psi(ref_df[ref_col].astype(float).values, cur_df[cur_col].astype(float).values)


def generate_quality_report_for_app(
    ref_df: pd.DataFrame,
    cur_df: pd.DataFrame,
    app_id: str,
    version_id: str,
    workspace_mgr: WorkspaceManager | None,
    s3_client,
) -> dict | None:
    """Run Evidently DataQuality report for a single app.

    Non-blocking observability — returns a small summary dict on success,
    or None on any failure. Never raises, never affects drift_detected.
    """
    try:
        monitor = SpanMonitoring(
            strategy=DataQualityStrategy(),
            numeric_features=NUMERIC_FEATURES,
            categorical_features=CATEGORICAL_FEATURES,
        )
        report_obj = monitor.execute(ref_df, cur_df)

        # Push to Evidently UI workspace (best-effort)
        if workspace_mgr:
            try:
                workspace_mgr.add_report(app_id, report_obj)
            except Exception as e:
                log.warning("Quality workspace push failed for %s: %s", app_id, e)

        # Upload HTML to S3 (best-effort)
        if s3_client:
            try:
                local_html = f"/tmp/quality_{app_id}_{version_id}.html"
                report_obj.save_html(local_html)
                with open(local_html, "rb") as f:
                    s3_client.put_object(
                        Bucket=S3_BUCKET,
                        Key=f"mlops/quality-reports/{version_id}/{app_id}/quality_report.html",
                        Body=f,
                        ContentType="text/html",
                    )
                log.info("Quality report saved for app: %s", app_id)
            except Exception as e:
                log.warning("Quality S3 upload failed for %s: %s", app_id, e)

        # Defensive summary extraction — Evidently schema may shift between versions
        summary = {"app_id": app_id, "report_uploaded": True}
        try:
            result = report_obj.as_dict()
            summary["metrics_count"] = len(result.get("metrics", []))
        except Exception:
            pass
        return summary
    except Exception as e:
        log.warning("DataQuality failed for app %s: %s", app_id, e)
        return None


def detect_drift_per_app(
    current_df: pd.DataFrame,
    prev_version: str,
    workspace_mgr: WorkspaceManager | None = None,
    version_id: str | None = None,
    s3_client=None,
) -> dict:
    """
    Detect drift for each app_id separately using Evidently.

    Returns:
        {
            "app_results": {app_id: drift_summary, ...},
            "drift_detected": bool (any app drifted),
            "drifted_apps": [app_ids that drifted],
        }
    """
    app_results = {}
    drifted_apps = []

    # Ensure app_id column exists
    if "app_id" not in current_df.columns:
        current_df = current_df.copy()
        current_df["app_id"] = "unknown"

    # Group by app_id
    for app_id, app_df in current_df.groupby("app_id"):
        log.info("Processing app: %s (%d rows)", app_id, len(app_df))

        # Skip unknown apps or apps with too few samples
        if app_id not in KNOWN_APPS:
            log.warning("Unknown app_id: %s, skipping", app_id)
            continue

        if len(app_df) < MIN_SAMPLE_COUNT:
            log.warning("App %s has too few samples (%d), skipping", app_id, len(app_df))
            app_results[app_id] = {"skipped": True, "reason": "insufficient_samples"}
            continue

        # Load reference data for this app
        try:
            ref_df = load_app_baseline(app_id, prev_version)
        except Exception as e:
            log.warning("No baseline for app %s: %s", app_id, e)
            app_results[app_id] = {"drift_detected": True, "reason": "no_baseline"}
            drifted_apps.append(app_id)
            continue

        # Run Evidently drift detection
        try:
            monitor = SpanMonitoring(
                strategy=DriftTestSuiteStrategy(),
                numeric_features=NUMERIC_FEATURES,
                categorical_features=CATEGORICAL_FEATURES,
            )

            # Check sample size
            if not monitor.check_sample_size(ref_df, app_df):
                log.warning("App %s: sample size too small for Evidently", app_id)
                psi = compute_psi_for_app(ref_df, app_df)
                app_results[app_id] = {"drift_detected": psi > PSI_THRESHOLD, "psi_fallback": psi}
                if psi > PSI_THRESHOLD:
                    drifted_apps.append(app_id)
                continue

            suite = monitor.execute(ref_df, app_df)
            summary = monitor.get_drift_summary(suite)

            # Add to workspace if available
            if workspace_mgr:
                workspace_mgr.add_test_suite(app_id, suite)

            app_results[app_id] = summary

            if summary.get("drift_detected"):
                drifted_apps.append(app_id)
                log.info("Drift detected for app: %s", app_id)

        except Exception as e:
            log.error("Evidently failed for app %s: %s", app_id, e)
            # Fallback to PSI for this app
            psi = compute_psi_for_app(ref_df, app_df)
            app_results[app_id] = {"drift_detected": psi > PSI_THRESHOLD, "psi_fallback": psi}
            if psi > PSI_THRESHOLD:
                drifted_apps.append(app_id)

        # DataQuality report — non-blocking observability layer
        if RUN_DATA_QUALITY and version_id:
            quality_summary = generate_quality_report_for_app(
                ref_df, app_df, app_id, version_id, workspace_mgr, s3_client
            )
            if quality_summary and app_id in app_results:
                app_results[app_id]["quality_summary"] = quality_summary

    return {
        "app_results": app_results,
        "drift_detected": len(drifted_apps) > 0,
        "drifted_apps": drifted_apps,
    }


def run():
    version_id = f"v{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    log.info("Drift detection starting, version_id=%s", version_id)

    # Check FORCE_DRIFT first - bypass all data checks for testing
    if FORCE_DRIFT:
        log.info("FORCE_DRIFT=true — forcing drift detection, skipping all checks")
        mlflow_run_id = start_pipeline_run(version_id)
        if mlflow_run_id:
            log.info("Started MLflow pipeline run: %s", mlflow_run_id)
        return write_xcom_and_return(version_id, True, mlflow_run_id, "trigger_retrain")

    window_minutes = DRIFT_WINDOW_MINUTES

    # Load current anomaly data from ClickHouse (replaces S3/DuckDB)
    try:
        current_df = load_recent_anomaly_data(window_minutes)
    except Exception as e:
        log.error("Failed to load data from ClickHouse: %s", e)
        return write_xcom_and_return(version_id, False, None, "no_retrain")

    if current_df.empty:
        log.error("No data in last %d mins — pipeline upstream may be broken, skipping retrain", window_minutes)
        return write_xcom_and_return(version_id, False, None, "no_retrain")

    if len(current_df) < MIN_SAMPLE_COUNT:
        log.warning("Insufficient samples (%d < %d) — skipping PSI", len(current_df), MIN_SAMPLE_COUNT)
        return write_xcom_and_return(version_id, False, None, "no_retrain")

    log.info("Current data: %d rows from last %d mins", len(current_df), window_minutes)

    prev_version = find_production_training_version()
    drift_detected = False
    psi_value = 0.0
    new_apis = []
    evidently_summary = {}
    per_app_results = {}
    drifted_apps = []
    use_evidently_this_run = USE_EVIDENTLY

    if prev_version is None:
        log.info("No previous training data found — first run, drift auto-detected")
        drift_detected = True
        per_app_results = {"all": {"reason": "first_run"}}
    else:
        log.info("Baseline version (Production): %s", prev_version)
        try:
            prev_df = read_parquet_from_s3(
                s3_path(f"mlops/training-data/{prev_version}/train.parquet")
            )
        except Exception as e:
            log.warning("Could not read baseline data: %s — treating as drift", e)
            drift_detected = True
            prev_df = None

        if prev_df is not None and not prev_df.empty:
            # Initialize workspace manager for Evidently UI (optional)
            workspace_mgr = None
            if os.getenv("EVIDENTLY_WORKSPACE"):
                try:
                    workspace_mgr = WorkspaceManager(os.getenv("EVIDENTLY_WORKSPACE"))
                except Exception as e:
                    log.warning("Could not init workspace: %s", e)

            # Pre-create S3 client once for per-app HTML uploads (drift + quality)
            import boto3
            shared_s3_client = boto3.client("s3", region_name=os.getenv("S3_REGION", "ap-southeast-1"))

            # Evidently-based drift detection (with feature flag)
            if use_evidently_this_run:
                try:
                    result = detect_drift_per_app(
                        current_df, prev_version, workspace_mgr,
                        version_id=version_id, s3_client=shared_s3_client,
                    )
                    drift_detected = result["drift_detected"]
                    per_app_results = result["app_results"]
                    drifted_apps = result["drifted_apps"]
                    evidently_summary = {
                        "method": "evidently",
                        "drifted_apps": drifted_apps,
                        "app_count": len(per_app_results),
                    }
                    log.info("Evidently per-app drift: detected=%s, apps=%s", drift_detected, drifted_apps)
                except Exception as e:
                    log.error("Evidently failed: %s, falling back to PSI", e)
                    use_evidently_this_run = False

            # PSI fallback (when USE_EVIDENTLY=false or Evidently failed)
            if not use_evidently_this_run:
                ref_duration = prev_df["duration_ns"].values if "duration_ns" in prev_df.columns else prev_df["duration"].values
                cur_duration = current_df["duration_ns"].values if "duration_ns" in current_df.columns else current_df["duration"].values

                psi_value = compute_psi(ref_duration.astype(float), cur_duration.astype(float))
                log.info("PSI(duration) = %.4f (threshold=%.2f)", psi_value, PSI_THRESHOLD)

                if psi_value > PSI_THRESHOLD:
                    drift_detected = True
                    log.info("Duration drift detected (PSI > threshold)")

                evidently_summary = {"method": "psi_fallback", "psi_value": psi_value, "psi_threshold": PSI_THRESHOLD}

            # New API check (always run, regardless of Evidently)
            prev_apis = set(zip(prev_df["service"], prev_df["operation"]))
            cur_apis = set(zip(current_df["service"], current_df["operation"]))
            new_api_set = cur_apis - prev_apis
            if new_api_set:
                new_apis = [{"service": s, "operation": o} for s, o in new_api_set]
                drift_detected = True
                log.info("New APIs detected: %d", len(new_apis))

            # Save per-app HTML reports to S3 (when Evidently was used)
            if use_evidently_this_run and per_app_results:
                try:
                    import boto3
                    s3_client = boto3.client("s3", region_name=os.getenv("S3_REGION", "ap-southeast-1"))
                    for app_id in per_app_results.keys():
                        if app_id in KNOWN_APPS:
                            try:
                                ref_app_df = load_app_baseline(app_id, prev_version)
                                cur_app_df = current_df[current_df["app_id"] == app_id]
                                if not cur_app_df.empty and not ref_app_df.empty:
                                    monitor = SpanMonitoring(
                                        strategy=DataDriftStrategy(),
                                        numeric_features=NUMERIC_FEATURES,
                                        categorical_features=CATEGORICAL_FEATURES,
                                    )
                                    report_obj = monitor.execute(ref_app_df, cur_app_df)
                                    local_html = f"/tmp/drift_{app_id}_{version_id}.html"
                                    report_obj.save_html(local_html)
                                    with open(local_html, "rb") as f:
                                        s3_client.put_object(
                                            Bucket=S3_BUCKET,
                                            Key=f"mlops/drift-reports/{version_id}/{app_id}/drift_report.html",
                                            Body=f,
                                            ContentType="text/html",
                                        )
                                    log.info("Saved HTML report for app: %s", app_id)
                            except Exception as e:
                                log.warning("Failed to save HTML report for %s: %s", app_id, e)
                except Exception as e:
                    log.warning("Failed to save HTML reports: %s", e)

    mlflow_run_id = None
    if drift_detected:
        mlflow_run_id = start_pipeline_run(version_id)
        if mlflow_run_id:
            log.info("Started MLflow pipeline run: %s", mlflow_run_id)

    report = {
        "version_id": version_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "drift_detected": drift_detected,
        "evidently_summary": evidently_summary,
        "per_app_results": per_app_results,
        "drifted_apps": drifted_apps,
        "psi_duration": psi_value,
        "psi_threshold": PSI_THRESHOLD,
        "new_apis": new_apis,
        "current_data_rows": len(current_df),
        "previous_version": prev_version,
        "mlflow_run_id": mlflow_run_id,
        "window_minutes": window_minutes,
    }

    report_key = f"mlops/drift-reports/{version_id}/drift_report.json"
    write_json_to_s3(report, report_key)
    log.info("Drift report saved to s3://%s/%s", S3_BUCKET, report_key)

    if drift_detected:
        log.info("Drift detected — proceeding with retraining")
        return write_xcom_and_return(version_id, True, mlflow_run_id, "trigger_retrain")
    else:
        log.info("No drift detected — skipping retraining")
        return write_xcom_and_return(version_id, False, mlflow_run_id, "no_retrain")


if __name__ == "__main__":
    run()
