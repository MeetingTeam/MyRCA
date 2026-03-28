"""
DAG 1: Training Pipeline
─────────────────────────
compact >> drift_detection >> preprocess >> train >> evaluate

Uses KubernetesPodOperator to run each step as a separate pod
with the mlops-pipeline image. Compaction merges small parquet files
before drift detection. Drift detection short-circuits the pipeline
if no drift is found.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.operators.python import ShortCircuitOperator
from airflow.utils.trigger_rule import TriggerRule
from kubernetes.client import models as k8s

default_args = {
    "owner": "mlops",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

PIPELINE_IMAGE = "asdads6495/mlops-pipeline:dev"
NAMESPACE = "airflow"

# Common env vars injected into every task pod
ENV_VARS = [
    k8s.V1EnvVar(name="MLFLOW_TRACKING_URI", value="http://mlflow.mlflow.svc.cluster.local:5000"),
    k8s.V1EnvVar(name="S3_BUCKET", value="kltn-anomaly-dateset-1"),
    k8s.V1EnvVar(name="S3_REGION", value="ap-southeast-1"),
    k8s.V1EnvVar(name="S3_ENDPOINT", value="s3.amazonaws.com"),
    k8s.V1EnvVar(name="S3_USE_SSL", value="true"),
]

# AWS credentials from secret
ENV_FROM = [
    k8s.V1EnvFromSource(secret_ref=k8s.V1SecretEnvSource(name="airflow-aws-secret")),
]


def check_drift(**context):
    """ShortCircuitOperator callable — returns True if drift detected, False to skip."""
    ti = context["ti"]
    xcom = ti.xcom_pull(task_ids="drift_detection", key="return_value")
    if xcom and isinstance(xcom, dict):
        return xcom.get("drift_detected", False)
    return False


with DAG(
    dag_id="training_pipeline",
    default_args=default_args,
    description="MLOps training pipeline: drift detection → preprocess → train → evaluate",
    schedule_interval=None,  # Manual trigger or "@weekly"
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["mlops", "training"],
) as dag:

    compact = KubernetesPodOperator(
        task_id="compact",
        name="compact",
        namespace=NAMESPACE,
        image=PIPELINE_IMAGE,
        image_pull_policy="Always",
        cmds=["python", "-m", "tasks.compaction"],
        env_vars=ENV_VARS,
        env_from=ENV_FROM,
        is_delete_operator_pod=True,
        get_logs=True,
        startup_timeout_seconds=1800,
        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "250m", "memory": "512Mi"},
            limits={"cpu": "1", "memory": "2Gi"},
        ),
    )

    drift_detection = KubernetesPodOperator(
        task_id="drift_detection",
        name="drift-detection",
        namespace=NAMESPACE,
        image=PIPELINE_IMAGE,
        image_pull_policy="Always",
        cmds=["python", "-m", "tasks.drift_detection"],
        env_vars=ENV_VARS,
        env_from=ENV_FROM,
        do_xcom_push=True,
        is_delete_operator_pod=True,
        get_logs=True,
        startup_timeout_seconds=600,
    )

    check_drift_result = ShortCircuitOperator(
        task_id="check_drift",
        python_callable=check_drift,
    )

    preprocess = KubernetesPodOperator(
        task_id="preprocess",
        name="preprocess",
        namespace=NAMESPACE,
        image=PIPELINE_IMAGE,
        image_pull_policy="Always",
        cmds=["python", "-m", "tasks.preprocessing"],
        env_vars=ENV_VARS + [
            k8s.V1EnvVar(
                name="VERSION_ID",
                value="{{ ti.xcom_pull(task_ids='drift_detection', key='return_value')['version_id'] }}",
            ),
        ],
        env_from=ENV_FROM,
        do_xcom_push=True,
        is_delete_operator_pod=True,
        get_logs=True,
        startup_timeout_seconds=300,
    )

    train = KubernetesPodOperator(
        task_id="train",
        name="train",
        namespace=NAMESPACE,
        image=PIPELINE_IMAGE,
        image_pull_policy="Always",
        cmds=["python", "-m", "tasks.training"],
        env_vars=ENV_VARS + [
            k8s.V1EnvVar(
                name="VERSION_ID",
                value="{{ ti.xcom_pull(task_ids='drift_detection', key='return_value')['version_id'] }}",
            ),
        ],
        env_from=ENV_FROM,
        do_xcom_push=True,
        is_delete_operator_pod=True,
        get_logs=True,
        startup_timeout_seconds=600,
        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "500m", "memory": "1Gi"},
            limits={"cpu": "2", "memory": "4Gi"},
        ),
    )

    evaluate = KubernetesPodOperator(
        task_id="evaluate",
        name="evaluate",
        namespace=NAMESPACE,
        image=PIPELINE_IMAGE,
        image_pull_policy="Always",
        cmds=["python", "-m", "tasks.evaluation"],
        env_vars=ENV_VARS + [
            k8s.V1EnvVar(
                name="VERSION_ID",
                value="{{ ti.xcom_pull(task_ids='drift_detection', key='return_value')['version_id'] }}",
            ),
        ],
        env_from=ENV_FROM,
        do_xcom_push=True,
        is_delete_operator_pod=True,
        get_logs=True,
        startup_timeout_seconds=600,
        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "500m", "memory": "1Gi"},
            limits={"cpu": "2", "memory": "4Gi"},
        ),
    )

    compact >> drift_detection >> check_drift_result >> preprocess >> train >> evaluate
