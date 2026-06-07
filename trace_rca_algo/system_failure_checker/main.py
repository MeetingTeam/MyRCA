import os
import logging
import json
import time
import requests
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from confluent_kafka import Producer
import uvicorn
import time
from clickhouse_driver import Client as ClickHouseClient

# ── Configuration ─────────────────────────────────────────────────────────────
KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "localhost:19092")
OUTPUT_TOPIC = os.getenv("INPUT_TOPIC", "rca-task-data")

FAILURE_THRESHOLD = float(os.getenv("FAILURE_THRESHOLD", "0.5"))
MINIMUM_ANOMALY_SPANS = int(os.getenv("MINIMUM_ANOMALY_SPANS", "10"))
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "1"))
TIME_WINDOW_MINUTES = int(os.getenv("TIME_WINDOW_MINUTES", "1"))
DELAY_MINUTES = int(os.getenv("DELAY_MINUTES", "1"))
APSCHEDULER_MAX_INSTANCES = int(os.getenv("APSCHEDULER_MAX_INSTANCES", "3"))
APSCHEDULER_MISFIRE_GRACE_TIME = int(os.getenv("APSCHEDULER_MISFIRE_GRACE_TIME", "30"))

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# ClickHouse config
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "9000"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "default")

# ── Global Objects ──────────────────────────────────────────────────────────
app = FastAPI(title="System Failure Checker", version="1.1.0")
scheduler = BackgroundScheduler()

producer = Producer({
    "bootstrap.servers": KAFKA_BROKERS,
    "linger.ms": 50
})

clickhouse_client = ClickHouseClient(
    host=CLICKHOUSE_HOST,
    port=CLICKHOUSE_PORT,
    user=CLICKHOUSE_USER,
    password=CLICKHOUSE_PASSWORD,
    database=CLICKHOUSE_DATABASE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("system-failure-checker")

# ── Helper Functions ────────────────────────────────────────────────────────
def _delivery_report(err, msg):
    if err:
        log.error("Kafka Delivery failed: %s", err)

def send_failure_notification(app_id, abnormal_services, start_dt, end_dt):
    if not DISCORD_WEBHOOK_URL: return
    
    start_ts = int(start_dt.replace(tzinfo=timezone.utc).timestamp())
    end_ts = int(end_dt.replace(tzinfo=timezone.utc).timestamp())
    discord_time = f"<t:{start_ts}:f> to <t:{end_ts}:t>"
    
    message = f"""
## ⚡ Alert: System Failure
`Time Window:` {discord_time}
`Status:` 🔍 **Running RCA Algorithm**
`App ID:` {app_id}
`Failure Services:` {', '.join(abnormal_services)}
    """
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=5).raise_for_status()
    except Exception as e:
        log.error(f"Discord notification failed: {e}")

# ── Core Logic ──────────────────────────────────────────────────────────────
def check_system_failures(start_dt, end_dt, record_timestamp):
    """Query ClickHouse anomalies table."""
    try:
        start_ts_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        end_ts_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")
        print(f"Querying spans from {start_ts_str} to {end_ts_str}...")

        query = """
            SELECT
                app_id,
                service,
                operation,
                AVG(is_anomaly) AS abnormal_ratio
            FROM anomalies
            WHERE timestamp >= %(start_dt)s AND timestamp < %(end_dt)s
            GROUP BY app_id, service, operation
            HAVING SUM(is_anomaly) > %(min_anomaly_spans)s
        """

        params = {
            "start_dt": start_dt,
            "end_dt": end_dt,
            "min_anomaly_spans": MINIMUM_ANOMALY_SPANS,
        }

        result = clickhouse_client.query_dataframe(query, params=params)

        if result.empty:
            log.info("No anomalies found in window %s to %s", start_ts_str, end_ts_str)
            return

        failures = result[result['abnormal_ratio'] > FAILURE_THRESHOLD]
        if failures.empty:
            log.info("No failures above threshold in window %s to %s", start_ts_str, end_ts_str)
            return

        for app_id in failures['app_id'].unique():
            app_failures = failures[failures['app_id'] == app_id]
            abnormal_services = app_failures['service'].unique().tolist()
            log.warning("FAILURE DETECTED for app=%s: %s", app_id, abnormal_services)
            record = {
                "app_id": app_id,
                "start_dt": start_dt.isoformat(),
                "end_dt": end_dt.isoformat(),
                "record_timestamp": record_timestamp
            }
            producer.produce(OUTPUT_TOPIC, json.dumps(record).encode("utf-8"), callback=_delivery_report)
            send_failure_notification(app_id, abnormal_services, start_dt, end_dt)

        producer.flush()

    except Exception as e:
        log.error("Error in check_system_failures: %s", e, exc_info=True)

def check_current_failure():
    record_timestamp = time.time_ns()
    end_dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=DELAY_MINUTES)
    start_dt = end_dt - timedelta(minutes=TIME_WINDOW_MINUTES)
    check_system_failures(start_dt, end_dt, record_timestamp)

# ── Lifecycle ───────────────────────────────────────────────────────────────
@app.on_event("startup")
def startup_event():
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
    clickhouse_client.disconnect()
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