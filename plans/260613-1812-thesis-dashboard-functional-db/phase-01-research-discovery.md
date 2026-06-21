---
phase: 1
title: "Research & Verification (DONE)"
status: completed
priority: P1
effort: "1h"
dependencies: []
---

# Phase 1: Research & Verification

## Overview
✅ **HOÀN THÀNH 2026-06-13.** Đã verify backend code + DB schema thực tế, output báo cáo verification.

## Outcome

Backend code đã định vị tại `trace_rca_algo/trace_rca_service/`:
- `api.py` — FastAPI app, 5 endpoints
- `incident_store.py` — ClickHouse client + DDL
- `auth.py` — Google OAuth verify + JWT (stateless)

CSDL thực tế: **1 bảng ClickHouse `incidents`** (xem báo cáo verification để có DDL đầy đủ).

Admin pages (api-keys, roles-users) là **client-side localStorage**, không có backend.

## Deliverable

📄 **Verification report:** `D:/KLTN/MyRCA/plans/reports/scout-260613-1824-dashboard-backend-db-reality.md`

Báo cáo gồm:
- Bảng so sánh "giả định ban đầu" vs "thực tế"
- Danh sách 5 API endpoints + DB hit mapping
- DDL gốc của bảng `incidents`
- Implication cho thesis content
- 3 unresolved questions cho user

## Success Criteria
- [x] Định vị backend code
- [x] Trích DDL `incidents` đầy đủ
- [x] Xác nhận api-keys + roles-users là localStorage-based
- [x] Báo cáo verification độc lập feed được Phase 2-3
- [ ] **PDF reference chưa đọc** — `D:/KLTN/docs/web-dashboard-architect.pdf` (sẽ làm đầu Phase 2 nếu cần align format)

## Next Steps
→ Phase 2 + 3 chạy song song được. Mỗi phase đầu sẽ skim PDF reference 5 phút để chốt format trình bày trước khi viết.
