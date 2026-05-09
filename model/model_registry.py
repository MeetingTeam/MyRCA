"""
Model Registry for Per-App Model Management
Manages loading, caching, and retrieval of models per app_id.
"""

import json
import logging
import os
import sys
import threading
from collections import OrderedDict
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
    """Container for a single app's model artifacts."""
    app_id: str
    model: TransformerAutoencoder
    encoders: Dict[str, Any]
    scalers: Dict[str, Any]
    threshold: float
    version: str
    device: torch.device


class ModelRegistry:
    """Thread-safe registry for per-app models with LRU eviction."""

    def __init__(
        self,
        s3_bucket: str,
        s3_region: str,
        max_models: int = 10,
        default_app_id: str = "k8s-repo-application",
        local_fallback_dir: Optional[str] = None,
    ):
        self.s3_bucket = s3_bucket
        self.s3_region = s3_region
        self.max_models = max_models
        self.default_app_id = default_app_id
        self.local_fallback_dir = local_fallback_dir
        self._cache: OrderedDict[str, AppModel] = OrderedDict()
        self._lock = threading.RLock()
        self._s3_client = boto3.client("s3", region_name=s3_region)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._stats = {"hits": 0, "misses": 0, "loads": 0, "failures": 0}

    def get_model(self, app_id: str) -> Optional[AppModel]:
        """Get model for app_id, loading from S3 if needed."""
        with self._lock:
            if app_id in self._cache:
                self._cache.move_to_end(app_id)
                self._stats["hits"] += 1
                return self._cache[app_id]

            self._stats["misses"] += 1
            app_model = self._load_model(app_id)
            if app_model:
                self._add_to_cache(app_id, app_model)
                return app_model

            if app_id != self.default_app_id:
                log.warning("Model not found for app_id=%s, using default", app_id)
                return self.get_model(self.default_app_id)

            if self.local_fallback_dir:
                log.info("Trying local fallback for default model")
                return self._load_local_model()

            return None

    def _load_model(self, app_id: str) -> Optional[AppModel]:
        """Load model artifacts from S3 (global model, app_id ignored)."""
        try:
            version = self._find_latest_version(app_id)
            if not version:
                log.warning("No model version found")
                return None

            log.info("Loading global model version=%s", version)

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

            app_encoder = encoders.get("app_id") or encoders.get("app")
            app_vocab_size = app_encoder.get_unknown_index() + 1 if app_encoder and hasattr(app_encoder, "get_unknown_index") else 2

            model = TransformerAutoencoder(
                service_vocab=encoders["service"].get_unknown_index() + 1,
                op_vocab=encoders["operation"].get_unknown_index() + 1,
                status_vocab=6,
                app_vocab=app_vocab_size,
                metrics_feature_num=1,
            ).to(self.device)

            model.load_state_dict(torch.load(model_path, map_location=self.device))
            model.eval()

            self._stats["loads"] += 1

            return AppModel(
                app_id=app_id,
                model=model,
                encoders=encoders,
                scalers=scalers,
                threshold=float(metadata.get("threshold", 0.33)),
                version=version,
                device=self.device,
            )

        except Exception as e:
            log.error("Failed to load model for app_id=%s: %s", app_id, e)
            self._stats["failures"] += 1
            return None

    def _find_latest_version(self, app_id: str) -> Optional[str]:
        """Find latest model version in S3 (global, ignores app_id)."""
        try:
            prefix = "mlops/models/"
            response = self._s3_client.list_objects_v2(
                Bucket=self.s3_bucket,
                Prefix=prefix,
                Delimiter="/",
            )

            versions = []
            for cp in response.get("CommonPrefixes", []):
                version = cp["Prefix"].rstrip("/").split("/")[-1]
                if version.startswith("v"):
                    versions.append(version)

            if not versions:
                return None

            versions.sort(reverse=True)
            return versions[0]

        except Exception as e:
            log.error("Failed to list versions: %s", e)
            return None

    def _load_local_model(self) -> Optional[AppModel]:
        """Load model from local filesystem as fallback."""
        if not self.local_fallback_dir:
            return None

        try:
            model_path = os.path.join(self.local_fallback_dir, "transformer_ae_model.pth")
            enc_path = os.path.join(self.local_fallback_dir, "transformer_ae_encoders.pkl")
            scl_path = os.path.join(self.local_fallback_dir, "transformer_ae_scalers.pkl")

            if not os.path.exists(model_path):
                log.warning("Local model not found at %s", model_path)
                return None

            encoders = joblib.load(enc_path)
            scalers = joblib.load(scl_path)

            app_encoder = encoders.get("app_id") or encoders.get("app")
            app_vocab_size = app_encoder.get_unknown_index() + 1 if app_encoder and hasattr(app_encoder, "get_unknown_index") else 2

            model = TransformerAutoencoder(
                service_vocab=encoders["service"].get_unknown_index() + 1,
                op_vocab=encoders["operation"].get_unknown_index() + 1,
                status_vocab=6,
                app_vocab=app_vocab_size,
                metrics_feature_num=1,
            ).to(self.device)

            model.load_state_dict(torch.load(model_path, map_location=self.device))
            model.eval()

            log.info("Loaded local fallback model")
            self._stats["loads"] += 1

            return AppModel(
                app_id="local",
                model=model,
                encoders=encoders,
                scalers=scalers,
                threshold=0.33,
                version="local",
                device=self.device,
            )

        except Exception as e:
            log.error("Failed to load local model: %s", e)
            self._stats["failures"] += 1
            return None

    def _add_to_cache(self, app_id: str, app_model: AppModel):
        """Add model to cache with LRU eviction."""
        if len(self._cache) >= self.max_models:
            evicted_id, _ = self._cache.popitem(last=False)
            log.info("Evicted model for app_id=%s from cache", evicted_id)

        self._cache[app_id] = app_model
        log.info("Cached model for app_id=%s (cache size: %d)", app_id, len(self._cache))

    def invalidate(self, app_id: str):
        """Remove model from cache (e.g., on new deployment)."""
        with self._lock:
            if app_id in self._cache:
                del self._cache[app_id]
                log.info("Invalidated cache for app_id=%s", app_id)

    def invalidate_all(self):
        """Clear entire cache."""
        with self._lock:
            self._cache.clear()
            log.info("Invalidated all cached models")

    def get_cache_stats(self) -> dict:
        """Return cache statistics for monitoring."""
        with self._lock:
            return {
                "cached_apps": list(self._cache.keys()),
                "cache_size": len(self._cache),
                "max_models": self.max_models,
                "stats": self._stats.copy(),
            }
