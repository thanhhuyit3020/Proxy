# Proxy Manager

Multi-instance proxy manager cho Windows: cho phep chay nhieu profile song song tren cung 1 may,
moi profile di ra Internet qua mot proxy (IP) rieng, quan ly tap trung qua web dashboard.

## Trang thai hien tai (MVP)

Da co (Giai doan 1):
- Proxy pool: import tu file `.txt`/`.csv`, health check (latency + IP thoat thuc te).
- Profile manager: tao/sua/xoa profile, cap phat cong local tu dong, sticky IP + doi IP thu cong,
  auto-rotate theo lich (bat/tat duoc). Sua profile: doi ten, doi pool proxy, bat/tat auto-rotate +
  chu ky, gan app theo ten tien trinh (co picker chon tu tien trinh dang chay).
- Auto-failover: sau moi health check, profile nao co proxy active vua chet se tu chuyen sang
  proxy con song trong pool. Neu het proxy song -> giu nguyen, kill-switch chan traffic (khong lo IP that).
- Layer A gateway: moi profile la 1 listener `127.0.0.1:<port>` noi ca SOCKS5 lan HTTP/HTTPS proxy,
  chain qua upstream proxy (HTTP/HTTPS/SOCKS5, co auth).
- Kill-switch fail-closed: neu proxy active bi danh dau chet, gateway tu choi ket noi thay vi
  fallback ra IP that.
- Process launcher: mo Chrome/Edge/Brave voi proxy tro thang vao gateway cua profile,
  kem user-data-dir co lap cho tung profile (moi profile = 1 phien trinh duyet rieng), chan QUIC
  va giai DNS qua SOCKS5 de tranh leak. App phai co ho tro proxy (trinh duyet); app khong ho tro
  can Layer B (Giai doan 2).
- Leak test & report: so IP quan sat qua gateway voi IP ky vong cua proxy, test kill-switch,
  export CSV/JSON.
- Web dashboard (FastAPI + WebSocket) tai `http://127.0.0.1:8800`.

Dang lam (Giai doan 2 — Layer B, xem thiet ke `docs/layer-b-design.md`):
- **B1 (PASS tren may that): WinDivert bring-up** — nap driver, bat goi outbound TCP + reinject
  nguyen trang, master on/off.
- **B2 (xong, cho self-test): PID->profile mapping** — SOCKET layer (sniff-only) xay bang
  local_port -> pid, doi chieu ten tien trinh voi assigned_process_names cua profile.
- B3..B7 (chua lam): transparent redirect, kill-switch muc goi, IPv6/DNS, QUIC, dong goi.
- Self-test thu cong tung buoc: xem muc "Layer B" ben duoi.

Chua lam:
- Chong DNS leak / IPv6 leak o tang he thong (B5).
- WebRTC leak test cho trinh duyet.

## Layer B (ep dinh tuyen — CAN Administrator + Windows)

Cai them WinDivert:

```bash
pip install -e ".[layerb]"
```

Kiem chung B1 (bring-up) tren may that — mo terminal **Run as administrator** roi chay:

```bash
.venv\Scripts\python.exe -m proxy_manager.layerb.selftest_b1
```

Trong ~15 giay, mo trinh duyet vao mot trang web. PASS neu trang tai binh thuong VA
`packets_seen > 0` (WinDivert bat duoc goi va reinject nguyen trang, khong lam dut ket noi).

Kiem chung B2 (PID->profile mapping), cung mo terminal admin:

```bash
.venv\Scripts\python.exe -m proxy_manager.layerb.selftest_b2
```

Trong ~20 giay, mo trinh duyet vao mot trang web. Script in bang `local_port -> pid -> ten
tien trinh`. Doi chieu PID trong bang voi Task Manager de xac nhan dung tien trinh. PASS neu
`events_seen > 0` va it nhat 1 dong khop voi app vua mo.

Layer B chi chay tren Windows co quyen admin; khi thieu, cac chuc nang Layer A van hoat dong binh thuong.

## Cai dat

Yeu cau Python 3.11+.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Test

```bash
pytest
```

Bo test hien co (70 test case): parse proxy list, SQLite CRUD, SOCKS5/HTTP CONNECT client
handshake (mock stream, khong can proxy that), profile manager (cap phat cong, rotate, sua profile
partial-update, auto-failover khi proxy chet, guard xoa khi dang chay, guard launch khi chua Start),
process launcher (build lenh Chromium voi socks5 + user-data-dir co lap, mock subprocess), leak-test
export CSV/JSON, end-to-end kill-switch fail-closed (gateway tu choi ket noi khi khong co proxy
active -- dam bao khong bao gio fallback ra IP that), va smoke test FastAPI dashboard (edit profile,
process picker endpoint; dung DB tam qua bien moi truong `PROXY_MANAGER_DB_PATH`, khong dung vao
`~/.proxy_manager` that).

## Dong goi EXE (PyInstaller)

```bash
pip install -e ".[dev]"
pyinstaller proxy_manager.spec
```

File thuc thi nam o `dist/proxy-manager/proxy-manager.exe`. Ban hien tai (Layer A) khong can
quyen Administrator. Khi Layer B (WinDivert) duoc them o Giai doan 2, spec se can bat
`uac_admin=True` va kem `WinDivert.dll` + `WinDivert64.sys` vao `datas`.

## Chay

```bash
proxy-manager --port 8800
```

Hoac:

```bash
python -m proxy_manager.cli --port 8800
```

Mo trinh duyet toi `http://127.0.0.1:8800`.

## Su dung nhanh

1. Vao muc **Proxy Pool**, import file proxy (`scheme://user:pass@host:port` moi dong,
   hoac `host:port:user:pass`), bam **Health Check All**.
2. Vao muc **Profiles**, tao profile moi voi danh sach Proxy ID (vd `1,2`).
3. Bam **Start** de mo gateway local cho profile. Cau hinh app/trinh duyet
   dung SOCKS5 hoac HTTP proxy toi `127.0.0.1:<port>` hien thi trong bang.
4. (Tuy chon) Chon trinh duyet o dropdown tren thanh cong cu roi bam **Mở app** de
   mo trinh duyet da cau hinh san proxy cua profile (khong can chinh tay).
5. Bam **Leak Test** de xac nhan IP thoat dung nhu ky vong va kill-switch hoat dong.

## Cau truc

```
src/proxy_manager/
  models.py        # Proxy, Profile dataclasses
  db.py             # SQLite storage
  proxy_pool.py     # import + health check
  socks_client.py   # SOCKS5 client handshake toi upstream
  http_client.py    # HTTP CONNECT client toi upstream
  upstream.py       # mo ket noi qua upstream proxy (dung chung)
  gateway.py        # Layer A: local SOCKS5/HTTP listener per profile
  launcher.py       # mo trinh duyet voi proxy cua profile (user-data-dir co lap)
  profile_manager.py
  leak_test.py
  web/app.py        # FastAPI + WebSocket
  web/static/        # dashboard HTML/CSS/JS
  cli.py
tests/                # pytest suite (xem muc Test o tren)
proxy_manager.spec    # PyInstaller build spec
```
