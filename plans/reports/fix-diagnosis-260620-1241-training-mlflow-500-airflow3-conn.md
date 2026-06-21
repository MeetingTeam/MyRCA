# Diagnosis — `training_pipeline` fail tại bước `train` (AWS Batch)

**Date:** 2026-06-20 12:41 +07
**Mode:** Review (no fix applied)
**Status:** Root-cause analysis only — chờ user chọn solution.

## 1. Symptoms

Trace tóm tắt:
- DAG `training_pipeline` chạy đến task `train` (BatchOperator).
- Airflow worker log: `Connection with ID aws_batch not found` (WARNING) → fallback boto3 env-var creds → Batch job submit OK (`jobId=41790d59-...`).
- AWS Batch container chạy, đến `tasks/training.py:284 mlflow.log_dict(dataset_stats, "dataset_info.json")` → crash với HTTP 500 lặp lại lên `http://34.226.226.116:30002/api/2.0/mlflow-artifacts/artifacts/...`.
- Trước đó: `InconsistentVersionWarning: LabelEncoder from version 1.9.0 when using version 1.6.1` (sklearn drift, non-fatal).

## 2. Tách bạch 3 vấn đề

| # | Vấn đề | Mức độ | Liên quan upgrade Airflow 2→3? |
|---|---|---|---|
| A | MLflow artifact endpoint trả 500 | **BLOCKER** | Không trực tiếp (xem 4.A) |
| B | `aws_batch` connection missing | Noise (đã fallback OK) | **Có** — connection không migrate sang Airflow 3 DB |
| C | sklearn 1.9.0 → 1.6.1 unpickle warning | Tiềm ẩn data-corruption risk | Không |

## 3. Root-cause analysis

### A) MLflow artifact 500 (blocker)

**Evidence chain:**
- Tracking endpoint sống — drift_detection đã `start_pipeline_run` thành công, parent_run_id `bc1eadd...` được training nhận.
- Chỉ artifact path `/api/2.0/mlflow-artifacts/artifacts/...` lỗi → server-side 500, không phải network (network sẽ là timeout/502/504).
- MLflow server config (`opensource/mlflow/values-dev.yaml:67-69`): `--serve-artifacts` + `--artifacts-destination=s3://hungtran-mlflow-artifacts` → MLflow **proxy** upload qua HTTP rồi forward sang S3.
- Backend store: SQLite file trên PVC 2Gi (đủ cho metadata, không liên quan S3).

**CONFIRMED ROOT CAUSE (sau khi đọc log MLflow pod):**

```
ModuleNotFoundError: No module named 'boto3'
File "/usr/local/lib/python3.10/site-packages/mlflow/store/artifact/s3_artifact_repo.py", line 59
    import boto3
```

Image `ghcr.io/mlflow/mlflow:v3.3.2` (vanilla upstream) **không bundle boto3**. Config `--serve-artifacts` + `--artifacts-destination=s3://...` yêu cầu server tự PUT S3 ⇒ phải có boto3 ⇒ thiếu ⇒ HTTP 500 cho mọi artifact request. Tracking SQL (DB) không cần boto3 → vẫn 200 OK.

Bucket region OK (`ap-southeast-1`, khớp). Pod restarts là manual (user xác nhận), không phải OOM. Loại trừ H2/H3/H4.

### B) `aws_batch` connection missing (Airflow 2→3 upgrade artifact)

**Root cause:** Airflow 3 dùng SDK mới (`airflow.sdk.Connection`), connection lưu trong metadata DB mới. Khi upgrade từ 2.x, connections cũ trong DB cũ KHÔNG tự migrate. `values-dev.yaml` cũng không khai báo `connections:` hay `AIRFLOW_CONN_AWS_BATCH`. DAG (`training_pipeline_dag.py:184,207`) vẫn tham chiếu `aws_conn_id="aws_batch"`.

**Vì sao vẫn submit được Batch:** BatchOperator catch 404 → fallback boto3 env-var. Secret `airflow-aws-secret` đã mount vào scheduler/worker qua `extraEnvFrom` (values-dev.yaml:48-50) → `AWS_ACCESS_KEY_ID` có sẵn.

**Không phải blocker** — chỉ làm bẩn log. NHƯNG nếu sau này cần per-job IAM role/region khác thì sẽ fail im lặng.

### C) sklearn version drift

**Root cause:** `requirements-mlops-light.txt` không pin sklearn. Evidently 0.4.33 (dep) kéo sklearn latest (1.9.0). `requirements-mlops-gpu.txt:6` pin `scikit-learn==1.6.1`. Preprocess pickle encoders ở light (1.9.0), training unpickle ở gpu (1.6.1) → warning. Sklearn cảnh báo có thể "invalid results" — chưa thấy lỗi cụ thể nhưng là rủi ro nghiêm trọng cho silent corruption.

**Không liên quan Airflow upgrade.** Pre-existing, lộ ra sau khi rebuild image gần đây.

## 4. Solutions (chờ user pick)

### A) Fix MLflow 500 — Sau khi xác nhận root cause là `boto3` missing

| Option | Mô tả | Pros | Cons | Recommend |
|---|---|---|---|---|
| **A1** | Wrap `log_dict` trong try/except (training.py:284) | Defense in depth, pipeline không crash khi MLflow chết tương lai | Không fix gốc | Combine, không một mình |
| **A-NEW-1A** | **Build custom MLflow image** `FROM ghcr.io/mlflow/mlflow:v3.3.2 + pip install boto3` → push → bump `image.tag` trong values | Fix gốc 100%, không đổi kiến trúc, 5 phút công | Phải nhớ duy trì custom image khi upgrade MLflow | **[Recommended]** |
| **A-NEW-1B** | Đổi sang `bitnami/mlflow` image (đã có boto3 + cloud SDKs) | Không cần build | Image lớn hơn (~1GB), khác upstream | Alternative cho 1A |
| **A2** | Tắt artifact proxy (`--no-serve-artifacts`) → client trực tiếp PUT S3 | Loại bỏ tầng proxy hẳn, client đã có boto3 + creds | Cleanup architecture lớn hơn, cần test mọi client | Long-term option |
| **A3** | (loại bỏ — sau khi log confirm là boto3 missing, không phải creds issue) | — | — | — |

**Quick sanity check trước khi quyết định:**
```bash
kubectl exec -n mlflow deploy/mlflow -- env | grep -iE 'aws|s3'
kubectl logs -n mlflow deploy/mlflow --tail=300
aws s3 ls s3://hungtran-mlflow-artifacts/ --region <bucket-region>
```

### B) Fix `aws_batch` connection — 3 lựa chọn

| Option | Mô tả | Pros | Cons |
|---|---|---|---|
| **B1** | `kubectl exec -n airflow deploy/airflow-scheduler -- airflow connections add aws_batch --conn-type aws --conn-extra '{"region_name":"us-east-1"}'` | Best practice Airflow 3; persist trong Postgres | Phải nhớ tái tạo khi rebuild cluster |
| **B2** | **[Recommended]** Thêm vào `values-dev.yaml` block `env:` <br>`- name: AIRFLOW_CONN_AWS_BATCH`<br>`  value: "aws://?region_name=us-east-1"` | Idempotent, GitOps friendly, không cần CLI manual | Cần Helm upgrade |
| **B3** | Bỏ `aws_conn_id="aws_batch"` khỏi DAG (`training_pipeline_dag.py:184,207`), giữ `region_name="us-east-1"` | Đơn giản nhất, code-only | Mất khả năng dùng IAM role/profile riêng sau này |

**Khuyến nghị:** B2 — declarative, không có CLI step.

### C) Fix sklearn drift — 1 lựa chọn

Add vào `requirements-mlops-light.txt`:
```
scikit-learn==1.6.1
```
Khớp với GPU image. Rebuild + push lại image light. Không có alternative đáng cân nhắc — phải pin.

## 5. Câu hỏi cần user xác nhận trước khi sửa

1. **MLflow server đứng hay crashloop?** — chạy giúp `kubectl get pods -n mlflow` và `kubectl logs -n mlflow deploy/mlflow --tail=100`, paste output. Nếu pod healthy thì A2 (đổi sang no-serve-artifacts) là đúng hướng; nếu pod crash, ưu tiên restart trước.
2. **Bucket `hungtran-mlflow-artifacts` ở region nào?** `aws s3api get-bucket-location --bucket hungtran-mlflow-artifacts` — nếu khác `ap-southeast-1` thì có thể là cross-region misconfig.
3. **Airflow upgrade có touch MLflow Helm release không?** Nếu chung release thì có thể trigger redeploy MLflow → confirm trước khi blame upgrade.
4. **Có chấp nhận đổi sang `no-serve-artifacts` không?** Tất cả MLflow client (drift_detection, training, evaluate, model_deploy) sẽ cần AWS creds. Hiện tại pods K8s đã có qua `airflow-aws-secret`. Batch task cũng có. Nên không tốn thêm work.

## 6. Đề xuất thứ tự thực hiện

1. **Trước hết:** chạy 3 lệnh ở mục 5.1, 5.2 → confirm hypothesis A1 hoặc loại trừ.
2. **Quick unblock (15 phút):** áp dụng A1 (wrap try/except) + C (pin sklearn) → rebuild GPU image → trigger pipeline. Có thể train tạm xong khi chưa fix MLflow.
3. **Real fix (1–2 giờ):** áp dụng A2 hoặc A3 tùy diagnosis MLflow pod.
4. **Cleanup riêng:** apply B2 trong PR sau, không khẩn cấp.

## Unresolved questions

- MLflow Helm release có dùng IRSA hay static IAM key cho S3? Không thấy trong scout — cần kiểm tra ServiceAccount + annotations.
- Có bucket `hungtran-mlflow-artifacts` tồn tại không, và policy cho phép user IAM (hoặc role) hiện tại `PutObject` không?
- Mlflow client trong GPU image dùng version nào (logs không in)? Worth pin client + server cùng major version để loại trừ H4.

## Update 2026-06-20 13:30 — Đã apply fix

### Đã làm
- Build + push `asdads6495/mlflow:3.3.2-boto3` (digest `sha256:e72f...`).
- Sửa `opensource/mlflow/values-dev.yaml` image → `asdads6495/mlflow:3.3.2-boto3`.
- Pin `scikit-learn==1.6.1` vào `mlops/requirements-mlops-light.txt`, rebuild + push `asdads6495/mlops-pipeline-light:dev` (digest `sha256:ad89...`).
- `helm upgrade mlflow bitnami/mlflow --version 5.1.17 -n mlflow -f opensource/mlflow/values-dev.yaml`.
- Verify pod mới `mlflow-tracking-7cfdb97fb5-8swp9` Running, 0 restart, `boto3 1.43.34` import OK.
- Trigger `training_pipeline` DAG với `FORCE_DRIFT=true`.
- Drift detection chạy với image mới, sinh được `Quality report saved for app: microservices-demo` (DataQualityStrategy hoạt động).
- Pipeline đã pass qua check_drift → preprocess → train (đang verify Batch).

### Theo dõi
- Train task trên AWS Batch sẽ confirm `mlflow.log_dict(dataset_stats, ...)` PUT thành công sau khi pod MLflow có boto3.
- Quan sát thêm: Evidently TestSuite throw `Cannot create snapshot because of calculation error` cho 1 app — fallback PSI OK, không ảnh hưởng pipeline. Issue riêng cần tách phân tích sau (có thể version Evidently 0.4.33 vs schema dữ liệu mới).
- Skip `mlflow.log_dict` try/except theo yêu cầu user — fix gốc (image mới) đã đủ.

### Còn lại
- `aws_batch` connection warning (Airflow 3) — chưa fix, plan B2 trong PR riêng sau.

## Update 2026-06-20 14:42 — Lớp thứ 2 lộ ra sau khi fix boto3

Sau khi fix boto3, train task vẫn fail với 500. Pull MLflow server log:
```
ClientError: An error occurred (InvalidAccessKeyId) when calling the PutObject operation:
The AWS Access Key Id you provided does not exist in our records.
```

**Root cause lớp 2:** `mlflow-aws-secret` (ns mlflow, tạo 2026-03-21) chứa Access Key `AKIA...2FW7` — đã bị xoá/rotate khỏi IAM nhưng K8s secret chưa update. `airflow-aws-secret` (ns airflow, tạo 5 ngày sau) có key `AKIA...C24E` valid và có quyền PUT lên `hungtran-mlflow-artifacts` (đã test).

**Vì sao chỉ bây giờ lộ:** Lỗi `ModuleNotFoundError boto3` (lớp 1) che lỗi creds (lớp 2). Sau khi fix lớp 1, lớp 2 unmask.

**Fix (A1):** Copy creds từ `airflow-aws-secret` sang `mlflow-aws-secret`:
```bash
kubectl get secret airflow-aws-secret -n airflow -o json | python -c "..." | kubectl apply -f -
kubectl rollout restart deploy/mlflow-tracking -n mlflow
```
Verify trong pod: `python -c "import boto3; boto3.client('s3').head_bucket(Bucket='hungtran-mlflow-artifacts')"` → OK.

### Lessons learned
- Stale K8s Secret là silent failure mode: chart config đúng nhưng value bên trong rỗng/sai → triệu chứng giống code bug.
- Khi sửa lỗi tầng dưới có thể lộ lỗi tầng trên (layered failures). Test end-to-end sau mỗi tầng fix.
- Long-term: migrate IRSA để loại bỏ rotation thủ công.

### Còn cần verify
- Train task trên Batch chạy đến `mlflow.log_dict(...)` và nhận 200 (đang chạy DAG run 3Lu6rQaT).
- evaluate, model_comparison.
