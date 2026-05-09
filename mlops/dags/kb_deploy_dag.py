from airflow import DAG
from airflow.utils.dates import days_ago
from airflow.models.param import Param
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from kubernetes.client import models as k8s
import os

KB_DEPLOY_IMAGE = "hungtran679/kb_deploy:latest"
MLFLOW_TRACKING_URI = "http://mlflow-tracking.mlflow.svc.cluster.local:5000"
MLFLOW_KB_MODEL = "rca-knowledge-base"

RCA_SERVICE_DEPLOYMENT = "trace-rca-service"
RCA_SERVICE_NAMESPACE = "rca"

with DAG(
    dag_id='kb_deploy_dag',
    start_date=days_ago(1),
    catchup=False,
    tags=['mlops', 'kb_deploy'],
    params={
        "version_id": Param(
            default="",
            type="string",
            description="Model version ID to deploy",
        ),
    },
) as dag:

    run_kb_k8s = KubernetesPodOperator(
        task_id='run_kb_deploy_pod',
        namespace='airflow',
        name='kb-deploy-pod',
        image=KB_DEPLOY_IMAGE,
        image_pull_policy="Always",
        env_vars={
            'MLFLOW_TRACKING_URI': MLFLOW_TRACKING_URI,
            'MLFLOW_KB_MODEL': MLFLOW_KB_MODEL,
            'MLFLOW_VERSION_ID': "{{ params.version_id }}",
            'RCA_SERVICE_DEPLOYMENT': RCA_SERVICE_DEPLOYMENT,
            'RCA_SERVICE_NAMESPACE': RCA_SERVICE_NAMESPACE,
        },
        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "50m", "memory": "128Mi"},
            limits={"cpu": "100m", "memory": "256Mi"},
        ),
        get_logs=True,
        on_finish_action="delete_pod",
        in_cluster=True,
        service_account_name="mlops-deployer-sa"
    )