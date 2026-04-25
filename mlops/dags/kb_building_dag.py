from airflow import DAG
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
import os
from airflow.utils.dates import days_ago
from datetime import datetime
from kubernetes.client import models as k8s

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "s3.amazonaws.com")
S3_REGION = os.getenv("S3_REGION", "ap-southeast-1")
S3_BUCKET = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")
S3_USE_SSL = os.getenv("S3_USE_SSL", "true").lower() == "true"

KB_BUILDER_IMAGE = os.getenv("KB_BUILDER_IMAGE", "hungtran679/kb_builder:dev")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow.mlflow.svc.cluster.local:5000")
MLFLOW_KB_MODEL = os.getenv("MLFLOW_KB_MODEL", "rca-knowledge-base")

# --- DAG Definition ---
with DAG(
    'kb_building_dag',
    schedule_interval='@weekly',
    start_date=days_ago(1),
    catchup=False,
    tags=['mlops', 'kb_building']
) as dag:

    # Run the Training/Building Pod
    run_kb_k8s = KubernetesPodOperator(
        task_id='run_kb_building_pod',
        namespace='airflow',
        name='kb-builder-pod',
        image=KB_BUILDER_IMAGE,
        image_pull_policy="Always",
        env_vars={
            'MLFLOW_TRACKING_URI': MLFLOW_TRACKING_URI,
            'S3_REGION': S3_REGION,
            'S3_BUCKET': S3_BUCKET,
            'AIRFLOW_RUN_ID': '{{ run_id }}'
        },
        env_from=[
            k8s.V1EnvFromSource(secret_ref=k8s.V1SecretEnvSource(name="airflow-aws-secret")),
        ],
        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "500m", "memory": "1Gi"},
            limits={"cpu": "500m", "memory": "1Gi"}
        ),
        get_logs=True,
        on_finish_action="keep_pod",
        in_cluster=True,
    )