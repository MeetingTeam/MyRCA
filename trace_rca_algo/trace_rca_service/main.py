from algo import rank_root_causes
from preproccessing import build_trace_dags_from_csv
import os
from confluent_kafka import Consumer, KafkaError, KafkaException
import json
import duckdb
from datetime import datetime, timezone
import boto3
from urllib.parse import urlparse
import requests
import logging

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

        print(f"Found {len(result_df)} spans between {start_dt} and {end_dt}")
        return result_df

    except Exception as e:
        print(f"Error querying spans: {e}")
        return None

def send_rca_notification(ranking, start_dt: datetime, end_dt: datetime):
    """Post the RCA ranking results to a Discord channel via webhook."""
    if not DISCORD_WEBHOOK_URL:
        print("Discord webhook URL not configured, skipping notification")
        return

    rank_text = ""
    for i, (svc, score) in enumerate(ranking[:3]): # Take up to 3
        medals = ["1️⃣", "2️⃣", "3️⃣"]
        rank_text += f"{medals[i]} `{svc}` (Score: {score:.4f})\n"
    
    # Discord Dynamic Markdown (Best for users in different timezones)
    start_ts = int(start_dt.replace(tzinfo=timezone.utc).timestamp())
    end_ts = int(end_dt.replace(tzinfo=timezone.utc).timestamp())
    discord_time = f"<t:{start_ts}:f> to <t:{end_ts}:t>"

    message = f"""
🚨 **System Failure Detected**
**Time Window:** {discord_time}

**Top 3 Root Cause Microservices:**
{rank_text}

    """
    
    payload = {"content": message}
    
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
        resp.raise_for_status()
        print("Sent RCA notification to Discord")
    except Exception as e:
        print(f"Failed to send Discord notification: {e}")

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

    # Load Knowledge Base from S3
    kb = fetch_s3_json(S3_KB_PATH)
    # Initialize DuckDB S3 connection
    init_duckdb_s3()
    
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
                    print("No spans found for the given time range")
                    continue
                
                traces = build_trace_dags_from_csv(spans_df)  # This will prepare the data structure for RCA
                ranking = rank_root_causes(traces, kb)
                print(f"RCA ranking: {ranking}")

                send_rca_notification(ranking, start_dt, end_dt)

            except Exception as e:
                log.error(f"Error processing RCA task: {e}", exc_info=True)
    except Exception:
        log.info("Shutting down RCA Service...")
    finally:
        consumer.close()
        db_con.close()

if __name__ == "__main__":
    main()
