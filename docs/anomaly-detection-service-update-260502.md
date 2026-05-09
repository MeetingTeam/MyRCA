# Anomaly Detection Service Update - 2026-05-02

## Overview

Cập nhật service để hỗ trợ **single global model** với `app_embedding` feature, cho phép model phân biệt traces từ các ứng dụng khác nhau.

## Changes Summary

### 1. Model Architecture (`transformer_ae/model.py`)

**Added:**
- `app_vocab` parameter (default=2)
- `app_embed_dim = 2`
- `app_embedding` layer
- `app_id` trong forward() signature

**Updated:**
- `context_dim`: 22 → 24 (+app_embed_dim)
- `input_projection`: 23 → 25 features
- `decoder_input_projection`: 86 → 88 features

```python
# Before
def forward(self, service_id, parent_service_id, op_id, parent_op_id, http_status, metrics_x)

# After  
def forward(self, service_id, parent_service_id, op_id, parent_op_id, http_status, app_id, metrics_x)
```

### 2. Evaluation (`transformer_ae/evaluate.py`)

**Updated:**
- `preprocess_test_df()`: thêm xử lý `app_id` column
- `build_sequences()`: trả về 8 values (thêm `apps`)
- `evaluate_model()`: truyền `app_vocab` khi khởi tạo model

### 3. Service (`anomaly_detection_service.py`)

**Updated:**
- Unpack 8 values từ `build_sequences()` (thêm `apps`)
- Thêm `apps` vào `TensorDataset`
- Cập nhật DataLoader loop để unpack `app_id`
- Model forward call: `model(s, ps, op, pop, h, a, x)`

### 4. Model Registry (`model_registry.py`)

**Updated:**
- Đọc `app_encoder` từ `encoders["app_id"]` hoặc `encoders["app"]`
- Truyền `app_vocab` khi khởi tạo `TransformerAutoencoder`
- Áp dụng cho cả S3 loading và local fallback

### 5. S3 Model Path (Simplified)

**Before:** Per-app model path
```
mlops/models/{app_id}/{version}/
```

**After:** Single global model
```
mlops/models/{version}/
```

**Removed:** `_find_legacy_version()` method

## Docker Image

| Version | Tag | Changes |
|---------|-----|---------|
| 1.3.0 | 27058b0 | Initial global model |
| 1.3.1 | 27058b0 | Sync model files |
| 1.4.0 | 27058b0 | Add app_embedding |
| 1.4.1 | 27058b0 | Fix unpack error |

**Current:** `asdads6495/myrca-anomaly-detection:1.4.1-27058b0`

## K8s Deployment

**Manifest:** `opensource/anomaly-detection-service/deployment.yaml`

**Namespace:** `anomaly-detection`

## Files Modified

```
MyRCA/model/
├── transformer_ae/
│   ├── model.py              # +app_embedding
│   └── evaluate.py           # +app_id handling
├── anomaly_detection_service.py  # +app_id in inference
├── model_registry.py         # +app_vocab, simplified S3 path
└── ...

MyRCA/opensource/anomaly-detection-service/
└── deployment.yaml           # Updated image tag
```

## S3 Model Location

```
s3://kltn-anomaly-dateset-1/mlops/models/v001/
├── model.pth      (662KB)
├── encoders.pkl   (65KB)
├── scalers.pkl    (896B)
└── metadata.json
```

## Verification

1. Service starts without errors
2. Health endpoint returns `{"status":"ok"}`
3. Model loads on first request
4. Anomaly scores calculated correctly for both apps
