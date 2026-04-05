from algo import rank_root_causes
from preproccessing import build_trace_dags_from_csv
from log_extractor import LokiLogExtractor
import llm_rca
import os
from confluent_kafka import Consumer, KafkaError, KafkaException
import json
import duckdb
from datetime import datetime, timezone
import requests
import logging
from mlflow import MlflowClient

# ── Configuration ─────────────────────────────────────────────────────────────

KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "localhost:19092")
INPUT_TOPIC = os.getenv("INPUT_TOPIC", "rca-task-data")
CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "rca-service-group")

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "s3.amazonaws.com")
S3_REGION = os.getenv("S3_REGION", "ap-southeast-7")
S3_BUCKET = os.getenv("S3_BUCKET", "kltn-anomaly-dateset")
S3_USE_SSL = os.getenv("S3_USE_SSL", "true").lower() == "true"
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

S3_KB_PATH = os.getenv("S3_KB_PATH", "s3://kltn-anomaly-dateset/knowledge_base.json")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
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

def fetch_kb_from_mlflow(model_name):
    """
    Fetches the Knowledge Base from MLflow using the production alias.
    Returns the KB dictionary loaded from the model's artifacts.
    """
    client = MlflowClient()
    
    try:
        # Get the model version with the production alias
        model_version = client.get_model_version_by_alias(
            name=model_name,
            alias="production"
        )
        run_id = model_version.run_id
        log.info(f"Found production KB model version {model_version.version} from run {run_id}")
        
        # Download the KB artifact from the run
        # The artifact is stored at kb_model/artifacts/kb_json
        artifact_path = client.download_artifacts(run_id, "kb_model")
        kb_file = os.path.join(artifact_path, "artifacts", "kb_json")
        
        # Load the KB JSON
        with open(kb_file, "r") as f:
            kb = json.load(f)
        
        log.info(f"Successfully loaded KB from MLflow (version {model_version.version})")
        return kb
        
    except Exception as e:
        log.error(f"Failed to fetch KB from MLflow: {e}", exc_info=True)
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

        result_df = db_con.cursor().execute(query, params).fetchdf()

        log.info(f"Found {len(result_df)} spans between {start_dt} and {end_dt}")
        return result_df

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

    # Load Knowledge Base from MLflow (production alias)
    kb = fetch_kb_from_mlflow(MLFLOW_KB_MODEL)
    # Initialize DuckDB S3 connection
    init_duckdb_s3()
    # Initialize Loki log extractor (Stage 2)
    log_extractor = LokiLogExtractor(LOKI_URL)
    
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
                try:
                    top_k_services = [svc for svc, _ in ranking[:5]]
                    logs = log_extractor.query_logs_for_services(
                        top_k_services, start_dt, end_dt
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

            except Exception as e:
                log.error(f"Error processing RCA task: {e}", exc_info=True)
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down RCA Service...")
    finally:
        consumer.close()
        db_con.close()

if __name__ == "__main__":
    main()
