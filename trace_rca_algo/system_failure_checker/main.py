"""
System Failure Checker Service
──────────────────────────────
FastAPI service with APScheduler that:
  1. Every minute, queries S3 anomaly data via DuckDB
  2. Counts abnormal/total spans per service/operation group
  3. Prints "failure system" if abnormal ratio exceeds threshold
"""

import os
import logging
from datetime import datetime, timedelta

import duckdb
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from confluent_kafka import Producer, KafkaError, KafkaException
import json
import requests

# ── Configuration ─────────────────────────────────────────────────────────────
KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "localhost:19092")
OUTPUT_TOPIC = os.getenv("INPUT_TOPIC", "rca-task-data")

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "s3.amazonaws.com")
S3_REGION = os.getenv("S3_REGION", "ap-southeast-7")
S3_BUCKET = os.getenv("S3_BUCKET", "kltn-anomaly-dateset")
S3_USE_SSL = os.getenv("S3_USE_SSL", "true").lower() == "true"
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

FAILURE_THRESHOLD = float(os.getenv("FAILURE_THRESHOLD", "0.7"))
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "1"))
TIME_WINDOW_MINUTES = int(os.getenv("TIME_WINDOW_MINUTES", "1"))
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# ── Setup ──────────────────────────────────────────────────────────
scheduler = BackgroundScheduler()

producer = Producer({
        "bootstrap.servers": KAFKA_BROKERS,
        "linger.ms": 50
})

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("system-failure-checker")

app = FastAPI(title="System Failure Checker", version="1.0.0")

def _delivery_report(err, msg):
    if err:
        log.error("Delivery failed for key=%s: %s", msg.key(), err)

def send_failure_notification(start_dt: datetime, end_dt: datetime):
    """Post the system failure alert to a Discord channel via webhook."""
    if not DISCORD_WEBHOOK_URL:
        print("Discord webhook URL not configured, skipping notification")
        return
    
    # Discord Dynamic Markdown (Best for users in different timezones)
    # <t:SECONDS:f> displays a short date/time like "March 8, 2024 10:30 PM"
    discord_time = f"<t:{int(start_dt.timestamp())}:f> to <t:{int(end_dt.timestamp())}:t>"

    message = f"""
🚨 **System Failure Detected**
**Time Window:** {discord_time}
    Start running RCA algorithm to identify root causes and impacted services.
    """
    payload = {"content": message}
    
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
        resp.raise_for_status()
        print("Sent RCA notification to Discord")
    except Exception as e:
        print(f"Failed to send Discord notification: {e}")

# ── DuckDB S3 Query Function ─────────────────────────────────────────────────
def check_system_failures(start_dt, end_dt):
    """Query S3 data and check for system failures per service/operation group."""
    try:
        con = duckdb.connect()
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute(f"""
            SET s3_endpoint='{S3_ENDPOINT}';
            SET s3_region='{S3_REGION}';
            SET s3_access_key_id='{AWS_ACCESS_KEY_ID}';
            SET s3_secret_access_key='{AWS_SECRET_ACCESS_KEY}';
            SET s3_use_ssl={'true' if S3_USE_SSL else 'false'};
            SET s3_url_style='path';
        """)

        # Query abnormal/total counts per service/operation
        start_date_str = start_dt.strftime("%Y-%m-%d")
        end_date_str = end_dt.strftime("%Y-%m-%d")
        start_ts_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        end_ts_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")
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
        
        result = con.execute(query).fetchdf()
        con.close()

        if result.empty:
            log.info("No data found in the last %d minutes", TIME_WINDOW_MINUTES)
            return

        log.info("Checked %d service/operation groups in last %d minutes",
                len(result), TIME_WINDOW_MINUTES)

        failures_found = False
        for _, row in result.iterrows():
            ratio = row['abnormal_ratio']
            # print(f"{row['service']}/{row['operation']} - abnormal ratio: {ratio:.4f} ({int(row['abnormal_spans'])}/{int(row['total_spans'])})")
            if ratio > FAILURE_THRESHOLD:
                log.warning("FAILURE SYSTEM: %s/%s - abnormal ratio %.4f (threshold: %.4f) - %d/%d spans",
                           row['service'], row['operation'], ratio, FAILURE_THRESHOLD,
                           int(row['abnormal_spans']), int(row['total_spans']))
                failures_found = True

        if failures_found:
            log.warning("One or more failure systems detected in the last %d minutes", TIME_WINDOW_MINUTES)
            record = {
                "start_dt": start_dt.isoformat(),
                "end_dt": end_dt.isoformat(),
            }
            producer.produce(
                    topic=OUTPUT_TOPIC,
                    value=json.dumps(record).encode("utf-8"),
                    callback=_delivery_report,
            )
            producer.flush()

            # Send notification to Discord channel
            send_failure_notification(start_dt, end_dt)

    except Exception as e:
        log.error("Error checking system failures: %s", e, exc_info=True)

def check_current_failure():
    """Check for failures in the last TIME_WINDOW_MINUTES minutes."""
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(minutes=TIME_WINDOW_MINUTES)
    check_system_failures(start_dt, end_dt)

@app.on_event("startup")
def startup_event():
    """Start the scheduler when FastAPI starts."""
    scheduler.add_job(
        check_current_failure,
        trigger=IntervalTrigger(hours=CHECK_INTERVAL_MINUTES),
        id="failure_check",
        name="Check System Failures",
        replace_existing=True
    )
    scheduler.start()
    log.info("System Failure Checker started - checking every %d minutes", CHECK_INTERVAL_MINUTES)

@app.on_event("shutdown")
def shutdown_event():
    """Shutdown the scheduler when FastAPI stops."""
    scheduler.shutdown()
    log.info("System Failure Checker shutdown")

# ── API Endpoints ────────────────────────────────────────────────────────────
@app.get("/healthcheck")
def health_check():
    """Health check endpoint to verify service is running."""
    return {"message": "Service is healthy"}

@app.get("/debug")
def debug():
    """Debug"""
    check_current_failure()
    return {"message": "Manual check completed"}

@app.get("/status")
def get_status():
    """Get scheduler status."""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time),
            "trigger": str(job.trigger)
        })

    return {
        "scheduler_running": scheduler.running,
        "jobs": jobs,
        "config": {
            "threshold": FAILURE_THRESHOLD,
            "interval_minutes": CHECK_INTERVAL_MINUTES,
            "time_window_minutes": TIME_WINDOW_MINUTES,
            "s3_bucket": S3_BUCKET
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
