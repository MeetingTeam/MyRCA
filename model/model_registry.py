"""
Model Registry for Per-App Model Management
Manages loading, caching, and retrieval of models per app_id.
"""

import json
import logging
import os
import sys
import threading
from dataclasses import dataclass
from typing import Optional, Dict, Any

import boto3
import joblib
import torch

from transformer_ae.model import TransformerAutoencoder
from common.safe_label_encoder import SafeLabelEncoder

# Register SafeLabelEncoder in __main__ for pickle compatibility with training scripts
# that define SafeLabelEncoder inline
sys.modules['__main__'].SafeLabelEncoder = SafeLabelEncoder

log = logging.getLogger("model-registry")


@dataclass
class AppModel:
    """Container for one loaded model and its artifacts."""
    model: TransformerAutoencoder
    encoders: Dict[str, Any]
    scalers: Dict[str, Any]
    threshold: float
    version: str
    device: torch.device


class ModelRegistry:
    """Thread-safe loader for one model version from S3."""

    def __init__(
        self,
        s3_bucket: str,
        s3_region: str,
        model_version: str,
    ):
        self.s3_bucket = s3_bucket
        self.s3_region = s3_region
        self.model_version = model_version
        self._model: Optional[AppModel] = None
        self._lock = threading.RLock()
        self._s3_client = boto3.client("s3", region_name=s3_region)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def get_model(self) -> Optional[AppModel]:
        """Get the model, loading it once from S3 if needed."""
        with self._lock:
            if self._model is None:
                self._model = self._load_model()
            return self._model

    def _load_model(self) -> Optional[AppModel]:
        """Load model artifacts from S3."""
        try:
            version = self.model_version.strip()
            if not version:
                log.warning("No model version configured")
                return None

            log.info("Loading model version=%s", version)

            local_dir = f"/tmp/models/{version}"
            os.makedirs(local_dir, exist_ok=True)

            prefix = f"mlops/models/{version}"

            model_path = os.path.join(local_dir, "model.pth")
            enc_path = os.path.join(local_dir, "encoders.pkl")
            scl_path = os.path.join(local_dir, "scalers.pkl")
            meta_path = os.path.join(local_dir, "metadata.json")

            for filename, local in [
                ("model.pth", model_path),
                ("encoders.pkl", enc_path),
                ("scalers.pkl", scl_path),
                ("metadata.json", meta_path),
            ]:
                self._s3_client.download_file(
                    self.s3_bucket, f"{prefix}/{filename}", local
                )

            with open(meta_path) as f:
                metadata = json.load(f)

            encoders = joblib.load(enc_path)
            scalers = joblib.load(scl_path)

            model = TransformerAutoencoder(
                service_vocab=encoders["service"].get_unknown_index() + 1,
                op_vocab=encoders["operation"].get_unknown_index() + 1,
                status_vocab=6,
                metrics_feature_num=1
            ).to(self.device)

            model.load_state_dict(torch.load(model_path, map_location=self.device))
            model.eval()

            return AppModel(
                model=model,
                encoders=encoders,
                scalers=scalers,
                threshold=float(metadata.get("threshold", 0.33)),
                version=version,
                device=self.device,
            )

        except Exception as e:
            log.error("Failed to load model version=%s: %s", self.model_version, e)
            return None
