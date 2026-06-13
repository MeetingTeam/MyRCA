import json
import os
from datetime import datetime, timedelta, timezone
import pandas as pd
import boto3
from clickhouse_driver import Client as ClickHouseClient
from kb_building import train_knowledge_base

# ── ClickHouse connection settings ──────────────────────────────────────────
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "30900"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "default")

# ── S3 / dataset settings ────────────────────────────────────────────────────
S3_REGION            = os.getenv("S3_REGION", "ap-southeast-1")
S3_BUCKET            = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")
AWS_ACCESS_KEY_ID    = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

TIME_WINDOW_DAYS = int(os.getenv("TIME_WINDOW_DAYS", "3"))
DATASET_LIMIT    = int(os.getenv("DATASET_LIMIT", "100000"))

AIRFLOW_RUN_ID = os.getenv("AIRFLOW_RUN_ID", "manual_run")

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:30002")
MLFLOW_KB_MODEL     = os.getenv("MLFLOW_KB_MODEL", "rca-knowledge-base")

# ── ClickHouse client (TCP) ──────────────────────────────────────────────────
clickhouse_client = ClickHouseClient(
    host=CLICKHOUSE_HOST,
    port=CLICKHOUSE_PORT,
    user=CLICKHOUSE_USER,
    password=CLICKHOUSE_PASSWORD,
    database=CLICKHOUSE_DATABASE,
)

# ── S3 client (unchanged) ────────────────────────────────────────────────────
s3_client = boto3.client(
    "s3",
    region_name=S3_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
)


def register_to_mlflow(new_kb_dict):
    import mlflow
    from mlflow.tracking import MlflowClient

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    try:
        model_uri = f"models:/{MLFLOW_KB_MODEL}@production"
        current_model = mlflow.pyfunc.load_model(model_uri)
        current_kb = current_model.predict(None)
    except Exception:
        current_kb = None

    if current_kb == new_kb_dict:
        print("No change in KB. Skip logging.")
        return current_kb

    print("Logging new KB metadata to MLflow and uploading KB directly to S3...")

    kb_path = "built_kb.json"
    with open(kb_path, "w") as f:
        json.dump(new_kb_dict, f)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    s3_key = f"mlops/{MLFLOW_KB_MODEL}/{AIRFLOW_RUN_ID}_{timestamp}/built_kb.json"
    s3_client.upload_file(kb_path, S3_BUCKET, s3_key)
    kb_s3_uri = f"s3://{S3_BUCKET}/{s3_key}"

    with mlflow.start_run() as run:
        client = MlflowClient()
        try:
            client.create_registered_model(MLFLOW_KB_MODEL)
        except Exception:
            pass

        new_version = client.create_model_version(
            name=MLFLOW_KB_MODEL,
            source=kb_s3_uri,
            run_id=run.info.run_id,
        )

        # Set tags
        client.set_model_version_tag(
            name=MLFLOW_KB_MODEL,
            version=new_version.version,
            key="airflow_run_id",
            value=AIRFLOW_RUN_ID,
        )
        client.set_model_version_tag(
            name=MLFLOW_KB_MODEL,
            version=new_version.version,
            key="kb_s3_uri",
            value=kb_s3_uri
        )
        print(f"✅ Registered new MLflow model version: {new_version.version}")


def main():
    end_dt   = datetime.now(timezone.utc).replace(tzinfo=None)
    start_dt = end_dt - timedelta(days=TIME_WINDOW_DAYS)
    start_date_str = start_dt.strftime("%Y-%m-%d")
    end_date_str   = end_dt.strftime("%Y-%m-%d")

    query = """
        SELECT *
        FROM anomalies
        WHERE timestamp >= %(start_dt)s AND timestamp < %(end_dt)s
        LIMIT %(limit)s
    """
    params = {
        "start_dt": start_dt,
        "end_dt":   end_dt,
        "limit":    DATASET_LIMIT,
    }

    rows, columns = clickhouse_client.execute(query, params, with_column_types=True)
    col_names = [col[0] for col in columns]
    df = pd.DataFrame(rows, columns=col_names)

    print(f"Fetched dataset successfully with length: {len(df)}")

    if df.empty:
        print(
            f"No dataset found within time range {start_date_str} to {end_date_str}. "
            "Please check your ClickHouse table and data availability."
        )
        return

    knowledge_base = train_knowledge_base(df)
    register_to_mlflow(knowledge_base)


if __name__ == "__main__":
    main()