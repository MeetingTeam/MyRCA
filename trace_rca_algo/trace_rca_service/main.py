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
from mlflow import MlflowClient
import mlflow
import boto3
from urllib.parse import urlparse

# ── Configuration ─────────────────────────────────────────────────────────────

KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "localhost:19092")
INPUT_TOPIC = os.getenv("INPUT_TOPIC", "rca-task-data")
CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "rca-service-group")

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "s3.amazonaws.com")
S3_REGION = os.getenv("S3_REGION", "ap-southeast-1")
S3_BUCKET = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")
S3_USE_SSL = os.getenv("S3_USE_SSL", "true").lower() == "true"
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

S3_KB_PATH = os.getenv("S3_KB_PATH", "s3://kltn-anomaly-dateset-1/knowledge_base.json")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:15000")
MLFLOW_KB_MODEL = os.getenv("MLFLOW_KB_MODEL", "rca-knowledge-base")
LOKI_URL = os.getenv("LOKI_URL", "http://loki.loki.svc.cluster.local:3100")
LLM_N_SAMPLES = int(os.getenv("LLM_N_SAMPLES", "3"))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("trace-rca-service")
# Persistent global DuckDB connection
db_con = duckdb.connect(database=':memory:') 

# ── Setup ──────────────────────────────────────────────────────────

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

def fetch_kb_from_s3(s3_path):
    """Fetch Knowledge Base JSON directly from S3 via DuckDB."""
    log.info(f"Loading KB from S3: {s3_path}")
    result = db_con.execute(f"SELECT * FROM read_json_auto('{s3_path}')").fetchdf()
    kb = json.loads(result.to_json(orient="records"))[0]
    log.info(f"Successfully loaded KB from S3 ({len(kb)} entries)")
    return kb

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

def fetch_kb_from_mlflow(model_name):
    """
    Fetches the Knowledge Base from MLflow using the production alias.
    Falls back to S3_KB_PATH if MLflow is unavailable.
    """
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = MlflowClient()

    try:
        model_version = client.get_model_version_by_alias(
            name=model_name,
            alias="production"
        )
        run_id = model_version.run_id
        log.info(f"Found production KB model version {model_version.version} from run {run_id}")
        
        # Download the KB artifact from the run
        # The artifact is stored at kb_model/artifacts/kb_json
        kb_file = client.download_artifacts(run_id, "kb_model/artifacts/built_kb.json", dst_path="./mlflow_artifacts")
        
        # Load the KB JSON
        with open(kb_file, "r") as f:
            kb = json.load(f)

        log.info(f"Successfully loaded KB from MLflow (version {model_version.version})")
        return kb

    except Exception as e:
        log.warning(f"MLflow KB fetch failed: {e}")
        if S3_KB_PATH:
            log.info("Falling back to S3 KB path...")
            return fetch_kb_from_s3(S3_KB_PATH)
        raise

def query_spans_by_timestamp(start_dt, end_dt):
    """
    Query spans from S3 within the given timestamp range.
    Returns DataFrame with span data.
    """
    try:
        # Query spans within timestamp range
        query = f"""
            WITH anomalous_traces AS (
                SELECT DISTINCT trace_id 
                FROM 's3://{S3_BUCKET}/anomalies/data.parquet/**/*.parquet'
                WHERE date_part BETWEEN ? AND ?
                AND is_anomaly = True
                AND "timestamp" BETWEEN ? AND ?
            )
            SELECT * FROM 's3://{S3_BUCKET}/anomalies/data.parquet/**/*.parquet'
            WHERE date_part BETWEEN ? AND ?
            AND trace_id IN (SELECT trace_id FROM anomalous_traces)
        """

        # Pass parameters safely to DuckDB
        params = [
            start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"),
            start_dt, end_dt,
            start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")
        ]

        # Retry on transient read errors (race condition: anomaly-detection
        # service may be overwriting the parquet file on S3 mid-read).
        max_retries = 6
        for attempt in range(max_retries):
            try:
                result_df = db_con.cursor().execute(query, params).fetchdf()
                log.info(f"Found {len(result_df)} spans between {start_dt} and {end_dt}")
                return result_df
            except (UnicodeDecodeError, duckdb.IOException) as read_err:
                if attempt < max_retries - 1:
                    log.warning("Transient S3 read error (attempt %d/%d): %s", attempt + 1, max_retries, read_err)
                    time.sleep(1)
                else:
                    log.warning("S3 read failed after %d attempts, skipping", max_retries)
                    return None

    except Exception as e:
        log.error(f"Error querying spans: {e}")
        return None

def send_rca_notification(
    ranking, start_dt: datetime, end_dt: datetime, llm_result: dict | None = None
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

    # Initialize DuckDB S3 connection (must be before KB fetch for S3 fallback)
    init_duckdb_s3()
    # Load Knowledge Base from MLflow (falls back to S3_KB_PATH)
    kb = fetch_s3_json(S3_KB_PATH)
    # Initialize Loki log extractor (Stage 2)
    log_extractor = LokiLogExtractor(LOKI_URL)

    # ── Start REST API server in background thread ────────────────
    api_module.set_db_con(db_con)
    threading.Thread(
        target=lambda: uvicorn.run(api_module.app, host="0.0.0.0", port=8080, log_level="warning"),
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
                if not "start_dt" in record or not "end_dt" in record:
                    log.error("Missing start_dt or end_dt in record")
                    continue
                
                # Convert timestamps to datetime objects
                start_dt = datetime.fromisoformat(record.get("start_dt"))
                end_dt = datetime.fromisoformat(record.get("end_dt"))
                log.info(f"Processing RCA task: {start_dt} to {end_dt}")

                # Query spans from S3
                spans_df = query_spans_by_timestamp(start_dt, end_dt)

                if spans_df is None or spans_df.empty:
                    log.warning("No spans found for the given time range")
                    continue
                
                traces = build_trace_dags_from_csv(spans_df)
                ranking = rank_root_causes(traces, kb)
                log.info(f"Stage 1 ranking: {ranking}")

                # ── Stage 2: Log Evidence + LLM Analysis ──────────────
                llm_result = None
                logs = {}
                try:
                    top_k_services = [svc for svc, _ in ranking[:5]]
                    from datetime import timedelta
                    log_start = start_dt - timedelta(minutes=5)
                    log_end = end_dt + timedelta(minutes=5)
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

                send_rca_notification(ranking, start_dt, end_dt, llm_result)

                # ── Save incident to S3 ──────────────────────────
                try:
                    inc = incident_store.build_incident(
                        ranking, llm_result, logs, traces, start_dt, end_dt
                    )
                    incident_store.save_incident(inc)
                except Exception as e:
                    log.error(f"Failed to save incident: {e}")

            except Exception as e:
                log.error(f"Error processing RCA task: {e}", exc_info=True)
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down RCA Service...")
    finally:
        consumer.close()
        db_con.close()

if __name__ == "__main__":
    main()
