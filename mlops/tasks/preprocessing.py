"""
Step 2: Preprocessing
─────────────────────
Reads raw span data from S3, applies encoding/scaling (reusing logic from
model/transformer_ae/train.py:preprocess_df), splits 70/30, and saves
train.parquet + test.parquet + encoders/scalers to S3.
"""

import json
import logging
import os
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from common.safe_label_encoder import SafeLabelEncoder
from common.util import map_status_group
from tasks.s3_utils import get_duckdb_connection, read_parquet_from_s3, write_parquet_to_s3, s3_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("preprocessing")


def preprocess_df(df):
    """Encode and scale features. Mirrors model/transformer_ae/train.py:preprocess_df."""
    df["http_status"] = df["http_status"].astype(int).apply(map_status_group)

    encoders = {}
    for col in ["service", "operation"]:
        encoder = SafeLabelEncoder()
        df[col] = encoder.fit_transform(df[col].astype(str))
        encoders[col] = encoder

    scalers = {}
    for col in ["duration"]:
        scaler = StandardScaler()
        df[col] = scaler.fit_transform(df[[col]])
        scalers[col] = scaler

    span_to_op = dict(zip(df["spanId"], df["operation"]))
    op_unknown = encoders["operation"].get_unknown_index()
    df["parent_op"] = df["parentSpanId"].map(span_to_op).fillna(op_unknown).astype(int)

    span_to_service = dict(zip(df["spanId"], df["service"]))
    sc_unknown = encoders["service"].get_unknown_index()
    df["parent_service"] = df["parentSpanId"].map(span_to_service).fillna(sc_unknown).astype(int)

    return df, encoders, scalers


def run():
    # Read version_id from XCom (passed via env by KubernetesPodOperator)
    version_id = os.getenv("VERSION_ID")
    if not version_id:
        log.error("VERSION_ID not set")
        sys.exit(1)

    log.info("Preprocessing starting, version_id=%s", version_id)

    # Read raw span data from inference output
    try:
        df = read_parquet_from_s3(s3_path("anomalies/data.parquet/**/*.parquet"))
    except Exception as e:
        log.error("Failed to read span data: %s", e)
        sys.exit(1)

    log.info("Raw data: %d rows", len(df))

    # Ensure required columns exist — map column names if needed
    if "duration_ns" in df.columns and "duration" not in df.columns:
        df["duration"] = df["duration_ns"]

    required = ["service", "operation", "http_status", "duration", "spanId", "parentSpanId",
                 "traceId", "startTime", "span_status"]
    # Use 'trace_id' → 'traceId' etc. if needed (S3 output uses snake_case)
    rename_map = {
        "trace_id": "traceId", "span_id": "spanId", "parent_span_id": "parentSpanId",
        "start_time": "startTime", "timestamp": "startTime",
    }
    for old, new in rename_map.items():
        if old in df.columns and new not in df.columns:
            df[new] = df[old]

    missing = [c for c in required if c not in df.columns]
    if missing:
        log.error("Missing columns: %s. Available: %s", missing, list(df.columns))
        sys.exit(1)

    # Save raw duration before scaling
    df["duration_ns"] = df["duration"].copy()

    # Preprocess
    df, encoders, scalers = preprocess_df(df)

    # Shuffle and split 70/30
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)
    split_idx = int(len(df) * 0.7)
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]

    log.info("Split: train=%d, test=%d", len(train_df), len(test_df))

    # Save to S3
    base = f"mlops/training-data/{version_id}"
    write_parquet_to_s3(train_df, s3_path(f"{base}/train.parquet"))
    write_parquet_to_s3(test_df, s3_path(f"{base}/test.parquet"))

    # Save encoders and scalers as pickle to local, then upload via boto3
    import boto3
    local_dir = "/tmp/mlops_artifacts"
    os.makedirs(local_dir, exist_ok=True)

    enc_path = os.path.join(local_dir, "encoders.pkl")
    scl_path = os.path.join(local_dir, "scalers.pkl")
    joblib.dump(encoders, enc_path)
    joblib.dump(scalers, scl_path)

    s3_client = boto3.client("s3", region_name=os.getenv("S3_REGION", "ap-southeast-1"))
    bucket = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")

    for local, key in [
        (enc_path, f"{base}/encoders.pkl"),
        (scl_path, f"{base}/scalers.pkl"),
    ]:
        s3_client.upload_file(local, bucket, key)
        log.info("Uploaded %s", key)

    # Write XCom
    xcom = {
        "version_id": version_id,
        "train_path": s3_path(f"{base}/train.parquet"),
        "test_path": s3_path(f"{base}/test.parquet"),
        "train_rows": len(train_df),
        "test_rows": len(test_df),
    }
    xcom_dir = "/airflow/xcom"
    os.makedirs(xcom_dir, exist_ok=True)
    with open(os.path.join(xcom_dir, "return.json"), "w") as f:
        json.dump(xcom, f)

    log.info("Preprocessing complete")


if __name__ == "__main__":
    run()
