"""
Step 4: Evaluation
──────────────────
Downloads model artifacts + test data from S3, runs inference,
computes anomaly scores, calculates p99 threshold from non-error spans,
and logs metrics to MLflow.

Reuses logic from model/transformer_ae/evaluate.py.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

import boto3
import joblib
import mlflow
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from transformer_ae.model import TransformerAutoencoder
from transformer_ae.evaluate import preprocess_test_df, build_sequences
from common.util import map_status_group
from tasks.s3_utils import read_parquet_from_s3, s3_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("evaluation")

SEQ_LEN = 20


def run():
    version_id = os.getenv("VERSION_ID")
    if not version_id:
        log.error("VERSION_ID not set")
        sys.exit(1)

    log.info("Evaluation starting, version_id=%s", version_id)

    mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow.mlflow.svc.cluster.local:5000")
    mlflow.set_tracking_uri(mlflow_uri)
    mlflow.set_experiment("transformer-ae-training")

    s3_client = boto3.client("s3", region_name=os.getenv("S3_REGION", "ap-southeast-1"))
    bucket = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")
    local_dir = "/tmp/mlops_eval"
    os.makedirs(local_dir, exist_ok=True)

    # Download model artifacts
    model_prefix = f"mlops/models/{version_id}"
    model_local = os.path.join(local_dir, "model.pth")
    enc_local = os.path.join(local_dir, "encoders.pkl")
    scl_local = os.path.join(local_dir, "scalers.pkl")

    s3_client.download_file(bucket, f"{model_prefix}/model.pth", model_local)
    s3_client.download_file(bucket, f"{model_prefix}/encoders.pkl", enc_local)
    s3_client.download_file(bucket, f"{model_prefix}/scalers.pkl", scl_local)

    encoders = joblib.load(enc_local)
    scalers = joblib.load(scl_local)

    # Download test data
    test_df = read_parquet_from_s3(s3_path(f"mlops/training-data/{version_id}/test.parquet"))
    log.info("Test data: %d rows", len(test_df))

    # Rename columns if needed (S3 output uses snake_case)
    rename_map = {
        "trace_id": "traceId", "span_id": "spanId", "parent_span_id": "parentSpanId",
    }
    for old, new in rename_map.items():
        if old in test_df.columns and new not in test_df.columns:
            test_df[new] = test_df[old]

    if "duration_ns" in test_df.columns and "duration" not in test_df.columns:
        test_df["duration"] = test_df["duration_ns"]

    # Preprocess test data with fitted encoders/scalers
    test_df = preprocess_test_df(test_df, encoders, scalers)

    metric_cols = ["duration"]
    services, parent_services, operations, parent_ops, statuses, metrics_x, row_idx = build_sequences(
        test_df, SEQ_LEN, metric_cols, stride=2
    )

    if len(services) == 0:
        log.error("No sequences built from test data")
        sys.exit(1)

    log.info("Built %d test sequences", len(services))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model = TransformerAutoencoder(
        service_vocab=encoders["service"].get_unknown_index() + 1,
        op_vocab=encoders["operation"].get_unknown_index() + 1,
        status_vocab=6,
        metrics_feature_num=len(metric_cols),
    ).to(device)

    model.load_state_dict(torch.load(model_local, map_location=device))
    model.eval()

    dataset = TensorDataset(
        torch.LongTensor(services),
        torch.LongTensor(parent_services),
        torch.LongTensor(operations),
        torch.LongTensor(parent_ops),
        torch.LongTensor(statuses),
        torch.FloatTensor(metrics_x),
        torch.LongTensor(row_idx),
    )
    loader = DataLoader(dataset, batch_size=64, shuffle=False)

    criterion = nn.MSELoss(reduction="none")
    test_df["anomaly_score"] = np.nan

    with torch.no_grad():
        for s, ps, op, pop, h, x, row_ids in loader:
            s, ps, op, pop, h, x = (
                s.to(device), ps.to(device), op.to(device),
                pop.to(device), h.to(device), x.to(device),
            )

            recon = model(s, ps, op, pop, h, x)
            timestep_loss = criterion(recon, x).sum(dim=2).cpu().numpy()
            row_ids_np = row_ids.numpy()

            for b in range(len(row_ids_np)):
                for t_idx in range(SEQ_LEN):
                    row = row_ids_np[b, t_idx]
                    metric = x[b, t_idx]
                    if row == -1 or metric == 0:
                        continue

                    score = float(timestep_loss[b, t_idx])

                    if test_df.at[row, "span_status"] == 2 or test_df.at[row, "http_status"] == 5:
                        score += 1000

                    if np.isnan(test_df.at[row, "anomaly_score"]):
                        test_df.at[row, "anomaly_score"] = score
                    else:
                        test_df.at[row, "anomaly_score"] = max(test_df.at[row, "anomaly_score"], score)

    scored_df = test_df.dropna(subset=["anomaly_score"])
    log.info("Scored %d / %d test spans", len(scored_df), len(test_df))

    # Calculate p99 threshold from non-error (normal) spans
    normal_mask = (scored_df["span_status"] != 2) & (scored_df["http_status"] != 5)
    normal_scores = scored_df.loc[normal_mask, "anomaly_score"].values

    if len(normal_scores) == 0:
        log.warning("No normal spans found — using overall p99")
        normal_scores = scored_df["anomaly_score"].values

    p99_threshold = float(np.percentile(normal_scores, 99))
    mean_score = float(scored_df["anomaly_score"].mean())

    log.info("p99_threshold=%.6f, mean_score=%.6f, test_samples=%d", p99_threshold, mean_score, len(scored_df))

    # Log to MLflow
    with mlflow.start_run(run_name=f"eval-{version_id}"):
        mlflow.log_params({"version_id": version_id, "seq_len": SEQ_LEN})
        mlflow.log_metrics({
            "p99_threshold": p99_threshold,
            "mean_score": mean_score,
            "test_samples": len(scored_df),
            "normal_samples": int(normal_mask.sum()),
        })

    # Save metadata.json
    metadata = {
        "version": version_id,
        "threshold": p99_threshold,
        "model_s3_path": f"s3://{bucket}/{model_prefix}/",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mean_score": mean_score,
        "test_samples": len(scored_df),
    }

    metadata_local = os.path.join(local_dir, "metadata.json")
    with open(metadata_local, "w") as f:
        json.dump(metadata, f, indent=2)

    s3_client.upload_file(metadata_local, bucket, f"{model_prefix}/metadata.json")
    log.info("Metadata saved to s3://%s/%s/metadata.json", bucket, model_prefix)

    # Write XCom
    xcom = {
        "version_id": version_id,
        "p99_threshold": p99_threshold,
        "mean_score": mean_score,
        "model_s3_path": f"s3://{bucket}/{model_prefix}/",
    }
    xcom_dir = "/airflow/xcom"
    os.makedirs(xcom_dir, exist_ok=True)
    with open(os.path.join(xcom_dir, "return.json"), "w") as f:
        json.dump(xcom, f)

    log.info("Evaluation complete")


if __name__ == "__main__":
    run()
