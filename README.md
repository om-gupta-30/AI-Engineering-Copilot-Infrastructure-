# AI Engineering Copilot

A production-grade AI assistant for software engineers. Ask a technical question — it detects the libraries involved, fetches real documentation, grounds an LLM answer in that context, validates the output, and caches the result.

Built with **FastAPI**, **OpenAI**, **Redis**, **Docker**, and a deterministic 6-step workflow engine.

---

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  React UI    │────▶│  API Server  │────▶│  MCP Server  │────▶│  Context7    │
│  :3000       │     │  :8000       │     │  :8100       │     │  (docs API)  │
└──────────────┘     └──────┬───────┘     └──────────────┘     └──────────────┘
                            │
                     ┌──────▼───────┐
                     │    Redis     │
                     │  :6379       │
                     └──────────────┘
```

**Request flow:**

1. User submits a question via the React UI or API
2. API generates a `trace_id` and starts the 6-step workflow
3. **Step 1** — Classify query intent
4. **Step 2** — Call MCP server to detect libraries (Redis, Celery, Docker, etc.)
5. **Step 3** — Call MCP server to fetch documentation per library
6. **Step 4** — Build a grounded prompt with the real docs
7. **Step 5** — Send prompt to OpenAI (GPT-4o-mini)
8. **Step 6** — Validate the response (empty check, length check, hallucination detection)
9. Cache the validated response in Redis (1 hour TTL)
10. Return the answer with `trace_id` for observability

---

## Quick Start

### Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/docs/#installation) 1.8+
- Docker + Docker Compose
- Node.js 18+ (for the frontend)

### Setup

```bash
# 1. Clone the repo
git clone <your-repo-url>
cd <repo-name>

# 2. Copy env file and add your OpenAI key
cp .env.example .env
# Edit .env → set OPENAI_API_KEY=sk-...

# 3. Start everything (backend + frontend)
make start
```

That's it. The app opens at:

| Service | URL |
|---|---|
| **React UI** | http://localhost:3000 |
| **API Swagger** | http://localhost:8000/docs |
| **MCP Swagger** | http://localhost:8100/docs |

### Other commands

```bash
make stop          # Shut down all containers
make restart       # Full restart
make logs          # Tail all container logs
make test          # Run pytest
make lint          # Run ruff linter
make help          # See all available commands
```

---

## Project Structure

```
.
├── ai_copilot_infra/           # Python package
│   ├── api/                    # FastAPI application
│   │   ├── app.py              # App factory + lifespan hooks
│   │   ├── routes/
│   │   │   ├── health.py       # GET  /api/v1/health
│   │   │   └── copilot.py      # POST /api/v1/copilot/query
│   │   └── middleware/
│   │       └── logging.py      # Structured request/response logging
│   ├── core/                   # Shared infrastructure layer
│   │   ├── config.py           # pydantic-settings (all env vars)
│   │   ├── dependencies.py     # FastAPI DI providers
│   │   ├── llm_service.py      # OpenAI async wrapper
│   │   ├── mcp_client.py       # HTTP client → MCP server
│   │   ├── redis_service.py    # Async Redis operations
│   │   └── validation.py       # Output quality validator
│   ├── workflows/              # Deterministic pipeline engine
│   │   ├── base.py             # WorkflowStep + StepPipeline ABCs
│   │   ├── state.py            # WorkflowState (shared context)
│   │   └── copilot_workflow.py # 6-step copilot pipeline
│   ├── mcp_server/             # MCP Tool Server (separate container)
│   │   ├── app.py              # FastAPI app for tool execution
│   │   ├── base.py             # BaseTool abstract class
│   │   ├── registry.py         # ToolRegistry
│   │   ├── library_detection_tool.py
│   │   ├── documentation_fetch_tool.py
│   │   ├── tools.py            # Default tool registration
│   │   └── run.py              # Uvicorn entrypoint
│   ├── context/                # External documentation client
│   │   └── context7_client.py  # Async HTTP client for Context7
│   ├── observability/
│   │   └── logger.py           # Loguru (JSON + text formats)
│   ├── infra/
│   │   └── redis_client.py     # Async Redis connection pool
│   └── main.py                 # Uvicorn entrypoint for API
├── copilot-ui/                 # React TypeScript frontend
│   ├── src/
│   │   ├── App.tsx             # Main UI component
│   │   └── App.css             # Dark theme styles
│   └── package.json
├── infra/
│   └── run.py                  # Local API launcher
├── tests/
│   └── test_health.py          # Health endpoint smoke test
├── .github/workflows/ci.yml   # GitHub Actions CI pipeline
├── Dockerfile                  # Production image (python:3.11-slim)
├── docker-compose.yml          # api + mcp + redis + context7
├── Makefile                    # All commands in one place
├── pyproject.toml              # Poetry config + tool settings
├── poetry.lock                 # Locked dependencies
└── .env.example                # Environment variable template
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in secrets. **Never commit `.env` to git.**

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | **Yes** | Your OpenAI API key |
| `REDIS_URL` | No | Redis connection string (default: `redis://redis:6379/0`) |
| `MCP_BASE_URL` | No | MCP server URL (default: `http://mcp:8100`) |
| `CONTEXT7_BASE_URL` | No | Context7 documentation API URL |
| `CONTEXT7_API_KEY` | No | Context7 authentication key |
| `LANGFUSE_PUBLIC_KEY` | No | Langfuse public key (future) |
| `LANGFUSE_SECRET_KEY` | No | Langfuse secret key (future) |
| `LOG_FORMAT` | No | `json` (production) or `text` (local dev) |

---

## API Reference

### `POST /api/v1/copilot/query`

```json
// Request
{ "query": "How do I configure Celery with Redis in Docker Compose?" }

// Response
{
  "answer": "To configure Celery with Redis in Docker Compose...",
  "libraries_used": ["Redis", "Celery", "Docker"],
  "validation_passed": true,
  "cached": false,
  "trace_id": "d4e5f6a7-..."
}
```

### `GET /api/v1/health`

```json
{ "status": "ok", "version": "0.1.0", "env": "development" }
```

---

## CI/CD

GitHub Actions runs on every push and PR to `main`/`master`/`develop`:

- **Lint** — `ruff check` + `ruff format --check`
- **Test** — `pytest` with a Redis service container
- **Docker Build** — builds the image and verifies it starts
- **Frontend** — `npm ci` + `npm run build`

---

## Security

- `.env` is in `.gitignore` — secrets never get committed
- `.dockerignore` excludes `.env`, `.git/`, and dev artefacts from images
- API keys are read from environment variables at runtime, never hardcoded
- Rate limiting: 20 requests/minute per IP via Redis

---

## Deployment

### Docker (self-hosted / GCP / AWS)

```bash
docker build -t ai-copilot .
docker run -p 8000:8000 --env-file .env ai-copilot
```

### Vercel (frontend only)

Deploy `copilot-ui/` as a static site. Set `REACT_APP_API_URL` to your deployed backend URL.

---

## License

MIT
