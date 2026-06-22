"""
Step 3: Training
────────────────
Downloads preprocessed training data from S3, builds sequences,
trains the TransformerAutoencoder (50 epochs), saves model artifacts to S3,
and logs to MLflow.

Supports:
- Checkpointing for Spot instance recovery
- S3 output for AWS Batch XCom replacement
- Nested MLflow runs under parent pipeline run
"""

import io
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
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

from transformer_ae.model import TransformerAutoencoder
from transformer_ae.train import build_sequences
from tasks.s3_utils import read_parquet_from_s3, s3_path
from tasks.mlflow_utils import setup_mlflow, start_nested_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("training")

SEQ_LEN = 20
STRIDE = 2
EPOCHS = 30
BATCH_SIZE = 64
LR = 5e-4
WEIGHT_DECAY = 1e-5
CHECKPOINT_INTERVAL = 10
NAN_TOLERANCE = 2  # early stop if loss is NaN/Inf for this many consecutive epochs


def _sanitize_json(obj):
    """Replace NaN/Inf with None recursively — Airflow 3 XCom API uses strict JSON encoder."""
    import math
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_json(v) for v in obj]
    return obj

def save_checkpoint(s3_client, bucket, version_id, epoch, model, optimizer, scheduler, loss):
    """Save training checkpoint to S3 for Spot interruption recovery."""
    checkpoint = {
        "epoch": epoch,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "scheduler_state_dict": scheduler.state_dict(),
        "loss": loss,
    }
    buffer = io.BytesIO()
    torch.save(checkpoint, buffer)
    buffer.seek(0)
    s3_client.put_object(
        Bucket=bucket,
        Key=f"mlops/checkpoints/{version_id}/checkpoint_latest.pt",
        Body=buffer.getvalue(),
    )
    log.info("Checkpoint saved at epoch %d", epoch)


def load_checkpoint(s3_client, bucket, version_id, model, optimizer, scheduler, device):
    """Load checkpoint if exists (for Spot recovery)."""
    try:
        response = s3_client.get_object(
            Bucket=bucket,
            Key=f"mlops/checkpoints/{version_id}/checkpoint_latest.pt",
        )
        buffer = io.BytesIO(response["Body"].read())
        checkpoint = torch.load(buffer, map_location=device)
        model.load_state_dict(checkpoint["model_state_dict"])
        optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
        scheduler.load_state_dict(checkpoint["scheduler_state_dict"])
        start_epoch = checkpoint["epoch"] + 1
        log.info("Resumed from checkpoint at epoch %d", checkpoint["epoch"])
        return start_epoch
    except s3_client.exceptions.NoSuchKey:
        log.info("No checkpoint found, starting from epoch 0")
        return 0
    except Exception as e:
        log.warning("Failed to load checkpoint: %s, starting fresh", e)
        return 0


def write_batch_output(s3_client, bucket, version_id: str, output_data: dict):
    """Write output to S3 for Airflow XCom replacement (Batch jobs).

    Sanitizes NaN/Inf because Airflow 3 XCom API uses strict JSON encoder.
    """
    sanitized = _sanitize_json(output_data)
    s3_client.put_object(
        Bucket=bucket,
        Key=f"mlops/batch-outputs/{version_id}/train_output.json",
        Body=json.dumps(sanitized),
        ContentType="application/json",
    )
    log.info("Batch output written to S3: mlops/batch-outputs/%s/train_output.json", version_id)


def run():
    version_id = os.getenv("VERSION_ID")
    if not version_id:
        log.error("VERSION_ID not set")
        sys.exit(1)

    parent_run_id = os.getenv("MLFLOW_PARENT_RUN_ID", "").strip() or None
    log.info("Training starting, version_id=%s, parent_run_id=%s", version_id, parent_run_id)

    s3_client = boto3.client("s3", region_name=os.getenv("S3_REGION", "ap-southeast-1"))
    bucket = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")
    local_dir = "/tmp/mlops_artifacts"
    os.makedirs(local_dir, exist_ok=True)

    train_path = s3_path(f"mlops/training-data/{version_id}/train.parquet")
    train_df = read_parquet_from_s3(train_path)
    log.info("Training data: %d rows", len(train_df))

    # Compute dataset stats for MLflow tracking (Phase 0: Evidently migration prerequisite)
    dataset_stats = {
        "train_data_path": train_path,
        "train_data_rows": len(train_df),
        "train_data_version": version_id,
    }

    # Per-app distribution (critical for per-app drift detection)
    if "app_id" in train_df.columns:
        app_counts = train_df["app_id"].value_counts().to_dict()
        dataset_stats["app_distribution"] = app_counts
        for app_id, count in app_counts.items():
            safe_app_id = str(app_id).replace("-", "_").replace(" ", "_")
            dataset_stats[f"app_{safe_app_id}_rows"] = int(count)

    # Date range (useful for debugging data freshness)
    ts_col = None
    for col in ["startTime", "timestamp", "start_time"]:
        if col in train_df.columns:
            ts_col = col
            break

    if ts_col:
        try:
            dataset_stats["data_start_time"] = str(pd.to_datetime(train_df[ts_col].min()))
            dataset_stats["data_end_time"] = str(pd.to_datetime(train_df[ts_col].max()))
        except Exception:
            pass

    # Feature stats
    dataset_stats["num_services"] = int(train_df["service"].nunique()) if "service" in train_df.columns else 0
    dataset_stats["num_operations"] = int(train_df["operation"].nunique()) if "operation" in train_df.columns else 0
    log.info("Dataset stats computed: %d apps, %d services", len(app_counts) if "app_id" in train_df.columns else 0, dataset_stats["num_services"])

    enc_local = os.path.join(local_dir, "encoders.pkl")
    s3_client.download_file(bucket, f"mlops/training-data/{version_id}/encoders.pkl", enc_local)
    encoders = joblib.load(enc_local)

    metric_cols = ["duration"]
    services, parent_services, operations, parent_ops, statuses, metrics_x = build_sequences(
        train_df, SEQ_LEN, metric_cols, STRIDE
    )

    if len(services) == 0:
        log.error("No sequences built — insufficient data")
        sys.exit(1)

    log.info("Built %d sequences", len(services))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log.info("Using device: %s", device)

    dataset = TensorDataset(
        torch.LongTensor(services),
        torch.LongTensor(parent_services),
        torch.LongTensor(operations),
        torch.LongTensor(parent_ops),
        torch.LongTensor(statuses),
        torch.FloatTensor(metrics_x),
    )
    loader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)

    # Model design rolled back at commit 82adf6c — no app embedding; app discrimination is
    # handled by drift_detection per-app, not by the autoencoder.
    model = TransformerAutoencoder(
        service_vocab=encoders["service"].get_unknown_index() + 1,
        op_vocab=encoders["operation"].get_unknown_index() + 1,
        status_vocab=6,
        metrics_feature_num=len(metric_cols),
    ).to(device)

    optimizer = optim.Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", factor=0.5, patience=5)
    criterion = nn.MSELoss()

    start_epoch = load_checkpoint(s3_client, bucket, version_id, model, optimizer, scheduler, device)

    mlflow_run = start_nested_run(parent_run_id, f"train-{version_id}")
    final_loss = 0.0

    try:
        if mlflow_run:
            import mlflow
            # Tags (searchable in MLflow UI)
            mlflow.set_tag("version_id", version_id)
            mlflow.set_tag("train_data_path", train_path)

            # Params (including dataset info for drift detection reference)
            mlflow.log_params({
                "version_id": version_id,
                "epochs": EPOCHS,
                "batch_size": BATCH_SIZE,
                "lr": LR,
                "seq_len": SEQ_LEN,
                "stride": STRIDE,
                "num_sequences": len(services),
                "d_model": 64,
                "latent_dim": 32,
                "resumed_from_epoch": start_epoch,
                "app_vocab": encoders["app_id"].get_unknown_index() + 1,
                "train_data_s3_path": train_path,
                "train_data_rows": len(train_df),
            })

            # Per-app row counts as separate params (for filtering in MLflow)
            if "app_id" in train_df.columns:
                for app_id_val, count in train_df["app_id"].value_counts().items():
                    safe_app_id = str(app_id_val).replace("-", "_").replace(" ", "_")
                    mlflow.log_param(f"app_{safe_app_id}_rows", int(count))

            # Log full dataset stats as JSON artifact
            mlflow.log_dict(dataset_stats, "dataset_info.json")

        for epoch in range(start_epoch, EPOCHS):
            model.train()
            total_loss = 0

            for s, ps, op, pop, h, x in loader:
                s, ps, op, pop, h, x = (
                    s.to(device), ps.to(device), op.to(device),
                    pop.to(device), h.to(device), x.to(device),
                )

                recon = model(s, ps, op, pop, h, x)
                loss = criterion(recon, x)

                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()

                total_loss += loss.item()

            avg_loss = total_loss / len(loader)
            scheduler.step(avg_loss)

            current_lr = optimizer.param_groups[0]["lr"]
            log.info("Epoch [%d/%d] Loss: %.6f | LR: %.6f", epoch, EPOCHS, avg_loss, current_lr)

            if mlflow_run:
                import mlflow
                mlflow.log_metrics({"train_loss": avg_loss, "lr": current_lr}, step=epoch)

            if (epoch + 1) % CHECKPOINT_INTERVAL == 0 or epoch == EPOCHS - 1:
                save_checkpoint(s3_client, bucket, version_id, epoch, model, optimizer, scheduler, avg_loss)

        final_loss = avg_loss

        if mlflow_run:
            import mlflow
            mlflow.log_metric("final_train_loss", final_loss)
            try:
                mlflow.pytorch.log_model(model, "model", registered_model_name="transformer-ae")
            except Exception as e:
                log.warning("Could not register model in MLflow: %s", e)

    finally:
        if mlflow_run:
            import mlflow
            mlflow.end_run()

    model_local = os.path.join(local_dir, "model.pth")
    torch.save(model.state_dict(), model_local)

    model_s3_prefix = f"mlops/models/{version_id}"
    s3_client.upload_file(model_local, bucket, f"{model_s3_prefix}/model.pth")
    s3_client.upload_file(enc_local, bucket, f"{model_s3_prefix}/encoders.pkl")

    scl_local = os.path.join(local_dir, "scalers.pkl")
    s3_client.download_file(bucket, f"mlops/training-data/{version_id}/scalers.pkl", scl_local)
    s3_client.upload_file(scl_local, bucket, f"{model_s3_prefix}/scalers.pkl")

    log.info("Model artifacts uploaded to s3://%s/%s/", bucket, model_s3_prefix)

    xcom = {
        "version_id": version_id,
        "model_s3_path": s3_path(f"{model_s3_prefix}/"),
        "final_train_loss": final_loss,
    }

    write_batch_output(s3_client, bucket, version_id, xcom)

    xcom_dir = "/airflow/xcom"
    if os.path.exists(os.path.dirname(xcom_dir)) or os.path.exists("/airflow"):
        os.makedirs(xcom_dir, exist_ok=True)
        with open(os.path.join(xcom_dir, "return.json"), "w") as f:
            json.dump(_sanitize_json(xcom), f)

    log.info("Training complete. final_loss=%.6f", final_loss)


if __name__ == "__main__":
    run()
