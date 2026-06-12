# Day 12 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found
1. Hardcoded `OPENAI_API_KEY` and `DATABASE_URL` expose secrets if the repo is pushed.
2. Config values such as `DEBUG`, `MAX_TOKENS`, host, and port are fixed in code instead of environment variables.
3. The app binds to `localhost`, so it is not reachable from outside a container or cloud runtime.
4. The port is hardcoded to `8000`; Railway/Render inject `PORT` dynamically.
5. Debug reload is enabled in runtime code, which is not suitable for production.
6. The app logs secrets and request data with `print()` instead of structured logging.
7. There is no `/health` endpoint, so a platform cannot detect and restart unhealthy containers.
8. There is no readiness check or graceful shutdown path.

### Exercise 1.3: Comparison table
| Feature | Develop | Production | Why Important? |
|---------|---------|------------|----------------|
| Config | Hardcoded constants | Environment variables | Same image can run in dev, staging, and production without code edits. |
| Secrets | API key and DB URL in code | Read from env | Prevents secret leaks in Git history and logs. |
| Host/port | `localhost:8000` | `0.0.0.0` and `PORT` env | Containers and cloud platforms can route traffic correctly. |
| Health check | Missing | `/health` | Platform can restart unhealthy instances. |
| Readiness | Missing | `/ready` | Load balancer can avoid routing to an instance that is still starting. |
| Logging | `print()` | JSON structured logs | Logs are searchable and easier to analyze in cloud logging tools. |
| Shutdown | No handler | Lifespan plus SIGTERM logging | In-flight requests and connections can finish cleanly. |
| CORS | Not configured | Env-driven origins | Keeps browser access explicit per environment. |

## Part 2: Docker

### Exercise 2.1: Dockerfile questions
1. Base image: the basic Dockerfile uses `python:3.11`; the production Dockerfile uses `python:3.11-slim`.
2. Working directory: `/app` in the runtime image.
3. `COPY requirements.txt` is done before copying source code so Docker can cache dependency installation when only app code changes.
4. `CMD` provides the default command and can be overridden at `docker run`; `ENTRYPOINT` defines the fixed executable and is harder to override.

### Exercise 2.3: Image size comparison
- Develop: 1.66 GB (`my-agent:develop`)
- Production: 241 MB (`batch02-day12_cloud_infras_and_deployment-agent:latest`)
- Difference: about 85.5% smaller.
- Reason: production uses `python:3.11-slim`, a builder stage, non-root runtime, and only copies installed packages plus runtime source.

### Exercise 2.4: Docker Compose stack
Architecture:

```text
Client -> Nginx (port 80) -> Agent containers (port 8000) -> Redis (port 6379)
```

Services:
- `nginx`: public entrypoint and load balancer.
- `agent`: FastAPI app; can be scaled with `docker compose up --scale agent=3`.
- `redis`: shared state for conversation history, rate limiting, and cost guard.

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment
- URL: `https://production-agent.up.railway.app` (Placeholder, replace after manual deployment)
- Screenshot: `(Screenshots pending manual deployment)`
- Environment variables to set: `PORT`, `REDIS_URL`, `AGENT_API_KEY`, `LOG_LEVEL`, `RATE_LIMIT_PER_MINUTE`, `MONTHLY_BUDGET_USD`.

### Exercise 3.2: Render vs Railway config
| Item | Railway | Render |
|------|---------|--------|
| Config file | `railway.toml` | `render.yaml` |
| Build | Dockerfile builder | Docker web service |
| Runtime port | Uses `$PORT` in start command | Uses platform-provided port with Docker service |
| Env vars | Set by `railway variables set` or dashboard | Defined in `render.yaml` and dashboard |
| Redis | Usually add Redis plugin/service and set `REDIS_URL` | Blueprint can define Redis service and inject connection string |

### Exercise 3.3: Cloud Run notes
`cloudbuild.yaml` describes image build and deployment steps, while `service.yaml` describes the Cloud Run service, container image, env vars, port, scaling, and health-related configuration.

## Part 4: API Security

### Exercise 4.1: API key authentication
- API key is checked in `app/auth.py` by reading the `X-API-Key` header.
- Missing or invalid keys return `401 Unauthorized`.
- Key rotation is done by changing `AGENT_API_KEY` in the deployment platform, redeploying/restarting, and distributing the new key to clients.

### Exercise 4.2: JWT authentication
The advanced example in `04-api-gateway/production/auth.py` creates a signed token with username, role, issued-at time, and expiration. The server verifies the `Authorization: Bearer <token>` header and rejects expired or invalid tokens. The final submitted app uses API key authentication because that is the explicit required auth mechanism in the delivery checklist.

### Exercise 4.3: Rate limiting
- Algorithm: Redis sorted-set sliding window.
- Limit: `10 req/min` per `user_id` by default.
- Admin bypass option: add a trusted role/API-key mapping and skip `check_rate_limit` for role `admin`, or give admin a separate higher limit key.

### Exercise 4.4: Cost guard implementation
The final app stores monthly spend in Redis with keys like `budget:{user_id}:YYYY-MM`. Before and after each request it estimates token cost, blocks users above `$10/month`, increments the monthly usage with `INCRBYFLOAT`, and expires the key after 32 days.

## Part 5: Scaling & Reliability

### Exercise 5.1: Health and readiness checks
- `/health` returns process status, version, uptime, request count, and instance ID.
- `/ready` verifies startup state and Redis connectivity. If Redis is unavailable it returns `503`.

### Exercise 5.2: Graceful shutdown
The app uses FastAPI lifespan for startup/shutdown state and registers a SIGTERM handler that logs `graceful_shutdown_signal`. Uvicorn is configured with graceful shutdown timeout in both local and Docker runtime commands.

### Exercise 5.3: Stateless design
Conversation history is not stored in Python memory. It is stored in Redis lists under `history:{user_id}`, so any scaled agent instance can read the same history.

### Exercise 5.4: Load balancing
`docker-compose.yml` includes `nginx`, `agent`, and `redis`. Run:

```bash
docker compose up --build --scale agent=3
```

Requests enter through Nginx and are forwarded to the agent service.

### Exercise 5.5: Stateless test
Use the same `user_id` across requests:

```bash
curl -X POST http://localhost/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"stateless-test","question":"My name is Alice"}'

curl -X POST http://localhost/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"stateless-test","question":"What is my name?"}'
```

The second response should mention Alice even if a different agent instance serves it, because history is in Redis.
