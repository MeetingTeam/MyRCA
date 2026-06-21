---
title: "Thesis content — Trace-RCA Dashboard: functional decomposition + database"
status: in-progress
created: 2026-06-13
revised: 2026-06-13
owner: HungPhung
scope: project
type: thesis-writing
language: vi
deliverables_path: D:/KLTN/docs/thesis-trace-rca-dashboard/
codebase_path: D:/KLTN/MyRCA/trace_rca_algo/rca-dashboard/
backend_path: D:/KLTN/MyRCA/trace_rca_algo/trace_rca_service/
reference_pdf: D:/KLTN/docs/web-dashboard-architect.pdf
verification_report: D:/KLTN/MyRCA/plans/reports/scout-260613-1824-dashboard-backend-db-reality.md
---

# Plan: Thesis content cho Trace-RCA Dashboard

## Mục tiêu
Soạn nội dung KLTN (tiếng Việt) cho 3 mục:
1. **Mô hình phân rã chức năng** (3 levels: Hệ thống → Module → Chức năng)
2. **Sơ đồ cơ sở dữ liệu** (ER diagram)
3. **Cơ sở dữ liệu** (mô tả bảng + ràng buộc + chính sách lưu trữ)

Kèm diagram draw.io XML (1 file `.drawio` nhiều pages). **Output tiếng Việt 100%**.

## Verification Log (2026-06-13)
Đã verify backend code và CSDL thực tế — thay đổi lớn so với plan ban đầu. Chi tiết:
`plans/reports/scout-260613-1824-dashboard-backend-db-reality.md`

**Findings chính:**
- Chỉ có **1 DB system**: ClickHouse (không có Postgres)
- Chỉ có **1 bảng**: `incidents` (14 columns)
- Backend stateless (Google OAuth + JWT, không persist user)
- Admin pages (`api-keys`, `roles-users`) lưu localStorage browser, **KHÔNG có backend persistence**
- `applications` là view dẫn xuất từ `SELECT DISTINCT app_id FROM incidents`

## Phạm vi (đã chỉnh)

- **Đối tượng:** `trace_rca_algo/rca-dashboard/` (React 18 SPA, Vite, Google OAuth)
- **Backend:** `trace_rca_algo/trace_rca_service/` (FastAPI, 5 endpoints)
- **DB scope (trình bày trong KLTN):**
  - **ClickHouse**: 1 bảng `incidents` — đã verify, đã triển khai
  - **Postgres**: 4 bảng cho Module Admin (`users`, `roles`, `user_roles`, `api_keys`) — trình bày như CSDL chính thức của hệ thống. Backend Postgres sẽ được user implement song song với việc viết KLTN để khớp narrative trước khi defense.
- **Tham chiếu:** `docs/web-dashboard-architect.pdf` (nhóm khác — align format)

## Deliverables (1 file .md + assets)

| File | Mô tả |
|------|-------|
| `D:/KLTN/docs/thesis-trace-rca-dashboard/thesis-trace-rca-dashboard.md` | **FILE CHÍNH** — 1 file markdown gồm 2 section: "Mô hình phân rã chức năng" + "Sơ đồ CSDL & Cơ sở dữ liệu". Cấu trúc LaTeX-friendly (Pandoc convertible). |
| `D:/KLTN/docs/thesis-trace-rca-dashboard/diagrams.drawio` | Source draw.io, 2 pages: `functional-decomp`, `er-diagram` |
| `D:/KLTN/docs/thesis-trace-rca-dashboard/functional-decomp.png` | Export PNG (3x DPI ≈ 300 DPI print quality) hoặc SVG vector |
| `D:/KLTN/docs/thesis-trace-rca-dashboard/er-diagram.png` | Export PNG (3x DPI ≈ 300 DPI print quality) hoặc SVG vector |

### LaTeX-friendly markdown constraints (BẮT BUỘC)

File `.md` PHẢI tuân thủ để convert sang LaTeX qua Pandoc/copy-paste sạch:
- ATX heading (`#`, `##`, `###`) — KHÔNG dùng setext (`===`, `---`)
- Pipe tables chuẩn (header + separator + rows), KHÔNG bảng HTML
- Fenced code blocks với language hint: ```` ```sql ````, ```` ```python ````
- Image reference đơn giản: `![Caption](functional-decomp.png)` — không HTML `<img>`, không attribute
- KHÔNG dùng: emoji trong heading, inline HTML, `<details>`, callout box GFM, footnote phức tạp, Mermaid blocks
- Reference figure/table bằng caption text (KLTN sẽ tự đánh số khi vào LaTeX)
- Math (nếu có): `$inline$` và `$$display$$` (Pandoc OK)
- List: dùng `-` cho unordered, `1.` cho ordered (consistent)

## Phases (đã chỉnh)
| # | Phase | File | Status | Effort |
|---|-------|------|--------|--------|
| 1 | Research & verification | [phase-01](./phase-01-research-discovery.md) | ✅ completed | 1h |
| 2 | Mô hình phân rã chức năng + draw.io page | [phase-02](./phase-02-functional-decomposition.md) | ✅ completed | 2h |
| 3 | Cơ sở dữ liệu + ER diagram page | [phase-03](./phase-03-database-schema.md) | ✅ completed | 2h |
| 4 | Compile + cross-review | [phase-04](./phase-04-compile-deliverables.md) | ✅ completed | 0.5h |

**Tổng effort còn lại:** 0h — DONE. Còn 1 việc thủ công: export PNG/SVG từ `diagrams.drawio` (xem README).

## Constraints
- Văn phong KLTN tiếng Việt (kỹ sư/nghiên cứu, tránh giọng AI) → invoke `thesis-writer` skill
- Diagram draw.io XML phải mở được trên app.diagrams.net
- Database section phải khớp với CODE THẬT (đã verify) — không bịa schema
- Phải xử lý đúng nature của localStorage features: không trình bày như DB chính thức

## Resolved Decisions (2026-06-13)

**Round 1 — initial scoping:**
1. ✅ DB scope: trực tiếp dashboard
2. ✅ Output: `D:/KLTN/docs/`
3. ✅ Decomp depth: 3 levels
4. ✅ Draw.io: 1 file nhiều pages

**Round 2 — sau verification:**
5. ✅ Module Admin: trình bày schema Postgres cho thesis
6. ✅ ClickHouse storage: đề cập sơ qua, không deep-dive

**Round 3 — sau red-team review:**
7. ✅ **Module Admin direction: bịa vào KLTN, implement Postgres backend NGAY SAU khi nộp content** — schema Postgres trình bày như đã có. User commit hiện thực backend song song với việc viết KLTN để khớp narrative tại thời điểm defense. KHÔNG dùng wording "thiết kế đề xuất pha mở rộng" trong KLTN.
8. ✅ **Encryption:** BỎ claim `encrypted_key`. Dùng `api_key TEXT` đơn giản, ghi chú "lưu trữ an toàn ngoài phạm vi luận văn".
9. ✅ **TTL/storage policy:** giữ trong section CSDL (section 3.6).
10. ✅ **Pandoc:** không cài → Phase 4 bỏ smoke test step, chỉ checklist thủ công.
