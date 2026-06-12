# Day 12 Lab — Solution (Parts 1–5)

> Đáp án chi tiết các bài tập codelab từ Part 1 đến Part 5.

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns tìm được trong `01-localhost-vs-production/develop/app.py`

1. **Hardcoded API key** — `OPENAI_API_KEY` được viết thẳng trong source code → nếu push lên GitHub public, key bị lộ ngay lập tức.
2. **Hardcoded database URL** — `DATABASE_URL` cũng hardcoded, cùng rủi ro bảo mật.
3. **Config cố định** — `DEBUG=True`, `MAX_TOKENS`, host, port đều hardcode, không thể thay đổi giữa các environment mà không sửa code.
4. **Bind `localhost`** — App chỉ lắng nghe trên `127.0.0.1`, nên không thể truy cập từ bên ngoài container hoặc từ cloud.
5. **Port hardcoded `8000`** — Railway/Render inject biến `PORT` động; nếu hardcode sẽ không chạy đúng trên cloud.
6. **Debug reload bật sẵn** — `reload=True` chạy trong production dễ gây instability và tốn resource.
7. **Logging bằng `print()`** — Không structured, không thể search/filter trong cloud logging (CloudWatch, Datadog…).
8. **Không có `/health` endpoint** — Platform không biết khi nào container healthy để restart.
9. **Không có readiness check** — Load balancer không biết khi nào app sẵn sàng nhận traffic.
10. **Không có graceful shutdown** — Khi SIGTERM, các request đang xử lý bị cắt ngang.

### Exercise 1.2: Chạy basic version

```bash
cd 01-localhost-vs-production/develop
pip install -r requirements.txt
python app.py
# App chạy trên http://localhost:8000
```

Test:
```bash
curl -X POST "http://localhost:8000/ask?question=hello"
# → Nhận response thành công
```

**Quan sát:** App chạy tốt trên localhost nhưng KHÔNG production-ready vì thiếu toàn bộ tính năng bảo mật, monitoring, và khả năng cấu hình.

### Exercise 1.3: Bảng so sánh Develop vs Production

| Feature | Develop (Basic) | Production (Advanced) | Tại sao quan trọng? |
|---------|----------------|----------------------|---------------------|
| Config | Hardcoded constants | Environment variables (`os.getenv`) | Cùng 1 image có thể chạy ở dev, staging, production mà không cần sửa code |
| Secrets | API key & DB URL trong code | Đọc từ env vars | Tránh rò rỉ secrets qua Git history và logs |
| Host/Port | `localhost:8000` cố định | `0.0.0.0` + `PORT` env var | Container và cloud platform route traffic đúng |
| Health check | ❌ Không có | ✅ `GET /health` | Platform tự restart instance lỗi |
| Readiness | ❌ Không có | ✅ `GET /ready` | Load balancer chỉ gửi traffic đến instance sẵn sàng |
| Logging | `print()` | JSON structured logging | Logs dễ search, filter, phân tích trong cloud logging tools |
| Shutdown | Tắt đột ngột | Graceful — Lifespan + SIGTERM handler | In-flight requests hoàn thành, connections đóng sạch |
| CORS | Không cấu hình | Env-driven allowed origins | Kiểm soát truy cập browser theo từng environment |
| Error handling | Crash trực tiếp | Proper HTTP error responses | User experience tốt hơn, debug dễ hơn |

### ✅ Checkpoint 1

- [x] Hiểu tại sao hardcode secrets là nguy hiểm
- [x] Biết cách dùng environment variables
- [x] Hiểu vai trò của health check endpoint
- [x] Biết graceful shutdown là gì

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions

1. **Base image:** Dockerfile develop dùng `python:3.11` (~1 GB); Dockerfile production dùng `python:3.11-slim` (~150 MB).
2. **Working directory:** `/app` — nơi chứa source code trong container.
3. **Tại sao COPY requirements.txt trước?** Tận dụng Docker layer caching. Khi chỉ thay đổi source code (không đổi dependencies), Docker skip rebuild layer `pip install` → build nhanh hơn rất nhiều.
4. **CMD vs ENTRYPOINT:**
   - `CMD` cung cấp default command, có thể bị override bằng `docker run <image> <custom-cmd>`.
   - `ENTRYPOINT` định nghĩa executable cố định, khó override hơn (phải dùng `--entrypoint`).
   - Best practice: dùng `ENTRYPOINT` cho executable, `CMD` cho default arguments.

### Exercise 2.2: Build và run basic container

```bash
# Build
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .

# Run
docker run -p 8000:8000 my-agent:develop

# Test
curl http://localhost:8000/ask -X POST \
  -H "Content-Type: application/json" \
  -d '{"question": "What is Docker?"}'

# Check image size
docker images my-agent:develop
# → SIZE: ~1.66 GB
```

### Exercise 2.3: Multi-stage build — Image size comparison

| Variant | Image | Size | Base |
|---------|-------|------|------|
| Develop | `my-agent:develop` | ~1.66 GB | `python:3.11` (full) |
| Production | `batch02-day12...-agent:latest` | ~241 MB | `python:3.11-slim` (multi-stage) |

**Giảm ~85.5%** nhờ:
- `python:3.11-slim` thay vì `python:3.11`
- Multi-stage: stage 1 (builder) compile deps, stage 2 (runtime) chỉ copy packages cần thiết
- Non-root user, không có build tools (gcc, pip cache)

**Stage 1 (Builder):** Cài đầy đủ build tools (gcc), compile dependencies.
**Stage 2 (Runtime):** Base image sạch, chỉ copy `/root/.local` (installed packages) và source code.

### Exercise 2.4: Docker Compose stack — Architecture diagram

```text
                    ┌─────────┐
                    │  Client │
                    └────┬────┘
                         │
                         ▼
                  ┌──────────────┐
                  │ Nginx (LB)   │  ← Port 80 (public)
                  │ Load Balancer│
                  └──────┬───────┘
                         │
           ┌─────────────┼─────────────┐
           ▼             ▼             ▼
      ┌─────────┐  ┌─────────┐  ┌─────────┐
      │ Agent 1 │  │ Agent 2 │  │ Agent 3 │  ← Port 8000 (internal)
      └────┬────┘  └────┬────┘  └────┬────┘
           │             │             │
           └─────────────┼─────────────┘
                         ▼
                  ┌──────────────┐
                  │    Redis     │  ← Port 6379 (internal)
                  │ Shared State │
                  └──────────────┘
```

**Services:**
- **nginx** — Public entrypoint, reverse proxy, load balancer (round-robin).
- **agent** — FastAPI application; scalable với `--scale agent=3`.
- **redis** — Shared state store cho conversation history, rate limiting, cost guard.

**Communication:** Tất cả services cùng Docker network `agent_net`, communicate qua service name (DNS).

### ✅ Checkpoint 2

- [x] Hiểu cấu trúc Dockerfile
- [x] Biết lợi ích của multi-stage builds
- [x] Hiểu Docker Compose orchestration
- [x] Biết cách debug container (`docker logs`, `docker exec`)

---

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment

- **URL:** `https://renewed-motivation-production-0f9d.up.railway.app/`
- **Health check:** `GET /health` → `{"status":"ok","uptime_seconds":...,"platform":"Railway","timestamp":"..."}`
- **Environment variables đã set:**
  - `PORT` — Railway tự inject
  - `REDIS_URL` — Redis plugin connection string
  - `AGENT_API_KEY` — Secret key cho authentication
  - `LOG_LEVEL` — `INFO`
  - `RATE_LIMIT_PER_MINUTE` — `10`
  - `MONTHLY_BUDGET_USD` — `10.0`
  - `ENVIRONMENT` — `production`

### Exercise 3.2: Railway vs Render config comparison

| Item | Railway (`railway.toml`) | Render (`render.yaml`) |
|------|--------------------------|------------------------|
| Config file format | TOML | YAML |
| Build method | `builder = "DOCKERFILE"` | `runtime: docker` |
| Start command | `startCommand` trong `[deploy]` | Platform tự dùng CMD từ Dockerfile |
| Health check | `healthcheckPath = "/health"` | `healthCheckPath: /health` |
| Env vars | CLI: `railway variables set KEY=value` hoặc dashboard | Khai báo trong `render.yaml` dưới `envVars` |
| Redis | Thêm Redis plugin qua dashboard, inject `REDIS_URL` | Blueprint có thể define `type: redis`, tự inject connection string |
| Auto deploy | Default khi push | `autoDeploy: true` trong YAML |
| Restart policy | `restartPolicyType = "ON_FAILURE"` | Managed by platform |
| Region | Dashboard setting | `region: singapore` trong YAML |
| Secret generation | Manual hoặc dashboard | `generateValue: true` trong YAML |

### Exercise 3.3: GCP Cloud Run notes

- **`cloudbuild.yaml`** — Mô tả CI/CD pipeline:
  - Step 1: Build Docker image
  - Step 2: Push lên Container Registry (GCR/Artifact Registry)
  - Step 3: Deploy lên Cloud Run
- **`service.yaml`** — Mô tả Cloud Run service:
  - Container image, env vars, port mapping
  - Scaling config (min/max instances, concurrency)
  - Health check và timeout settings
  - Traffic splitting (cho canary deployment)

### ✅ Checkpoint 3

- [x] Deploy thành công lên Railway
- [x] Có public URL hoạt động: `https://renewed-motivation-production-0f9d.up.railway.app/`
- [x] Hiểu cách set environment variables trên cloud
- [x] Biết cách xem logs (`railway logs`)

---

## Part 4: API Security

### Exercise 4.1: API Key authentication

- **Vị trí check:** `app/auth.py` — function `verify_api_key()` đọc header `X-API-Key`.
- **Cơ chế:** Dùng `secrets.compare_digest()` (timing-safe comparison) so sánh key nhận được với `settings.agent_api_key`.
- **Nếu sai key:** Trả về HTTP `401 Unauthorized` với message `"Missing or invalid API key"`.
- **Rotate key:**
  1. Thay đổi `AGENT_API_KEY` trên deployment platform (Railway dashboard / `railway variables set`)
  2. Redeploy hoặc restart service
  3. Phân phối key mới cho clients
  4. **Lưu ý:** Không cần sửa code, chỉ thay env var.

### Exercise 4.2: JWT authentication

File `04-api-gateway/production/auth.py` implement JWT flow:

1. **Login** — Client gửi `POST /token` với `username` + `password`.
2. **Token creation** — Server tạo signed JWT chứa: `sub` (username), `role`, `iat` (issued at), `exp` (expiration).
3. **Token verification** — Mỗi request gửi `Authorization: Bearer <token>`, server decode và verify:
   - Chữ ký hợp lệ? (signed đúng secret)
   - Token chưa hết hạn? (`exp` > now)
   - Payload hợp lệ?
4. **Reject** — Token invalid/expired → HTTP 401.

**Lý do final app dùng API Key:** Delivery checklist yêu cầu API key authentication, phù hợp với use case M2M (machine-to-machine) đơn giản hơn JWT.

### Exercise 4.3: Rate limiting

- **Algorithm:** Redis sorted-set sliding window.
  - Mỗi request thêm 1 member vào sorted set, score = timestamp (milliseconds).
  - Trước mỗi request, xóa tất cả entries cũ hơn 60 giây.
  - Đếm số entries còn lại → nếu >= limit → reject.
- **Limit:** `10 requests/minute` per `user_id` (cấu hình qua `RATE_LIMIT_PER_MINUTE`).
- **Bypass cho admin:**
  - Option 1: Mapping API key → role, nếu role = `admin` thì skip `check_rate_limit`.
  - Option 2: Admin dùng separate key với limit cao hơn (e.g., `1000 req/min`).
  - Option 3: Whitelist admin user_id trong config.

### Exercise 4.4: Cost guard implementation

File `app/cost_guard.py` implement budget protection:

```python
# Key pattern: budget:{user_id}:YYYY-MM
def check_budget(user_id, estimated_cost):
    key = f"budget:{user_id}:{month}"
    current = float(redis.get(key) or 0)
    if current + estimated_cost > $10/month:
        raise HTTPException(402, "Monthly budget exceeded")

def record_usage(user_id, input_tokens, output_tokens):
    cost = estimate_cost(input_tokens, output_tokens)
    redis.incrbyfloat(key, cost)
    redis.expire(key, 32 * 24 * 3600)  # 32 days TTL
```

**Flow:**
1. Trước mỗi request → `estimate_cost()` tính chi phí dự kiến.
2. `check_budget()` kiểm tra: `current_spending + estimated > monthly_budget` → block nếu vượt.
3. Sau khi xử lý xong → `record_usage()` cập nhật chi phí thực tế vào Redis.
4. Key tự expire sau 32 ngày (tự reset hàng tháng).

### ✅ Checkpoint 4

- [x] Implement API key authentication
- [x] Hiểu JWT flow
- [x] Implement rate limiting (Redis sorted-set sliding window)
- [x] Implement cost guard với Redis ($10/month per user)

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health và readiness checks

```python
@app.get("/health")
def health():
    """Liveness probe — container còn sống không?"""
    return {
        "status": "ok",
        "version": settings.app_version,
        "instance": INSTANCE_ID,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": request_count,
        "error_count": error_count,
    }

@app.get("/ready")
def ready():
    """Readiness probe — sẵn sàng nhận traffic không?"""
    if not is_ready:
        raise HTTPException(status_code=503, detail="Application is not ready")
    try:
        ping_redis()  # Check Redis connectivity
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Redis is not ready") from exc
    return {"ready": True, "storage": "redis", "instance": INSTANCE_ID}
```

**Sự khác biệt:**
- `/health` (Liveness) — Chỉ check process còn chạy không. Platform dùng để restart container nếu fail.
- `/ready` (Readiness) — Check dependencies (Redis, DB). Load balancer dùng để quyết định có gửi traffic đến instance không.

### Exercise 5.2: Graceful shutdown

```python
import signal

def handle_sigterm(signum, _frame):
    logger.info(json.dumps({"event": "graceful_shutdown_signal", "signal": signum}))

signal.signal(signal.SIGTERM, handle_sigterm)

# Uvicorn config
uvicorn.run(
    "app.main:app",
    host="0.0.0.0",
    port=8000,
    timeout_graceful_shutdown=30,  # 30 seconds to finish in-flight requests
)
```

**Flow khi nhận SIGTERM:**
1. Handler log signal event.
2. Uvicorn ngừng accept connections mới.
3. Chờ tối đa 30 giây để in-flight requests hoàn thành.
4. FastAPI lifespan `yield` chạy phần shutdown (set `is_ready = False`, log shutdown event).
5. Process exit cleanly.

### Exercise 5.3: Stateless design

**Anti-pattern (Stateful):**
```python
# ❌ State trong memory → mất khi restart, không share giữa instances
conversation_history = {}
```

**Correct (Stateless):**
```python
# ✅ State trong Redis → persist, shared across instances
def load_history(user_id):
    raw_messages = redis_client.lrange(f"history:{user_id}", 0, -1)
    return [json.loads(msg) for msg in raw_messages]

def append_history(user_id, role, content):
    key = f"history:{user_id}"
    redis_client.rpush(key, json.dumps(message))
    redis_client.ltrim(key, -20, -1)  # Keep last 20 messages
    redis_client.expire(key, 30 * 24 * 3600)  # 30 days TTL
```

**Tại sao stateless?** Khi scale ra 3 instances, mỗi instance có memory riêng. Request 1 vào Agent 1 (lưu history trong memory), request 2 vào Agent 2 → Agent 2 không biết history → UX bị hỏng.

### Exercise 5.4: Load balancing

```bash
docker compose up --build --scale agent=3
```

**Kết quả:**
- 3 agent instances được start (agent-1, agent-2, agent-3)
- Nginx phân tán requests theo round-robin
- Mỗi response có header `X-Instance-ID` khác nhau → chứng minh requests được phân tán
- Nếu 1 instance die → Nginx tự redirect traffic sang instances còn lại (`proxy_next_upstream`)

### Exercise 5.5: Stateless test

```bash
# Request 1: Introduce name → có thể vào Agent 1
curl -X POST http://localhost/ask \
  -H "X-API-Key: dev-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"stateless-test","question":"My name is Alice"}'

# Request 2: Ask name → có thể vào Agent 2 hoặc Agent 3
curl -X POST http://localhost/ask \
  -H "X-API-Key: dev-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"stateless-test","question":"What is my name?"}'
```

**Expected:** Response thứ 2 trả về "You told me your name is Alice." dù được serve bởi instance khác, vì history nằm trong Redis (shared).

### ✅ Checkpoint 5

- [x] Implement health và readiness checks
- [x] Implement graceful shutdown
- [x] Refactor code thành stateless (history trong Redis)
- [x] Hiểu load balancing với Nginx
- [x] Test stateless design — conversation history persist qua instances

---

## Summary

| Part | Concepts | Status |
|------|----------|--------|
| 1 | Dev vs Production, 12-Factor, Env vars, Health checks | ✅ Hoàn thành |
| 2 | Dockerfile, Multi-stage build, Docker Compose | ✅ Hoàn thành |
| 3 | Railway/Render deployment, Cloud config | ✅ Hoàn thành |
| 4 | API Key auth, JWT, Rate limiting, Cost guard | ✅ Hoàn thành |
| 5 | Health/Ready probes, Graceful shutdown, Stateless, LB | ✅ Hoàn thành |
