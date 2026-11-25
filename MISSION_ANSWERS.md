# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

Đọc `01-localhost-vs-production/develop/app.py`, tôi tìm được 9 vấn đề:

1. **API key hardcode** (dòng 17): `OPENAI_API_KEY = "sk-hardcoded-..."`. Push lên GitHub là lộ key ngay, và lịch sử git vẫn giữ key dù sau này xoá.
2. **Chuỗi kết nối DB có mật khẩu hardcode** (dòng 18): `postgresql://admin:password123@localhost:5432/mydb`. Cùng rủi ro lộ secret, và trỏ cứng vào `localhost` nên không dùng được ở môi trường khác.
3. **Không có config management** (dòng 21–22): `DEBUG = True` và `MAX_TOKENS = 500` viết cứng. Muốn đổi giữa dev, staging, production phải sửa code và build lại.
4. **Log bằng `print()`** (dòng 33, 36, 38): không có level, không có timestamp, không phải JSON nên log aggregator (Datadog, Loki) khó parse.
5. **Log ra secret** (dòng 34): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`. Key lọt vào log, và log thường được nhiều người xem hoặc gửi sang dịch vụ ngoài. Khi chạy, output có đúng dòng `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this`.
6. **Không có health check** (dòng 42–43): không có `/health` hay `/ready`. Tôi gọi `GET /health` và nhận **404**. Nền tảng cloud không biết agent đã crash để restart, load balancer không biết khi nào nên ngừng gửi traffic.
7. **Host và port cố định** (dòng 51–52): `host="localhost"`, `port=8000`. Bind `localhost` thì container không nhận được kết nối từ ngoài. Railway/Render inject cổng qua biến `PORT` mà code không đọc.
8. **`reload=True`** (dòng 53): chế độ auto-reload dành cho dev, tốn tài nguyên và không ổn định khi chạy thật.
9. **Không xử lý shutdown** (cả file): không có lifespan hay handler SIGTERM, nên khi platform tắt container, request đang chạy có thể bị cắt ngang.

Ngoài ra còn hai điểm nhỏ: endpoint `/ask` nhận `question` qua query string thay vì JSON body, và không có xác thực, ai gọi cũng được.

### Exercise 1.2: Chạy bản develop

```bash
cd 01-localhost-vs-production/develop
pip install -r requirements.txt
python app.py
```

Kết quả gọi thật (Windows, Python 3.12.10):

```bash
curl -X POST "http://localhost:8000/ask?question=Hello"
# {"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}

curl http://localhost:8000/health
# 404 Not Found (không có health check)

curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
# 422 Unprocessable Entity (app nhận question qua query, không nhận JSON body)
```

Quan sát: app chạy được nhưng **chưa production-ready**. Log in ra đúng dòng lộ key:

```text
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
```

Lần chạy đầu trên Windows, request đầu tiên trả **500 Internal Server Error**. Nguyên nhân: `print()` ghi tiếng Việt ra console mã hoá cp1252 và ném `UnicodeEncodeError`. Tôi chạy lại với `PYTHONUTF8=1` thì hết lỗi. Đây cũng là một dấu hiệu "chạy được trên máy tôi": hành vi phụ thuộc vào môi trường (OS, encoding) mà code không kiểm soát.

### Exercise 1.3: Bảng so sánh develop và production

So sánh `develop/app.py` với `production/app.py` và `production/config.py`:

| Feature | Develop | Production | Tại sao quan trọng? |
|---------|---------|------------|---------------------|
| Config | Hardcode trong code (`DEBUG = True`, `MAX_TOKENS = 500`) | Đọc từ env vars qua `config.py` (`Settings` dataclass, `os.getenv`) | Đổi cấu hình giữa dev/staging/production mà không sửa code. Đúng nguyên tắc 12-Factor "config in env". |
| Secrets | `OPENAI_API_KEY` và mật khẩu DB nằm trong code | `OPENAI_API_KEY`, `AGENT_API_KEY` đọc từ env; `validate()` báo lỗi nếu thiếu `AGENT_API_KEY` khi `ENVIRONMENT=production` | Secret không vào git. Thiếu cấu hình bắt buộc thì app fail ngay lúc khởi động (fail fast), không đợi tới lúc chạy. |
| Host binding | `host="localhost"` | `host=settings.host`, mặc định `0.0.0.0` | Trong container, bind `localhost` thì không ai ngoài container gọi vào được. |
| Port | Cứng `8000` | `settings.port` đọc từ `PORT` | Railway/Render inject `PORT`. Không đọc thì service không nhận được traffic. |
| Reload | `reload=True` luôn bật | `reload=settings.debug`, chỉ bật khi `DEBUG=true` | Auto-reload chỉ dành cho dev, bật ở production gây tốn tài nguyên và rủi ro. |
| Health check | Không có (`GET /health` → 404) | `GET /health` (liveness, trả uptime, version) và `GET /ready` (readiness, trả 503 khi chưa sẵn sàng) | Platform dựa vào `/health` để restart container hỏng. Load balancer dựa vào `/ready` để quyết định có route traffic vào không. |
| Logging | `print()`, in cả secret | `logging` với JSON (`json.dumps({...})`), không log secret, chỉ log `question_length` | Log có cấu trúc dễ parse, lọc, cảnh báo. Không log secret thì không lộ qua hệ thống log. |
| Shutdown | Đột ngột, không có handler | `lifespan` (startup/shutdown) và handler `SIGTERM` | Request đang xử lý được hoàn thành trước khi tắt, kết nối được đóng gọn, không mất dữ liệu. |
| CORS | Không có | `CORSMiddleware` với `allowed_origins` cấu hình được | Chỉ cho phép các origin được cấu hình truy cập từ trình duyệt. |
| Validate input | Tham số `question` qua query, không kiểm tra rõ ràng | Đọc JSON body, trả 422 nếu thiếu `question` | Trả lỗi rõ ràng cho client, hợp đồng API nhất quán. |

### Checkpoint 1: tự kiểm tra

- **Vì sao hardcode secret nguy hiểm?** Secret nằm trong mã nguồn nên đi theo mọi bản clone và lịch sử git. Push public là lộ ngay, xoá file sau đó cũng không đủ vì commit cũ vẫn còn. Phải thu hồi và tạo key mới.
- **Dùng env var thế nào?** Đọc bằng `os.getenv("TÊN", mặc_định)` trong một file config duy nhất (`config.py`). Giá trị thật đặt ở môi trường chạy (shell, `.env` không commit, dashboard của Railway/Render). Repo chỉ commit `.env.example`.
- **Vai trò của health check:** `/health` trả lời "process còn sống không", nền tảng dùng để restart. `/ready` trả lời "sẵn sàng nhận traffic chưa", load balancer dùng để chọn instance.
- **Graceful shutdown:** khi nhận SIGTERM, app ngừng nhận request mới, xử lý xong request đang chạy, đóng kết nối rồi mới thoát. Nhờ vậy khi deploy hoặc scale in không có request nào bị cắt ngang.

Một anti-pattern cụ thể mà production đã sửa: `develop/app.py` dòng 17 hardcode `OPENAI_API_KEY`, còn `production/config.py` dòng 27 đọc `os.getenv("OPENAI_API_KEY", "")`.

> Lưu ý: tôi so sánh hai bản bằng cách đọc code, và chỉ chạy thật bản develop. Chưa chạy bản `production/`.

## Part 2: Docker

> **Ghi chú trung thực về môi trường:** trên máy tôi, container của Docker Desktop không phân giải được tên miền (`Temporary failure in name resolution`), nên `pip install` trong `docker build` thất bại với Dockerfile gốc. Tôi đã thử `--dns 8.8.8.8`, `--network host` và truyền proxy của Docker Desktop qua `--build-arg`, đều không được. Cách xử lý: tải sẵn các file wheel bằng pip trên máy, rồi build bằng hai Dockerfile **tạm đặt ngoài repo**. Chúng giống bản gốc, chỉ khác bước cài package (`pip install --no-index --find-links=/wheels ...`), và ở stage builder của production bỏ thêm lệnh `apt-get install gcc libpq-dev` vì cần mạng. Stage builder không đi vào image cuối nên không ảnh hưởng kích thước. Dockerfile gốc trong repo không bị sửa. Với Dockerfile gốc trên máy có mạng bình thường, kết quả sẽ tương đương.

### Exercise 2.1: Dockerfile questions (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11`, bản Python đầy đủ (không phải `slim`), nặng vì chứa nhiều công cụ build.
2. **Working directory:** `/app` (`WORKDIR /app`).
3. **Vì sao `COPY requirements.txt` trước:** Docker cache theo từng layer. File requirements ít thay đổi, nên layer `pip install` được dùng lại. Sửa code chỉ làm vô hiệu hoá các layer từ `COPY app.py` trở xuống. Nếu `COPY . .` trước thì mỗi lần sửa code đều phải cài lại toàn bộ dependencies.
4. **CMD khác ENTRYPOINT:** `CMD` là lệnh mặc định, người dùng ghi đè dễ dàng bằng cách thêm lệnh sau `docker run <image> ...`. `ENTRYPOINT` là chương trình cố định của container; tham số truyền vào `docker run` được nối thêm sau nó, và muốn thay phải dùng `--entrypoint`. Hai cái hay dùng chung: `ENTRYPOINT` là chương trình, `CMD` là tham số mặc định. Dockerfile này chỉ dùng `CMD ["python", "app.py"]`.

### Exercise 2.2: Build và run (bản develop)

Build từ gốc repo (`-f 02-docker/develop/Dockerfile -t my-agent:develop .`), chạy `docker run -p 8000:8000 my-agent:develop`:

```bash
curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
# {"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

curl http://localhost:8000/health
# {"status":"ok","uptime_seconds":4.9,"container":true}

curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"What is Docker?"}'
# 422 (bản develop nhận question qua query, không nhận JSON body)
```

`docker exec <container> whoami` trả `root`: bản develop chạy bằng quyền root trong container.

**Kích thước image `my-agent:develop`:** `docker images` hiển thị **1.67 GB**. `docker image inspect` (kích thước nén) cho **426 MB** (426.319.058 byte).

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`)

- **Stage 1 (`builder`)** dựa trên `python:3.11-slim`. Nó cài công cụ build (gcc, libpq-dev) và chạy `pip install --user`, đưa package vào `/root/.local`. Stage này chỉ để build, **không được deploy**.
- **Stage 2 (`runtime`)** cũng dựa trên `python:3.11-slim`. Nó tạo user không phải root (`appuser`), chỉ `COPY --from=builder /root/.local` (các package đã cài) cùng code của app, rồi chạy bằng `appuser` với `HEALTHCHECK` và `uvicorn --workers 2`.
- **Vì sao image nhỏ hơn:** (a) base là `slim` thay vì bản đầy đủ; (b) toàn bộ gcc, apt cache và công cụ build nằm ở stage 1 và bị bỏ đi, image cuối không chứa chúng; (c) không có pip cache (`--no-cache-dir`).

Kích thước đo được sau khi build (`docker images`, đo trên máy tôi):

- Develop: **1.67 GB** (nén: 426 MB)
- Production (`my-agent:advanced`): **240 MB** (nén: 57,4 MB)
- Chênh lệch: production nhỏ hơn develop khoảng **86%**, theo cả hai cách đo: (1670 − 240) / 1670 ≈ 85,6% theo `docker images`, và (426,3 − 57,4) / 426,3 ≈ 86,5% theo kích thước nén. Production dưới 500 MB, đạt yêu cầu.

Chạy thử `my-agent:advanced`:

```bash
curl http://localhost:8000/health
# {"status":"ok","uptime_seconds":3.3,"version":"2.0.0","timestamp":"..."}
curl http://localhost:8000/ready
# {"ready":true}
curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"What is Docker?"}'
# {"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

`whoami` trong container cho `appuser` (không phải root). `docker inspect` báo `health=healthy`.

### Exercise 2.4: Docker Compose stack

Chạy: `docker compose -p k5-day14-docker up -d` trong `02-docker/production/` (đã tạo file `.env.local` rỗng và dùng `-p` như hướng dẫn trong README). Cả 4 service lên được:

| Service | Image | Trạng thái | Cổng ra ngoài |
|---------|-------|-----------|---------------|
| `agent` | image build từ `02-docker/production/Dockerfile` (stage `runtime`) | Up, healthy | không (chỉ trong mạng `internal`, cổng 8000) |
| `redis` | `redis:7-alpine` | Up, healthy | không (6379 nội bộ) |
| `qdrant` | `qdrant/qdrant:v1.9.0` | Up, healthy | không (6333 nội bộ) |
| `nginx` | `nginx:alpine` | Up | **80** và **443** |

Sơ đồ kiến trúc:

```text
                 Internet / curl
                       │  :80 (:443)
                       ▼
              ┌──────────────────┐
              │      nginx       │  reverse proxy, rate limit 10 req/s,
              │  (nginx:alpine)  │  security headers
              └────────┬─────────┘
   ════ mạng bridge "internal" (cô lập, chỉ nginx mở cổng ra ngoài) ════
                       │ proxy_pass http://agent:8000
                       ▼
              ┌──────────────────┐
              │      agent       │  FastAPI + uvicorn (2 workers)
              │   (non-root)     │
              └───────┬──────────┘
        redis://redis:6379 │      │ http://qdrant:6333
                  ▼                  ▼
          ┌────────────┐      ┌────────────┐
          │   redis    │      │   qdrant   │
          │ (session / │      │ (vector DB │
          │ rate limit)│      │  cho RAG)  │
          └────────────┘      └────────────┘
```

**Các service giao tiếp thế nào:** chúng cùng nằm trong mạng bridge `internal`, nên gọi nhau bằng tên service (DNS nội bộ của Docker): nginx gọi `agent:8000`, agent gọi `redis:6379` và `qdrant:6333` qua biến `REDIS_URL` và `QDRANT_URL`. Chỉ nginx publish cổng 80/443 ra máy chủ, nên mọi request từ ngoài phải đi qua nginx. `depends_on` với `condition: service_healthy` bảo đảm redis và qdrant khoẻ rồi agent mới khởi động, và nginx chờ agent.

Nhận xét thêm: `main.py` của agent không import hay dùng Redis hay Qdrant. Hai service này được dựng sẵn cho các phần sau (rate limit, session, RAG), nhưng ở bài này agent chưa kết nối tới.

Kết quả test qua Nginx:

```bash
curl http://localhost/health
# {"status":"ok","uptime_seconds":10.5,"version":"2.0.0","timestamp":"..."}   [200]

curl -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
# {"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}   [200]
```

Header trả về có `Server: nginx` (không lộ version nhờ `server_tokens off`) và `X-Frame-Options: DENY`. Tôi gọi tuần tự 40 request liên tiếp và đều nhận 200, vì curl tuần tự không vượt được ngưỡng 10 req/s kèm burst 20 của nginx, nên chưa thấy 429 ở bài này.

Xong thì tôi đã dọn bằng `docker compose -p k5-day14-docker down -v`.

### Checkpoint 2: tự kiểm tra

- **Cấu trúc Dockerfile:** `FROM` (base) → `WORKDIR` → `COPY requirements` → `RUN pip install` → `COPY code` → `EXPOSE` → `CMD`. Thứ tự đặt từ ít thay đổi đến hay thay đổi để tận dụng cache.
- **Lợi ích multi-stage:** image cuối chỉ chứa thứ cần để chạy, nhỏ hơn khoảng 86% và ít bề mặt tấn công hơn. Chạy bằng user không phải root.
- **Docker Compose orchestration:** một file mô tả nhiều service, mạng nội bộ, volume và thứ tự khởi động; một lệnh `up` dựng cả stack.
- **Debug container:** `docker logs <tên>` xem log, `docker exec -it <tên> /bin/sh` vào bên trong, `docker inspect` xem trạng thái health.
- **Số MB trong bài** là số tôi đo bằng `docker images` và `docker image inspect` trên máy mình, không chép từ README.

## Part 3: Cloud Deployment

_(chưa làm)_

## Part 4: API Security

_(chưa làm)_

## Part 5: Scaling & Reliability

_(chưa làm)_

## Part 6: Output `check_production_ready.py`

_(chưa làm)_

## AI log

| Lần | Hỏi gì | Nhận gì | Tôi tự sửa / kiểm tra thế nào |
|-----|--------|---------|-------------------------------|
| 2 | Làm Part 2: đọc Dockerfile/compose, build và đo image, chạy container và stack, viết phần Part 2 | Câu trả lời 2.1–2.4, cách xử lý lỗi mạng Docker (build offline bằng wheel tải sẵn, Dockerfile tạm đặt ngoài repo), sơ đồ stack | Tự chạy các lệnh build, `docker images`, curl, `docker compose`. Số MB lấy từ output thật. Cần bạn đọc lại và xác nhận trước khi nộp. |
| 1 | Đọc `develop/app.py` và `production/app.py`, liệt kê anti-pattern, viết phần Part 1 | Danh sách anti-pattern, bảng so sánh, câu trả lời Checkpoint 1 | Chạy lại bản develop để lấy output curl và log thật. Số dòng code đối chiếu trực tiếp với file. _(Bạn cần đọc lại và xác nhận trước khi nộp.)_ |
