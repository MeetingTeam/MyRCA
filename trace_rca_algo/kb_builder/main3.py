import json
import duckdb
import os
from datetime import datetime, timedelta, timezone
import json
from kb_building import train_knowledge_base
import mlflow
import pandas as pd

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "s3.amazonaws.com")
S3_REGION = os.getenv("S3_REGION", "ap-southeast-1")
S3_BUCKET = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")
S3_USE_SSL = os.getenv("S3_USE_SSL", "true").lower() == "true"
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

TIME_WINDOW_DAYS = int(os.getenv("TIME_WINDOW_DAYS", "2"))
DATASET_LIMIT = int(os.getenv("DATASET_LIMIT", "10000"))

AIRFLOW_RUN_ID = os.getenv("AIRFLOW_RUN_ID", "manual_run")

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:15000")
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

# Initialize MLflow
mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

def register_to_mlflow(new_kb_dict):
    mlflow_artifact_path = "kb_json"

    # 1. Get current production KB
    try:
        model_uri = f"models:/{MLFLOW_KB_MODEL}@production"
        current_kb = mlflow.pyfunc.load_model(model_uri).predict(None)
    except Exception:
        current_kb = None

    # 2. Simple comparison
    if current_kb == new_kb_dict:
        print("No change in KB. Skip logging.")
        return current_kb

    print("Logging new KB to MLflow...")

    # 3. Write file
    kb_path = "built_kb.json"
    with open(kb_path, "w") as f:
        json.dump(new_kb_dict, f)

    # 4. Minimal MLflow model wrapper
    class KBModel(mlflow.pyfunc.PythonModel):
        def load_context(self, context):
            with open(context.artifacts[mlflow_artifact_path], "r") as f:
                self.kb = json.load(f)

        def predict(self, context, model_input=None):
            return self.kb

    # 5. Log model
    with mlflow.start_run() as run:
        mlflow.set_tag("airflow_run_id", AIRFLOW_RUN_ID)

        print("Tracking URI:", mlflow.get_tracking_uri())
        mlflow.pyfunc.log_model(
            artifact_path="kb_model",
            python_model=KBModel(),
            artifacts={mlflow_artifact_path: kb_path},
            registered_model_name=MLFLOW_KB_MODEL
        )

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
        f's3://{S3_BUCKET}/anomalies/data.parquet/**/*.parquet',
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