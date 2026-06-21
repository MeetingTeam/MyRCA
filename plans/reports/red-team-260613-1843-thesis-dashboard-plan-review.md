# Red-Team Review — Thesis Dashboard Plan

**Date:** 2026-06-13 18:43
**Target:** `plans/260613-1812-thesis-dashboard-functional-db/`
**Mindset:** Hostile reviewer (giảng viên phản biện), KISS/YAGNI/DRY, academic integrity

## Severity legend
- 🔴 **BLOCKER** — sẽ thua khi defense / vấn đề liêm chính
- 🟠 **HIGH** — reviewer chắc chắn pushback
- 🟡 **MEDIUM** — nên fix, không catastrophic
- 🟢 **LOW** — nitpick

---

## 🔴 BLOCKER #1: Academic integrity — "bịa" Postgres vs localStorage reality

**Vấn đề:** Plan trình bày 4 bảng Postgres cho Module Admin như đã thiết kế. Code thật:
- `api-keys-page.jsx:21,35` đọc/ghi `localStorage.getItem('rca-api-keys')`
- `roles-users-page.jsx:21,44` đọc/ghi `localStorage.getItem('rca-users')`
- Backend `api.py` KHÔNG có endpoint nào cho admin

**Phản biện chắc chắn xảy ra:**
- GV xem code → "Sao section CSDL có 4 bảng Postgres mà backend không có endpoint admin?"
- GV chạy demo → mở DevTools → thấy localStorage → "Đây là client-side, không phải database design"
- GV hỏi "show migration files" → không có

**3 options:**
| Option | Tradeoff |
|--------|----------|
| (A) Đổi narrative: trình bày Postgres là "thiết kế đề xuất cho pha tiếp theo", section riêng trong KLTN | An toàn nhất, không bóp méo sự thật. Reviewer chấp nhận "thiết kế chưa implement" nếu trình bày minh bạch. |
| (B) Loại Module Admin khỏi KLTN | YAGNI nhất, ngắn gọn nhất, không có rủi ro phản biện |
| (C) Implement nhanh backend Postgres cho admin (vài chục dòng FastAPI + alembic) | Khớp design — code, không "bịa". Nhưng tốn 4-8h |

**[Recommended]** **(A)** — tách rõ "Phần đã hiện thực" và "Phần thiết kế cho pha mở rộng". KLTN level thiết kế chấp nhận được nếu trình bày trung thực.

---

## 🟠 HIGH #2: `api_keys` schema không khớp UI

**Schema thiết kế:**
```sql
api_keys (key_id, provider, model, encrypted_key, is_active, created_by, ...)
UNIQUE (provider, model)
```

**UI thật (`api-keys-page.jsx`):**
- State `keys: {}` là object keyed by `provider` (KHÔNG phải `(provider, model)`)
- 1 user thấy chỉ 1 set keys → field `created_by` thừa
- UI chỉ track 1 active model TỔNG (`rca-active-model`), không per-provider

**Phản biện:** "Schema phức tạp hơn nhu cầu UI. UNIQUE composite không phản ánh hành vi 1 key/provider."

**Fix:** Đơn giản hoá thành:
```sql
api_keys (provider PRIMARY KEY, encrypted_key, active_model, updated_at)
```
Và `active_model` là 1 setting riêng (table `system_settings`) — không cần `is_active` flag.

---

## 🟠 HIGH #3: `encrypted_key` mở Pandora's box

**Vấn đề:** Thiết kế viết `encrypted_key TEXT NOT NULL -- AES-256 encrypted at rest`. KLTN level CSDL phải trả lời:
- Key encryption key (KEK) lưu ở đâu? KMS? Env var? File?
- Rotation policy?
- Algorithm chi tiết (AES-256-GCM? CBC? IV management?)

**Reality:** localStorage lưu PLAIN TEXT — UI không có encryption.

**Phản biện:** "Bạn nói encrypted_key nhưng KEK quản lý thế nào? Có demo encrypt/decrypt không?"

**Fix:** Hoặc bỏ encryption claim (chỉ `api_key TEXT` + ghi chú "lưu trữ an toàn ngoài phạm vi luận văn") hoặc viết thêm phụ lục về KMS.

---

## 🟠 HIGH #4: `applications` KHÔNG phải VIEW

**Plan viết:** `applications` là "VIEW dẫn xuất từ `SELECT DISTINCT app_id FROM incidents`"

**Reality (`incident_store.py`):** chỉ là 1 hàm Python `list_applications()` chạy SELECT, KHÔNG có `CREATE VIEW`.

**Phản biện:** "Đâu là DDL của VIEW này? Show me."

**Fix:** Đổi từ "VIEW dẫn xuất" thành "truy vấn dẫn xuất" hoặc "phương thức dẫn xuất". Trong ER diagram đánh dấu rõ "Logical query, not stored view".

---

## 🟠 HIGH #5: `confidence_level String` lỏng kiểu

**Schema thật:** `confidence_level String`

**Phản biện:** "Tại sao String? Đáng lẽ Enum (Low/Medium/High) hoặc Float (xác suất). Lập luận tránh chuẩn hóa kiểu là gì?"

**Fix:** Trong section 3.4 phải có 1 câu giải thích — vd "lưu chuỗi để dễ tương thích với LLM output dạng text, parse phía application". Hoặc đề xuất chuyển sang Enum8 trong "Hướng phát triển".

---

## 🟡 MEDIUM #6: Chicken-and-egg trong `user_roles.granted_by`

**Schema thiết kế:**
```sql
granted_by VARCHAR(255) REFERENCES users(email)
```

**Phản biện:** "User đầu tiên (super admin) được ai grant role admin? FK NULL?"

**Fix:** Cho `granted_by` NULLABLE + ghi chú "NULL = system bootstrap". Hoặc có row `users` đặc biệt `system@bootstrap`.

---

## 🟡 MEDIUM #7: TTL + storage_policy thuộc CSDL hay Deployment?

**Plan đặt vào CSDL section 3.6.**

**Phản biện:** "Đây là data retention policy + infrastructure config — thuộc 'Triển khai' chứ không phải 'Thiết kế CSDL'."

**Fix:** OK để lại trong CSDL nếu lập luận "schema-level constraint" (TTL declared in DDL). Nhưng phải có 1 câu defend. Hoặc tách thành "Chính sách dữ liệu" subsection riêng.

---

## 🟡 MEDIUM #8: Module 4 "Tích hợp Quan sát" inflated

**Plan:** Module riêng cho 2 component link (Grafana, MLOps).

**Phản biện:** "Đây không phải module chức năng, chỉ là menu link tĩnh."

**Fix:** Hoặc:
- Merge vào Module 5 (Navigation)
- Giữ + đổi mô tả thành "Module Liên kết Hệ thống Phụ trợ" + giải thích vai trò là entry point sang observability stack

---

## 🟡 MEDIUM #9: Chức năng 6.3 "Chọn model AI" overlap với 6.1

**Plan:** 6.1 "Quản lý API Keys" + 6.3 "Chọn model AI đang dùng" — UI thật chỉ là 1 page (api-keys-page.jsx), 6.3 là dropdown bên trong 6.1.

**Phản biện:** "Sao tách thành 2 chức năng? Cùng 1 màn hình."

**Fix:** Gộp 6.1 + 6.3 thành 1 chức năng có 2 thao tác con. Hoặc giữ tách nhưng giải thích là "2 workflow độc lập trên cùng giao diện".

---

## 🟡 MEDIUM #10: API endpoint `/api/healthcheck` chưa map

**Plan:** "100% endpoints (5) mapped" — nhưng `api.py` có 6 endpoints (kèm `/api/healthcheck`).

**Fix:** Hoặc:
- Khai báo rõ "5 endpoints user-facing + 1 infra healthcheck (không nằm trong phân rã chức năng người dùng)"
- Hoặc thêm chức năng "Health check liveness" vào Module 5 Navigation (gượng ép, không khuyến nghị)

---

## 🟢 LOW #11: Math 21 vs 20 chức năng

**Plan:** Success criteria nói "≥21 chức năng". Sum thực: 4+5+3+2+3+3 = **20**.

**Fix:** Đổi "≥21" → "≥20".

---

## 🟢 LOW #12: PNG export 2x DPI không đủ in ấn

**Plan:** "≥2x DPI" cho PNG export.

**Phản biện:** "Print quality KLTN cần 300 DPI (3x). 2x = 200 DPI có thể bị răng cưa khi in."

**Fix:** Đổi yêu cầu lên 3x hoặc export SVG (vector, không phụ thuộc DPI).

---

## 🟢 LOW #13: Module 3 có thể merge vào Module 2

**Plan:** Module 3 "Lọc Ứng dụng" riêng. Nhưng filter app CHỈ dùng cho incident list.

**Fix:** Optional — merge thành sub-feature của Module 2. KISS hơn nhưng làm Module 2 to.

---

## 🟢 LOW #14: Pandoc smoke test không bắt buộc

**Plan:** Phase 4 step 3 "smoke test (nếu có)" — không có Pandoc thì skip.

**Fix:** Recommend cài Pandoc 1 lần (5 phút download) để Phase 4 có validate thực sự. Hoặc đề xuất alternative: VSCode markdown preview extension.

---

## Tóm tắt khuyến nghị (ưu tiên theo severity)

| # | Action | Effort |
|---|--------|--------|
| 1 | **Quyết định hướng cho Module Admin: option A (designed-for-future) ↔ B (bỏ) ↔ C (implement)** | 0h decision, 0-8h execute |
| 2 | Đơn giản hoá `api_keys` schema (provider PK, bỏ composite UNIQUE, bỏ created_by) | 15 phút |
| 3 | Bỏ `encrypted_key` claim hoặc viết phụ lục KMS | 15 phút |
| 4 | Đổi `applications` "VIEW" → "truy vấn dẫn xuất" trong cả plan + diagram | 5 phút |
| 5 | Thêm 1 câu defend cho `confidence_level String` | 5 phút |
| 6 | `user_roles.granted_by` NULLABLE + ghi chú bootstrap | 5 phút |
| 7 | Defend TTL trong CSDL hoặc tách "Chính sách dữ liệu" | 5 phút |
| 8 | Module 4 đổi tên hoặc merge | 5 phút |
| 9 | Gộp 6.1 + 6.3 hoặc giải thích tại sao tách | 5 phút |
| 10 | Khai báo healthcheck là infra endpoint | 2 phút |
| 11 | Sửa math 21 → 20 | 1 phút |
| 12 | PNG export 3x hoặc SVG | 1 phút |
| 13 | (Optional) merge Module 3 → 2 | 5 phút |
| 14 | (Optional) recommend cài Pandoc | 2 phút |

**Total fix effort:** ~1.5h, không tính #1.

---

## Câu hỏi mở (CẦN user quyết)

1. **Module Admin direction:** A/B/C? (option A = trình bày designed-for-future, B = loại bỏ, C = implement nhanh)
2. **`encrypted_key`:** giữ + viết phụ lục KMS, hay bỏ encryption claim?
3. **TTL/storage:** giữ trong CSDL hay tách "Chính sách dữ liệu"?
4. **Pandoc:** có cài để Phase 4 có smoke test thật không?
