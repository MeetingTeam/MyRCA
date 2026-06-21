## Mô hình phân rã chức năng

Mô hình phân rã chức năng của Trace-RCA Dashboard được xây dựng theo cách tiếp cận top-down, chia hệ thống thành các nhóm chức năng (module) độc lập về mặt nghiệp vụ và phụ thuộc tối thiểu lẫn nhau. Mỗi module gói các chức năng có cùng mục đích, cùng nguồn dữ liệu hoặc cùng giao diện người dùng. Cấu trúc gồm ba mức: mức 1 là toàn bộ hệ thống dashboard, mức 2 là các module nghiệp vụ, mức 3 là từng chức năng cụ thể mà người dùng có thể tương tác.

### Sơ đồ phân rã

![Hình. Mô hình phân rã chức năng Trace-RCA Dashboard](functional-decomp.png)

Sơ đồ trên thể hiện toàn bộ 6 module và 19 chức năng nghiệp vụ. Mỗi nhánh con của cây phân rã tương ứng một component giao diện trong mã nguồn React, đồng thời ánh xạ tới một (hoặc nhiều) endpoint phía backend.

### Module 1. Xác thực và Phiên người dùng

Module xác thực chịu trách nhiệm kiểm soát quyền truy cập vào dashboard. Phương thức đăng nhập duy nhất là Google OAuth 2.0; backend xác minh ID token nhận từ Google, sau đó cấp phát một JWT phiên ngắn hạn để các yêu cầu tiếp theo gắn kèm trong header `Authorization`.

| STT | Tên chức năng | Mô tả | Component / Route | Endpoint backend |
|-----|---------------|-------|--------------------|------------------|
| 1.1 | Đăng nhập Google OAuth | Người dùng đăng nhập bằng tài khoản Google; backend xác minh ID token, tạo JWT phiên trả về client | `login-page.jsx`, route `/login` | `POST /api/auth/google` |
| 1.2 | Lấy thông tin phiên hiện tại | Lấy dữ liệu người dùng (email, tên, ảnh đại diện) đang đăng nhập từ JWT trong header | `auth-context.jsx` | `GET /api/auth/me` |
| 1.3 | Đăng xuất | Xoá JWT khỏi `localStorage` của trình duyệt, chuyển hướng về trang đăng nhập | `auth-context.jsx`, `App.jsx` (UserMenu) | (không gọi backend) |
| 1.4 | Bảo vệ tuyến truy cập | Trước mọi tuyến chính, kiểm tra trạng thái đã đăng nhập; chuyển hướng `/login` nếu phản hồi 401 từ backend | `App.jsx` (ProtectedRoute) | (kế thừa 1.2) |

### Module 2. Giám sát Sự cố

Đây là module trung tâm của dashboard, hiển thị các sự cố (incident) được phát hiện bởi mô hình anomaly detection cùng kết quả phân tích nguyên nhân gốc rễ (RCA) hai giai đoạn. Toàn bộ dữ liệu sự cố được lưu trong ClickHouse và truy xuất qua API.

| STT | Tên chức năng | Mô tả | Component / Route | Endpoint backend |
|-----|---------------|-------|--------------------|------------------|
| 2.1 | Liệt kê sự cố | Hiển thị danh sách sự cố theo thứ tự thời gian, hỗ trợ lọc theo ứng dụng và giới hạn số lượng | `incident-list.jsx`, route `/` | `GET /api/incidents` |
| 2.2 | Xem chi tiết sự cố | Hiển thị toàn bộ thông tin của một sự cố: thời gian, ứng dụng liên quan, nguyên nhân gốc rễ, mức độ tin cậy, log evidence | `incident-detail.jsx`, route `/incident/:id` | `GET /api/incidents/{id}` |
| 2.3 | Hiển thị mức độ nghiêm trọng | Tính mức độ nghiêm trọng từ `confidence_level` và hiển thị dưới dạng badge màu tương ứng (cao/trung bình/thấp) | `severity-badge.jsx` | (suy ra từ 2.2) |
| 2.4 | Hiển thị chuỗi lan truyền lỗi | Trực quan hoá thứ tự các dịch vụ bị ảnh hưởng (stage 1 ranking) dưới dạng chuỗi node liên kết | `propagation-chain.jsx` | (parse từ trường `stage1_ranking` của 2.2) |
| 2.5 | Tra cứu log evidence | Hiển thị log liên quan đến sự cố, phân tách theo dịch vụ và mức độ severity | `log-evidence.jsx` | (parse từ trường `log_evidence` của 2.2) |

### Module 3. Lọc theo Ứng dụng

Một hệ thống có thể giám sát nhiều ứng dụng cùng lúc. Module này cung cấp khả năng thu hẹp phạm vi xem xét xuống một hoặc nhiều ứng dụng cụ thể, đồng thời lưu trạng thái lọc vào URL để chia sẻ liên kết.

| STT | Tên chức năng | Mô tả | Component / Route | Endpoint backend |
|-----|---------------|-------|--------------------|------------------|
| 3.1 | Lấy danh sách ứng dụng | Lấy tập các giá trị `app_id` xuất hiện trong dữ liệu sự cố | `App.jsx` (AppFilterContext) | `GET /api/applications` |
| 3.2 | Lọc đa lựa chọn | Cho phép chọn nhiều ứng dụng đồng thời thông qua dropdown trên sidebar | `sidebar.jsx` | (kế thừa 2.1) |
| 3.3 | Lưu trạng thái lọc qua URL | Ghi danh sách `app_ids` đã chọn vào query string, hỗ trợ chia sẻ liên kết và khôi phục trạng thái khi tải lại trang | `App.jsx` (`useSearchParams`) | (không gọi backend) |

### Module 4. Liên kết Hệ thống Phụ trợ

Trace-RCA Dashboard không tự hiển thị toàn bộ metric hay biểu đồ huấn luyện mô hình. Thay vào đó, dashboard cung cấp các liên kết trực tiếp tới các hệ thống quan sát và MLOps đã có sẵn trong hạ tầng, giúp người dùng chuyển ngữ cảnh khi cần phân tích sâu hơn.

| STT | Tên chức năng | Mô tả | Component / Route | Endpoint backend |
|-----|---------------|-------|--------------------|------------------|
| 4.1 | Liên kết tới Grafana | Cung cấp các shortcut tới ba bảng điều khiển Grafana: tổng quan dịch vụ, anomalies, hệ thống | `grafana-links.jsx`, route `/grafana` | (không gọi backend) |
| 4.2 | Liên kết tới MLOps panel | Cung cấp shortcut tới Evidently (data drift), Airflow (pipeline điều phối), MLflow (model registry) | `mlops-links.jsx`, route `/mlops` | (không gọi backend) |

### Module 5. Điều hướng và Phiên giao diện

Module hỗ trợ trải nghiệm người dùng thông qua sidebar có thể thu gọn, bộ định tuyến phía client và lưu giữ trạng thái UI giữa các phiên trình duyệt.

| STT | Tên chức năng | Mô tả | Component / Route | Endpoint backend |
|-----|---------------|-------|--------------------|------------------|
| 5.1 | Sidebar thu gọn | Cho phép người dùng thu/mở sidebar, trạng thái lưu vào `localStorage` (`sidebar-collapsed`) | `sidebar.jsx`, `App.jsx` | (không gọi backend) |
| 5.2 | Auto-collapse trên màn hình nhỏ | Tự động thu gọn sidebar khi chiều rộng cửa sổ dưới 768 px (`window.matchMedia`) | `App.jsx` | (không gọi backend) |
| 5.3 | Định tuyến phía client | Quản lý điều hướng giữa các trang bằng `react-router-dom` v6, không tải lại trang | `App.jsx` | (không gọi backend) |

### Module 6. Quản trị Cấu hình

Module quản trị dành cho người dùng có vai trò admin, hỗ trợ cấu hình các khoá API LLM (dùng cho phân tích nguyên nhân gốc rễ giai đoạn 2) và quản lý danh sách người dùng cùng vai trò trong hệ thống.

| STT | Tên chức năng | Mô tả | Component / Route | Endpoint backend |
|-----|---------------|-------|--------------------|------------------|
| 6.1 | Quản lý khoá API và Model AI | Thêm, sửa, xoá khoá API theo provider (OpenAI, Anthropic, ...); chọn provider và model đang được sử dụng cho RCA giai đoạn 2 | `api-keys-page.jsx`, route `/api-keys` | Postgres `api_keys` |
| 6.2 | Quản lý Người dùng và Vai trò | Thêm, sửa, xoá người dùng theo địa chỉ email; gán vai trò admin hoặc viewer | `roles-users-page.jsx`, route `/users` | Postgres `users`, `roles`, `user_roles` |

### Bảng tổng hợp

Bảng dưới đây tổng hợp số lượng chức năng và datastore tương ứng theo từng module.

| STT | Module | Số chức năng | Datastore |
|-----|--------|--------------|-----------|
| 1 | Xác thực và Phiên người dùng | 4 | Stateless JWT (không lưu trữ phía server) |
| 2 | Giám sát Sự cố | 5 | ClickHouse — bảng `incidents` |
| 3 | Lọc theo Ứng dụng | 3 | ClickHouse — truy vấn dẫn xuất từ `incidents` |
| 4 | Liên kết Hệ thống Phụ trợ | 2 | Không có (external link) |
| 5 | Điều hướng và Phiên giao diện | 3 | `localStorage` trình duyệt (UX state) |
| 6 | Quản trị Cấu hình | 2 | Postgres — `users`, `roles`, `user_roles`, `api_keys` |
| | **Tổng** | **19** | |

Sáu module trên phủ toàn bộ năm tuyến API người dùng (`/api/auth/google`, `/api/auth/me`, `/api/applications`, `/api/incidents`, `/api/incidents/{id}`). Endpoint `/api/healthcheck` là endpoint hạ tầng phục vụ kiểm tra sức khoẻ container, không thuộc phạm vi phân rã chức năng người dùng.
