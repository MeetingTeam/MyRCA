---
phase: 3
title: "Sơ đồ CSDL + Cơ sở dữ liệu + ER diagram page"
status: pending
priority: P1
effort: "2h"
dependencies: [1]
---

# Phase 3: Sơ đồ CSDL + Cơ sở dữ liệu

## Overview
Viết section KLTN "Sơ đồ CSDL" + "Cơ sở dữ liệu" cho phần dashboard. Gồm 2 datastore: **ClickHouse `incidents` (đã verify)** + **Postgres 4 bảng cho Module Admin (thiết kế)**. Kèm 1 page draw.io ER diagram. Output tiếng Việt.

## Requirements

- **Functional:**
  - ER diagram thể hiện 2 nhóm entity: Postgres (auth/admin) + ClickHouse (RCA data)
  - Postgres tables (thiết kế): `users`, `roles`, `user_roles`, `api_keys` — schema hợp lý dựa trên UI hiện tại
  - ClickHouse table (verified): `incidents` 14 cols + `applications` view dẫn xuất
  - Data dictionary đầy đủ cho từng bảng
  - Mục riêng "Chính sách lưu trữ ClickHouse" — đề cập SƠ QUA TTL 90 ngày + MergeTree (không deep-dive `hot_cold`)
- **Non-functional:**
  - Notation Crow's foot (chốt theo PDF reference)
  - Schema Postgres: thiết kế cho Module Admin (user implement backend song song); schema ClickHouse: đã verify từ code
  - Văn phong KLTN tiếng Việt

## Architecture

### Postgres (CSDL chính thức cho Module Admin)

> KLTN trình bày như CSDL đã triển khai. User sẽ implement Postgres backend song song để khớp narrative trước defense. KHÔNG dùng wording "thiết kế đề xuất" hay "pha mở rộng".

```sql
-- users: danh sách user dashboard, định danh qua email (Google OAuth)
CREATE TABLE users (
    email        VARCHAR(255) PRIMARY KEY,
    name         VARCHAR(255) NOT NULL,
    picture_url  TEXT,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- roles: vai trò có sẵn (admin, viewer, ...)
CREATE TABLE roles (
    role_name    VARCHAR(50) PRIMARY KEY,
    description  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- user_roles: quan hệ M-N user ↔ role
CREATE TABLE user_roles (
    email        VARCHAR(255) NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    role_name    VARCHAR(50)  NOT NULL REFERENCES roles(role_name) ON DELETE RESTRICT,
    granted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    granted_by   VARCHAR(255) REFERENCES users(email),   -- NULLABLE: NULL = system bootstrap (super admin đầu tiên)
    PRIMARY KEY (email, role_name)
);

-- api_keys: cấu hình khoá API LLM cho hệ thống RCA (1 key per provider)
CREATE TABLE api_keys (
    provider     VARCHAR(50) PRIMARY KEY,        -- 'openai', 'anthropic', ...
    api_key      TEXT NOT NULL,                  -- giá trị token, lưu trữ an toàn nằm ngoài phạm vi luận văn
    model        VARCHAR(100) NOT NULL,          -- model gắn với key này, vd 'gpt-4o', 'claude-3-opus'
    is_active    BOOLEAN NOT NULL DEFAULT FALSE, -- ràng buộc cấp ứng dụng: chỉ 1 row active toàn hệ thống
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by   VARCHAR(255) REFERENCES users(email)
);
```

**Ghi chú thiết kế (đưa vào section CSDL của KLTN):**
- `api_keys.is_active` ràng buộc "chỉ 1 row active" thực thi ở cấp ứng dụng (transaction trong handler khi user đổi active). Không dùng partial unique index để giữ schema đơn giản.
- `api_keys.api_key` lưu thuần text trong scope luận văn. Trong sản xuất, cần mở rộng với KMS/vault — thuộc phạm vi triển khai an toàn, không nằm trong thiết kế CSDL cốt lõi.
- `user_roles.granted_by` cho phép NULL để bootstrap super admin đầu tiên (không có user nào "grant" trước đó).

### ClickHouse (verified)

```sql
CREATE TABLE incidents (
    incident_id          String,
    app_id               String,
    created_at           DateTime,
    time_window_start    DateTime,
    time_window_end      DateTime,
    stage1_ranking       String,        -- JSON: [{service, score}, ...]
    root_cause           String,
    confidence_level     String,
    analysis_summary     String,
    total_traces         UInt32,
    anomalous_traces     UInt32,
    services             Array(String),
    log_evidence         String,        -- JSON
    status               String
) ENGINE = MergeTree()
ORDER BY (created_at, app_id)
TTL created_at + INTERVAL 90 DAY DELETE
SETTINGS storage_policy = 'hot_cold';

-- applications: KHÔNG phải VIEW vật lý, chỉ là truy vấn dẫn xuất từ application layer
-- Backend (incident_store.list_applications) chạy:
SELECT DISTINCT app_id FROM incidents;
```

### Relationships

```
Postgres:
  users (1) ──< (N) user_roles (N) >── (1) roles
  users (1) ──< (N) api_keys                       [created_by]

ClickHouse:
  incidents (đứng độc lập, denormalized)
       │
       └── applications (truy vấn dẫn xuất từ application layer, không phải VIEW vật lý)

Logical reference (giữa 2 DB):
  users.email ┄┄┄┄ (audit) ┄┄┄┄ incidents.created_by    -- nếu mở rộng audit, hiện chưa có
```

## Related Code Files

**Đọc:**
- `trace_rca_algo/trace_rca_service/incident_store.py` (DDL line 59-79)
- `trace_rca_algo/rca-dashboard/src/components/api-keys-page.jsx` (UI shape → infer api_keys columns)
- `trace_rca_algo/rca-dashboard/src/components/roles-users-page.jsx` (UI shape → infer users/roles columns)
- Verification report
- (Optional) PDF reference — skim notation

**Create:**
- `D:/KLTN/MyRCA/plans/260613-1812-thesis-dashboard-functional-db/snippets/section-database-schema.md` (snippet, Phase 4 sẽ merge vào file chính)
- Page `er-diagram` thêm vào `D:/KLTN/docs/thesis-trace-rca-dashboard/diagrams.drawio`
- Export PNG: `D:/KLTN/docs/thesis-trace-rca-dashboard/er-diagram.png`

## Implementation Steps

1. **Skim PDF reference** chốt notation (Crow's foot khuyến nghị).
2. **Vẽ draw.io page `er-diagram`:**
   - Container 2 nhóm: **"Postgres (Xác thực & Quản trị)"** + **"ClickHouse (Dữ liệu RCA)"**
   - Postgres: 4 entity `users`, `roles`, `user_roles`, `api_keys` với đầy đủ columns
   - PK đánh dấu (icon khóa hoặc gạch dưới), FK gạch nét đứt + ký hiệu
   - Relationship Crow's foot:
     - `users` 1—N `user_roles` N—1 `roles`
     - `users` 1—N `api_keys`
   - ClickHouse: 1 entity `incidents` với 14 cols, đánh dấu sort key `(created_at, app_id)`
   - JSON columns: chú thích "(JSON)" trong type
   - `applications`: dashed border + label "Truy vấn dẫn xuất (không phải VIEW vật lý)"
   - Không vẽ relationship cross-DB (đề cập trong text)
3. **Export draw.io page → PNG 3x DPI (~300 DPI print)** hoặc SVG vector, lưu vào `D:/KLTN/docs/thesis-trace-rca-dashboard/er-diagram.png`.
4. **Viết `snippets/section-database-schema.md` (tiếng Việt, LaTeX-friendly):**
   - Heading mở đầu `## Sơ đồ và Cơ sở dữ liệu` (level 2)
   - `### Tổng quan kiến trúc lưu trữ` — 2 datastore, lý do tách (OLTP/auth/admin → Postgres, OLAP/timeseries/RCA → ClickHouse). Trade-off ngắn.
   - `### Sơ đồ cơ sở dữ liệu` — `![Hình X. Sơ đồ CSDL Trace-RCA Dashboard](er-diagram.png)`
   - `### Cơ sở dữ liệu Postgres (Xác thực & Quản trị)`
     - `#### Bảng users` — vai trò + pipe table data dictionary
     - `#### Bảng roles` — tương tự
     - `#### Bảng user_roles` — tương tự + giải thích composite PK
     - `#### Bảng api_keys` — tương tự + ghi chú `is_active` ràng buộc cấp ứng dụng + 1 câu disclaimer "lưu trữ an toàn ngoài phạm vi luận văn"
   - `### Cơ sở dữ liệu ClickHouse (Lớp dữ liệu RCA)`
     - `#### Bảng incidents` — pipe table data dictionary 14 cols
     - **Defend `confidence_level String`:** thêm 1 câu giải thích — "lưu chuỗi để dễ tương thích với output của LLM dạng nhãn văn bản (low/medium/high), parse hậu kỳ ở application layer; có thể chuẩn hoá thành Enum8 trong pha tối ưu"
     - `#### Cấu trúc JSON nested` — `stage1_ranking`, `log_evidence` (mô tả keys con)
     - `#### Truy vấn dẫn xuất applications` — KHÔNG phải VIEW vật lý; thực thi tại application layer (`incident_store.list_applications`)
   - `### Khoá và Ràng buộc` — pipe table tổng hợp PK / FK / UNIQUE / INDEX
   - `### Chính sách lưu trữ ClickHouse` — 1 đoạn ≤200 từ: MergeTree + sort key + TTL 90 ngày + 1 câu disclaimer cho hot/cold policy
   - Đảm bảo TẤT CẢ rules LaTeX-friendly trong `plan.md`
   - SQL fence dùng ```` ```sql ```` để Pandoc syntax-highlight đúng
5. **Verify** `incidents` schema khớp `incident_store.py:59-79`; Postgres schema inferred từ UI (api-keys-page, roles-users-page) — không nhắc gốc inferring trong KLTN.

## Success Criteria
- [ ] Snippet `section-database-schema.md` đầy đủ các sub-section
- [ ] Page `er-diagram` mở được, đủ 4 Postgres entity + 1 ClickHouse entity + 1 view
- [ ] PNG export đặt đúng `D:/KLTN/docs/thesis-trace-rca-dashboard/er-diagram.png`
- [ ] Data dictionary đầy đủ cho cả 5 bảng (4 Postgres + 1 ClickHouse)
- [ ] JSON sub-schemas có liệt kê key (stage1_ranking, log_evidence)
- [ ] Section "Khoá và Ràng buộc" có bảng tổng hợp PK/FK/UNIQUE
- [ ] Section "Chính sách lưu trữ" ngắn gọn (≤200 từ), không deep-dive hot_cold
- [ ] Crow's foot notation đúng cardinality
- [ ] Văn phong KLTN tiếng Việt
- [ ] LaTeX-friendly: ATX heading only, pipe table chuẩn, SQL fence có language hint, không HTML/emoji

## Risk Assessment

| Rủi ro | Mitigation |
|--------|-----------|
| Reviewer hỏi "code Postgres đâu?" | User implement backend Postgres SONG SONG với việc viết KLTN; tại thời điểm defense sẽ có code thật khớp narrative. Đây là phụ thuộc cứng — KLTN content không thể defense nếu user chưa implement xong backend |
| Reviewer hỏi `hot_cold` cụ thể | Pre-empt: section 3.6 có 1 câu disclaimer "chi tiết cấu hình triển khai" |
| `api_keys.is_active` ràng buộc cấp ứng dụng dễ bị race condition | Ghi rõ trong section CSDL: "thực thi qua transaction trong handler" |
| Reviewer hỏi tại sao `applications` không tạo VIEW thật | Trả lời: YAGNI — query đơn giản, không cần materialize, save storage |

## Next Steps
- Song song với Phase 2
- Sau Phase 4 → đưa vào chương "Thiết kế CSDL" của KLTN
