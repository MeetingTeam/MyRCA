"""
Anomaly Detection Serving API (Multi-Model)
────────────────────────────────────────────
Kafka batch consumer with per-app model routing:
  1. Consumes preprocessed span records from Redpanda topic `preprocess-data`
  2. Routes inference to app-specific models via ModelRegistry
  3. Writes results (Parquet, partitioned by date) to AWS S3 via DuckDB
"""

import json
import os
import signal
import logging
import time
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

import duckdb
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from confluent_kafka import Consumer, KafkaError, KafkaException

from model_registry import ModelRegistry
from transformer_ae.evaluate import preprocess_test_df, build_sequences

# ── Configuration ─────────────────────────────────────────────────────────────

KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "localhost:19092")
INPUT_TOPIC = os.getenv("INPUT_TOPIC", "preprocess-data")
CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "anomaly-group")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "500"))

# Multi-model config
MAX_CACHED_MODELS = int(os.getenv("MAX_CACHED_MODELS", "10"))
DEFAULT_APP_ID = os.getenv("DEFAULT_APP_ID", "k8s-repo-application")
DEFAULT_THRESHOLD = float(os.getenv("ANOMALY_THRESHOLD", "0.33"))

# Write buffer settings
FLUSH_ROW_THRESHOLD = int(os.getenv("FLUSH_ROW_THRESHOLD", "500"))
FLUSH_INTERVAL_SECONDS = int(os.getenv("FLUSH_INTERVAL_SECONDS", "60"))

# S3 config
S3_REGION = os.getenv("S3_REGION", "ap-southeast-1")
S3_BUCKET = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

# Health server
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8080"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("anomaly-detection")

db_con = duckdb.connect(database=':memory:')

# ── Graceful shutdown ─────────────────────────────────────────────────────────

running = True

def _stop(signum, _frame):
    global running
    log.info("Received signal %s, shutting down…", signum)
    running = False

signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)

# ── Global model registry ─────────────────────────────────────────────────────

model_registry: ModelRegistry = None

def init_model_registry():
    """Initialize the global model registry."""
    global model_registry
    local_fallback = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transformer_ae")

    model_registry = ModelRegistry(
        s3_bucket=S3_BUCKET,
        s3_region=S3_REGION,
        max_models=MAX_CACHED_MODELS,
        default_app_id=DEFAULT_APP_ID,
        local_fallback_dir=local_fallback,
    )
    log.info("Model registry initialized (max_models=%d, default=%s)", MAX_CACHED_MODELS, DEFAULT_APP_ID)

# ── Health server ─────────────────────────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/health" or self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        elif self.path == "/cache-stats":
            stats = model_registry.get_cache_stats() if model_registry else {}
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(stats).encode())
        else:
            self.send_response(404)
            self.end_headers()

def start_health_server(port: int):
    server = HTTPServer(("", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("Health server started on port %d", port)

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
            REGION '{S3_REGION}'
        );
    """)

def write_to_s3(result_df: pd.DataFrame):
    """Write the result DataFrame to S3 as Parquet."""
    if result_df.empty:
        return

    write_con = duckdb.connect(database=":memory:")
    try:
        write_con.execute("INSTALL httpfs; LOAD httpfs;")
        write_con.execute(f"""
            CREATE OR REPLACE SECRET (
                TYPE S3,
                KEY_ID '{AWS_ACCESS_KEY_ID}',
                SECRET '{AWS_SECRET_ACCESS_KEY}',
                REGION '{S3_REGION}'
            );
        """)
        write_con.register("result_df", result_df)
        write_con.execute(f"""
            COPY (
                SELECT
                    make_timestamp(startTime::BIGINT // 1000) AS timestamp,
                    app_id,
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
            (FORMAT PARQUET, PARTITION_BY (date_part), APPEND);
        """)
        log.info("Wrote %d records to s3://%s/anomalies/", len(result_df), S3_BUCKET)
    finally:
        write_con.close()

# ── Per-app batch processing ──────────────────────────────────────────────────

def process_app_batch(app_id: str, df: pd.DataFrame) -> pd.DataFrame:
    """Process batch for a single app_id using its specific model."""
    app_model = model_registry.get_model(app_id)
    if app_model is None:
        log.warning("No model available for app_id=%s, skipping %d records", app_id, len(df))
        return pd.DataFrame()

    log.debug("Processing %d records for app_id=%s with model version=%s",
              len(df), app_id, app_model.version)

    df = preprocess_test_df(df.copy(), app_model.encoders, app_model.scalers)

    seq_len = 20
    metric_cols = ["duration"]
    apps, services, parent_services, operations, parent_ops, statuses, metrics_x, row_idx = build_sequences(
        df, seq_len, metric_cols, stride=1
    )

    if len(services) == 0:
        log.debug("No sequences built from %d records for app_id=%s", len(df), app_id)
        return pd.DataFrame()

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
    df["anomaly_score"] = np.nan

    with torch.no_grad():
        for a, s, ps, op, pop, h, x, row_ids in loader:
            a = a.to(app_model.device)
            s = s.to(app_model.device)
            ps = ps.to(app_model.device)
            op = op.to(app_model.device)
            pop = pop.to(app_model.device)
            h = h.to(app_model.device)
            x = x.to(app_model.device)

            recon = app_model.model(s, ps, op, pop, h, a, x)
            timestep_loss = criterion(recon, x).mean(dim=2).cpu().numpy()
            row_ids_np = row_ids.numpy()

            for b in range(len(row_ids_np)):
                for t_idx in range(seq_len):
                    row = row_ids_np[b, t_idx]
                    metric = x[b, t_idx]
                    if row == -1 or metric == 0:
                        continue

                    score = float(timestep_loss[b, t_idx])

                    if df.at[row, "span_status"] == 2 or df.at[row, "http_status"] == 5:
                        score += 1000

                    if np.isnan(df.at[row, "anomaly_score"]):
                        df.at[row, "anomaly_score"] = score
                    else:
                        df.at[row, "anomaly_score"] = max(df.at[row, "anomaly_score"], score)

    df["is_anomaly"] = df["anomaly_score"] > app_model.threshold

    result_df = df.dropna(subset=["anomaly_score"]).copy()
    if result_df.empty:
        return pd.DataFrame()

    anomaly_count = result_df["is_anomaly"].sum()
    log.info("app_id=%s: %d records → %d scored → %d anomalies (threshold=%.4f)",
             app_id, len(df), len(result_df), anomaly_count, app_model.threshold)

    return result_df

# ── Batch processing pipeline (multi-model) ──────────────────────────────────

def process_batch(messages: list) -> pd.DataFrame:
    """
    Process batch with per-app model routing:
      1. Parse JSON → DataFrame
      2. Group by app_id
      3. For each app_id: get model, preprocess, infer
      4. Merge results
    """
    records = []
    for msg in messages:
        try:
            record = json.loads(msg.value())
            records.append(record)
        except (json.JSONDecodeError, TypeError) as e:
            log.warning("Skipping malformed message: %s", e)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    required_cols = ["app_id", "service", "operation", "http_status", "duration",
                     "spanId", "parentSpanId", "traceId", "startTime", "span_status", "kind"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        log.error("Missing required columns: %s — skipping batch", missing)
        return pd.DataFrame()

    df["duration_raw"] = df["duration"]

    result_dfs = []
    for app_id, app_df in df.groupby("app_id"):
        try:
            app_result = process_app_batch(app_id, app_df)
            if app_result is not None and not app_result.empty:
                result_dfs.append(app_result)
        except Exception as e:
            log.error("Error processing app_id=%s: %s", app_id, e, exc_info=True)

    if not result_dfs:
        return pd.DataFrame()

    return pd.concat(result_dfs, ignore_index=True)

# ── Main consumer loop ───────────────────────────────────────────────────────

def flush_buffer(buffer: list[pd.DataFrame]) -> int:
    """Concatenate buffered DataFrames and write to S3."""
    if not buffer:
        return 0
    combined = pd.concat(buffer, ignore_index=True)
    write_to_s3(combined)
    return len(combined)


def main():
    log.info("Anomaly Detection Service (Multi-Model) starting…")

    init_model_registry()
    start_health_server(HEALTH_PORT)

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

    init_duckdb_s3()

    total_processed = 0
    write_buffer: list[pd.DataFrame] = []
    buffer_rows = 0
    last_flush_time = time.time()

    try:
        while running:
            messages = consumer.consume(num_messages=BATCH_SIZE, timeout=5.0)

            if messages:
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
                        result_df = process_batch(valid_msgs)
                        if result_df is not None and not result_df.empty:
                            write_buffer.append(result_df)
                            buffer_rows += len(result_df)
                    except Exception as e:
                        log.error("Error processing batch: %s", e, exc_info=True)

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
        if write_buffer:
            try:
                flushed = flush_buffer(write_buffer)
                total_processed += flushed
                log.info("Final flush: %d records to S3", flushed)
            except Exception as e:
                log.error("Error in final flush: %s", e, exc_info=True)
        consumer.close()
        db_con.close()
        log.info("Cache stats at shutdown: %s", model_registry.get_cache_stats())
        log.info("Shutdown complete. total_processed=%d", total_processed)


if __name__ == "__main__":
    main()
