---
phase: 2
title: "Mô hình phân rã chức năng + draw.io page"
status: pending
priority: P1
effort: "2h"
dependencies: [1]
---

# Phase 2: Mô hình phân rã chức năng

## Overview
Viết section KLTN "Mô hình phân rã chức năng" (3 levels: Hệ thống → Module → Chức năng) cho Trace-RCA Dashboard kèm 1 page draw.io thể hiện cây phân cấp. Output tiếng Việt.

## Requirements

- **Functional:**
  - Cây phân rã 3 cấp: **Hệ thống Trace-RCA Dashboard → Module → Chức năng**
  - Mỗi module có mô tả ngắn (1-2 câu) + danh sách chức năng kèm component + route + endpoint
  - Module admin phải có CHÚ THÍCH client-side localStorage rõ ràng
  - Diagram draw.io page tên `functional-decomp`, layout dạng cây từ trên xuống
- **Non-functional:**
  - Văn phong KLTN tiếng Việt → invoke `thesis-writer` skill
  - Mở `.drawio` không lỗi trên app.diagrams.net

## Architecture (cây phân rã ĐÃ VERIFY)

```
Trace-RCA Dashboard
├── 1. Module Xác thực & Phiên (Authentication)
│   ├── 1.1 Đăng nhập Google OAuth (POST /api/auth/google → JWT)
│   ├── 1.2 Lấy thông tin phiên hiện tại (GET /api/auth/me)
│   ├── 1.3 Đăng xuất (xoá JWT khỏi localStorage, redirect /login)
│   └── 1.4 Bảo vệ tuyến (ProtectedRoute → /login khi 401)
│       Backend: stateless (JWT, không persist user)
│
├── 2. Module Giám sát Sự cố (Incident Monitoring)
│   ├── 2.1 Liệt kê sự cố (GET /api/incidents, lọc theo app_id/limit)
│   ├── 2.2 Xem chi tiết sự cố (GET /api/incidents/{id})
│   ├── 2.3 Hiển thị mức độ nghiêm trọng (severity badge, tính từ confidence_level)
│   ├── 2.4 Hiển thị chuỗi lan truyền lỗi (propagation chain từ stage1_ranking JSON)
│   └── 2.5 Tra cứu log evidence (parse từ log_evidence JSON)
│       Backend: ClickHouse incidents
│
├── 3. Module Lọc Ứng dụng (Application Filter)
│   ├── 3.1 Lấy danh sách app (GET /api/applications — DISTINCT app_id)
│   ├── 3.2 Multi-select filter (URL query state via react-router)
│   └── 3.3 Persist selection qua searchParams (deep-link sharable)
│
├── 4. Module Liên kết Hệ thống Phụ trợ (External System Links)
│   ├── 4.1 Liên kết tới Grafana dashboards (3 bảng điều khiển khác nhau)
│   └── 4.2 Liên kết tới MLOps panel: Evidently (data drift), Airflow (pipeline), MLflow (registry)
│       Backend: KHÔNG — entry point sang observability/MLOps stack ngoài
│
├── 5. Module Điều hướng & Phiên UI (Navigation)
│   ├── 5.1 Sidebar collapsible (persist localStorage: sidebar-collapsed)
│   ├── 5.2 Auto-collapse trên mobile (responsive listener)
│   └── 5.3 Routing client-side (react-router-dom v6)
│
└── 6. Module Quản trị Cấu hình (Admin Configuration)
    ├── 6.1 Quản lý API Keys & Model AI (gộp thao tác cấu hình LLM)
    │      • Thêm/sửa/xoá khoá API theo provider (OpenAI, Anthropic, ...)
    │      • Chọn provider + model đang active cho hệ thống RCA
    │      Backend: Postgres `api_keys`
    └── 6.2 Quản lý Người dùng & Vai trò
           • Thêm/sửa/xoá user theo email
           • Gán role (admin, viewer, ...)
           Backend: Postgres `users`, `roles`, `user_roles`
```

**Tổng: 6 module, 19 chức năng level-3** (Module 1: 4, Module 2: 5, Module 3: 3, Module 4: 2, Module 5: 3, Module 6: 2)

> Endpoint `/api/healthcheck` là **infra endpoint**, không thuộc phân rã chức năng người dùng. Tổng cộng API: 6 endpoints = 5 user-facing + 1 infra.

## Related Code Files

**Đọc:**
- `trace_rca_algo/rca-dashboard/src/App.jsx` (routes)
- `trace_rca_algo/rca-dashboard/src/api.js` (5 API calls)
- `trace_rca_algo/rca-dashboard/src/components/*.jsx` (12 components)
- `trace_rca_algo/rca-dashboard/src/auth-context.jsx`
- `trace_rca_algo/trace_rca_service/api.py` (5 endpoints)
- Verification report (cross-check số lượng + tên)
- (Optional) `D:/KLTN/docs/web-dashboard-architect.pdf` — skim format

**Create:**
- `D:/KLTN/MyRCA/plans/260613-1812-thesis-dashboard-functional-db/snippets/section-functional-decomposition.md` (snippet, Phase 4 sẽ merge vào file chính)
- Page `functional-decomp` trong `D:/KLTN/docs/thesis-trace-rca-dashboard/diagrams.drawio`
- Export PNG: `D:/KLTN/docs/thesis-trace-rca-dashboard/functional-decomp.png`

## Implementation Steps

1. **Skim PDF reference 5-10 phút** để chốt format trình bày (cây vs bảng vs hybrid).
2. **Vẽ draw.io page `functional-decomp`:**
   - XML cấu trúc `<mxfile>` với `<diagram name="functional-decomp">`
   - Root node trên cùng (Trace-RCA Dashboard)
   - 6 nhánh module level-2 dưới
   - Chức năng level-3 dưới mỗi module
   - Module 6 (Admin) tô màu khác (xám/cam nhạt) + tag "Prototype"
   - Color coding: root xanh đậm, module xanh nhạt, chức năng xám
   - Edge style: `edgeStyle=orthogonalEdgeStyle`
   - Position thủ công x/y để layout đẹp
3. **Export draw.io page → PNG 3x DPI (~300 DPI print)** hoặc SVG vector, lưu vào `D:/KLTN/docs/thesis-trace-rca-dashboard/functional-decomp.png`.
4. **Viết `snippets/section-functional-decomposition.md` (tiếng Việt, LaTeX-friendly):**
   - Heading mở đầu là `##` (level 2) vì file chính sẽ là `#` (chương): `## Mô hình phân rã chức năng`
   - **Mở đầu** — 1 đoạn mục đích + phương pháp phân rã (1-2 câu)
   - **Sơ đồ phân rã** — `![Hình X. Mô hình phân rã chức năng Trace-RCA Dashboard](functional-decomp.png)`
   - **Mô tả các Module** — 6 sub-section `###`, mỗi module:
     - Vai trò (1-2 câu)
     - Pipe table: STT \| Tên chức năng \| Mô tả \| Component / Route \| Endpoint backend
   - **Bảng tổng hợp** — pipe table: STT \| Module \| Số chức năng \| Datastore
   - Đảm bảo TẤT CẢ rules LaTeX-friendly trong `plan.md` (ATX heading, pipe table, không HTML/emoji/Mermaid)
5. **Cross-check** với verification report: 100% routes + 5 endpoints được phủ.

## Success Criteria
- [ ] Snippet `section-functional-decomposition.md` đầy đủ 3 levels, 6 modules, 19 chức năng
- [ ] Page `functional-decomp` trong `.drawio` mở được, không overlap
- [ ] PNG export đặt đúng `D:/KLTN/docs/thesis-trace-rca-dashboard/functional-decomp.png` (3x DPI hoặc SVG)
- [ ] 100% routes App.jsx được map vào module
- [ ] 5 user-facing endpoints được map; `/api/healthcheck` khai báo là infra (không thuộc phân rã)
- [ ] Module 6 trình bày đầy đủ như đã triển khai (ánh xạ vào 4 bảng Postgres, không nhắc localStorage/prototype)
- [ ] Văn phong KLTN tiếng Việt, không giọng AI
- [ ] LaTeX-friendly: ATX heading only, pipe table chuẩn, không HTML/emoji/Mermaid

## Risk Assessment

| Rủi ro | Mitigation |
|--------|-----------|
| Phân loại module chủ quan | 6 module hiện tại = mỗi module = 1 concern UI/backend rõ ràng |
| Module 6 schema thiết kế nhưng chưa implement → mismatch khi demo | KLTN trình bày level thiết kế, không cần demo backend; nếu reviewer hỏi code → trả lời "thuộc phạm vi mở rộng" |
| draw.io XML layout overlap | Test trên app.diagrams.net trước khi đóng phase |

## Next Steps
- Chạy song song với Phase 3
- Sau Phase 4 compile → đưa vào chương "Phân tích thiết kế" của KLTN
