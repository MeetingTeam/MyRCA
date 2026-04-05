"""
DAG 2: Model Deploy
───────────────────
Manually triggered with a `version_id` parameter. Deploys the specified
model version by updating the anomaly-detection-service ConfigMap and
triggering a rolling restart.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.models.param import Param
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from kubernetes.client import models as k8s

default_args = {
    "owner": "mlops",
    "retries": 0,
}

PIPELINE_IMAGE = "asdads6495/mlops-pipeline:dev"
NAMESPACE = "airflow"

ENV_VARS = [
    k8s.V1EnvVar(name="MLFLOW_TRACKING_URI", value="http://mlflow.mlflow.svc.cluster.local:5000"),
    k8s.V1EnvVar(name="S3_BUCKET", value="kltn-anomaly-dateset-1"),
    k8s.V1EnvVar(name="S3_REGION", value="ap-southeast-1"),
    k8s.V1EnvVar(name="S3_ENDPOINT", value="s3.amazonaws.com"),
    k8s.V1EnvVar(name="S3_USE_SSL", value="true"),
]

ENV_FROM = [
    k8s.V1EnvFromSource(secret_ref=k8s.V1SecretEnvSource(name="airflow-aws-secret")),
]

with DAG(
    dag_id="model_deploy",
    default_args=default_args,
    description="Deploy a trained model version to the anomaly detection service",
    schedule_interval=None,  # Manual trigger only
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["mlops", "deploy"],
    params={
        "version_id": Param(
            default="",
            type="string",
            description="Model version ID to deploy (e.g., v20240315-120000)",
        ),
    },
) as dag:

    deploy = KubernetesPodOperator(
        task_id="deploy_model",
        name="deploy-model",
        namespace=NAMESPACE,
        image=PIPELINE_IMAGE,
        image_pull_policy="Always",
        cmds=["python", "-m", "tasks.model_deploy"],
        env_vars=ENV_VARS + [
            k8s.V1EnvVar(name="VERSION_ID", value="{{ params.version_id }}"),
        ],
        env_from=ENV_FROM,
        service_account_name="airflow-deploy-sa",
        is_delete_operator_pod=True,
        get_logs=True,
        startup_timeout_seconds=300,
    )
