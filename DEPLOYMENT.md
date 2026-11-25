# Deployment Information

## Public URL

https://ai-agent-phqg.onrender.com

## Platform

**Render** (Blueprint, gói Free, vùng Singapore). Agent là chính `06-lab-complete/` của repo này, build bằng `Dockerfile` trong thư mục đó và dựng bằng `06-lab-complete/render.yaml`.

| Tài nguyên | Loại | Ghi chú |
|------------|------|---------|
| `ai-agent` | Web Service (Docker) | Deploy từ commit `ea17ce9` trên nhánh `main`, deploy mất 1 phút 9 giây, trạng thái **Live** |
| `agent-redis` | Key Value (Valkey 8.1.10, tương thích Redis) | Vùng Singapore, trạng thái **Available** |

Ghi chú: gói Free của Render cho service "ngủ" khi không có request; lần gọi đầu sau đó có thể chậm khoảng 50 giây.

## Test Commands

Đặt `BASE` và `AGENT_API_KEY` (giá trị key lấy trong dashboard Render, **không ghi vào repo**):

```bash
BASE=https://ai-agent-phqg.onrender.com
```

### Health Check

```bash
curl -sS $BASE/health
# {"status":"ok","uptime_seconds":...,"environment":"production"}   → HTTP 200
```

### Readiness (kiểm tra kết nối Redis)

```bash
curl -sS $BASE/ready
# {"ready":true}   → HTTP 200
```

### Authentication bắt buộc (không có key → 401)

```bash
curl -sS -X POST $BASE/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# {"detail":"Invalid or missing API key. Send header: X-API-Key: <key>"}   → HTTP 401
```

### API Test (có API key → 200)

```bash
curl -sS -X POST $BASE/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# {"question":"Hello","answer":"..."}   → HTTP 200
```

### Kết quả đã chạy (ngày 25/11/2026)

| Lệnh | Mã HTTP | Mong đợi |
|------|---------|----------|
| `GET /health` | 200 | 200 |
| `GET /ready` | 200 | 200 |
| `POST /ask` không có key | 401 | 401 |
| `POST /ask` có key đúng | 200 | 200 |

Ngoài ra, `python check_production_ready.py --public-url https://ai-agent-phqg.onrender.com` (bản đầy đủ, chạy trong WSL2) báo **PASS 12/12**, 44/44 kiểm tra, trong đó có `Public URL: GET .../health → 200`.

## Environment Variables Set

Khai báo trong `06-lab-complete/render.yaml`; **không có giá trị secret nào nằm trong repo**:

| Biến | Nguồn giá trị |
|------|---------------|
| `ENVIRONMENT` | `production` (ghi trong `render.yaml`) |
| `AGENT_API_KEY` | **Render tự sinh** (`generateValue: true`), chỉ xem được trong dashboard |
| `REDIS_URL` | Lấy từ `agent-redis` qua `fromService` (`connectionString`) |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `MONTHLY_BUDGET_USD` | `10.0` |
| `PORT` | Do Render cấp; Dockerfile đọc qua `${PORT:-8000}` |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png): trang `ai-agent` trên Render, trạng thái Live, URL và commit
- [Service running](screenshots/running.png): log hoặc events của service đang chạy
- [Test results](screenshots/test.png): kết quả bốn lệnh kiểm tra (200, 200, 401, 200)
