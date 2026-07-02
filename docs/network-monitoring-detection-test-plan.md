# Kế hoạch kiểm thử: Khả năng phát hiện định tuyến proxy theo tiến trình (per-process proxy routing)

## 1. Mục đích
Đánh giá năng lực của hệ thống giám sát/kiểm soát mạng nội bộ (EDR, DLP, NDR, proxy gateway, firewall, SIEM...) trong việc **phát hiện và cảnh báo** khi một máy trạm trong mạng công ty sử dụng kỹ thuật định tuyến proxy riêng biệt cho từng tiến trình/ứng dụng (per-app IP), bao gồm cả trường hợp ứng dụng bị ép định tuyến ở tầng hệ thống (kernel-level packet redirection).

Đây là tài liệu **kế hoạch**, không kèm công cụ né tránh phát hiện. Việc triển khai kỹ thuật (nếu được phê duyệt) phải do đội SOC/Network Security thực hiện trong môi trường kiểm soát, có giám sát chéo (four-eyes) và log đầy đủ.

## 2. Phạm vi & thẩm quyền
- **Đối tượng kiểm thử:** hệ thống giám sát mạng nội bộ do công ty sở hữu (proxy/firewall log, EDR, NDR, SIEM, DLP).
- **Máy trạm dùng để test:** máy thuộc sở hữu công ty, được cấp riêng cho bài test, KHÔNG dùng máy công tác hàng ngày của cá nhân.
- **Phê duyệt bắt buộc trước khi thực hiện:**
  - Văn bản phê duyệt từ Trưởng nhóm An ninh mạng/CISO (hoặc cấp tương đương).
  - Thông báo cho đội SOC/NOC về cửa sổ thời gian test (change window) để tránh false-positive gây nhiễu vận hành, hoặc cố ý KHÔNG thông báo trước nếu mục tiêu là test khả năng phát hiện của SOC (blind test) — nhưng khi đó bắt buộc có "get-out-of-jail" ticket được người có thẩm quyền ký, và một người quan sát độc lập (không thuộc SOC) theo dõi để dừng ngay nếu có rủi ro.
  - Xác nhận phạm vi mạng test không ảnh hưởng hệ thống production/khách hàng.
- **Ngoài phạm vi:** không thử nghiệm trên tài sản không thuộc sở hữu công ty; không thực hiện trên máy cá nhân của nhân viên khác mà không có sự đồng ý; không dùng dữ liệu thật của khách hàng trong quá trình test.

## 3. Kỹ thuật được mô phỏng (test vectors)
| # | Vector | Mô tả | Tầng bị ảnh hưởng |
|---|--------|-------|---------------------|
| 1 | Proxy setting ở tầng ứng dụng | App có hỗ trợ cấu hình proxy (trình duyệt, tool) trỏ ra proxy ngoài khác IP thật | Application layer |
| 2 | Ép định tuyến ở tầng OS/kernel | Dùng driver bắt gói tin theo PID (packet filter driver) để chuyển hướng traffic của app không hỗ trợ proxy | OS/kernel layer |
| 3 | Nhiều IP thoát khác nhau trên cùng 1 host | Nhiều tiến trình trên cùng máy thoát ra Internet bằng các IP khác nhau cùng lúc | Network egress |
| 4 | Đổi IP theo chu kỳ | IP thoát của một tiến trình thay đổi định kỳ trong phiên làm việc | Network egress / session |
| 5 | DNS qua kênh khác | Truy vấn DNS không đi qua resolver nội bộ chuẩn của công ty | DNS layer |
| 6 | IPv6 song song | Traffic thoát qua IPv6 trực tiếp trong khi IPv4 bị định tuyến qua proxy | Network layer |

## 4. Mục tiêu phát hiện cần đánh giá (đối với đội Blue Team / hệ thống giám sát)
Với mỗi vector ở mục 3, xác định:
- Hệ thống có **ghi log** sự kiện không (proxy log, firewall log, EDR process-network correlation)?
- Có **cảnh báo (alert)** được sinh ra không? Alert có tự động hay cần phân tích thủ công?
- **Thời gian phát hiện** (time-to-detect) tính từ lúc bắt đầu hành vi đến khi có alert.
- Có **quy tắc tương quan tiến trình ↔ kết nối mạng** (process-to-connection mapping) để phát hiện một host thoát ra nhiều IP bất thường không?
- Có phát hiện được **driver/packet-filter lạ** được cài trên endpoint (qua EDR/AV signature, service list, driver load event) không?
- Có phát hiện DNS bất thường (query tới resolver ngoài whitelist) không?

## 5. Kịch bản kiểm thử
1. **Baseline:** ghi nhận traffic bình thường của máy test (không có kỹ thuật gì) để so sánh.
2. **Kịch bản A — Proxy hợp lệ nhưng nhiều IP khác nhau cho nhiều app:** cấu hình 2-3 ứng dụng trỏ tới 2-3 proxy khác nhau, quan sát log/alert.
3. **Kịch bản B — Ép định tuyến tầng hệ thống:** dùng một tiến trình test không hỗ trợ proxy, ép định tuyến bằng driver bắt gói, quan sát:
   - Alert từ EDR khi driver được load.
   - Alert từ NDR/firewall khi phát hiện egress bất thường.
4. **Kịch bản C — Đổi IP theo chu kỳ:** thay proxy sau mỗi khoảng thời gian cố định, đo thời gian SOC phát hiện pattern.
5. **Kịch bản D — DNS/IPv6 leak giả lập:** tạo truy vấn DNS ra ngoài whitelist / traffic IPv6 song song, quan sát alert.
6. **Rollback:** sau mỗi kịch bản, khôi phục máy về trạng thái baseline (gỡ driver, xoá route, restart network stack), xác minh máy sạch trước khi chuyển kịch bản tiếp theo.

## 6. Tiêu chí Pass/Fail
Với mỗi vector: **Pass (phát hiện được)** nếu hệ thống sinh log + alert trong thời gian mục tiêu (đề xuất: ≤ 15 phút cho alert tự động, ≤ 4 giờ nếu qua phân tích thủ công/threat hunting). **Fail (không phát hiện)** nếu không có log, hoặc có log nhưng không có cơ chế alert/correlation nào chỉ ra hành vi bất thường.

## 7. Báo cáo
Xuất báo cáo dạng bảng cho từng vector: mô tả kỹ thuật, log có ghi nhận không, alert có sinh ra không, thời gian phát hiện, kết luận pass/fail, khuyến nghị cải thiện (rule mới, threshold, tăng cường EDR policy...).

## 8. Nguyên tắc an toàn khi thực hiện
- Toàn bộ hoạt động chỉ chạy trên máy test cô lập, có snapshot/backup trước khi bắt đầu.
- Không để lộ dữ liệu nội bộ nhạy cảm qua các proxy/IP dùng trong test.
- Dừng ngay lập tức nếu phát sinh ảnh hưởng ngoài dự kiến tới hệ thống production.
- Toàn bộ log, cấu hình, và kết quả test được lưu trữ theo chính sách bảo mật nội bộ, không public.

## 9. Việc cần điền trước khi trình phê duyệt
- [ ] Người phê duyệt & ngày ký duyệt: __________
- [ ] Cửa sổ thời gian thực hiện: __________
- [ ] Máy trạm test (asset tag/hostname): __________
- [ ] Có phải blind test với SOC không (Có/Không): __________
- [ ] Người quan sát độc lập (nếu blind test): __________
