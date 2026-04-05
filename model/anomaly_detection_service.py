"""
Anomaly Detection Serving API
─────────────────────────────
Kafka batch consumer that:
  1. Consumes preprocessed span records from Redpanda topic `preprocess-data`
  2. Runs Transformer Autoencoder inference to compute anomaly scores
  3. Writes results (Parquet, partitioned by date) to AWS S3 via DuckDB
"""

import json
import os
import signal
import logging
import time
from datetime import datetime, timezone

import boto3
import duckdb
import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from confluent_kafka import Consumer, KafkaError, KafkaException

from transformer_ae.model import TransformerAutoencoder
from transformer_ae.evaluate import preprocess_test_df, build_sequences
from common.util import map_status_group

# ── Configuration ─────────────────────────────────────────────────────────────

KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "localhost:19092")
INPUT_TOPIC = os.getenv("INPUT_TOPIC", "traces")
CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "anomaly-group")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "500"))
ANOMALY_THRESHOLD = float(os.getenv("ANOMALY_THRESHOLD", "0.3293778896331787"))

# Write buffer settings: flush when row count OR time threshold is reached
FLUSH_ROW_THRESHOLD = int(os.getenv("FLUSH_ROW_THRESHOLD", "500"))
FLUSH_INTERVAL_SECONDS = int(os.getenv("FLUSH_INTERVAL_SECONDS", "60"))

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "s3.amazonaws.com")
S3_REGION = os.getenv("S3_REGION", "ap-southeast-1")
S3_BUCKET = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")
S3_USE_SSL = os.getenv("S3_USE_SSL", "true").lower() == "true"
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("anomaly-detection")
# Persistent global DuckDB connection
db_con = duckdb.connect(database=':memory:') 

# ── Graceful shutdown ─────────────────────────────────────────────────────────

running = True

def _stop(signum, _frame):
    global running
    log.info("Received signal %s, shutting down…", signum)
    running = False

signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)

# ── Model loading (one-time) ─────────────────────────────────────────────────

def _download_s3_model(model_s3_path: str, local_dir: str):
    """Download model artifacts from S3 to a local directory."""
    s3_client = boto3.client("s3", region_name=S3_REGION)
    # Parse bucket and prefix from s3://bucket/prefix/
    parts = model_s3_path.replace("s3://", "").split("/", 1)
    bucket = parts[0]
    prefix = parts[1].rstrip("/")

    os.makedirs(local_dir, exist_ok=True)
    for filename in ["model.pth", "encoders.pkl", "scalers.pkl"]:
        key = f"{prefix}/{filename}"
        local_path = os.path.join(local_dir, filename)
        log.info("Downloading s3://%s/%s → %s", bucket, key, local_path)
        s3_client.download_file(bucket, key, local_path)


def load_model():
    """Load the Transformer Autoencoder model, encoders, and scalers.

    If MODEL_S3_PATH is set, downloads artifacts from S3.
    Otherwise, falls back to local filesystem loading (backward compatible).
    """
    model_s3_path = os.getenv("MODEL_S3_PATH", "")
    model_version = os.getenv("MODEL_VERSION", "")

    if model_s3_path:
        log.info("Loading model from S3: %s (version=%s)", model_s3_path, model_version)
        local_dir = "/tmp/model"
        _download_s3_model(model_s3_path, local_dir)
        model_path = os.path.join(local_dir, "model.pth")
        encoders = joblib.load(os.path.join(local_dir, "encoders.pkl"))
        scalers = joblib.load(os.path.join(local_dir, "scalers.pkl"))
    else:
        log.info("Loading model from local filesystem (no MODEL_S3_PATH set)")
        BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transformer_ae")
        model_path = os.path.join(BASE_DIR, "transformer_ae_model.pth")
        encoders = joblib.load(os.path.join(BASE_DIR, "transformer_ae_encoders.pkl"))
        scalers = joblib.load(os.path.join(BASE_DIR, "transformer_ae_scalers.pkl"))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model = TransformerAutoencoder(
        service_vocab=encoders["service"].get_unknown_index() + 1,
        op_vocab=encoders["operation"].get_unknown_index() + 1,
        status_vocab=6,
        metrics_feature_num=1,  # duration only
    ).to(device)

    model.load_state_dict(torch.load(model_path, map_location=device))
    model.eval()

    source = f"S3 ({model_version})" if model_s3_path else "local"
    log.info("Model loaded from %s on device=%s", source, device)
    return model, encoders, scalers, device

# ── DuckDB ───────────────────────────────────────────────────────
def init_duckdb_s3():
    """Initialize S3 credentials and extensions once."""
    log.info("Initializing DuckDB S3 Connection...")
    db_con.execute("INSTALL httpfs; LOAD httpfs;")
    db_con.execute(f"""
        CREATE OR REPLACE SECRET (
            TYPE S3,
            KEY_ID '{AWS_ACCESS_KEY_ID}',
            SECRET '{AWS_SECRET_ACCESS_KEY}',
            REGION '{S3_REGION}',
            URL_STYLE 'path'
        );
    """)

def write_to_s3(result_df: pd.DataFrame):
    """Write the result DataFrame to S3 as Parquet via DuckDB."""
    if result_df.empty:
        return

    # Register the DataFrame so DuckDB can reference it
    db_con.register("result_df", result_df)

    db_con.execute(f"""
        COPY (
            SELECT
                make_timestamp(startTime::BIGINT // 1000) AS timestamp,
                traceId AS trace_id,
                spanId AS span_id,
                parentSpanId AS parent_span_id,
                raw_service AS service,
                raw_operation AS operation,
                http_status,
                duration_raw AS duration_ns,
                kind,
                span_status,
                anomaly_score,
                is_anomaly,
                current_date AS date_part
            FROM result_df
        )
        TO 's3://{S3_BUCKET}/anomalies/data.parquet'
        (FORMAT PARQUET, PARTITION_BY (date_part), OVERWRITE_OR_IGNORE 1);
    """)

    log.info("Wrote %d records to s3://%s/anomalies/", len(result_df), S3_BUCKET)

# ── Batch processing pipeline ────────────────────────────────────────────────

def process_batch(messages: list, model, encoders, scalers, device):
    """
    Process a batch of Kafka messages:
      1. Parse JSON → DataFrame
      2. Preprocess (encode + scale)
      3. Build sequences (groups of 20 spans)
      4. Model inference → anomaly scores
      5. Threshold comparison
      6. Write to S3
    """
    # 1. Parse messages into records
    records = []
    for msg in messages:
        try:
            record = json.loads(msg.value())
            records.append(record)
        except (json.JSONDecodeError, TypeError) as e:
            log.warning("Skipping malformed message: %s", e)

    if not records:
        return 0

    df = pd.DataFrame(records)

    # Validate required columns
    required_cols = ["service", "operation", "http_status", "duration",
                     "spanId", "parentSpanId", "traceId", "startTime", "span_status", "kind"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        log.error("Missing required columns: %s — skipping batch", missing)
        return 0

    # Save raw duration before preprocessing scales it
    df["duration_raw"] = df["duration"]

    # 2. Preprocess
    df = preprocess_test_df(df, encoders, scalers)

    # 3. Build sequences
    seq_len = 20
    metric_cols = ["duration"]

    services, parent_services, operations, parent_ops, statuses, metrics_x, row_idx = build_sequences(
        df, seq_len, metric_cols, stride=1
    )

    if len(services) == 0:
        log.info("No sequences built from %d records (groups too small)", len(df))
        return 0

    # 4. Model inference
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
    df["anomaly_score"] = np.nan

    with torch.no_grad():
        for s, ps, op, pop, h, x, row_ids in loader:
            s = s.to(device)
            ps = ps.to(device)
            op = op.to(device)
            pop = pop.to(device)
            h = h.to(device)
            x = x.to(device)

            recon = model(s, ps, op, pop, h, x)

            # (B, T, F) → per-timestep score (B, T)
            timestep_loss = criterion(recon, x).sum(dim=2).cpu().numpy()
            row_ids_np = row_ids.numpy()

            for b in range(len(row_ids_np)):
                for t_idx in range(seq_len):
                    row = row_ids_np[b, t_idx]
                    metric = x[b, t_idx]
                    if row == -1 or metric == 0:
                        continue

                    score = float(timestep_loss[b, t_idx])

                    # Boost score for server errors / OTel error status
                    if df.at[row, "span_status"] == 2 or df.at[row, "http_status"] == 5:
                        score += 1000

                    if np.isnan(df.at[row, "anomaly_score"]):
                        df.at[row, "anomaly_score"] = score
                    else:
                        df.at[row, "anomaly_score"] = max(df.at[row, "anomaly_score"], score)

    # 5. Threshold comparison
    df["is_anomaly"] = df["anomaly_score"] > ANOMALY_THRESHOLD

    # Drop rows without a score (weren't part of any sequence)
    result_df = df.dropna(subset=["anomaly_score"]).copy()

    if result_df.empty:
        log.info("No scored spans in this batch")
        return 0

    anomaly_count = result_df["is_anomaly"].sum()
    log.info(
        "Batch processed: %d records → %d scored → %d anomalies",
        len(records), len(result_df), anomaly_count,
    )
    return result_df


# ── Main consumer loop ───────────────────────────────────────────────────────

def flush_buffer(buffer: list[pd.DataFrame]) -> int:
    """Concatenate buffered DataFrames and write to S3. Returns row count written."""
    if not buffer:
        return 0
    combined = pd.concat(buffer, ignore_index=True)
    write_to_s3(combined)
    return len(combined)


def main():
    log.info("Anomaly Detection Service starting…")

    # Load model once
    model, encoders, scalers, device = load_model()

    # Kafka consumer
    consumer = Consumer({
        "bootstrap.servers": KAFKA_BROKERS,
        "group.id": CONSUMER_GROUP,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    })
    consumer.subscribe([INPUT_TOPIC])
    log.info(
        "Consuming from [%s], group=[%s], batch_size=%d, flush_rows=%d, flush_interval=%ds",
        INPUT_TOPIC, CONSUMER_GROUP, BATCH_SIZE, FLUSH_ROW_THRESHOLD, FLUSH_INTERVAL_SECONDS,
    )

    # Initialize DuckDB S3 connection
    init_duckdb_s3()

    total_processed = 0
    write_buffer: list[pd.DataFrame] = []
    buffer_rows = 0
    last_flush_time = time.time()

    try:
        while running:
            # Batch consume
            messages = consumer.consume(num_messages=BATCH_SIZE, timeout=5.0)

            if messages:
                # Filter out errors
                valid_msgs = []
                for msg in messages:
                    if msg.error():
                        if msg.error().code() == KafkaError._PARTITION_EOF:
                            continue
                        log.error("Consumer error: %s", msg.error())
                        continue
                    valid_msgs.append(msg)

                if valid_msgs:
                    log.info("Received %d messages, processing…", len(valid_msgs))
                    try:
                        result_df = process_batch(valid_msgs, model, encoders, scalers, device)
                        if result_df is not None and not result_df.empty:
                            write_buffer.append(result_df)
                            buffer_rows += len(result_df)
                    except Exception as e:
                        log.error("Error processing batch: %s", e, exc_info=True)

            # Flush buffer if row threshold or time interval is reached
            should_flush = (
                buffer_rows >= FLUSH_ROW_THRESHOLD
                or (write_buffer and time.time() - last_flush_time >= FLUSH_INTERVAL_SECONDS)
            )

            if should_flush:
                try:
                    flushed = flush_buffer(write_buffer)
                    total_processed += flushed
                    log.info("Flushed %d buffered records to S3", flushed)
                except Exception as e:
                    log.error("Error flushing buffer to S3: %s", e, exc_info=True)
                write_buffer.clear()
                buffer_rows = 0
                last_flush_time = time.time()

    except KafkaException as e:
        log.error("Kafka exception: %s", e)
    finally:
        # Flush remaining buffer on shutdown
        if write_buffer:
            try:
                flushed = flush_buffer(write_buffer)
                total_processed += flushed
                log.info("Final flush: %d records to S3", flushed)
            except Exception as e:
                log.error("Error in final flush: %s", e, exc_info=True)
        consumer.close()
        db_con.close()
        log.info("Shutdown complete. total_processed=%d", total_processed)


if __name__ == "__main__":
    main()
