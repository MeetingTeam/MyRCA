"""
Knowledge Base Deploy
─────────────────────────────────
Reads metadata.json from S3 for the given MLFLOW_VERSION_ID, patches the
anomaly-detection-service ConfigMap with new threshold and model path,
and triggers a rolling restart of the deployment.
"""

import logging
import os
import sys
from datetime import datetime, timezone
from kubernetes import client, config
import mlflow

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("model-deploy")

RCA_NAMESPACE = os.getenv("RCA_SERVICE_NAMESPACE", "rca")
RCA_CONFIGMAP_NAME = os.getenv("RCA_SERVICE_CONFIGMAP", "trace-rca-service-configmap")
RCA_DEPLOYMENT_NAME = os.getenv("RCA_SERVICE_DEPLOYMENT", "trace-rca-service")
MLFLOW_VERSION_ID = os.getenv("MLFLOW_VERSION_ID")
MLFLOW_KB_MODEL = os.getenv("MLFLOW_KB_MODEL", "rca-knowledge-base")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow.mlflow.svc.cluster.local:5000")

def run():
    if not MLFLOW_VERSION_ID:
        log.error("VERSION_ID not set")
        sys.exit(1)

    mlflow_client = mlflow.MlflowClient(tracking_uri=MLFLOW_TRACKING_URI)
    
    # Get the S3 path of the KB artifact from MLflow
    v = mlflow_client.get_model_version(
        name=MLFLOW_KB_MODEL,
        version=MLFLOW_VERSION_ID
    )
    KB_S3_PATH = v.source

    # Load in-cluster Kubernetes config
    config.load_incluster_config()
    v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()

    # Patch ConfigMap
    cm_patch = {
        "data": {
            "S3_KB_PATH": str(KB_S3_PATH),
            "MLFLOW_KB_VERSION": str(MLFLOW_VERSION_ID),
        }
    }
    v1.patch_namespaced_config_map(RCA_CONFIGMAP_NAME, RCA_NAMESPACE, cm_patch)
    log.info("ConfigMap %s patched", RCA_CONFIGMAP_NAME)

    # Trigger rolling restart by patching deployment annotation
    restart_patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()
                    }
                }
            }
        }
    }
    apps_v1.patch_namespaced_deployment(RCA_DEPLOYMENT_NAME, RCA_NAMESPACE, restart_patch)
    log.info("Deployment %s rolling restart triggered", RCA_DEPLOYMENT_NAME)

    # Transition model to Production in MLflow (optional, best-effort)
    mlflow_client.set_registered_model_alias(
        name=MLFLOW_KB_MODEL,
        alias="production",
        version=MLFLOW_VERSION_ID
    )
    log.info("MLflow model version %s transitioned to Production", MLFLOW_VERSION_ID)

    log.info("Model deploy complete for version %s", MLFLOW_VERSION_ID)


if __name__ == "__main__":
    run()