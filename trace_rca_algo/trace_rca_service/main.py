from algo import rank_root_causes
from preproccessing import build_trace_dags_from_csv
from log_extractor import LokiLogExtractor
import llm_rca
import incident_store
import api as api_module
import os
import time
import threading
from confluent_kafka import Consumer, KafkaError, KafkaException
import json
import duckdb
import uvicorn
from datetime import datetime, timezone
import requests
import logging
import boto3
from urllib.parse import urlparse
from performance_metrics import MetricsTracker
from clickhouse_driver import Client as ClickHouseClient

# ── Configuration ─────────────────────────────────────────────────────────────

KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "localhost:19092")
INPUT_TOPIC = os.getenv("INPUT_TOPIC", "rca-task-data")
CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "rca-service-group")

S3_REGION = os.getenv("S3_REGION", "ap-southeast-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

# Toggle detailed performance measurement (timing + metrics calculation)
PERF_MEASUREMENT_ENABLED = os.getenv("PERF_MEASUREMENT_ENABLED", "false").lower() == "true"

S3_KB_PATH = os.getenv("S3_KB_PATH", "s3://kltn-anomaly-dateset-1/knowledge_base.json")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

LOKI_URL = os.getenv("LOKI_URL", "http://loki.loki.svc.cluster.local:3100")
LLM_N_SAMPLES = int(os.getenv("LLM_N_SAMPLES", "3"))

# ClickHouse config
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "9000"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "default")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("trace-rca-service")

clickhouse_client = ClickHouseClient(
    host=CLICKHOUSE_HOST,
    port=CLICKHOUSE_PORT,
    user=CLICKHOUSE_USER,
    password=CLICKHOUSE_PASSWORD,
    database=CLICKHOUSE_DATABASE,
)

# ── Setup ──────────────────────────────────────────────────────────
def fetch_s3_json(s3_path):
    """
    Fetches a JSON object from S3 and converts it to a Python object.
    """
    # Parse the S3 URI (e.g., s3://my-bucket/key/path.json)
    parsed_url = urlparse(s3_path)
    bucket_name = parsed_url.netloc
    key = parsed_url.path.lstrip('/')

    # Initialize S3 client (uses environment variables for credentials)
    s3 = boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=S3_REGION
    )

    # Get the object and read the body
    response = s3.get_object(Bucket=bucket_name, Key=key)
    content = response['Body'].read().decode('utf-8')
        
    return json.loads(content)

# def fetch_kb_from_mlflow(model_name):
#     """
#     Fetches the Knowledge Base from MLflow using the production alias.
#     Falls back to S3_KB_PATH if MLflow is unavailable.
#     """
#     mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
#     client = MlflowClient()

#     try:
#         model_version = client.get_model_version_by_alias(
#             name=model_name,
#             alias="production"
#         )
#         run_id = model_version.run_id
#         log.info(f"Found production KB model version {model_version.version} from run {run_id}")
        
#         # Download the KB artifact from the run
#         # The artifact is stored at kb_model/artifacts/kb_json
#         kb_file = client.download_artifacts(run_id, "kb_model/artifacts/built_kb.json", dst_path="./mlflow_artifacts")
        
#         # Load the KB JSON
#         with open(kb_file, "r") as f:
#             kb = json.load(f)

#         log.info(f"Successfully loaded KB from MLflow (version {model_version.version})")
#         return kb

#     except Exception as e:
#         log.warning(f"MLflow KB fetch failed: {e}")
#         if S3_KB_PATH:
#             log.info("Falling back to S3 KB path...")
#             return fetch_kb_from_s3(S3_KB_PATH)
#         raise

def query_spans_by_timestamp(start_dt, end_dt, app_id: str = None):
    """
    Query spans from ClickHouse within the given timestamp range.
    Returns DataFrame with span data.
    """
    try:
        start_ts_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        end_ts_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

        app_filter = "AND app_id = %(app_id)s" if app_id else ""
        query = f"""
            SELECT *
            FROM anomalies
            WHERE timestamp BETWEEN %(start_ts)s AND %(end_ts)s
            {app_filter}
        """

        params = {
            "start_ts": start_ts_str,
            "end_ts": end_ts_str,
        }
        if app_id:
            params["app_id"] = app_id

        result_df = clickhouse_client.query_dataframe(query, params=params)
        log.info(f"Found {len(result_df)} spans between {start_dt} and {end_dt}")
        return result_df

    except Exception as e:
        log.error(f"Error querying spans: {e}")
        return None

def send_rca_notification(
    app_id, ranking, start_dt: datetime, end_dt: datetime, llm_result: dict | None = None
):
    """Post the RCA ranking results to a Discord channel via webhook."""
    if not DISCORD_WEBHOOK_URL:
        log.info("Discord webhook URL not configured, skipping notification")
        return

    rank_text = ""
    for i, (svc, score) in enumerate(ranking[:3]):
        medals = ["1️⃣", "2️⃣", "3️⃣"]
        rank_text += f"{medals[i]} `{svc}` (Score: {score:.4f})\n"

    start_ts = int(start_dt.replace(tzinfo=timezone.utc).timestamp())
    end_ts = int(end_dt.replace(tzinfo=timezone.utc).timestamp())
    discord_time = f"<t:{start_ts}:f> to <t:{end_ts}:t>"

    message = f"""🚨 **System Failure Detected**
**Time Window:** {discord_time}
**App ID:** {app_id}

**Stage 1 — Structural Ranking:**
{rank_text}"""

    # Append Stage 2 LLM results if available
    if llm_result and llm_result.get("root_cause"):
        rc = llm_result["root_cause"]
        confidence_level = llm_result.get("confidence_level", "N/A")
        agreement = llm_result.get("agreement_ratio", 0)
        chain = " → ".join(llm_result.get("propagation_chain", [])) or "N/A"

        message += f"""
**Stage 2 — LLM Analysis:**
🎯 Root Cause: `{rc['service']}` (confidence: {rc['confidence']:.2f}, level: {confidence_level})
🤝 Agreement: {agreement:.0%} ({LLM_N_SAMPLES} samples)
🔗 Propagation: {chain}
"""
        # Add per-service analysis
        for a in llm_result.get("analysis", [])[:3]:
            icon = "🔴" if a.get("classification") == "INTRINSIC" else "🟡"
            message += f"{icon} `{a['service']}` [{a['classification']}]: {a.get('evidence', '')[:100]}\n"

    payload = {"content": message}

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
        resp.raise_for_status()
        log.info("Sent RCA notification to Discord")
    except Exception as e:
        log.error(f"Failed to send Discord notification: {e}")

def main():
    log.info("Starting RCA Service...")
    
    # Setup Kafka consumer
    consumer = Consumer({
        "bootstrap.servers": KAFKA_BROKERS,
        "group.id": CONSUMER_GROUP,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    })
    consumer.subscribe([INPUT_TOPIC])

    # Load Knowledge Base from MLflow (falls back to S3_KB_PATH)
    kb = fetch_s3_json(S3_KB_PATH)
    print(f"Loaded KB with {len(kb)} entries")
    
    # Initialize Loki log extractor (Stage 2)
    log_extractor = LokiLogExtractor(LOKI_URL)

    # Initialise metrics tracker
    metrics_tracker = MetricsTracker()

    # ── Start REST API server in background thread ────────────────
    threading.Thread(
        target=lambda: uvicorn.run(api_module.app, host="0.0.0.0", port=8082, log_level="warning"),
        daemon=True,
    ).start()
    log.info("API server started on port 8080")

    try:
        while True:
            try:
                msg = consumer.poll(timeout=1.0)
                if msg is None or msg.error():
                    continue

                record = json.loads(msg.value().decode("utf-8"))
                if "type" in record and record["type"] == "reset":
                    log.info("Received metrics reset command")
                    metrics_tracker.reset_metrics()
                    continue
                if not "start_dt" in record or not "end_dt" in record or not "record_timestamp" in record:
                    log.error("Missing start_dt or end_dt or record_timestamp in record")
                    continue

                # Convert timestamps to datetime objects
                start_dt = datetime.fromisoformat(record.get("start_dt"))
                end_dt = datetime.fromisoformat(record.get("end_dt"))
                app_id = record.get("app_id")
                log.info(f"Processing RCA task: app={app_id}, {start_dt} to {end_dt}")

                # Query spans from S3 (filter by app_id if provided)
                if PERF_MEASUREMENT_ENABLED:
                    start_ns = time.perf_counter_ns()
                spans_df = query_spans_by_timestamp(start_dt, end_dt, app_id)
                if PERF_MEASUREMENT_ENABLED:
                    end_ns = time.perf_counter_ns()
                    log.info(f"Queried spans in {(end_ns - start_ns) / 1e9:.2f} seconds")

                if spans_df is None or spans_df.empty:
                    log.warning("No spans found for the given time range")
                    continue
                
                if PERF_MEASUREMENT_ENABLED:
                    start_ns = time.perf_counter_ns()
                traces = build_trace_dags_from_csv(spans_df)
                ranking = rank_root_causes(traces, kb)
                if PERF_MEASUREMENT_ENABLED:
                    rca_processed_time = time.perf_counter_ns() - start_ns
                else:
                    rca_processed_time = None

                log.info(f"Stage 1 ranking: {ranking}")

                # ── Stage 2: Log Evidence + LLM Analysis ──────────────
                llm_result = None
                logs = {}
                try:
                    top_k_services = [svc for svc, _ in ranking[:3]]
                    from datetime import timedelta
                    log_start = start_dt - timedelta(minutes=0.25)
                    log_end = end_dt
                    logs = log_extractor.query_logs_for_services(
                        top_k_services, log_start, log_end
                    )
                    llm_result = llm_rca.analyze_with_consistency(
                        ranking, traces, logs, n_samples=LLM_N_SAMPLES
                    )
                    log.info(
                        f"Stage 2 result: root_cause={llm_result['root_cause']}, "
                        f"confidence_level={llm_result['confidence_level']}"
                    )
                except Exception as e:
                    log.error(f"Stage 2 failed, falling back to Stage 1: {e}", exc_info=True)

                send_rca_notification(app_id, ranking, start_dt, end_dt, llm_result)

                # ── Save incident to S3 ──────────────────────────
                try:
                    inc = incident_store.build_incident(
                        ranking, llm_result, logs, traces, start_dt, end_dt, app_id
                    )
                    incident_store.save_incident(inc)
                except Exception as e:
                    log.error(f"Failed to save incident: {e}")

                if PERF_MEASUREMENT_ENABLED:
                    metrics_tracker.calculate_performance_metrics(spans_df, record["record_timestamp"], rca_processed_time)

            except Exception as e:
                log.error(f"Error processing RCA task: {e}", exc_info=True)
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down RCA Service...")
    finally:
        consumer.close()
        clickhouse_client.disconnect()

if __name__ == "__main__":
    main()