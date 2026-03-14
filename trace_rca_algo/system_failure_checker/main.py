import os
import logging
import json
import requests
import duckdb
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from confluent_kafka import Producer
import uvicorn

# ── Configuration ─────────────────────────────────────────────────────────────
KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "localhost:19092")
OUTPUT_TOPIC = os.getenv("INPUT_TOPIC", "rca-task-data")

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "s3.amazonaws.com")
S3_REGION = os.getenv("S3_REGION", "ap-southeast-7")
S3_BUCKET = os.getenv("S3_BUCKET", "kltn-anomaly-dateset")
S3_USE_SSL = os.getenv("S3_USE_SSL", "true").lower() == "true"
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

FAILURE_THRESHOLD = float(os.getenv("FAILURE_THRESHOLD", "0.5"))
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "1"))
TIME_WINDOW_MINUTES = int(os.getenv("TIME_WINDOW_MINUTES", "1"))
APSCHEDULER_MAX_INSTANCES = int(os.getenv("APSCHEDULER_MAX_INSTANCES", "3"))
APSCHEDULER_MISFIRE_GRACE_TIME = int(os.getenv("APSCHEDULER_MISFIRE_GRACE_TIME", "30"))

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# ── Global Objects ──────────────────────────────────────────────────────────
app = FastAPI(title="System Failure Checker", version="1.1.0")
scheduler = BackgroundScheduler()
# Persistent global DuckDB connection
db_con = duckdb.connect(database=':memory:') 

producer = Producer({
    "bootstrap.servers": KAFKA_BROKERS,
    "linger.ms": 50
})

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("system-failure-checker")

# ── Helper Functions ────────────────────────────────────────────────────────
def _delivery_report(err, msg):
    if err:
        log.error("Kafka Delivery failed: %s", err)

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

def send_failure_notification(abnormal_services, start_dt, end_dt):
    if not DISCORD_WEBHOOK_URL: return
    
    start_ts = int(start_dt.replace(tzinfo=timezone.utc).timestamp())
    end_ts = int(end_dt.replace(tzinfo=timezone.utc).timestamp())
    discord_time = f"<t:{start_ts}:f> to <t:{end_ts}:t>"
    
    message = f"""
## ⚡ Alert: System Failure
`Time Window:` {discord_time}
`Status:` 🔍 **Running RCA Algorithm**
`Failure Services:` {', '.join(abnormal_services)}
    """
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=5).raise_for_status()
    except Exception as e:
        log.error(f"Discord notification failed: {e}")

# ── Core Logic ──────────────────────────────────────────────────────────────
def check_system_failures(start_dt, end_dt):
    """Query S3 data using the persistent global connection."""
    try:
        # Optimization: Use Hive Partitioning (date_part) to prune S3 files
        start_date_str = start_dt.strftime("%Y-%m-%d")
        end_date_str = end_dt.strftime("%Y-%m-%d")
        start_ts_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        end_ts_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")
        print(f"Querying spans from {start_ts_str} to {end_ts_str}...")

        query = f"""
            SELECT
                service,
                operation,
                COUNT(*) as total_spans,
                SUM(is_anomaly::INT) as abnormal_spans,
                ROUND(AVG(is_anomaly::INT), 4) as abnormal_ratio
            FROM read_parquet('s3://{S3_BUCKET}/anomalies/data.parquet/*/*.parquet', hive_partitioning = 1)
            WHERE date_part BETWEEN '{start_date_str}' AND '{end_date_str}'
              AND "timestamp" BETWEEN '{start_ts_str}'::TIMESTAMP AND '{end_ts_str}'::TIMESTAMP
            GROUP BY service, operation
            HAVING abnormal_spans > 0
            ORDER BY abnormal_ratio DESC
        """
        
        # Use a cursor for thread-safety if multiple instances run
        result = db_con.cursor().execute(query).fetchdf()

        if result.empty:
            log.info("No anomalies found in window %s to %s", start_ts_str, end_ts_str)
            return

        abnormal_services = result[result['abnormal_ratio'] > FAILURE_THRESHOLD]['service'].unique().tolist()

        if abnormal_services:
            log.warning("FAILURE DETECTED: %s", abnormal_services)
            record = {"start_dt": start_dt.isoformat(), "end_dt": end_dt.isoformat()}
            producer.produce(OUTPUT_TOPIC, json.dumps(record).encode("utf-8"), callback=_delivery_report)
            producer.flush()
            send_failure_notification(abnormal_services, start_dt, end_dt)

    except Exception as e:
        log.error("Error in check_system_failures: %s", e, exc_info=True)

def check_current_failure():
    end_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    start_dt = end_dt - timedelta(minutes=TIME_WINDOW_MINUTES)
    check_system_failures(start_dt, end_dt)

# ── Lifecycle ───────────────────────────────────────────────────────────────
@app.on_event("startup")
def startup_event():
    init_duckdb_s3()
    scheduler.add_job(
        check_current_failure,
        trigger=IntervalTrigger(minutes=CHECK_INTERVAL_MINUTES),
        id="failure_check",
        replace_existing=True,
        max_instances=APSCHEDULER_MAX_INSTANCES,
        misfire_grace_time=APSCHEDULER_MISFIRE_GRACE_TIME
    )
    scheduler.start()
    log.info("Service started. Interval: %dm, Threshold: %f", CHECK_INTERVAL_MINUTES, FAILURE_THRESHOLD)

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()
    db_con.close()
    log.info("Service shutdown.")

# ── Endpoints ───────────────────────────────────────────────────────────────
@app.get("/debug")
def debug(
    start_dt: datetime = None,
    end_dt: datetime = None
):
    """Debug"""
    check_system_failures(start_dt, end_dt)
    return {"message": "Manual check completed"}

@app.get("/healthcheck")
def get_healthcheck():
    return { "status": "ok" }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)