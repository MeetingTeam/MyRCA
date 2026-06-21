## Sơ đồ và Cơ sở dữ liệu

### Tổng quan kiến trúc lưu trữ

Trace-RCA Dashboard sử dụng hai hệ quản trị cơ sở dữ liệu cho hai loại workload khác nhau:

- **PostgreSQL** đảm nhiệm dữ liệu giao dịch của module quản trị: tài khoản người dùng, vai trò và khoá API cấu hình. Đây là dữ liệu có tính nhất quán cao, đòi hỏi ràng buộc khoá ngoại và giao dịch ACID, do đó hệ quản trị quan hệ truyền thống là lựa chọn phù hợp.
- **ClickHouse** đảm nhiệm dữ liệu phân tích sự cố RCA: mỗi sự cố là một bản ghi phân tích lớn (hàng KB tới hàng chục KB) với nhiều trường dạng JSON và trường ngữ cảnh dạng mảng. Khối lượng dữ liệu tăng tuyến tính theo thời gian, truy vấn chủ yếu là quét theo cửa sổ thời gian và tổng hợp theo `app_id`. Đặc tính workload OLAP này phù hợp với kiến trúc cột của ClickHouse và bảng MergeTree.

Việc tách hai hệ là quyết định có chủ đích: tránh ràng buộc một mô hình lưu trữ duy nhất phải gánh đồng thời hai loại workload trái ngược (OLTP cho quản trị, OLAP cho phân tích).

### Sơ đồ cơ sở dữ liệu

![Hình. Sơ đồ cơ sở dữ liệu Trace-RCA Dashboard](er-diagram.png)

Sơ đồ trên gồm hai cụm: cụm Postgres ở bên trái với bốn thực thể và các quan hệ khoá ngoại, cụm ClickHouse ở bên phải với một thực thể chính `incidents` cùng truy vấn dẫn xuất `applications`.

### Cơ sở dữ liệu Postgres

Postgres lưu trữ bốn bảng phục vụ Module Quản trị Cấu hình.

#### Bảng `users`

Bảng `users` lưu thông tin định danh người dùng dashboard. Khoá chính là địa chỉ email do Google OAuth cấp.

| STT | Tên cột | Kiểu | Ràng buộc | Mô tả |
|-----|---------|------|-----------|-------|
| 1 | `email` | `VARCHAR(255)` | PK | Địa chỉ email Google của người dùng |
| 2 | `name` | `VARCHAR(255)` | NOT NULL | Họ tên đầy đủ (lấy từ Google profile) |
| 3 | `picture_url` | `TEXT` | NULL | URL ảnh đại diện |
| 4 | `is_active` | `BOOLEAN` | NOT NULL, mặc định `TRUE` | Trạng thái kích hoạt; `FALSE` đồng nghĩa với việc người dùng bị vô hiệu hoá quyền đăng nhập |
| 5 | `created_at` | `TIMESTAMPTZ` | NOT NULL, mặc định `NOW()` | Thời điểm tạo bản ghi |
| 6 | `updated_at` | `TIMESTAMPTZ` | NOT NULL, mặc định `NOW()` | Thời điểm cập nhật gần nhất |

#### Bảng `roles`

Bảng `roles` định nghĩa danh sách vai trò có sẵn trong hệ thống. Số lượng vai trò nhỏ, ít thay đổi, nên dùng tên vai trò làm khoá chính.

| STT | Tên cột | Kiểu | Ràng buộc | Mô tả |
|-----|---------|------|-----------|-------|
| 1 | `role_name` | `VARCHAR(50)` | PK | Tên vai trò, ví dụ `admin`, `viewer` |
| 2 | `description` | `TEXT` | NULL | Mô tả phạm vi quyền của vai trò |
| 3 | `created_at` | `TIMESTAMPTZ` | NOT NULL, mặc định `NOW()` | Thời điểm tạo vai trò |

#### Bảng `user_roles`

Bảng `user_roles` mô hình hoá quan hệ nhiều-nhiều giữa `users` và `roles`. Một người dùng có thể nhận đồng thời nhiều vai trò; một vai trò có thể gán cho nhiều người dùng. Khoá chính là cặp `(email, role_name)`.

| STT | Tên cột | Kiểu | Ràng buộc | Mô tả |
|-----|---------|------|-----------|-------|
| 1 | `email` | `VARCHAR(255)` | PK, FK → `users(email)`, `ON DELETE CASCADE` | Người dùng được gán vai trò |
| 2 | `role_name` | `VARCHAR(50)` | PK, FK → `roles(role_name)`, `ON DELETE RESTRICT` | Vai trò được gán |
| 3 | `granted_at` | `TIMESTAMPTZ` | NOT NULL, mặc định `NOW()` | Thời điểm gán vai trò |
| 4 | `granted_by` | `VARCHAR(255)` | NULL, FK → `users(email)` | Người thực hiện cấp vai trò; `NULL` cho trường hợp khởi tạo super admin đầu tiên (bootstrap) |

Ràng buộc `ON DELETE CASCADE` ở cột `email` cho phép khi xoá một người dùng, các vai trò gán cho người đó cũng được xoá theo. Ngược lại, `ON DELETE RESTRICT` ở `role_name` bảo vệ vai trò khỏi việc xoá nhầm khi vẫn còn người dùng đang giữ vai trò đó.

#### Bảng `api_keys`

Bảng `api_keys` lưu khoá API của các nhà cung cấp LLM (OpenAI, Anthropic, …) phục vụ phân tích nguyên nhân gốc rễ giai đoạn 2 của hệ thống. Mỗi nhà cung cấp có tối đa một khoá tại một thời điểm; do đó khoá chính chính là tên nhà cung cấp.

| STT | Tên cột | Kiểu | Ràng buộc | Mô tả |
|-----|---------|------|-----------|-------|
| 1 | `provider` | `VARCHAR(50)` | PK | Tên nhà cung cấp LLM, ví dụ `openai`, `anthropic` |
| 2 | `api_key` | `TEXT` | NOT NULL | Giá trị khoá API; phương án lưu trữ an toàn (vault, KMS) nằm ngoài phạm vi của luận văn |
| 3 | `model` | `VARCHAR(100)` | NOT NULL | Tên model gắn với khoá, ví dụ `gpt-4o`, `claude-3-opus-20240229` |
| 4 | `is_active` | `BOOLEAN` | NOT NULL, mặc định `FALSE` | Đánh dấu khoá đang được hệ thống sử dụng |
| 5 | `updated_at` | `TIMESTAMPTZ` | NOT NULL, mặc định `NOW()` | Thời điểm cập nhật gần nhất |
| 6 | `updated_by` | `VARCHAR(255)` | NULL, FK → `users(email)` | Người dùng cập nhật |

Ràng buộc nghiệp vụ "chỉ một bản ghi `is_active = TRUE` trong toàn bảng" được thực thi ở cấp ứng dụng thông qua một giao dịch khi người dùng đổi khoá active: thiết lập `FALSE` cho mọi bản ghi đang active rồi mới thiết lập `TRUE` cho bản ghi được chọn. Lựa chọn này giữ schema đơn giản và tránh phụ thuộc vào tính năng partial unique index không phải cơ sở dữ liệu nào cũng hỗ trợ.

### Cơ sở dữ liệu ClickHouse

ClickHouse lưu trữ một bảng chính là `incidents` và một truy vấn dẫn xuất `applications`.

#### Bảng `incidents`

Bảng `incidents` lưu trữ kết quả của một sự cố hoàn chỉnh sau khi pipeline RCA hai giai đoạn hoàn tất. Mỗi bản ghi chứa cả ngữ cảnh đầu vào (cửa sổ thời gian, ứng dụng) lẫn kết quả phân tích (xếp hạng dịch vụ, nguyên nhân gốc rễ, mức độ tin cậy, log evidence). Cấu trúc bảng được denormalize có chủ đích để giảm số truy vấn join và phù hợp với mô hình lưu cột của ClickHouse.

| STT | Tên cột | Kiểu | Ràng buộc | Mô tả |
|-----|---------|------|-----------|-------|
| 1 | `incident_id` | `String` | Khoá ngữ nghĩa (UUID) | Mã định danh duy nhất của sự cố |
| 2 | `app_id` | `String` | Thuộc sort key | Mã ứng dụng liên quan |
| 3 | `created_at` | `DateTime` | Thuộc sort key, mốc TTL | Thời điểm sinh sự cố (UTC) |
| 4 | `time_window_start` | `DateTime` | — | Thời điểm bắt đầu cửa sổ phân tích |
| 5 | `time_window_end` | `DateTime` | — | Thời điểm kết thúc cửa sổ phân tích |
| 6 | `stage1_ranking` | `String` (JSON) | — | Mảng JSON xếp hạng dịch vụ giai đoạn 1, mỗi phần tử có dạng `{service, score}` |
| 7 | `root_cause` | `String` | — | Nguyên nhân gốc rễ do LLM xác định ở giai đoạn 2 |
| 8 | `confidence_level` | `String` | — | Mức độ tin cậy do LLM trả về dạng nhãn (`low`, `medium`, `high`); kiểu chuỗi được chọn để tương thích trực tiếp với đầu ra của LLM, parse ở tầng ứng dụng; có thể chuẩn hoá thành `Enum8` ở giai đoạn tối ưu |
| 9 | `analysis_summary` | `String` | — | Bản tóm tắt phân tích sự cố do LLM sinh |
| 10 | `total_traces` | `UInt32` | — | Tổng số trace nằm trong cửa sổ phân tích |
| 11 | `anomalous_traces` | `UInt32` | — | Số trace được mô hình anomaly đánh dấu bất thường |
| 12 | `services` | `Array(String)` | — | Danh sách dịch vụ xuất hiện trong tập trace |
| 13 | `log_evidence` | `String` (JSON) | — | Đối tượng JSON chứa log liên quan, gom theo dịch vụ và severity |
| 14 | `status` | `String` | — | Trạng thái xử lý của sự cố, hiện luôn là `completed` |

Bảng dùng engine `MergeTree` với sort key `(created_at, app_id)`, tối ưu cho hai truy vấn phổ biến: liệt kê sự cố mới nhất và lọc theo ứng dụng.

#### Cấu trúc JSON lồng trong các cột

Hai cột `stage1_ranking` và `log_evidence` lưu chuỗi JSON; ứng dụng chịu trách nhiệm parse khi đọc. Cấu trúc các đối tượng JSON như sau.

`stage1_ranking` — mảng các phần tử mô tả mức độ bất thường của từng dịch vụ:

```json
[
  { "service": "checkout-service", "score": 0.8421 },
  { "service": "payment-service", "score": 0.6135 }
]
```

`log_evidence` — đối tượng gom log theo dịch vụ, mỗi dịch vụ là một mảng các bản ghi log đã rút trích:

```json
{
  "checkout-service": [
    { "timestamp": "2026-06-13T10:22:14Z", "level": "ERROR", "message": "..." }
  ],
  "payment-service": [
    { "timestamp": "2026-06-13T10:22:30Z", "level": "WARN", "message": "..." }
  ]
}
```

#### Truy vấn dẫn xuất `applications`

Danh sách ứng dụng mà dashboard hiển thị không được lưu thành một bảng vật lý. Thay vào đó, backend chạy truy vấn dẫn xuất sau đây tại tầng ứng dụng mỗi khi client gọi `GET /api/applications`:

```sql
SELECT DISTINCT app_id FROM incidents;
```

Cách tiếp cận này tuân theo nguyên lý YAGNI: trong khi danh sách ứng dụng hoàn toàn có thể được suy ra từ dữ liệu sự cố hiện hữu, việc duy trì một bảng `applications` đồng bộ đòi hỏi logic ghi kép và xử lý lỗi không cần thiết.

### Khoá và Ràng buộc

Bảng dưới đây tổng hợp các khoá chính, khoá ngoại và ràng buộc duy nhất của toàn bộ năm bảng.

| STT | Bảng | Loại ràng buộc | Cột | Tham chiếu / Ghi chú |
|-----|------|----------------|-----|----------------------|
| 1 | `users` | PK | `email` | — |
| 2 | `roles` | PK | `role_name` | — |
| 3 | `user_roles` | PK | `(email, role_name)` | Khoá ghép |
| 4 | `user_roles` | FK | `email` | → `users(email)`, `ON DELETE CASCADE` |
| 5 | `user_roles` | FK | `role_name` | → `roles(role_name)`, `ON DELETE RESTRICT` |
| 6 | `user_roles` | FK | `granted_by` | → `users(email)`, cho phép `NULL` |
| 7 | `api_keys` | PK | `provider` | — |
| 8 | `api_keys` | FK | `updated_by` | → `users(email)`, cho phép `NULL` |
| 9 | `api_keys` | Ràng buộc nghiệp vụ | `is_active` | Tối đa một bản ghi `TRUE` trong toàn bảng (thực thi ở tầng ứng dụng) |
| 10 | `incidents` | Khoá ngữ nghĩa | `incident_id` | UUID; ClickHouse không enforce PK |
| 11 | `incidents` | Sort key | `(created_at, app_id)` | Engine `MergeTree` |

### Chính sách lưu trữ ClickHouse

Bảng `incidents` áp dụng hai chính sách dữ liệu ở cấp DDL. Thứ nhất, mệnh đề `TTL created_at + INTERVAL 90 DAY DELETE` quy định mọi bản ghi tự động bị xoá sau 90 ngày kể từ thời điểm tạo, qua đó giới hạn lượng dữ liệu phân tích lưu trữ và duy trì tính kịp thời của thông tin RCA. Thứ hai, tham số `storage_policy = 'hot_cold'` cấu hình ClickHouse phân tầng dữ liệu giữa bộ nhớ nóng và bộ nhớ lạnh: các phần dữ liệu mới ưu tiên lưu trên bộ nhớ tốc độ cao, các phần dữ liệu cũ được chuyển sang bộ nhớ chi phí thấp khi đạt ngưỡng tuổi hoặc dung lượng. Chi tiết cấu hình tầng lưu trữ thuộc phạm vi triển khai hệ thống và không đi sâu trong phạm vi luận văn.
