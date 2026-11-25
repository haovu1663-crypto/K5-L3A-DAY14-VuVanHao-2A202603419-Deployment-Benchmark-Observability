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

Nền tảng chính: **Render** (deploy chính agent Part 6 trong `06-lab-complete/`, không deploy app mẫu của `03-cloud-deployment/`).

### Kết quả deploy trên Render

- **URL public:** https://ai-agent-phqg.onrender.com
- **Cách deploy:** Render → New → Blueprint, repo của tôi, nhánh `main`, **Blueprint Path = `06-lab-complete/render.yaml`** (file nằm trong thư mục con nên phải chỉ đường dẫn; để trống thì Render báo `render.yaml not found on main branch`). Render đọc được file và liệt kê đúng hai tài nguyên: Key Value `agent-redis` và web service `ai-agent`. Sync hoàn tất, build Docker và deploy mất **1 phút 9 giây**, trạng thái **Live**. Redis (Valkey 8.1.10, vùng Singapore) ở trạng thái **Available**.
- **Biến môi trường** đặt qua `render.yaml`, không có secret trong repo: `AGENT_API_KEY` do Render tự sinh (`generateValue: true`), `REDIS_URL` lấy từ `agent-redis` qua `fromService`.

Bốn lệnh tự kiểm (key được nhập bằng ô ẩn, không lộ):

```text
GET  /health               -> 200
GET  /ready                -> 200   (agent trên Render kết nối được Redis)
POST /ask (không có key)   -> 401
POST /ask (có key đúng)    -> 200
```

`python check_production_ready.py --public-url https://ai-agent-phqg.onrender.com` (bản đầy đủ): **PASS 12/12**, 44/44 kiểm tra, gồm `Public URL: GET .../health → 200`.

Ảnh chụp: `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`. Chi tiết lệnh và biến môi trường nằm trong `DEPLOYMENT.md`.

Lưu ý: trang `/docs` (Swagger của FastAPI) đang truy cập được công khai trên URL này (trả 200). Nó không lộ secret, nhưng với production nghiêm túc nên tắt.

### So sánh `railway.toml` và `render.yaml`

So sánh hai file cấu hình của Part 6 (`06-lab-complete/railway.toml` và `06-lab-complete/render.yaml`), có đối chiếu với hai file mẫu trong `03-cloud-deployment/`:

| Điểm so sánh | `railway.toml` | `render.yaml` |
|--------------|----------------|---------------|
| Định dạng | TOML, ngắn: chỉ hai mục `[build]` và `[deploy]` | YAML dạng Blueprint (Infrastructure as Code), mô tả cả hệ thống |
| Phạm vi | Chỉ cấu hình **cách build và chạy một service** | Khai báo **nhiều tài nguyên** trong một file: web service **và** Redis (`type: keyvalue`), cùng biến môi trường |
| Chọn cách build | `builder = "DOCKERFILE"` (mẫu của lớp dùng `NIXPACKS` + `startCommand`) | `runtime: docker` + `dockerfilePath` / `dockerContext` (mẫu dùng `runtime: python` + `buildCommand` / `startCommand`) |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout = 30` | `healthCheckPath: /health` (khác cách viết hoa chữ C) |
| Khởi động lại khi lỗi | Khai báo rõ: `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3` | Không khai báo trong file; nền tảng tự restart khi health check thất bại |
| Biến môi trường và secret | **Không có** trong file; đặt bằng dashboard hoặc `railway variables set ...` | Khai báo ngay trong file: giá trị thường (`value`), secret tự sinh (`generateValue: true`) hoặc nhập tay (`sync: false`) |
| Redis | Không khai báo trong file; phải tự thêm Redis plugin trong dashboard rồi trỏ `REDIS_URL` | Khai báo trong file, và nối vào agent bằng `fromService` (`property: connectionString`) |
| Cách kích hoạt deploy | Dùng CLI: `railway up` | Push lên GitHub, Render đọc Blueprint rồi tự deploy (`autoDeploy: true`) |
| Cổng | Railway cấp biến `PORT`; app đọc qua `${PORT:-8000}` trong CMD | Render cũng cấp biến `PORT`; dùng chung CMD |

**Vì sao khác nhau:** Railway coi file cấu hình là phần "build và chạy một service", còn hạ tầng (Redis, biến) tạo bằng dashboard hoặc CLI. Render đi theo hướng Infrastructure as Code: một file `render.yaml` được commit vào git là đủ để dựng lại cả hệ thống (web + Redis + biến) bằng một Blueprint. Cái giá của Render là file dài hơn và phải khai báo đúng cú pháp riêng của nó; cái lợi là không phải bấm tay nhiều bước và cấu hình được kiểm soát bằng git. Với đề bài này, agent cần Redis nên cách của Render gọn hơn.

Điểm giống nhau quan trọng: cả hai đều **không ghi secret vào file**, đều gọi `/health` để biết service còn sống và đều cấp biến `PORT`.

### Exercise 3.3: Pipeline CI/CD của Cloud Run (`cloudbuild.yaml` và `service.yaml`)

Tôi chỉ đọc hai file này, không deploy (không cần tài khoản GCP).

**`cloudbuild.yaml`** là pipeline CI/CD, kích hoạt khi push lên nhánh `main`. Bốn bước chạy tuần tự (mỗi bước có `waitFor` bước trước):
1. **test:** cài `requirements.txt` và chạy `pytest tests/`. Test thất bại thì pipeline dừng, không build.
2. **build:** `docker build`, gắn hai tag `ai-agent:$COMMIT_SHA` và `ai-agent:latest`, dùng `--cache-from` image `latest` để tận dụng cache layer.
3. **push:** đẩy mọi tag lên Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **deploy:** `gcloud run deploy` với image theo `COMMIT_SHA`, vùng `asia-southeast1`, `--min-instances=1` (tránh cold start), `--max-instances=10` (giới hạn chi phí), và lấy `OPENAI_API_KEY` từ **Secret Manager** (`--set-secrets`) thay vì ghi trong file.

**`service.yaml`** là định nghĩa Cloud Run dạng khai báo (kiểu Knative Service, `gcloud run services replace`): autoscaling từ 1 tới 10 instance, mỗi instance xử lý tối đa 80 request đồng thời, timeout 60 giây, giới hạn CPU và bộ nhớ, secret (`OPENAI_API_KEY`, `AGENT_API_KEY`) lấy qua `secretKeyRef`, `livenessProbe` gọi `/health` và `startupProbe` gọi `/ready`.

Nhận xét: tag bằng `COMMIT_SHA` giúp truy ngược bản chạy về đúng commit và rollback dễ. Trong thư mục `production-cloud-run/` **không có thư mục `tests/`**, nên bước 1 sẽ thất bại nếu chạy đúng như đang viết; muốn dùng thật phải thêm test hoặc bỏ bước này.

## Part 4: API Security

> Mọi output dưới đây do tôi chạy thật trên máy (Windows, Python 3.12, chạy `python app.py` trực tiếp). Token JWT đã được che.

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)

- **API key được check ở đâu?** Trong hàm `verify_api_key` (dòng 39–54), đọc header `X-API-Key` bằng `APIKeyHeader(auto_error=False)` rồi so với biến `API_KEY`. Hàm này được gắn vào `/ask` bằng `Depends(verify_api_key)`. `/` và `/health` để public.
- **Sai key thì sao?** Thiếu key trả **401**, có key nhưng sai trả **403**.
- **Rotate key thế nào?** Key đọc từ biến môi trường `AGENT_API_KEY`, nên chỉ cần đặt giá trị mới rồi khởi động lại, không sửa code. Thực tế nên cho phép hai key cùng hợp lệ trong lúc chuyển đổi để client cũ không bị lỗi, rồi mới huỷ key cũ.

Chạy: `AGENT_API_KEY=secret-key-123 python app.py`. Bản này đọc JSON body:

```text
# Không có key
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# Sai key (X-API-Key: wrong-key)
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

# Đúng key (X-API-Key: secret-key-123)
HTTP/1.1 200 OK
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 4.2: JWT authentication (`04-api-gateway/production/`)

Luồng JWT (đọc `auth.py`): client gửi username và password tới `POST /auth/token`; server kiểm tra rồi ký một token chứa `user_id`, `role` và thời điểm hết hạn (60 phút); client gửi token ở header `Authorization: Bearer <token>`; mỗi request server chỉ xác minh chữ ký và hạn, không cần tra database.

```text
# /ask không có token
HTTP/1.1 401 Unauthorized
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# Đăng nhập sai mật khẩu
HTTP/1.1 401 Unauthorized
{"detail":"Invalid credentials"}

# Đăng nhập student / demo123
HTTP 200, access_token = eyJ... (đã che, dài 168 ký tự)
```

Dùng token để gọi `/ask`: trả 200 với `usage.requests_remaining` giảm dần (xem 4.3).

**Phân quyền theo role:** `student` (role `user`) gọi `GET /admin/stats` nhận `403 {"detail":"Admin only"}`.

### Exercise 4.3: Rate limiting (`rate_limiter.py`)

- **Thuật toán:** Sliding Window Counter. Mỗi user có một `deque` chứa timestamp các request; mỗi lần gọi bỏ các timestamp ngoài cửa sổ 60 giây rồi đếm.
- **Giới hạn:** `student` (role `user`) **10 request/phút**; `teacher` (role `admin`) **100 request/phút** (`rate_limiter_user` và `rate_limiter_admin`).
- **Bypass cho admin:** không bypass hoàn toàn. Admin dùng một limiter khác có ngưỡng cao hơn, chọn theo `role` trong token (`limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`).

Gọi liên tục 20 request bằng token `student`:

```text
 1 -> 200  requests_remaining=9
 2 -> 200  requests_remaining=8
 ...
10 -> 200  requests_remaining=0
11 -> 429  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":39}}
12 -> 429  ...
...
20 -> 429  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":20}}
```

Header của một response 429:

```text
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795599133
retry-after: 20
```

Request thứ 11 bị chặn đúng như ngưỡng 10 request/phút. Số giây `retry_after_seconds` giảm dần theo thời gian. Với `teacher`, 15 request liên tiếp đều trả 200 (ngưỡng 100/phút).

Lưu ý: limiter này lưu trong **bộ nhớ của tiến trình** (`defaultdict(deque)`). Khi chạy nhiều instance hoặc nhiều worker, mỗi instance đếm riêng nên giới hạn không còn chính xác, và restart là mất bộ đếm. Vì vậy Part 6 yêu cầu lưu trong Redis.

### Exercise 4.4: Cost guard

**Cách tiếp cận trong repo (`cost_guard.py`):** mỗi request, `check_budget(user_id)` chạy **trước khi** gọi LLM; sau khi gọi xong, `record_usage` cộng chi phí tính theo token (`input/1000 × 0.00015 + output/1000 × 0.0006`). Có hai tầng:
1. Ngân sách **từng user: $1/ngày** — vượt thì trả **402 Payment Required**.
2. Ngân sách **toàn hệ thống: $10/ngày** — vượt thì trả **503**.
Khi dùng tới 80% ngân sách thì ghi log cảnh báo. Bộ đếm tự đặt lại khi sang ngày mới (so sánh chuỗi ngày `YYYY-MM-DD`).

Tôi minh hoạ 402 bằng cách tạo `CostGuard(daily_budget_usd=0.001)` rồi gọi lặp lại:

```text
1 OK  cost= 0.00075
2 OK  cost= 0.0015
3 HTTP 402 {'error': 'Daily budget exceeded', 'used_usd': 0.0015, 'budget_usd': 0.001, 'resets_at': 'midnight UTC'}
```

Lưu ý khi đọc kết quả: request số 2 vẫn được qua dù tổng đã vượt $0.001, vì `check_budget` chỉ kiểm tra chi phí **đã dùng** trước khi gọi, không ước lượng chi phí của request sắp chạy. Vì vậy mỗi user có thể vượt ngân sách tối đa một request.

**Khác với đề trong `CODE_LAB.md`:** đề mô tả cost guard theo **tháng, $10/user, lưu bằng Redis** (khoá `budget:{user}:{YYYY-MM}`, `INCRBYFLOAT`, `EXPIRE` 32 ngày). Bản trong repo là **theo ngày, $1/user, lưu in-memory**. Cách Redis đúng hơn cho production vì state sống sót qua restart và dùng chung được giữa nhiều instance; tôi chưa chạy bản Redis ở bài này, sẽ làm ở Part 6.

**Vì sao cần cả rate limit và cost guard:** rate limit bảo vệ **tốc độ** (chặn spam, bảo vệ server và bị giới hạn theo phút), còn cost guard bảo vệ **tiền** (chặn tổng chi phí LLM). Một user có thể gửi vài request mỗi phút, không bao giờ chạm rate limit, nhưng mỗi request là prompt rất dài và vẫn tiêu hết ngân sách. Ngược lại, rate limit không biết request đắt hay rẻ. Cần cả hai.

### Checkpoint 3: tự kiểm tra

- Đã thấy **429** từ vòng lặp gọi liên tục do tôi chạy (request thứ 11).
- Đã thấy cả ba mã của API key: 401 (thiếu), 403 (sai), 200 (đúng).
- Cần hiểu: 401 là chưa xác thực, 403 là đã xác thực nhưng không đủ quyền hoặc sai key, 429 là quá nhiều request, 402 là hết ngân sách.

## Part 5: Scaling & Reliability

> **Ghi chú về cách chạy trên máy tôi (3 điểm khác hướng dẫn gốc):**
> 1. **Build image offline.** Như ở Part 2, container Docker trên máy tôi không có mạng, nên `pip install` trong `docker build` thất bại. Tôi build bằng Dockerfile tạm đặt ngoài repo, dùng wheel tải sẵn (bỏ thêm lệnh `apt-get gcc` ở stage builder, stage này không vào image cuối). Dockerfile gốc không bị sửa.
> 2. **Cổng 8090 thay vì 8080.** Cổng 8080 trên máy tôi đang bị một container khác (không thuộc lab) dùng. Tôi giữ nguyên container đó và publish Nginx của stack lab ở cổng **8090** bằng một file `override` đặt ngoài repo. `test_stateless.py` gốc cứng cổng 8080, nên tôi chạy một bản sao chỉ đổi cổng sang 8090 (file gốc không sửa).
> 3. **SIGTERM thật cho Exercise 5.2.** Windows không gửi SIGTERM thật như Linux, nên tôi chạy `develop/app.py` bên trong một container Linux (mount thư mục `develop/`, chạy `python app.py`) và dùng `docker stop`, lệnh này gửi SIGTERM thật.

### Exercise 5.1: Health và readiness (`05-scaling-reliability/develop/app.py`)

```text
GET /health -> 200
{"status":"ok","uptime_seconds":1.0,"version":"1.0.0","environment":"development","timestamp":"...","checks":{"memory":{"status":"ok","note":"psutil not installed"}}}

GET /ready  -> 200
{"ready":true,"in_flight_requests":1}
```

- **`/health` (liveness probe):** trả lời "process còn sống không". Trả 200 khi process chạy, kèm uptime, version, trạng thái các kiểm tra (ví dụ bộ nhớ). Nền tảng gọi định kỳ; nếu lỗi hoặc timeout thì **restart container**.
- **`/ready` (readiness probe):** trả lời "sẵn sàng nhận traffic chưa". Trả **503** khi đang khởi động hoặc đang shutdown (cờ `_is_ready = False`), trả 200 khi sẵn sàng. Load balancer dùng để quyết định **có đưa traffic vào instance này không**, nhưng không restart nó.
- Khác biệt: instance chưa sẵn sàng thì không hỏng, chỉ cần tạm thời không nhận traffic; còn instance không trả lời `/health` thì mới cần restart.

(Giá trị `in_flight_requests: 1` là chính request `/ready` đang gọi, vì middleware đếm cả nó.)

### Exercise 5.2: Graceful shutdown

Trong `develop/app.py`, `/ask` có độ trễ giả lập 3 giây. Tôi gửi một request chậm, một giây sau chạy `docker stop` (SIGTERM):

```text
in-flight request -> HTTP 200 after 3.05s
docker stop xong sau 2.58 giay
exit code = 0

Log container:
INFO:     Shutting down
INFO:     172.17.0.1:33128 - "POST /ask?question=Long%20task" 200 OK
INFO:     Waiting for application shutdown.
... 🔄 Graceful shutdown initiated...
... ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [1]
... Received signal 15 — uvicorn will handle graceful shutdown
```

**Kết luận:** request đang chạy **được hoàn thành** (200 sau 3,05 giây) dù SIGTERM tới sau 1 giây. Container thoát **sạch với exit code 0**, không bị cắt ngang. Thứ tự: uvicorn nhận SIGTERM → ngừng nhận kết nối mới → chờ request đang chạy xong → chạy phần shutdown của `lifespan` (đặt `_is_ready=False`, chờ `_in_flight_requests` về 0, tối đa 30 giây) → thoát. Nếu không có graceful shutdown (ví dụ `SIGKILL`), request kia sẽ mất và client nhận lỗi kết nối.

### Exercise 5.3: Stateless design (`05-scaling-reliability/production/app.py`)

- Bản production lưu session và lịch sử hội thoại **trong Redis** (`save_session`, `load_session`, `append_to_history`; khoá `session:{id}`, có TTL 1 giờ), không giữ trong biến của tiến trình. Response có trường `"storage": "redis"` để xác nhận.
- **Vì sao state trong RAM hỏng khi scale:** mỗi instance có bộ nhớ riêng. Nếu lịch sử nằm trong một `dict` của instance A, request tiếp theo do load balancer chuyển tới instance B sẽ **không thấy** lịch sử đó; khi A bị restart hoặc scale in thì mất luôn. Đưa state ra Redis dùng chung thì instance nào cũng đọc ghi được, nên có thể thêm, bớt, restart instance tuỳ ý.
- Ngoài ra `/health` và `/ready` của bản này kiểm tra cả kết nối Redis (`redis_connected`), nên instance mất Redis sẽ báo `degraded` hoặc 503.

### Exercise 5.4: Load balancing

Stack: `redis`, `nginx` và `agent` với 3 instance (`docker compose -p k5-day14-scaling up -d --scale agent=3`). Cả 3 agent đều `healthy`. Chỉ Nginx publish cổng ra ngoài (8090 trên máy tôi; 8080 theo hướng dẫn gốc).

Gọi 10 request `POST /chat` (mỗi request một session mới), cột 2 là `served_by`:

```text
1 instance-200a8e   2 instance-601a48   3 instance-e001dd
4 instance-200a8e   5 instance-601a48   6 instance-e001dd
7 instance-200a8e   8 instance-601a48   9 instance-e001dd
10 instance-200a8e
Phân bố: instance-200a8e = 4, instance-601a48 = 3, instance-e001dd = 3
```

Nginx chia **luân phiên (round-robin)** đều cho 3 instance. Response cũng có header `X-Served-By: <ip>:8000` do Nginx thêm vào.

### Exercise 5.5: Test stateless (`test_stateless.py`)

Gửi 5 câu trong **cùng một session**. Kết quả:

```text
Request 1: [instance-e001dd]   Request 2: [instance-200a8e]   Request 3: [instance-601a48]
Request 4: [instance-e001dd]   Request 5: [instance-200a8e]
Instances used: {'instance-601a48', 'instance-e001dd', 'instance-200a8e'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10   (5 user + 5 assistant, đúng thứ tự)
✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 request của cùng một session đi qua cả 3 instance khác nhau, nhưng khi đọc lại history vẫn thấy đủ 10 tin nhắn. Điều đó chứng minh state **không nằm trong bộ nhớ của từng instance** mà nằm trong Redis dùng chung. Script này không tự tắt instance nào.

**Thử nghiệm thêm: tắt một instance giữa chừng** (script riêng do tôi viết, không thuộc lab). Gửi 3 request, `docker stop` một agent, rồi gửi tiếp 6 request cùng session:

```text
truoc khi tat: Q1..Q3 (3 instance khác nhau)
>>> docker stop k5-day14-scaling-agent-1
sau khi tat : Q4 OK, Q5 OK, Q6 LOI (timed out), Q7 OK, Q8 OK, Q9 OK
ok=5 loi=1; history count=16
```

- **Dữ liệu không mất:** các request sau đó vẫn thành công và nối tiếp đúng session. History gồm 16 tin nhắn = 8 lượt hoàn thành × 2 (3 trước khi tắt + 5 thành công sau đó). Lượt Q6 lỗi nên không để lại gì trong history.
- **Nhưng có một request bị treo:** Q6 bị timeout ở phía client (tôi đặt 30 giây). Nginx vẫn gửi một request tới instance vừa bị tắt, và phải chờ hết thời gian kết nối (mặc định 60 giây) mới chuyển sang instance khác. `nginx.conf` có `proxy_next_upstream error timeout http_503` nên về lý thuyết sẽ thử instance khác, nhưng chỉ sau khi timeout kết nối. Nếu muốn giảm độ trễ này, cần đặt `proxy_connect_timeout` ngắn hơn (ví dụ 2–3 giây) và/hoặc `max_fails`, `fail_timeout` cho upstream. Tôi chỉ quan sát chứ chưa sửa cấu hình.
- Chỉ có 1 lần xảy ra trong lần chạy này; tôi chưa lặp lại để đo xác suất.

Sau khi xong tôi đã dọn bằng `docker compose -p k5-day14-scaling ... down -v` và xoá image tạm.

### Checkpoint 4: tự kiểm tra

- **Liveness (`/health`) khác readiness (`/ready`):** liveness quyết định có **restart** không; readiness quyết định có **đưa traffic vào** không.
- **Graceful shutdown:** đã quan sát request đang chạy hoàn thành và container thoát với exit code 0.
- **Stateless:** state phải nằm ở nơi dùng chung (Redis); nếu nằm trong RAM của instance thì scale ngang sẽ làm lệch hoặc mất dữ liệu.
- **Load balancing với Nginx:** round-robin đều cho 3 instance (4/3/3 trong 10 request).
- **Kết quả test stateless:** `test_stateless.py` cho thấy cùng một session đi qua 3 instance mà history vẫn đủ 10 tin nhắn.

## Part 6: Output `check_production_ready.py`

Chạy trong `06-lab-complete/`, **chế độ đầy đủ** (không `--skip-docker`, không `--static-only`), trên WSL2 Ubuntu với Python 3.11 (`os.name` = `posix`) và Docker Desktop. Kết quả: **PASS 12/12**, 43/43 kiểm tra. Image build ra nặng **63 MB**, `docker stop` mất **1,2 giây** với exit code 0.

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Các dòng chi tiết đáng chú ý của lần chạy này:

```text
Docker: build image thành công — 44s
Docker: image < 500 MB — 63 MB
Rate limiting: 429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)
Rate limiting: restart agent vẫn bị 429 (state nằm trong Redis)
Cost guard: 402 ở request thứ 1 (budget 0.000001 USD)
Structured logging: 12 dòng JSON
Graceful shutdown: SIGTERM lúc đang có request → request vẫn 200, exit code 0
Graceful shutdown: `docker stop` exit code 0, 1.2s
```

`check_production_ready.py` **không bị sửa** (`git diff` trên file này trống).

### Các quyết định thiết kế

| Thành phần | Cách làm | Lý do |
|------------|----------|-------|
| `config.py` | Mọi giá trị đọc bằng `os.getenv`, có giá trị mặc định cho local. `AGENT_API_KEY` mặc định là chuỗi rỗng. | Không có secret trong code. Key rỗng nghĩa là "chưa cấu hình" và app từ chối mọi `/ask`, thay vì mở toang. |
| `auth.py` | `APIKeyHeader(auto_error=False)`, tự raise **401**; so sánh bằng `secrets.compare_digest`. | Nếu để FastAPI xử lý header bắt buộc thì trả 403/422. `compare_digest` tránh lộ key qua thời gian xử lý. |
| `rate_limiter.py` | Sliding window log bằng Redis sorted set, chạy trong **một script Lua** (ZREMRANGEBYSCORE → ZCARD → ZADD → EXPIRE). Key Redis là hash SHA-256 của API key. Dùng `TIME` của Redis. | Chạy rời từng lệnh thì 2 worker có thể cùng thấy "còn chỗ" và cùng thêm request, làm vượt giới hạn. Script Lua chạy atomic. Hash để secret không nằm trong tên key Redis. |
| `cost_guard.py` | Cộng chi phí vào Redis theo ngày và theo tháng (`INCRBYFLOAT`, có TTL); `check_budget()` trước khi gọi LLM, `record_cost()` sau. Vượt `DAILY_BUDGET_USD` hoặc `MONTHLY_BUDGET_USD` thì **402**. | Bám đề trong `DAY14_DELIVERY_CHECKLIST.md` ($10/tháng) và README (theo ngày). |
| Khi Redis chết | `/health` vẫn 200, `/ready` trả 503, còn `/ask` trả **503** (fail closed). | Không kiểm soát được tốc độ và chi phí thì không nên cho request đi qua. |
| `redis_client.py` | `redis.from_url(...)` chỉ tạo client, **không ping lúc import**; timeout kết nối 1 giây. | App khởi động được khi Redis chưa sẵn sàng; `/ready` không bị treo khi Redis chết. |
| Logging | `JsonFormatter` tự viết, `json.dumps` mỗi dòng một object, có `ts`, `lvl`, `event`, `path`, `status`, `ms`. Không bao giờ log API key. | Dễ parse trong log aggregator. |
| Graceful shutdown | Dùng `lifespan` của FastAPI, **không tự đăng ký handler SIGTERM**. Sau SIGTERM, `/ready` chuyển 503. | uvicorn đã xử lý SIGTERM: ngừng nhận kết nối mới, chờ request đang chạy xong rồi thoát. Tự gắn handler mà không gọi lại handler cũ sẽ làm process không bao giờ tắt. |
| Dockerfile | 2 stage: builder tạo virtualenv `/opt/venv`, runtime (`python:3.11-slim`) chỉ copy venv và code; user non-root; `HEALTHCHECK` gọi `/health`; `CMD ["sh","-c","exec uvicorn ... --port ${PORT:-8000}"]`. | `exec` để uvicorn thành PID 1, nhận SIGTERM trực tiếp. `COPY requirements.txt` trước code để tận dụng cache layer. Cổng đọc từ `PORT` cho Render/Railway. |
| `docker-compose.yml` | Service `agent` (build từ Dockerfile) + `redis:7-alpine` có healthcheck; `REDIS_URL=redis://redis:6379/0`; `depends_on` redis `service_healthy`; `env_file` với `required: false`. | Chạy được bằng `docker compose up` kể cả khi chưa có file `.env`. |
| Deploy | Viết cả `railway.toml` và `render.yaml` (Render tự sinh `AGENT_API_KEY` bằng `generateValue: true`, Redis là Key Value). | Cần cho tiêu chí 12 và để so sánh hai nền tảng ở Part 3. |

### Kiểm tra thêm ngoài script chấm

Tôi chạy thật `docker compose up --build` với một file `.env` tạm (đã xoá sau đó, và `.env` nằm trong `.gitignore`):

```text
GET /health -> 200 {"status":"ok",...}        GET /ready -> 200 {"ready":true}
POST /ask không key     -> 401
POST /ask đúng key      -> 200 (câu trả lời)
Lỗi đầu vào (tất cả trả JSON rõ ràng, không có stack trace):
  question rỗng           -> 422  (String should have at least 1 character)
  JSON hỏng               -> 422  (JSON decode error)
  thiếu body              -> 422  (Field required)
  question dài 2500 ký tự -> 422  (giới hạn 2000)
  /nope -> 404 {"detail":"Not Found"}    GET /ask -> 405 {"detail":"Method Not Allowed"}
Rate limit mặc định 10/phút: 9 request 200 rồi 429, header retry-after: 57
Dừng Redis giữa chừng:
  /ready -> 503  /health -> 200  /ask -> 503 {"detail":"Service temporarily unavailable"}
Log container: mỗi dòng là một object JSON hợp lệ
```

### Môi trường chạy và những điểm cần nói rõ

- **WSL2 và Docker:** Ubuntu trong WSL chưa bật tích hợp Docker Desktop, nên lệnh `docker` không có sẵn. Tôi thêm một script wrapper `~/.local/bin/docker` (chỉ nằm trong thư mục home của WSL, ngoài repo). Nó gọi `docker.exe` của Docker Desktop và đổi đường dẫn `/mnt/d/...` sang dạng Windows. Script chấm vẫn chạy nguyên bản và dùng Docker thật.
- **Python của WSL:** bản mặc định là 3.14, không cài được `pydantic==2.9.0` trong `requirements.txt`. Tôi tạo virtualenv Python 3.11 bằng `uv` tại `~/k5-venv` (ngoài repo) để chạy script chấm.
- **Cost guard có thể vượt budget một chút:** `check_budget()` chạy trước và `record_cost()` chạy sau khi gọi LLM, nên request chạy song song có thể làm tổng vượt ngưỡng một ít. Muốn chặt hơn cần "đặt trước" chi phí ước tính trước khi gọi.
- **Số token là ước lượng:** mock LLM không trả số token thật, nên tôi ước lượng ~4 ký tự mỗi token.
- **`render.yaml`:** script chấm chỉ kiểm tra cú pháp ở mức tĩnh, nhưng file này sau đó đã được Render chấp nhận và deploy thành công ở Part 3 (xem mục Part 3).

## AI log

| Lần | Hỏi gì | Nhận gì | Tôi tự sửa / kiểm tra thế nào |
|-----|--------|---------|-------------------------------|
| 6 | Làm Part 3: viết phần so sánh `railway.toml` / `render.yaml` và phần Cloud Run, hướng dẫn từng bước deploy Render, kiểm tra URL public, viết `DEPLOYMENT.md` | Nội dung mục Part 3, `DEPLOYMENT.md`, script kiểm tra URL có nhập key bằng ô ẩn | Bạn tự thao tác trên Render và tự nhập key; tôi chỉ đọc mã HTTP (không thấy key). Bốn kết quả 200, 200, 401, 200 lấy từ file kết quả script và ảnh `test.png` của bạn; `check_production_ready.py --public-url` chạy lại → PASS 12/12. Cần bạn đọc lại và xác nhận. |
| 5 | Làm Part 6: viết code cho các chỗ TODO trong `06-lab-complete/` (config, auth, rate limiter Redis/Lua, cost guard, log JSON, health/ready, Dockerfile multi-stage, compose, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`); dựng môi trường WSL để chạy script chấm | Toàn bộ code và cấu hình của Part 6, lệnh chạy script chấm trong WSL | Đọc kỹ các phép kiểm tra của script chấm trước khi viết. Chạy script chấm đầy đủ → PASS 12/12, không sửa script. Tự chạy `docker compose up` và thử các trường hợp lỗi (401, 422, 429, Redis chết). Cần bạn đọc và hiểu từng file trong `06-lab-complete/app/` vì Lab Coach có thể hỏi giải thích. |
| 4 | Làm Part 5: đọc code health/ready, graceful shutdown, Redis session, nginx; chạy develop trong container để gửi SIGTERM thật; dựng stack 3 agent + Redis + Nginx, chạy `test_stateless.py`; thử tắt một instance | Câu trả lời 5.1–5.5, cách xử lý lỗi mạng Docker (build offline), xung đột cổng 8080 (đổi sang 8090 bằng file override ngoài repo) | Tự chạy mọi lệnh và lấy output thật. Bản sao `test_stateless.py` đổi cổng 8080→8090 (file gốc không sửa). Thử nghiệm tắt instance là script do tôi viết thêm, không thuộc lab. Cần bạn đọc lại và xác nhận. |
| 3 | Làm Part 4: đọc code API key, JWT, rate limiter, cost guard; chạy server và test 401/403/200/429/402; viết phần Part 4 | Câu trả lời 4.1–4.4 và các lệnh test | Tự chạy server, curl và script Python; lần đầu vòng lặp bị 422 do tôi quote JSON sai trong PowerShell, đã chạy lại bằng script Python. 402 minh hoạ bằng cách gọi trực tiếp `CostGuard` (không qua HTTP). Cần bạn đọc lại và xác nhận. |
| 2 | Làm Part 2: đọc Dockerfile/compose, build và đo image, chạy container và stack, viết phần Part 2 | Câu trả lời 2.1–2.4, cách xử lý lỗi mạng Docker (build offline bằng wheel tải sẵn, Dockerfile tạm đặt ngoài repo), sơ đồ stack | Tự chạy các lệnh build, `docker images`, curl, `docker compose`. Số MB lấy từ output thật. Cần bạn đọc lại và xác nhận trước khi nộp. |
| 1 | Đọc `develop/app.py` và `production/app.py`, liệt kê anti-pattern, viết phần Part 1 | Danh sách anti-pattern, bảng so sánh, câu trả lời Checkpoint 1 | Chạy lại bản develop để lấy output curl và log thật. Số dòng code đối chiếu trực tiếp với file. _(Bạn cần đọc lại và xác nhận trước khi nộp.)_ |
