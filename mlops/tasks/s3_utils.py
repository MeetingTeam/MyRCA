"""
DuckDB S3 helpers for the MLOps pipeline.
Reuses the pattern from anomaly_detection_service.py.
"""

import os
import duckdb
import boto3


S3_ENDPOINT = os.getenv("S3_ENDPOINT", "s3.amazonaws.com")
S3_REGION = os.getenv("S3_REGION", "ap-southeast-1")
S3_BUCKET = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")
S3_USE_SSL = os.getenv("S3_USE_SSL", "true").lower() == "true"
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")


def get_duckdb_connection() -> duckdb.DuckDBPyConnection:
    """Return a DuckDB connection with S3/httpfs configured."""
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
    return con


def read_parquet_from_s3(s3_path: str, where_clause: str = "") -> "pd.DataFrame":
    """Read a Parquet dataset from S3 via DuckDB and return a pandas DataFrame."""
    import pandas as pd
    con = get_duckdb_connection()
    query = f"SELECT * FROM read_parquet('{s3_path}', hive_partitioning=1, union_by_name=1)"
    if where_clause:
        query += f" WHERE {where_clause}"
    df = con.execute(query).fetchdf()
    con.close()
    return df


def write_parquet_to_s3(df: "pd.DataFrame", s3_path: str):
    """Write a pandas DataFrame to S3 as Parquet via DuckDB."""
    con = get_duckdb_connection()
    con.register("df_to_write", df)
    con.execute(f"""
        COPY df_to_write TO '{s3_path}'
        (FORMAT PARQUET);
    """)
    con.close()


def s3_path(relative: str) -> str:
    """Build a full S3 path from a relative path within the bucket."""
    return f"s3://{S3_BUCKET}/{relative}"


def get_s3_client():
    """Return a boto3 S3 client configured from env vars."""
    return boto3.client("s3", region_name=S3_REGION)


def list_partition_dirs(prefix: str) -> list[str]:
    """List hive partition directories under a prefix using boto3.

    Returns partition values (e.g. ['2026-03-22', '2026-03-23']).
    Much faster than DuckDB glob for buckets with many small files.
    """
    client = get_s3_client()
    paginator = client.get_paginator("list_objects_v2")
    partitions = set()
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            # Extract partition value from "anomalies/data.parquet/date_part=2026-03-22/"
            part_dir = cp["Prefix"].rstrip("/").split("/")[-1]
            if "=" in part_dir:
                partitions.add(part_dir.split("=", 1)[1])
    return sorted(partitions)


def list_s3_keys(prefix: str) -> list[str]:
    """List all object keys under a prefix using boto3."""
    client = get_s3_client()
    paginator = client.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def delete_s3_keys(keys: list[str]):
    """Batch-delete S3 keys using boto3 (up to 1000 per request)."""
    client = get_s3_client()
    # S3 delete_objects accepts max 1000 keys per call
    for i in range(0, len(keys), 1000):
        batch = [{"Key": k} for k in keys[i:i + 1000]]
        client.delete_objects(Bucket=S3_BUCKET, Delete={"Objects": batch})


def list_s3_versions(prefix: str) -> list[str]:
    """List versioned directories under a prefix using boto3."""
    client = get_s3_client()
    paginator = client.get_paginator("list_objects_v2")
    versions = []
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            versions.append(cp["Prefix"])
    return versions
