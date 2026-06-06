"""
ClickHouse utilities for MLOps pipeline.
Replaces DuckDB S3 queries with direct ClickHouse queries.
Works for both K8s (internal DNS) and AWS Batch (NodePort).
"""
import os
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
from clickhouse_driver import Client

log = logging.getLogger(__name__)

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "clickhouse-cluster-client.clickhouse.svc.cluster.local")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "9000"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "default")

_client = None


def get_clickhouse_client() -> Client:
    """Get or create ClickHouse client (singleton pattern)."""
    global _client
    if _client is None:
        _client = Client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            user=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            database=CLICKHOUSE_DATABASE,
        )
        log.info("ClickHouse client connected to %s:%s", CLICKHOUSE_HOST, CLICKHOUSE_PORT)
    return _client


def query_to_dataframe(query: str) -> pd.DataFrame:
    """Execute query and return pandas DataFrame."""
    client = get_clickhouse_client()
    result, columns = client.execute(query, with_column_types=True)
    col_names = [c[0] for c in columns]
    return pd.DataFrame(result, columns=col_names)


def load_anomaly_data(window_days: int) -> pd.DataFrame:
    """Load anomaly data from ClickHouse for the last N days.

    ClickHouse auto-routes to EBS (hot) or S3 (cold) transparently.
    Column aliases maintain compatibility with existing preprocessing code.
    """
    query = f"""
        SELECT
            timestamp,
            app_id,
            trace_id AS traceId,
            span_id AS spanId,
            parent_span_id AS parentSpanId,
            service,
            operation,
            http_status,
            duration_ns AS duration,
            kind,
            span_status,
            anomaly_score,
            is_anomaly
        FROM anomalies
        WHERE timestamp >= now() - INTERVAL {window_days} DAY
        ORDER BY timestamp
    """
    log.info("Loading anomaly data from ClickHouse (last %d days)", window_days)
    df = query_to_dataframe(query)
    log.info("Loaded %d rows from ClickHouse", len(df))
    return df


def load_recent_anomaly_data(minutes: int) -> pd.DataFrame:
    """Load recent anomaly data for drift detection.

    ClickHouse auto-routes to correct storage tier.
    """
    query = f"""
        SELECT
            timestamp,
            app_id,
            trace_id AS traceId,
            span_id AS spanId,
            parent_span_id AS parentSpanId,
            service,
            operation,
            http_status,
            duration_ns,
            kind,
            span_status,
            anomaly_score,
            is_anomaly
        FROM anomalies
        WHERE timestamp >= now() - INTERVAL {minutes} MINUTE
        ORDER BY timestamp
    """
    log.info("Loading recent anomaly data from ClickHouse (last %d minutes)", minutes)
    df = query_to_dataframe(query)
    log.info("Loaded %d rows from ClickHouse", len(df))
    return df


def get_anomaly_count(window_days: int) -> int:
    """Get count of anomaly records in time window."""
    query = f"""
        SELECT count() as cnt
        FROM anomalies
        WHERE timestamp >= now() - INTERVAL {window_days} DAY
    """
    df = query_to_dataframe(query)
    return int(df["cnt"].iloc[0]) if len(df) > 0 else 0


def check_clickhouse_connection() -> bool:
    """Check if ClickHouse is reachable."""
    try:
        client = get_clickhouse_client()
        client.execute("SELECT 1")
        return True
    except Exception as e:
        log.error("ClickHouse connection failed: %s", e)
        return False
