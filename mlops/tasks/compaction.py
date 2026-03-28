"""
Step 0: S3 Parquet Compaction
─────────────────────────────
Reads all small parquet files per date partition under anomalies/data.parquet/
and rewrites each partition as a single file. This dramatically reduces the
number of files DuckDB has to open for downstream reads.

Uses boto3 for partition discovery and file cleanup, DuckDB glob for reading.
Runs as the first step of the training pipeline before drift detection.
"""

import logging
import sys

from tasks.s3_utils import (
    S3_BUCKET,
    get_duckdb_connection,
    s3_path,
    list_partition_dirs,
    list_s3_keys,
    delete_s3_keys,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("compaction")

DATA_PREFIX = "anomalies/data.parquet/"


def run():
    log.info("Starting S3 parquet compaction")

    # Use boto3 to discover date partitions (fast, no DuckDB glob)
    partitions = list_partition_dirs(DATA_PREFIX)

    if not partitions:
        log.info("No partitions found, nothing to compact")
        return

    log.info("Found %d date partitions to compact", len(partitions))

    con = get_duckdb_connection()
    total_rows = 0

    for date_val in partitions:
        partition_prefix = f"{DATA_PREFIX}date_part={date_val}/"

        # List files in this partition via boto3
        keys = list_s3_keys(partition_prefix)
        parquet_keys = [k for k in keys if k.endswith(".parquet")]

        if len(parquet_keys) <= 1:
            log.info("Partition date_part=%s: %d file(s), skipping", date_val, len(parquet_keys))
            continue

        log.info("Partition date_part=%s: %d files, compacting...", date_val, len(parquet_keys))

        compact_key = f"{partition_prefix}compacted.parquet"
        compact_s3 = s3_path(f"anomalies/data.parquet/date_part={date_val}/compacted.parquet")

        # Use DuckDB S3 glob pattern instead of inline file list — much faster for large partitions
        glob_pattern = s3_path(f"anomalies/data.parquet/date_part={date_val}/*.parquet")

        try:
            row_count = con.execute(f"""
                SELECT count(*) FROM read_parquet('{glob_pattern}', union_by_name=1)
            """).fetchone()[0]

            con.execute(f"""
                COPY (
                    SELECT * FROM read_parquet('{glob_pattern}', union_by_name=1)
                )
                TO '{compact_s3}' (FORMAT PARQUET);
            """)

            # Delete old files via boto3 (except the compacted one)
            old_keys = [k for k in parquet_keys if k != compact_key]
            if old_keys:
                delete_s3_keys(old_keys)

            total_rows += row_count
            log.info(
                "Compacted date_part=%s: %d files → 1 file (%d rows)",
                date_val, len(parquet_keys), row_count,
            )
        except Exception as e:
            log.error("Failed to compact date_part=%s: %s", date_val, e)

    con.close()
    log.info("Compaction complete. Total rows processed: %d", total_rows)


if __name__ == "__main__":
    run()
