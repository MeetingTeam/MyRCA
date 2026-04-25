from airflow import DAG
from airflow.operators.python import PythonOperator
import os
import datetime
from airflow.utils.dates import days_ago
from airflow.models.param import Param
from kubernetes import client, config

KB_DEPLOY_IMAGE = os.getenv("KB_BUILDER_IMAGE", "hungtran679/kb_deploy:latest")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow.mlflow.svc.cluster.local:5000")
MLFLOW_KB_MODEL = os.getenv("MLFLOW_KB_MODEL", "rca-knowledge-base")

RCA_SERVICE_DEPLOYMENT = os.getenv("RCA_SERVICE_DEPLOYMENT", "trace-rca-service")
RCA_SERVICE_NAMESPACE = os.getenv("RCA_SERVICE_NAMESPACE", "rca")

# --- DAG Definition ---
with DAG(
    'kb_deploy_dag',
    start_date=days_ago(1),
    catchup=False,
    tags=['mlops', 'kb_deploy'],
    params={
        "version_id": Param(
            default="",
            type="string",
            description="Model version ID to deploy (e.g., 1, 2, 3)",
        ),
    },
) as dag:
    
    # Run the Training/Building Pod
    run_kb_k8s = KubernetesPodOperator(
        task_id='run_kb_deploy_pod',
        namespace='airflow',
        name='kb-deploy-pod',
        image=KB_DEPLOY_IMAGE,
        image_pull_policy="Always",
        env_vars={
            'MLFLOW_TRACKING_URI': MLFLOW_TRACKING_URI,
            'MLFLOW_KB_MODEL': MLFLOW_KB_MODEL,
        },
        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "50m", "memory": "128Mi"},
            limits={"cpu": "100m", "memory": "256Mi"}
        ),
        get_logs=True,
        on_finish_action="keep_pod",
        in_cluster=True,
    )