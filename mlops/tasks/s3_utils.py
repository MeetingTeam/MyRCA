"""
S3 utilities for the MLOps pipeline.
Uses boto3 + pyarrow for Parquet operations (DuckDB removed).
"""
import io
import os
from datetime import datetime, timedelta, timezone

import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

DRIFT_WINDOW_MINUTES = int(os.getenv("DRIFT_WINDOW_MINUTES", "1440"))

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "s3.amazonaws.com")
S3_REGION = os.getenv("S3_REGION", "ap-southeast-1")
S3_BUCKET = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")

_s3_client = None


def get_s3_client():
    """Return a boto3 S3 client (cached)."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3", region_name=S3_REGION)
    return _s3_client


def s3_path(relative: str) -> str:
    """Build a full S3 path from a relative path within the bucket."""
    return f"s3://{S3_BUCKET}/{relative}"


def read_parquet_from_s3(s3_uri: str) -> pd.DataFrame:
    """Read a Parquet file from S3 and return a pandas DataFrame.

    Args:
        s3_uri: Full S3 URI (s3://bucket/key) or just the key
    """
    if s3_uri.startswith("s3://"):
        parts = s3_uri[5:].split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""
    else:
        bucket = S3_BUCKET
        key = s3_uri

    client = get_s3_client()
    response = client.get_object(Bucket=bucket, Key=key)
    buffer = io.BytesIO(response["Body"].read())
    return pd.read_parquet(buffer)


def write_parquet_to_s3(df: pd.DataFrame, s3_uri: str):
    """Write a pandas DataFrame to S3 as Parquet.

    Args:
        df: DataFrame to write
        s3_uri: Full S3 URI (s3://bucket/key) or just the key
    """
    if s3_uri.startswith("s3://"):
        parts = s3_uri[5:].split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""
    else:
        bucket = S3_BUCKET
        key = s3_uri

    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False)
    buffer.seek(0)

    client = get_s3_client()
    client.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())


def list_partition_dirs(prefix: str) -> list[str]:
    """List hive partition directories under a prefix.

    Returns partition values (e.g. ['2026-03-22', '2026-03-23']).
    """
    client = get_s3_client()
    paginator = client.get_paginator("list_objects_v2")
    partitions = set()
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            part_dir = cp["Prefix"].rstrip("/").split("/")[-1]
            if "=" in part_dir:
                partitions.add(part_dir.split("=", 1)[1])
    return sorted(partitions)


def list_s3_keys(prefix: str) -> list[str]:
    """List all object keys under a prefix."""
    client = get_s3_client()
    paginator = client.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def delete_s3_keys(keys: list[str]):
    """Batch-delete S3 keys (up to 1000 per request)."""
    client = get_s3_client()
    for i in range(0, len(keys), 1000):
        batch = [{"Key": k} for k in keys[i:i + 1000]]
        client.delete_objects(Bucket=S3_BUCKET, Delete={"Objects": batch})


def list_s3_versions(prefix: str) -> list[str]:
    """List versioned directories under a prefix."""
    client = get_s3_client()
    paginator = client.get_paginator("list_objects_v2")
    versions = []
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            versions.append(cp["Prefix"])
    return versions


def list_recent_s3_keys(prefix: str, minutes: int = DRIFT_WINDOW_MINUTES) -> list[str]:
    """List S3 keys modified in last N minutes."""
    client = get_s3_client()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    keys = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["LastModified"].replace(tzinfo=timezone.utc) > cutoff:
                keys.append(obj["Key"])
    return keys


def write_json_to_s3(data: dict, s3_key: str):
    """Write a JSON object to S3."""
    import json
    client = get_s3_client()
    client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=json.dumps(data),
        ContentType="application/json",
    )
