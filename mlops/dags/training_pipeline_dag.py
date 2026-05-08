"""
DAG 1: Training Pipeline (Hybrid K8s + AWS Batch)
─────────────────────────────────────────────────
compact >> drift_detection >> preprocess >> train (Batch) >> evaluate (Batch)

Uses KubernetesPodOperator for lightweight tasks and BatchOperator
for GPU-intensive training/evaluation on AWS Batch Spot instances.
"""

from datetime import datetime, timedelta
import json

from airflow import DAG
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.providers.amazon.aws.operators.batch import BatchOperator
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.operators.empty import EmptyOperator
from airflow.utils.trigger_rule import TriggerRule
from kubernetes.client import models as k8s
import boto3

default_args = {
    "owner": "mlops",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

PIPELINE_IMAGE = "asdads6495/mlops-pipeline-light:dev"
NAMESPACE = "airflow"
BATCH_REGION = "us-east-1"
S3_REGION = "ap-southeast-1"
S3_BUCKET = "kltn-anomaly-dateset-1"

ENV_VARS = [
    k8s.V1EnvVar(name="MLFLOW_TRACKING_URI", value="http://mlflow.mlflow.svc.cluster.local:5000"),
    k8s.V1EnvVar(name="S3_BUCKET", value=S3_BUCKET),
    k8s.V1EnvVar(name="S3_REGION", value=S3_REGION),
    k8s.V1EnvVar(name="S3_ENDPOINT", value="s3.amazonaws.com"),
    k8s.V1EnvVar(name="S3_USE_SSL", value="true"),
    k8s.V1EnvVar(name="FORCE_DRIFT", value="false"),  # Production: detect real drift
    k8s.V1EnvVar(name="USE_EVIDENTLY", value="true"),  # Enable Evidently drift detection
    k8s.V1EnvVar(name="EVIDENTLY_WORKSPACE", value="http://evidently-ui.mlops.svc.cluster.local:8000"),
]

ENV_FROM = [
    k8s.V1EnvFromSource(secret_ref=k8s.V1SecretEnvSource(name="airflow-aws-secret")),
]


def check_drift(**context) -> str:
    """BranchPythonOperator callable — returns task_id to execute."""
    ti = context["ti"]
    xcom = ti.xcom_pull(task_ids="drift_detection", key="return_value")
    if xcom and xcom.get("drift_detected"):
        return "trigger_retrain"
    return "no_retrain"


def read_batch_output(version_id: str, task_name: str, max_retries: int = 5) -> dict:
    """Read Batch job output from S3 with retry (XCom replacement)."""
    import time
    from botocore.exceptions import ClientError

    s3 = boto3.client("s3", region_name=S3_REGION)

    for attempt in range(max_retries):
        try:
            response = s3.get_object(
                Bucket=S3_BUCKET,
                Key=f"mlops/batch-outputs/{version_id}/{task_name}_output.json",
            )
            return json.loads(response["Body"].read().decode("utf-8"))
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                if attempt == max_retries - 1:
                    raise ValueError(f"S3 output not found after {max_retries} retries: {task_name}_output.json")
                wait_time = 2 ** attempt
                print(f"S3 output not found, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                raise


def fetch_train_output(**context):
    """Fetch training output from S3 after Batch job completes."""
    ti = context["ti"]
    drift_xcom = ti.xcom_pull(task_ids="drift_detection", key="return_value")
    version_id = drift_xcom.get("version_id") if drift_xcom else None

    if not version_id:
        raise ValueError("version_id not found in drift_detection XCom")

    output = read_batch_output(version_id, "train")
    ti.xcom_push(key="return_value", value=output)
    return output


def fetch_evaluate_output(**context):
    """Fetch evaluation output from S3 after Batch job completes."""
    ti = context["ti"]
    drift_xcom = ti.xcom_pull(task_ids="drift_detection", key="return_value")
    version_id = drift_xcom.get("version_id") if drift_xcom else None

    if not version_id:
        raise ValueError("version_id not found in drift_detection XCom")

    output = read_batch_output(version_id, "evaluate")
    ti.xcom_push(key="return_value", value=output)
    return output


with DAG(
    dag_id="training_pipeline",
    default_args=default_args,
    description="MLOps training pipeline: K8s for lightweight tasks, AWS Batch for GPU training",
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["mlops", "training", "batch"],
) as dag:

    # ─────────────────────────────────────────────────────────────
    # Lightweight tasks on K8s (unchanged)
    # ─────────────────────────────────────────────────────────────

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

    check_drift_result = BranchPythonOperator(
        task_id="check_drift",
        python_callable=check_drift,
    )

    trigger_retrain = EmptyOperator(task_id="trigger_retrain")
    no_retrain = EmptyOperator(task_id="no_retrain")

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

    # ─────────────────────────────────────────────────────────────
    # GPU tasks on AWS Batch Spot (NEW)
    # ─────────────────────────────────────────────────────────────

    train = BatchOperator(
        task_id="train",
        job_name="mlops-train-{{ ti.xcom_pull(task_ids='drift_detection', key='return_value')['version_id'] }}",
        job_queue="gpu-spot-queue",
        job_definition="mlops-train-job",
        region_name=BATCH_REGION,
        aws_conn_id="aws_batch",
        container_overrides={
            "environment": [
                {"name": "VERSION_ID", "value": "{{ ti.xcom_pull(task_ids='drift_detection', key='return_value')['version_id'] }}"},
                {"name": "MLFLOW_PARENT_RUN_ID", "value": "{{ ti.xcom_pull(task_ids='drift_detection', key='return_value')['mlflow_run_id'] | default('', true) }}"},
            ],
        },
        wait_for_completion=True,
        poll_interval=30,
        max_retries=600,
    )

    fetch_train_result = PythonOperator(
        task_id="fetch_train_output",
        python_callable=fetch_train_output,
    )

    evaluate = BatchOperator(
        task_id="evaluate",
        job_name="mlops-evaluate-{{ ti.xcom_pull(task_ids='drift_detection', key='return_value')['version_id'] }}",
        job_queue="gpu-spot-queue",
        job_definition="mlops-evaluate-job",
        region_name=BATCH_REGION,
        aws_conn_id="aws_batch",
        container_overrides={
            "environment": [
                {"name": "VERSION_ID", "value": "{{ ti.xcom_pull(task_ids='drift_detection', key='return_value')['version_id'] }}"},
                {"name": "MLFLOW_PARENT_RUN_ID", "value": "{{ ti.xcom_pull(task_ids='drift_detection', key='return_value')['mlflow_run_id'] | default('', true) }}"},
            ],
        },
        wait_for_completion=True,
        poll_interval=30,
        max_retries=180,
    )

    fetch_evaluate_result = PythonOperator(
        task_id="fetch_evaluate_output",
        python_callable=fetch_evaluate_output,
    )

    # ─────────────────────────────────────────────────────────────
    # Task dependencies
    # ─────────────────────────────────────────────────────────────

    compact >> drift_detection >> check_drift_result >> [trigger_retrain, no_retrain]
    trigger_retrain >> preprocess >> train >> fetch_train_result >> evaluate >> fetch_evaluate_result
