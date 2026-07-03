# Layer B — Forced Routing Engine (WinDivert): Thiết kế để duyệt

> Trạng thái: **ĐÃ DUYỆT — đang implement cuốn chiếu B1→B7.** Đây là phần rủi ro cao nhất
> của dự án (cần quyền admin + kernel driver), nên làm từng bước nhỏ, có checkpoint sau mỗi bước.
>
> **Quyết định đã chốt (03-07-2026):**
> - App mục tiêu **chủ yếu TCP** → B6 (UDP/SOCKS5 UDP-associate) HOÃN; v1 chặn QUIC ép về TCP.
> - **Chấp nhận chạy as Administrator** + nạp WinDivert driver (UAC elevation khi bật Layer B).
> - Triển khai **cuốn chiếu B1→B7**, checkpoint sau mỗi bước.
> - **B1 (bring-up): PASS trên máy thật** (03-07-2026, packets_seen=308, web tải bình thường).
> - Đang ở: **B2 (PID→profile mapping)** — code xong, chờ self-test B2 trên máy thật.

## 1. Mục tiêu
Ép các app **không hỗ trợ cấu hình proxy** (game client, tool bất kỳ) đi ra Internet qua
gateway của profile — mà app không hề biết nó bị chuyển hướng. Layer A đã lo app có proxy
setting; Layer B lo phần còn lại ở tầng hệ thống.

## 2. Vì sao WinDivert (không phải TUN adapter)
Yêu cầu cốt lõi là định tuyến **theo tiến trình** (per-app), không phải theo IP đích. TUN
adapter (WinTun + tun2socks) chỉ định tuyến theo route/IP, không phân biệt được app nào.
WinDivert bắt gói ở kernel VÀ biết được PID của luồng → đúng công cụ cho per-app. Đây cũng
là hướng đã nêu trong prompt gốc.

## 3. Kiến trúc: mô hình 2-handle
WinDivert có giới hạn: layer biết PID thì không sửa được gói, layer sửa được gói thì không
kèm PID. Nên dùng đồng thời 2 handle:

- **Handle A — SOCKET layer** (`WINDIVERT_LAYER_SOCKET`, sniff-only): nhận sự kiện CONNECT/
  BIND kèm **PID + 5-tuple** ngay khi app mở kết nối. Dùng để xây bảng `5-tuple → PID`.
- **Handle B — NETWORK layer** (sửa được gói): bắt gói TCP outbound, tra bảng ở Handle A để
  biết gói thuộc PID nào → quyết định có chuyển hướng không.

Bảng `5-tuple → PID` cũng có thể bổ sung/đối chiếu bằng `GetExtendedTcpTable` (Windows API)
để chống race khi kết nối mở quá nhanh.

## 4. Transparent redirect + bảng đích gốc (phần khó nhất)
App kết nối tới `dest_ip:dest_port` thật. Ta phải:

1. **Gói outbound** (app → dest): ghi đè đích thành `127.0.0.1:<gateway_port>` của profile,
   tính lại checksum, reinject. Lưu lại `src_port → (dest_ip, dest_port)` vào **bảng đích gốc**.
2. **Gói inbound** (gateway → app): gateway trả lời từ `127.0.0.1:gwport`, nhưng app đang chờ
   trả lời từ `dest_ip:dest_port` → phải ghi đè src của gói về lại `dest_ip:dest_port` trước
   khi giao cho app. Tra ngược bằng `src_port`.
3. **Gateway cần biết đích thật** để chain qua upstream. Nhưng sau khi redirect trong suốt,
   gateway chỉ thấy một kết nối tới `127.0.0.1:gwport` không kèm đích. Giải pháp: một
   **side-channel** — engine mở API nội bộ (vd hàm/endpoint `lookup(peer_src_port) →
   dest_ip:dest_port`) để gateway hỏi đích gốc theo cổng nguồn của kết nối đến. Đây chính là
   bản Windows của `SO_ORIGINAL_DST` trên Linux (iptables REDIRECT).

→ Layer A gateway sẽ cần thêm một chế độ "transparent": thay vì đọc đích từ giao thức SOCKS/
HTTP, nó tra đích gốc qua side-channel rồi mới chain upstream.

## 5. Các vấn đề an toàn bắt buộc
- **Tự loại trừ (chống vòng lặp):** gói outbound của CHÍNH tiến trình proxy-manager (khi
  gateway đi tới upstream) phải KHÔNG bị bắt lại — lọc theo PID của chính mình. Nếu không sẽ
  loop vô hạn.
- **Kill-switch mức gói (fail-closed):** nếu profile không còn proxy sống → **DROP** gói của
  app được quản (không reinject), tuyệt đối không thả ra mạng thật. Đồng bộ với kill-switch
  của Layer A.
- **Chống IPv6 leak:** app có thể đi thẳng ra IPv6 thật. v1 đơn giản & an toàn nhất: **DROP**
  toàn bộ IPv6 outbound của app được quản → ép về IPv4 qua proxy.
- **DNS leak:** app forced không biết dùng remote DNS. Phải chặn UDP 53 trực tiếp và phân giải
  DNS qua proxy (SOCKS5 remote DNS hoặc một resolver-over-SOCKS nội bộ). Đây là mảng khó, tách
  thành bước riêng.
- **QUIC/UDP:** game hay dùng UDP/QUIC. v1: **chặn QUIC (UDP 443)** để ép app rơi về TCP; nêu
  rõ giới hạn app chỉ-UDP chưa hỗ trợ. SOCKS5 UDP-associate để sau (phức tạp).
- **Master off cứng:** một nút/handler đóng TẤT CẢ handle WinDivert và khôi phục mạng bình
  thường ngay lập tức, phòng khi engine lỗi làm nghẽn mạng.

## 6. Module dự kiến (chưa viết)
```
src/proxy_manager/layerb/
  admin.py         # kiem tra/yeu cau quyen Administrator
  driver.py        # nap/kiem tra WinDivert driver (.sys/.dll), master on/off
  pid_map.py       # Handle A: SOCKET layer -> bang 5-tuple -> PID (+ GetExtendedTcpTable)
  redirector.py    # Handle B: NETWORK layer, ghi de dich, bang dich goc, reinject
  orig_dest.py     # bang src_port -> (dest_ip,dest_port) + side-channel cho gateway
  killswitch.py    # DROP goi khi khong co proxy song; DROP IPv6; chan QUIC
```
Gateway (Layer A) thêm **transparent mode**: đọc đích gốc qua `orig_dest` thay vì qua SOCKS/HTTP.

## 7. Rủi ro & giảm thiểu
| Rủi ro | Giảm thiểu |
|---|---|
| Cần admin + driver ký số | Bundle `WinDivert64.sys`+`.dll`, manifest UAC `requireAdministrator`; báo lỗi rõ nếu thiếu |
| Bug kernel làm nghẽn mạng cả máy | Master-off cứng; test trên máy QA cô lập có snapshot; không chạy trên máy production |
| EDR/AV của công ty chặn WinDivert | Có thể xảy ra — **nhưng đúng ra lại là mục tiêu test phát hiện** (khớp test-plan SOC ở `docs/network-monitoring-detection-test-plan.md`) |
| Vòng lặp bắt lại traffic gateway | Loại trừ theo PID của chính mình (bắt buộc) |
| Khó unit-test (kernel) | B1–B2 test passthrough/PID-map bằng integration; redirect (B3+) verify thủ công bằng leak-test có sẵn |

## 8. Kế hoạch chia bước (mỗi bước có checkpoint, dừng được)
- **B1 — Bring-up:** kiểm tra admin, nạp driver, bắt gói của 1 PID mục tiêu rồi **reinject
  nguyên trạng** (chưa redirect). Chứng minh: app vẫn kết nối bình thường + master on/off chạy.
- **B2 — PID→profile:** dựng bảng `5-tuple→PID` (SOCKET layer), quyết định gói nào thuộc app
  được quản. Chứng minh: nhận diện đúng traffic của app đã gán.
- **B3 — Transparent redirect:** ghi đè đích + bảng đích gốc + side-channel cho gateway
  (transparent mode). Chứng minh: **leak-test PASS** — app forced thoát ra đúng IP proxy.
- **B4 — Kill-switch + self-exclude:** DROP khi hết proxy sống; loại trừ PID chính mình.
- **B5 — IPv6 + DNS:** DROP IPv6; phân giải DNS qua proxy. Chứng minh: leak-test DNS/IPv6 PASS.
- **B6 — QUIC/UDP:** chặn QUIC ép về TCP; ghi rõ giới hạn UDP.
- **B7 — Đóng gói:** bundle WinDivert, manifest admin, cập nhật `proxy_manager.spec`.

## 9. Câu hỏi mở (cần trả lời trước khi code)
1. **Giao thức app:** các app/game bạn cần ép chủ yếu dùng **TCP hay UDP**? (Quyết định B6 UDP
   là bắt buộc hay hoãn được — nhiều game dùng UDP nên đây là điểm mấu chốt.)
2. **Quyền admin:** chấp nhận chạy toàn bộ app dưới quyền Administrator khi bật Layer B chứ?
3. **EDR công ty:** nếu EDR/AV của công ty phát hiện & chặn WinDivert thì có chấp nhận không —
   hay đó chính là thứ bạn muốn đo (khớp với mục tiêu test-plan SOC)?
4. **Cách triển khai:** làm cuốn chiếu B1→B7 (checkpoint sau mỗi bước) hay bạn muốn gộp?
```
