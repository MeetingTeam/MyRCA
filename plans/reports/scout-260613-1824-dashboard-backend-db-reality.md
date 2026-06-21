# Scout Report — Backend & CSDL thực tế của Trace-RCA Dashboard

**Date:** 2026-06-13 18:24
**Trigger:** User confirm backend ở MyRCA, yêu cầu verify trước khi update plan
**Plan reference:** `plans/260613-1812-thesis-dashboard-functional-db/`

## Findings (vs giả định ban đầu)

| Mục | Plan cũ giả định | Thực tế (code) |
|-----|------------------|----------------|
| Số DB system | 2 (Postgres + ClickHouse) | **1 (ClickHouse only)** |
| Postgres tables | users, roles, user_roles, api_keys, applications | **KHÔNG TỒN TẠI** |
| ClickHouse tables | incidents, stage2_result, logs | **Chỉ 1 bảng: `incidents`** |
| User persistence | Bảng users | **Không persist — Google OAuth + JWT stateless** |
| API keys storage | Bảng `api_keys` | **localStorage browser: `rca-api-keys`** |
| Roles/Users admin | Bảng `roles`, `user_roles` | **localStorage browser: `rca-users`** |
| Applications | Bảng riêng | **View dẫn xuất: `SELECT DISTINCT app_id FROM incidents`** |
| Stage 2 result | Bảng/JSON riêng | **Flatten vào cột `root_cause`, `confidence_level`, `analysis_summary` của `incidents`** |
| Log evidence | Bảng logs | **Cột `log_evidence String` (JSON) trong `incidents`** |

## Backend code locations
- `trace_rca_algo/trace_rca_service/api.py` — FastAPI app, 5 endpoints
- `trace_rca_algo/trace_rca_service/incident_store.py` — ClickHouse client, DDL, CRUD
- `trace_rca_algo/trace_rca_service/auth.py` — Google OAuth verify + JWT (stateless, không có user DB)

## API endpoints THẬT (5 endpoints)
| Endpoint | Method | Mục đích | DB hit |
|----------|--------|----------|--------|
| `/api/healthcheck` | GET | Health check | none |
| `/api/auth/google` | POST | Verify Google ID token → JWT | none (stateless) |
| `/api/auth/me` | GET | Decode JWT → user info | none |
| `/api/applications` | GET | DISTINCT `app_id` từ incidents | ClickHouse |
| `/api/incidents` | GET | List incidents (filter app_id, limit) | ClickHouse |
| `/api/incidents/{id}` | GET | Get 1 incident | ClickHouse |

## Schema THẬT của `incidents` (ClickHouse)
```sql
CREATE TABLE IF NOT EXISTS incidents (
    incident_id String,
    app_id String,
    created_at DateTime,
    time_window_start DateTime,
    time_window_end DateTime,
    stage1_ranking String,           -- JSON: [{service, score}, ...]
    root_cause String,
    confidence_level String,
    analysis_summary String,
    total_traces UInt32,
    anomalous_traces UInt32,
    services Array(String),
    log_evidence String,             -- JSON
    status String
) ENGINE = MergeTree()
ORDER BY (created_at, app_id)
TTL created_at + INTERVAL 90 DAY DELETE
SETTINGS storage_policy = 'hot_cold'
```

## Implication cho thesis content

1. **Mô hình phân rã chức năng:** vẫn giữ 6 modules, nhưng phải ghi chú rõ:
   - Module "Quản trị" (api-keys, roles-users) — **UI client-side, lưu trên localStorage**, chưa có backend persistence → KLTN cần neutral wording (vd "lưu trữ phía client trong giai đoạn hiện tại")
   - Module "Lọc theo Application" — không có bảng `applications` riêng, là view dẫn xuất
2. **Sơ đồ CSDL:** chỉ có 1 entity `incidents`. ER diagram đơn giản: 1 entity + self-derived `applications` view + (optional) localStorage shapes mô tả như "lưu trữ phía client" (không phải DB chính thức).
3. **Cơ sở dữ liệu:** chương này NGẮN hơn nhiều so với dự kiến — chủ yếu mô tả 1 bảng + giải thích kiến trúc OLAP-only (ClickHouse) + 90-day TTL + hot/cold storage policy.

## Unresolved questions

1. KLTN có yêu cầu mô tả localStorage shape như là "cơ sở dữ liệu phía client" không, hay chỉ track DB thật của hệ thống?
2. Có nên đề cập module Admin "đang ở giai đoạn UI prototype" trong KLTN — hay loại hẳn module này ra khỏi phân rã chức năng để tránh phải giải thích?
3. ClickHouse `hot_cold` storage policy có thuộc phạm vi "thiết kế CSDL" trong KLTN không?
