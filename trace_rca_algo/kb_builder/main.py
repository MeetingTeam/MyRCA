import json
import pandas as pd
import duckdb
import os
from datetime import datetime, timedelta, timezone
import json
import mlflow
import mlflow.pyfunc
from mlflow import MlflowClient
from kb_building import train_knowledge_base

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "s3.amazonaws.com")
S3_REGION = os.getenv("S3_REGION", "ap-southeast-7")
S3_BUCKET = os.getenv("S3_BUCKET", "kltn-anomaly-dateset")
S3_USE_SSL = os.getenv("S3_USE_SSL", "true").lower() == "true"
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

TIME_WINDOW_DAYS = int(os.getenv("TIME_WINDOW_DAYS", "7"))
DATASET_LIMIT = int(os.getenv("DATASET_LIMIT", "500000"))

AIRFLOW_RUN_ID = os.getenv("AIRFLOW_RUN_ID", "manual_run")

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:15000")

# Initialize DuckDB connection
db_con = duckdb.connect()
db_con.execute("INSTALL httpfs; LOAD httpfs;")
db_con.execute(f"""
        SET s3_endpoint='{S3_ENDPOINT}';
        SET s3_region='{S3_REGION}';
        SET s3_access_key_id='{AWS_ACCESS_KEY_ID}';
        SET s3_secret_access_key='{AWS_SECRET_ACCESS_KEY}';
        SET s3_use_ssl={'true' if S3_USE_SSL else 'false'};
        SET s3_url_style='path';
""")

# Initialize MLflow (ensure your SQLite/Docker server is running)
mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
client = MlflowClient()
MODEL_NAME = "rca-knowledge-base"

class KBModelWrapper(mlflow.pyfunc.PythonModel):
    """Wraps the KB JSON so MLflow can manage it as a Model."""
    def load_context(self, context):
        with open(context.artifacts["kb_json"], 'r') as f:
            self.kb_data = json.load(f)

def get_production_kb():
    """Fetches the current production KB JSON data from MLflow."""
    try:
        # Load directly using the @production alias
        model_uri = f"models:/{MODEL_NAME}@production"
        prod_model = mlflow.pyfunc.load_model(model_uri)
        # Access the raw dictionary from the wrapper
        return prod_model._model_impl.python_model.kb_data
    except Exception:
        print("No production model found. Starting fresh.")
        return None

def register_to_mlflow(new_kb_dict):
    # 1. Comparison logic
    current_kb = get_production_kb()
    
    if current_kb == new_kb_dict: # Simple dict equality check
        print("No changes detected in Knowledge Base. Skipping update.")
        return

    print("Changes detected. Registering new version...")

    # 2. Upload and Register with MLflow
    # Save locally first for MLflow to pick up
    temp_path = "temp_kb.json"
    with open(temp_path, "w") as f:
        json.dump(new_kb_dict, f)

    with mlflow.start_run(run_name=f"Airflow_{AIRFLOW_RUN_ID}"):
        # Store Airflow metadata
        mlflow.set_tag("airflow_run_id", AIRFLOW_RUN_ID)
        
        # Log as a Model to enable Aliases
        mlflow.pyfunc.log_model(
            artifact_path="kb_model",
            python_model=KBModelWrapper(),
            artifacts={"kb_json": temp_path},
            registered_model_name=MODEL_NAME
        )
        
        # 3. Promote to Production Alias
        # This automatically moves @production from the old version to this one
        # client.set_registered_model_alias(
        #     name=MODEL_NAME,
        #     alias="production",
        #     version=model_info.registered_model_version
        # )
        # print(f"KB Version {model_info.registered_model_version} is now Production.")

def main(): 
    end_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    start_dt = end_dt - timedelta(days=TIME_WINDOW_DAYS)
    start_date_str = start_dt.strftime("%Y-%m-%d")
    end_date_str = end_dt.strftime("%Y-%m-%d")
    
    df = db_con.execute(f"""
            SELECT * 
            FROM read_parquet('s3://{S3_BUCKET}/anomalies/data.parquet/*/*.parquet', hive_partitioning = 1)
            WHERE date_part BETWEEN '{start_date_str}' AND '{end_date_str}'
            LIMIT {DATASET_LIMIT}
    """).fetchdf()

    if df.empty:
        print(f"No dataset found within time range {start_date_str} to {end_date_str}. Please check your S3 path and data availability.")
        return

    knowledge_base = train_knowledge_base(df)

    register_to_mlflow(knowledge_base)

if __name__ == "__main__":
    main()