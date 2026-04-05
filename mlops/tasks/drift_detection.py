"""
Step 1: Drift Detection
───────────────────────
Checks for data drift between current inference span data and the previous
training snapshot using PSI (Population Stability Index) on duration_ns,
and detects new API endpoints (service × operation combos).

Writes drift report to S3 and outputs XCom for downstream tasks.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from tasks.s3_utils import (
    S3_BUCKET,
    get_duckdb_connection,
    read_parquet_from_s3,
    s3_path,
    list_s3_keys,
    list_s3_versions,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("drift-detection")

PSI_THRESHOLD = float(os.getenv("PSI_THRESHOLD", "0.2"))
NUM_BINS = 10


def compute_psi(reference: np.ndarray, current: np.ndarray, bins: int = NUM_BINS) -> float:
    """Compute Population Stability Index between reference and current distributions."""
    # Use reference quantiles as bin edges
    breakpoints = np.quantile(reference, np.linspace(0, 1, bins + 1))
    breakpoints[0] = -np.inf
    breakpoints[-1] = np.inf

    ref_counts = np.histogram(reference, bins=breakpoints)[0].astype(float)
    cur_counts = np.histogram(current, bins=breakpoints)[0].astype(float)

    # Normalize to proportions, add small epsilon to avoid log(0)
    eps = 1e-6
    ref_pct = ref_counts / ref_counts.sum() + eps
    cur_pct = cur_counts / cur_counts.sum() + eps

    psi = np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct))
    return float(psi)


def find_latest_training_version() -> str | None:
    """Find the latest training data version in S3 using boto3."""
    # List version directories under mlops/training-data/
    versions = list_s3_versions("mlops/training-data/")
    # Filter for version dirs and extract version name
    version_names = []
    for v in versions:
        parts = v.rstrip("/").split("/")
        name = parts[-1]
        if name.startswith("v"):
            version_names.append(name)
    if not version_names:
        return None
    # Sort descending (lexicographic works for vYYYYMMDD-HHMMSS format)
    version_names.sort(reverse=True)
    return version_names[0]


def run():
    version_id = f"v{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    log.info("Drift detection starting, version_id=%s", version_id)

    # Read current inference data using explicit file list (avoids DuckDB glob on many files)
    try:
        keys = list_s3_keys("anomalies/data.parquet/")
        parquet_files = [f"s3://{S3_BUCKET}/{k}" for k in keys if k.endswith(".parquet")]
        if not parquet_files:
            log.error("No parquet files found in S3")
            sys.exit(1)
        log.info("Found %d parquet files to read", len(parquet_files))
        file_list_sql = ", ".join(f"'{f}'" for f in parquet_files)
        con = get_duckdb_connection()
        current_df = con.execute(f"""
            SELECT * FROM read_parquet([{file_list_sql}], hive_partitioning=1, union_by_name=1)
        """).fetchdf()
        con.close()
    except Exception as e:
        log.error("Failed to read current data from S3: %s", e)
        sys.exit(1)

    if current_df.empty:
        log.error("No current inference data found in S3")
        sys.exit(1)

    log.info("Current data: %d rows", len(current_df))

    # Find previous training data
    prev_version = find_latest_training_version()
    drift_detected = False
    psi_value = 0.0
    new_apis = []

    if prev_version is None:
        log.info("No previous training data found — first run, drift auto-detected")
        drift_detected = True
    else:
        log.info("Previous training version: %s", prev_version)
        try:
            prev_df = read_parquet_from_s3(
                s3_path(f"mlops/training-data/{prev_version}/train.parquet")
            )
        except Exception as e:
            log.warning("Could not read previous data: %s — treating as drift", e)
            drift_detected = True
            prev_df = None

        if prev_df is not None and not prev_df.empty:
            # PSI on duration_ns
            ref_duration = prev_df["duration_ns"].values if "duration_ns" in prev_df.columns else prev_df["duration"].values
            cur_duration = current_df["duration_ns"].values if "duration_ns" in current_df.columns else current_df["duration"].values

            psi_value = compute_psi(ref_duration.astype(float), cur_duration.astype(float))
            log.info("PSI(duration) = %.4f (threshold=%.2f)", psi_value, PSI_THRESHOLD)

            if psi_value > PSI_THRESHOLD:
                drift_detected = True
                log.info("Duration drift detected (PSI > threshold)")

            # New API check
            prev_apis = set(zip(prev_df["service"], prev_df["operation"]))
            cur_apis = set(zip(current_df["service"], current_df["operation"]))
            new_api_set = cur_apis - prev_apis
            if new_api_set:
                new_apis = [{"service": s, "operation": o} for s, o in new_api_set]
                drift_detected = True
                log.info("New APIs detected: %d", len(new_apis))

    # Save drift report
    report = {
        "version_id": version_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "drift_detected": drift_detected,
        "psi_duration": psi_value,
        "psi_threshold": PSI_THRESHOLD,
        "new_apis": new_apis,
        "current_data_rows": len(current_df),
        "previous_version": prev_version,
    }

    report_path = s3_path(f"mlops/drift-reports/{version_id}/drift_report.json")
    con = get_duckdb_connection()
    con.execute(f"""
        COPY (SELECT '{json.dumps(report)}' AS report)
        TO '{report_path}' (FORMAT CSV, HEADER false);
    """)
    con.close()
    log.info("Drift report saved to %s", report_path)

    # Write XCom output for Airflow
    xcom = {
        "version_id": version_id,
        "drift_detected": drift_detected,
    }
    xcom_dir = "/airflow/xcom"
    os.makedirs(xcom_dir, exist_ok=True)
    with open(os.path.join(xcom_dir, "return.json"), "w") as f:
        json.dump(xcom, f)

    if not drift_detected:
        log.info("No drift detected — downstream tasks will be skipped")
    else:
        log.info("Drift detected — proceeding with retraining")


if __name__ == "__main__":
    run()
