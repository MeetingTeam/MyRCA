"""
Step 3: Training
────────────────
Downloads preprocessed training data from S3, builds sequences,
trains the TransformerAutoencoder (50 epochs), saves model artifacts to S3,
and logs to MLflow.

Reuses logic from model/transformer_ae/train.py:train_model().
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
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

from transformer_ae.model import TransformerAutoencoder
from tasks.s3_utils import read_parquet_from_s3, s3_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("training")

SEQ_LEN = 20
STRIDE = 2
EPOCHS = 50
BATCH_SIZE = 64
LR = 5e-4
WEIGHT_DECAY = 1e-5


def build_sequences(df, seq_len, metric_cols, stride=1):
    """Build fixed-length sequences grouped by context features (training version, no row indices)."""
    grouped = df.groupby(["service", "parent_service", "operation", "parent_op", "http_status"], sort=False)

    services, parent_services, operations, parent_ops, statuses = [], [], [], [], []
    metrics_seq = []
    metric_cols = list(metric_cols)

    for (s, ps, op, pop, h), g in grouped:
        metrics = g[metric_cols].to_numpy(dtype=np.float32)
        n = metrics.shape[0]

        if n < seq_len:
            continue

        last_start = n - seq_len
        for i in range(0, last_start + 1, stride):
            services.append(s)
            parent_services.append(ps)
            operations.append(op)
            parent_ops.append(pop)
            statuses.append(h)
            metrics_seq.append(metrics[i:i + seq_len])

        if last_start % stride != 0:
            services.append(s)
            parent_services.append(ps)
            operations.append(op)
            parent_ops.append(pop)
            statuses.append(h)
            metrics_seq.append(metrics[last_start:last_start + seq_len])

    return (
        np.asarray(services),
        np.asarray(parent_services),
        np.asarray(operations),
        np.asarray(parent_ops),
        np.asarray(statuses),
        np.stack(metrics_seq) if metrics_seq else np.empty((0, seq_len, len(metric_cols))),
    )


def run():
    version_id = os.getenv("VERSION_ID")
    if not version_id:
        log.error("VERSION_ID not set")
        sys.exit(1)

    log.info("Training starting, version_id=%s", version_id)

    mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow.mlflow.svc.cluster.local:5000")
    mlflow.set_tracking_uri(mlflow_uri)
    mlflow.set_experiment("transformer-ae-training")

    # Download training data
    train_path = s3_path(f"mlops/training-data/{version_id}/train.parquet")
    train_df = read_parquet_from_s3(train_path)
    log.info("Training data: %d rows", len(train_df))

    # Download encoders to get vocab sizes
    s3_client = boto3.client("s3", region_name=os.getenv("S3_REGION", "ap-southeast-1"))
    bucket = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")
    local_dir = "/tmp/mlops_artifacts"
    os.makedirs(local_dir, exist_ok=True)

    enc_local = os.path.join(local_dir, "encoders.pkl")
    s3_client.download_file(bucket, f"mlops/training-data/{version_id}/encoders.pkl", enc_local)
    encoders = joblib.load(enc_local)

    # Build sequences
    metric_cols = ["duration"]
    services, parent_services, operations, parent_ops, statuses, metrics_x = build_sequences(
        train_df, SEQ_LEN, metric_cols, STRIDE
    )

    if len(services) == 0:
        log.error("No sequences built — insufficient data")
        sys.exit(1)

    log.info("Built %d sequences", len(services))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    dataset = TensorDataset(
        torch.LongTensor(services),
        torch.LongTensor(parent_services),
        torch.LongTensor(operations),
        torch.LongTensor(parent_ops),
        torch.LongTensor(statuses),
        torch.FloatTensor(metrics_x),
    )
    loader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)

    model = TransformerAutoencoder(
        service_vocab=encoders["service"].get_unknown_index() + 1,
        op_vocab=encoders["operation"].get_unknown_index() + 1,
        status_vocab=6,
        metrics_feature_num=len(metric_cols),
    ).to(device)

    optimizer = optim.Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", factor=0.5, patience=5)
    criterion = nn.MSELoss()

    with mlflow.start_run(run_name=f"train-{version_id}"):
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
        })

        for epoch in range(EPOCHS):
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

            if (epoch + 1) % 10 == 0 or epoch == 0:
                log.info("Epoch [%d/%d] Loss: %.6f | LR: %.6f", epoch + 1, EPOCHS, avg_loss, current_lr)

            mlflow.log_metrics({"train_loss": avg_loss, "lr": current_lr}, step=epoch)

        final_loss = avg_loss
        mlflow.log_metric("final_train_loss", final_loss)

        # Save model artifacts locally
        model_local = os.path.join(local_dir, "model.pth")
        torch.save(model.state_dict(), model_local)

        # Upload to S3
        model_s3_prefix = f"mlops/models/{version_id}"
        s3_client.upload_file(model_local, bucket, f"{model_s3_prefix}/model.pth")
        s3_client.upload_file(enc_local, bucket, f"{model_s3_prefix}/encoders.pkl")

        scl_local = os.path.join(local_dir, "scalers.pkl")
        s3_client.download_file(bucket, f"mlops/training-data/{version_id}/scalers.pkl", scl_local)
        s3_client.upload_file(scl_local, bucket, f"{model_s3_prefix}/scalers.pkl")

        log.info("Model artifacts uploaded to s3://%s/%s/", bucket, model_s3_prefix)

        # Register model in MLflow (best-effort — S3 is the primary artifact store)
        try:
            mlflow.pytorch.log_model(model, "model", registered_model_name="transformer-ae")
        except Exception as e:
            log.warning("Could not register model in MLflow: %s", e)

    # Write XCom
    xcom = {
        "version_id": version_id,
        "model_s3_path": s3_path(f"{model_s3_prefix}/"),
        "final_train_loss": final_loss,
    }
    xcom_dir = "/airflow/xcom"
    os.makedirs(xcom_dir, exist_ok=True)
    with open(os.path.join(xcom_dir, "return.json"), "w") as f:
        json.dump(xcom, f)

    log.info("Training complete. final_loss=%.6f", final_loss)


if __name__ == "__main__":
    run()
