import json
import duckdb
import os
from datetime import datetime, timedelta, timezone
import json
from kb_building import train_knowledge_base
import pandas as pd
import boto3

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "s3.amazonaws.com")
S3_REGION = os.getenv("S3_REGION", "ap-southeast-1")
S3_BUCKET = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")
S3_USE_SSL = os.getenv("S3_USE_SSL", "true").lower() == "true"
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

TIME_WINDOW_DAYS = int(os.getenv("TIME_WINDOW_DAYS", "0"))
DATASET_LIMIT = int(os.getenv("DATASET_LIMIT", "100000"))

AIRFLOW_RUN_ID = os.getenv("AIRFLOW_RUN_ID", "manual_run")

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://34.226.226.116:30002")
MLFLOW_KB_MODEL = os.getenv("MLFLOW_KB_MODEL", "rca-knowledge-base")

# Initialize DuckDB connection
db_con = duckdb.connect(database=':memory:')
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

# Initialize direct S3 client
s3_client = boto3.client(
    "s3",
    region_name=S3_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

def register_to_mlflow(new_kb_dict):
    import mlflow
    from mlflow.tracking import MlflowClient
    
    # Initialize MLflow
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    
    # # 1. Get current production KB metadata only
    try:
        model_uri = f"models:/{MLFLOW_KB_MODEL}@production"
        current_model = mlflow.pyfunc.load_model(model_uri)
        current_kb = current_model.predict(None)
    except Exception:
        current_kb = None

    # # 2. Simple comparison
    if current_kb == new_kb_dict:
        print("No change in KB. Skip logging.")
        return current_kb

    print("Logging new KB metadata to MLflow and uploading KB directly to S3...")

    # 3. Write file locally
    kb_path = "built_kb.json"
    with open(kb_path, "w") as f:
        json.dump(new_kb_dict, f)

    # # 4. Upload directly to S3
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    s3_key = f"mlops/{MLFLOW_KB_MODEL}/{AIRFLOW_RUN_ID}_{timestamp}/built_kb.json"

    s3_client.upload_file(kb_path, S3_BUCKET, s3_key)

    kb_s3_uri = f"s3://{S3_BUCKET}/{s3_key}"

    # # 5. Log only metadata to MLflow (no artifact upload)
    with mlflow.start_run() as run:
        client = MlflowClient()
        
        # Create the registered model if it doesn't exist
        try:
            client.create_registered_model(MLFLOW_KB_MODEL)
        except Exception:
            pass  # Model already exists
        
        new_version = client.create_model_version(
            name=MLFLOW_KB_MODEL,
            source=kb_s3_uri,
            run_id=run.info.run_id,
        )
        client.set_model_version_tag(
            name=MLFLOW_KB_MODEL,
            version=new_version.version,
            key="airflow_run_id",
            value=AIRFLOW_RUN_ID,
        )

        print(f"✅ Registered new MLflow model version: {new_version.version}")

def main():
    end_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    start_dt = end_dt - timedelta(days=TIME_WINDOW_DAYS)
    start_date_str = start_dt.strftime("%Y-%m-%d")
    end_date_str = end_dt.strftime("%Y-%m-%d")

    # This will print exactly what is breaking before it hits DuckDB
    df = db_con.cursor().execute("""
        SELECT * FROM read_parquet(?, hive_partitioning = 1)
        WHERE date_part BETWEEN ? AND ?
        LIMIT ?
    """, [
        f's3://{S3_BUCKET}/anomalies/data.parquet/date_part=*/*.parquet',
        start_date_str,
        end_date_str,
        DATASET_LIMIT
    ]).fetchdf()

    print(f"Fetched dataset successfully with length: {len(df)}")

    if df.empty:
        print(f"No dataset found within time range {start_date_str} to {end_date_str}. Please check your S3 path and data availability.")
        return

    knowledge_base = train_knowledge_base(df)

    register_to_mlflow(knowledge_base)

if __name__ == "__main__":
    main()