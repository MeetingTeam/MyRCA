---
phase: 4
title: "Merge snippets → 1 file .md + LaTeX-friendly review"
status: pending
priority: P2
effort: "0.5h"
dependencies: [2, 3]
---

# Phase 4: Merge snippets → 1 file .md

## Overview
Gộp 2 snippet từ Phase 2 + 3 thành 1 file `.md` duy nhất tại `D:/KLTN/docs/thesis-trace-rca-dashboard/thesis-trace-rca-dashboard.md`. File phải LaTeX-friendly để convert qua Pandoc hoặc copy-paste vào file `.tex` KLTN. Output 100% tiếng Việt.

## Requirements

- **Functional:**
  - 1 file `.md` cuối cùng (không có file `.md` phụ ở deliverables_path)
  - Cấu trúc heading nhất quán: `#` chương → `##` section lớn → `###` sub-section → `####` bảng/component
  - Image reference dùng relative path đến PNG export
  - 2 PNG export từ draw.io đặt đúng vị trí
- **Non-functional:**
  - Pandoc convertible: `pandoc thesis-trace-rca-dashboard.md -o thesis.tex` chạy không lỗi
  - Sẵn sàng copy-paste vào KLTN LaTeX chính

## Architecture (output structure)

```
D:/KLTN/docs/thesis-trace-rca-dashboard/
├── thesis-trace-rca-dashboard.md           ← 1 FILE CHÍNH
├── diagrams.drawio                          ← source draw.io
├── functional-decomp.png                    ← export PNG
└── er-diagram.png                           ← export PNG
```

## Related Code Files

**Đọc:**
- `D:/KLTN/MyRCA/plans/260613-1812-thesis-dashboard-functional-db/snippets/section-functional-decomposition.md` (output phase 2)
- `D:/KLTN/MyRCA/plans/260613-1812-thesis-dashboard-functional-db/snippets/section-database-schema.md` (output phase 3)

**Create:**
- `D:/KLTN/docs/thesis-trace-rca-dashboard/thesis-trace-rca-dashboard.md`

## Implementation Steps

1. **Tạo file `thesis-trace-rca-dashboard.md`** theo cấu trúc:

   ```markdown
   # Chương X. Trace-RCA Dashboard

   <1-2 đoạn giới thiệu tổng quan chương, dẫn dắt 2 section>

   [SNIPPET 2 — Mô hình phân rã chức năng]

   [SNIPPET 3 — Sơ đồ và Cơ sở dữ liệu]

   ## Kết luận chương

   <1 đoạn tổng kết: dashboard 6 module, kiến trúc lưu trữ đa-store hợp lý>
   ```

   - `#` chương = "Trace-RCA Dashboard" (số chương để KLTN tự gán)
   - Concat trực tiếp 2 snippet (đã level-2 `##`)
   - Thêm phần Kết luận chương cuối

2. **Cross-review checklist (LaTeX-friendly tăng cường):**
   - [ ] Chỉ dùng ATX heading (`#`, `##`, ...) — không setext
   - [ ] Heading level đúng hierarchy: 1 → 2 → 3 → 4, không skip level (vd `##` → `####`)
   - [ ] Pipe table chuẩn: hàng header → hàng separator `|---|---|` → rows. Không bảng HTML.
   - [ ] Code fence có language hint (```sql, ```python, ```javascript)
   - [ ] Image: `![Caption](filename.png)` — relative path, không URL, không inline HTML `<img>`
   - [ ] Không emoji trong heading (Pandoc OK nhưng nhiều LaTeX font không support)
   - [ ] Không HTML inline (vd `<br>`, `<strong>`, `<details>`)
   - [ ] Không Mermaid block ``` ```mermaid ```
   - [ ] List nhất quán: `-` cho unordered, `1.` cho ordered
   - [ ] Tên module/chức năng nhất quán giữa 2 section
   - [ ] Module 6 ánh xạ đúng vào 4 bảng Postgres
   - [ ] Mọi cột ClickHouse TRACE được về `incident_store.py:59-79`
   - [ ] Văn phong tiếng Việt thống nhất, không giọng AI ("trong phần này", "hãy cùng")
   - [ ] KHÔNG nhắc "localStorage" / "prototype" / "thiết kế đề xuất" / "pha mở rộng" / "chưa implement" — Module Admin trình bày như đã có
   - [ ] User được thông báo: cần implement Postgres backend cho Module Admin SONG SONG để khớp narrative trước defense

3. **Smoke test thủ công** (không cài Pandoc — bỏ smoke test tự động):
   - Preview markdown trong VSCode (mặc định) — đảm bảo render OK
   - Visual scan: heading hierarchy 1→2→3→4, không skip; tables render đầy đủ; không có raw `<` `>` HTML; code fence có syntax highlight
   - Check 2 image reference resolve được file PNG/SVG cùng folder

4. **Optional polish:** invoke `thesis-writer` skill chạy qua file cuối để clean văn phong tiếng Việt.

## Success Criteria
- [ ] 1 file `.md` duy nhất tại `D:/KLTN/docs/thesis-trace-rca-dashboard/thesis-trace-rca-dashboard.md`
- [ ] 2 PNG export đặt đúng vị trí, reference từ `.md` hoạt động
- [ ] File `.drawio` source 2 pages
- [ ] Tất cả 14 mục checklist LaTeX-friendly PASS
- [ ] VSCode preview render đầy đủ, không lỗi (no raw HTML, table render đúng, image resolve)
- [ ] Có thể copy-paste section vào KLTN LaTeX chính không cần chỉnh sửa lớn

## Risk Assessment

| Rủi ro | Mitigation |
|--------|-----------|
| Pipe table có cell chứa `\|` (escape char) → break parse | Replace `\|` trong text content bằng `\\|` hoặc dùng từ tiếng Việt thay thế |
| SQL code fence bị Pandoc highlight ra warning | Test với `pandoc --highlight-style=tango` |
| PNG export quá lớn (>5MB) làm LaTeX build chậm | Compress qua `pngquant` hoặc giảm DPI xuống 2x; hoặc dùng SVG (vector, file nhỏ) |
| Không có Pandoc → không validate convert được | Checklist LaTeX-friendly 14 mục đủ guarantee; khi user import vào KLTN sẽ phát hiện ngay nếu có lỗi |

## Next Steps
- Sau khi phase này done: 1 file `.md` sẵn sàng copy-paste hoặc Pandoc convert vào KLTN LaTeX
- Optional: `/ck:plan archive` để archive plan + viết journal entry
