"""
Anomaly Detection Serving API (Multi-Model)
────────────────────────────────────────────
Kafka batch consumer with per-app model routing:
  1. Consumes preprocessed span records from Redpanda topic `preprocess-data`
  2. Routes inference to app-specific models via ModelRegistry
  3. Writes results to ClickHouse (tiered storage: EBS hot → S3 cold)
"""

import json
import os
import signal
import logging
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from confluent_kafka import Consumer, KafkaError, KafkaException

from model_registry import ModelRegistry
from transformer_ae.evaluate import preprocess_test_df, build_sequences
from common.performance_metrics import MetricsTracker
from clickhouse_driver import Client as ClickHouseClient

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
FLUSH_INTERVAL_SECONDS = int(os.getenv("FLUSH_INTERVAL_SECONDS", "5"))

# S3 config (for model registry)
S3_REGION = os.getenv("S3_REGION", "ap-southeast-1")
S3_BUCKET = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")
MODEL_VERSION = os.getenv("MODEL_VERSION", "latest")

# Toggle detailed performance measurement (timing + metrics calculation)
PERF_MEASUREMENT_ENABLED = os.getenv("PERF_MEASUREMENT_ENABLED", "false").lower() == "true"
# Health server
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8080"))

# ClickHouse config
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "9000"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "default")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("anomaly-detection")

# ClickHouse client (initialized in main)
clickhouse_client = ClickHouseClient(
    host=CLICKHOUSE_HOST,
    port=CLICKHOUSE_PORT,
    user=CLICKHOUSE_USER,
    password=CLICKHOUSE_PASSWORD,
    database=CLICKHOUSE_DATABASE,
)

# Initialise metrics tracker
metrics_tracker = MetricsTracker()

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
    model_registry = ModelRegistry(
        s3_bucket=S3_BUCKET,
        s3_region=S3_REGION,
        model_version=MODEL_VERSION,
    )
    log.info("Model registry initialized (version=%s)", MODEL_VERSION)

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
        else:
            self.send_response(404)
            self.end_headers()

def start_health_server(port: int):
    server = HTTPServer(("", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("Health server started on port %d", port)

# ── ClickHouse ───────────────────────────────────────────────────────

def init_clickhouse():
    """Initialize ClickHouse connection."""
    log.info("Initializing ClickHouse Connection...")
    # Tạo bảng nếu chưa có
    clickhouse_client.execute("""
        CREATE TABLE IF NOT EXISTS anomalies (
            timestamp        DateTime,
            app_id           String,
            trace_id         String,
            span_id          String,
            parent_span_id   String,
            service          String,
            operation        String,
            http_status      String,
            duration_ns      Int64,
            kind             String,
            span_status      String,
            anomaly_score    Float64,
            is_anomaly       UInt8
        )
        ENGINE = MergeTree()
        ORDER BY (timestamp, app_id)
        SETTINGS storage_policy = 'hot_cold';
    """)

def write_to_clickhouse(result_df: pd.DataFrame):
    """Write anomaly results to ClickHouse."""
    if result_df.empty:
        return

    try:
        timestamps = pd.to_datetime(
            result_df["startTime"].astype("int64"),
            unit="ns"
        )

        data = list(zip(
            timestamps,
            result_df["app_id"].astype(str),
            result_df["traceId"].astype(str),
            result_df["spanId"].astype(str),
            result_df["parentSpanId"].fillna("").astype(str),
            result_df["raw_service"].astype(str),
            result_df["raw_operation"].astype(str),
            result_df["http_status"].astype(str),
            result_df["duration_raw"].astype("int64"),
            result_df["kind"].astype(str),
            result_df["span_status"].astype(str),
            result_df["anomaly_score"].astype(float),
            result_df["is_anomaly"].astype("uint8"),
        ))

        clickhouse_client.execute("""
            INSERT INTO anomalies (
                timestamp,
                app_id,
                trace_id,
                span_id,
                parent_span_id,
                service,
                operation,
                http_status,
                duration_ns,
                kind,
                span_status,
                anomaly_score,
                is_anomaly
            ) VALUES
        """, data)

        log.info("Inserted %d anomaly records to clickhouse", len(data))

    except Exception:
        log.exception("Failed to write anomalies to ClickHouse")
        raise

# ── Per-app batch processing ──────────────────────────────────────────────────

def process_app_batch(app_id: str, df: pd.DataFrame) -> pd.DataFrame:
    """Process batch for a single app_id using its specific model."""
    app_model = model_registry.get_model()
    if app_model is None:
        log.warning("No model available, skipping %d records for app_id=%s", len(df), app_id)
        return pd.DataFrame()

    log.debug("Processing %d records for app_id=%s with model version=%s",
              len(df), app_id, app_model.version)

    df = preprocess_test_df(df, app_model.encoders, app_model.scalers)

    seq_len = 20
    metric_cols = ["duration"]
    services, parent_services, operations, parent_ops, statuses, metrics_x, row_idx = build_sequences(
        df, seq_len, metric_cols, stride=1
    )

    if len(services) == 0:
        log.debug("No sequences built from %d records for app_id=%s", len(df), app_id)
        return pd.DataFrame()

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
            s = s.to(app_model.device)
            ps = ps.to(app_model.device)
            op = op.to(app_model.device)
            pop = pop.to(app_model.device)
            h = h.to(app_model.device)
            x = x.to(app_model.device)

            recon = app_model.model(s, ps, op, pop, h, x)
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

    log.info("app_id=%s: %d records → %d scored → threshold=%.4f",
             app_id, len(df), len(result_df), app_model.threshold)

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
    """Concatenate buffered DataFrames and write to S3 and ClickHouse in parallel."""
    if not buffer:
        return 0
    
    combined = pd.concat(buffer, ignore_index=True)
    write_to_clickhouse(combined)

    # with ThreadPoolExecutor(max_workers=2) as executor:
    #     futures = {
    #         executor.submit(write_to_s3, combined): "S3",
    #         executor.submit(write_to_clickhouse, combined): "ClickHouse",
    #     }
    #     for future in as_completed(futures):
    #         name = futures[future]
    #         try:
    #             future.result()
    #         except Exception as e:
    #             log.error("Failed to write to %s: %s", name, e)

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

    init_clickhouse()

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
                        # Start timer (high precision) only when performance measurement enabled
                        if PERF_MEASUREMENT_ENABLED:
                            start_ns = time.perf_counter_ns()

                        result_df = process_batch(valid_msgs)

                        # Record per-row ML processing time only when enabled and result exists
                        if PERF_MEASUREMENT_ENABLED and result_df is not None and not result_df.empty:
                            ml_batch_processed_time = time.perf_counter_ns() - start_ns
                            result_df["ml_batch_processed_time"] = ml_batch_processed_time / len(result_df)
                        
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
                    if PERF_MEASUREMENT_ENABLED:
                        metrics_tracker.calculate_performance_metrics(write_buffer)
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
                if PERF_MEASUREMENT_ENABLED:
                    metrics_tracker.calculate_performance_metrics(write_buffer)
            except Exception as e:
                log.error("Error in final flush: %s", e, exc_info=True)
        consumer.close()
        clickhouse_client.disconnect()
        log.info("Shutdown complete. total_processed=%d", total_processed)


if __name__ == "__main__":
    main()
