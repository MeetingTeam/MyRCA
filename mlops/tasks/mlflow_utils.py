"""
MLflow utilities with environment-based configuration and graceful fallback.
Shared across training, evaluation, and drift_detection tasks.
"""

import logging
import os
from typing import Any, Optional

import mlflow
import requests

log = logging.getLogger(__name__)

MLFLOW_EXPERIMENT = "transformer-ae-training"


def setup_mlflow() -> Optional[Any]:
    """Setup MLflow with environment-based URI and graceful fallback.

    Environment variables:
        MLFLOW_TRACKING_URI: MLflow server URI (required for tracking)
        MLFLOW_DISABLE: Set to "true" to skip MLflow entirely

    Returns:
        mlflow module if connected, None if disabled or unreachable
    """
    if os.getenv("MLFLOW_DISABLE", "false").lower() == "true":
        log.info("MLflow disabled via MLFLOW_DISABLE env var")
        return None

    mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "").strip()

    if not mlflow_uri:
        log.info("MLFLOW_TRACKING_URI not set, skipping MLflow tracking")
        return None

    if mlflow_uri.endswith(".svc.cluster.local:5000"):
        log.warning("MLflow URI is K8s internal DNS — may fail from AWS Batch")

    try:
        mlflow.set_tracking_uri(mlflow_uri)
        requests.get(f"{mlflow_uri}/health", timeout=5)
        mlflow.set_experiment(MLFLOW_EXPERIMENT)
        log.info("MLflow connected: %s", mlflow_uri)
        return mlflow
    except requests.exceptions.RequestException as e:
        log.warning("MLflow unreachable (%s): %s — proceeding without tracking", mlflow_uri, e)
        return None
    except Exception as e:
        log.warning("MLflow setup failed: %s — proceeding without tracking", e)
        return None


def start_pipeline_run(version_id: str) -> Optional[str]:
    """Start a parent pipeline run and return run_id for nested runs.

    Call this from drift_detection task when drift is detected.
    Pass the returned run_id to train/evaluate tasks via XCom.

    Returns:
        MLflow run_id string, or None if MLflow disabled
    """
    mlflow_client = setup_mlflow()
    if not mlflow_client:
        return None

    run = mlflow.start_run(run_name=f"pipeline-{version_id}")
    mlflow.log_param("version_id", version_id)
    mlflow.log_param("pipeline_type", "training")
    log.info("Started pipeline run: %s", run.info.run_id)
    return run.info.run_id


def start_nested_run(parent_run_id: Optional[str], run_name: str) -> Optional[mlflow.ActiveRun]:
    """Start a nested run under parent pipeline run.

    Args:
        parent_run_id: Run ID from start_pipeline_run(), or None
        run_name: Name for this nested run (e.g., "train-v123")

    Returns:
        ActiveRun context manager, or None if MLflow disabled
    """
    mlflow_client = setup_mlflow()
    if not mlflow_client:
        return None

    if parent_run_id:
        return mlflow.start_run(run_id=parent_run_id, nested=True, run_name=run_name)
    else:
        return mlflow.start_run(run_name=run_name)


def end_pipeline_run(parent_run_id: Optional[str]):
    """End the parent pipeline run after all nested runs complete.

    Call this from evaluate task (last task in pipeline).
    """
    if not parent_run_id:
        return

    mlflow_client = setup_mlflow()
    if mlflow_client:
        try:
            mlflow.end_run()
            log.info("Pipeline run ended: %s", parent_run_id)
        except Exception as e:
            log.warning("Failed to end pipeline run: %s", e)
