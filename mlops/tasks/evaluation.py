"""
Step 4: Evaluation
──────────────────
Downloads model artifacts + test data from S3, runs inference,
computes anomaly scores, calculates p99 threshold from non-error spans,
and logs metrics to MLflow.

Supports:
- S3 output for AWS Batch XCom replacement
- Nested MLflow runs under parent pipeline run
- Ends parent pipeline run (final task in pipeline)
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

import boto3
import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import precision_recall_curve
from torch.utils.data import DataLoader, TensorDataset

from transformer_ae.model import TransformerAutoencoder
from transformer_ae.evaluate import preprocess_test_df, build_sequences
from common.util import map_status_group
from tasks.s3_utils import read_parquet_from_s3, s3_path
from tasks.mlflow_utils import setup_mlflow, start_nested_run, end_pipeline_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("evaluation")

SEQ_LEN = 20


def write_batch_output(s3_client, bucket, version_id: str, output_data: dict):
    """Write output to S3 for Airflow XCom replacement (Batch jobs)."""
    s3_client.put_object(
        Bucket=bucket,
        Key=f"mlops/batch-outputs/{version_id}/evaluate_output.json",
        Body=json.dumps(output_data),
        ContentType="application/json",
    )
    log.info("Batch output written to S3: mlops/batch-outputs/%s/evaluate_output.json", version_id)


def compute_classification_metrics(scored_df: pd.DataFrame) -> dict:
    """Compute F1, precision, recall using is_anomaly as ground truth."""
    if "is_anomaly" not in scored_df.columns:
        log.warning("No 'is_anomaly' column found, skipping classification metrics")
        return {}

    y_true = scored_df["is_anomaly"].astype(bool).values
    y_score = scored_df["anomaly_score"].values

    prec, rec, thresholds = precision_recall_curve(y_true, y_score)
    f1 = 2 * (prec * rec) / (prec + rec + 1e-9)
    best_idx = np.argmax(f1)

    best_threshold = float(thresholds[best_idx]) if best_idx < len(thresholds) else float(thresholds[-1])
    best_f1 = float(f1[best_idx])
    best_precision = float(prec[best_idx])
    best_recall = float(rec[best_idx])

    log.info("Classification metrics: threshold=%.6f, F1=%.4f, precision=%.4f, recall=%.4f",
             best_threshold, best_f1, best_precision, best_recall)

    return {
        "best_threshold": best_threshold,
        "f1_score": best_f1,
        "precision": best_precision,
        "recall": best_recall,
    }


def run():
    version_id = os.getenv("VERSION_ID")
    if not version_id:
        log.error("VERSION_ID not set")
        sys.exit(1)

    parent_run_id = os.getenv("MLFLOW_PARENT_RUN_ID", "").strip() or None
    log.info("Evaluation starting, version_id=%s, parent_run_id=%s", version_id, parent_run_id)

    s3_client = boto3.client("s3", region_name=os.getenv("S3_REGION", "ap-southeast-1"))
    bucket = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")
    local_dir = "/tmp/mlops_eval"
    os.makedirs(local_dir, exist_ok=True)

    model_prefix = f"mlops/models/{version_id}"
    model_local = os.path.join(local_dir, "model.pth")
    enc_local = os.path.join(local_dir, "encoders.pkl")
    scl_local = os.path.join(local_dir, "scalers.pkl")

    s3_client.download_file(bucket, f"{model_prefix}/model.pth", model_local)
    s3_client.download_file(bucket, f"{model_prefix}/encoders.pkl", enc_local)
    s3_client.download_file(bucket, f"{model_prefix}/scalers.pkl", scl_local)

    encoders = joblib.load(enc_local)
    scalers = joblib.load(scl_local)

    external_test_path = "mlops/external-datasets/mt-test-data.parquet"
    test_df = read_parquet_from_s3(s3_path(external_test_path))
    log.info("Using external test dataset: %s (%d rows)", external_test_path, len(test_df))

    # Compute eval dataset stats for MLflow tracking
    eval_dataset_stats = {
        "eval_data_path": s3_path(external_test_path),
        "eval_data_rows": len(test_df),
        "eval_data_source": "external_fixed",
        "eval_data_version": "mt-test-data-v1",
    }

    if "app_id" in test_df.columns:
        app_counts = test_df["app_id"].value_counts().head(10).to_dict()
        eval_dataset_stats["app_distribution"] = {str(k): int(v) for k, v in app_counts.items()}
        eval_dataset_stats["num_apps"] = int(test_df["app_id"].nunique())

    for col in ["startTime", "timestamp", "start_time"]:
        if col in test_df.columns:
            try:
                eval_dataset_stats["data_start_time"] = str(pd.to_datetime(test_df[col].min()))
                eval_dataset_stats["data_end_time"] = str(pd.to_datetime(test_df[col].max()))
            except Exception:
                pass
            break

    log.info("Eval dataset stats: %d rows, source=%s",
             eval_dataset_stats["eval_data_rows"], eval_dataset_stats["eval_data_source"])

    rename_map = {
        "trace_id": "traceId", "span_id": "spanId", "parent_span_id": "parentSpanId",
    }
    for old, new in rename_map.items():
        if old in test_df.columns and new not in test_df.columns:
            test_df[new] = test_df[old]

    if "duration_ns" in test_df.columns and "duration" not in test_df.columns:
        test_df["duration"] = test_df["duration_ns"]

    test_df = preprocess_test_df(test_df, encoders, scalers)

    metric_cols = ["duration"]
    apps, services, parent_services, operations, parent_ops, statuses, metrics_x, row_idx = build_sequences(
        test_df, SEQ_LEN, metric_cols, stride=2
    )

    if len(services) == 0:
        log.error("No sequences built from test data")
        sys.exit(1)

    log.info("Built %d test sequences", len(services))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log.info("Using device: %s", device)

    model = TransformerAutoencoder(
        service_vocab=encoders["service"].get_unknown_index() + 1,
        op_vocab=encoders["operation"].get_unknown_index() + 1,
        status_vocab=6,
        app_vocab=encoders["app_id"].get_unknown_index() + 1,
        metrics_feature_num=len(metric_cols),
    ).to(device)

    model.load_state_dict(torch.load(model_local, map_location=device))
    model.eval()

    dataset = TensorDataset(
        torch.LongTensor(apps),
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
        for a, s, ps, op, pop, h, x, row_ids in loader:
            a, s, ps, op, pop, h, x = (
                a.to(device), s.to(device), ps.to(device), op.to(device),
                pop.to(device), h.to(device), x.to(device),
            )

            recon = model(s, ps, op, pop, h, a, x)
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

    classification_metrics = compute_classification_metrics(scored_df)

    normal_mask = (scored_df["span_status"] != 2) & (scored_df["http_status"] != 5)
    normal_scores = scored_df.loc[normal_mask, "anomaly_score"].values

    if len(normal_scores) == 0:
        log.warning("No normal spans found — using overall p99")
        normal_scores = scored_df["anomaly_score"].values

    p99_threshold = float(np.percentile(normal_scores, 99))
    mean_score = float(scored_df["anomaly_score"].mean())

    log.info("p99_threshold=%.6f, mean_score=%.6f, test_samples=%d", p99_threshold, mean_score, len(scored_df))

    mlflow_run = start_nested_run(parent_run_id, f"eval-{version_id}")

    if mlflow_run:
        import mlflow
        try:
            # Tags (searchable in MLflow UI)
            mlflow.set_tag("eval_data_path", eval_dataset_stats["eval_data_path"])
            mlflow.set_tag("eval_data_source", eval_dataset_stats["eval_data_source"])

            # Params
            mlflow.log_params({
                "version_id": version_id,
                "seq_len": SEQ_LEN,
                "eval_data_s3_path": eval_dataset_stats["eval_data_path"],
                "eval_data_rows": eval_dataset_stats["eval_data_rows"],
                "eval_data_source": eval_dataset_stats["eval_data_source"],
            })

            # Metrics
            mlflow.log_metrics({
                "p99_threshold": p99_threshold,
                "mean_score": mean_score,
                "test_samples": len(scored_df),
                "normal_samples": int(normal_mask.sum()),
                **classification_metrics,
            })

            # Full eval dataset stats as artifact
            mlflow.log_dict(eval_dataset_stats, "eval_dataset_info.json")
        finally:
            mlflow.end_run()

    end_pipeline_run(parent_run_id)

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

    xcom = {
        "version_id": version_id,
        "p99_threshold": p99_threshold,
        "mean_score": mean_score,
        "model_s3_path": f"s3://{bucket}/{model_prefix}/",
        **classification_metrics,
    }

    write_batch_output(s3_client, bucket, version_id, xcom)

    xcom_dir = "/airflow/xcom"
    if os.path.exists(os.path.dirname(xcom_dir)) or os.path.exists("/airflow"):
        os.makedirs(xcom_dir, exist_ok=True)
        with open(os.path.join(xcom_dir, "return.json"), "w") as f:
            json.dump(xcom, f)

    log.info("Evaluation complete")


if __name__ == "__main__":
    run()
