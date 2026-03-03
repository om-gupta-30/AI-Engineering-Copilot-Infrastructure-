# ─────────────────────────────────────────────────────────────────────────────
# AI Engineering Copilot — root Makefile
#
# ONE COMMAND TO RULE THEM ALL:
#   make start         → backend (Docker) + frontend (React) in one go
#   make stop          → kill everything
# ─────────────────────────────────────────────────────────────────────────────

.DEFAULT_GOAL := help

BOLD   := \033[1m
RESET  := \033[0m
GREEN  := \033[32m
CYAN   := \033[36m
YELLOW := \033[33m

# ── Help ──────────────────────────────────────────────────────────────────────

.PHONY: help
help:
	@echo ""
	@echo "$(BOLD)AI Engineering Copilot$(RESET)"
	@echo ""
	@echo "$(GREEN)★  ONE COMMAND$(RESET)"
	@echo "  $(BOLD)make start$(RESET)       Backend (Docker) + Frontend (React) — everything"
	@echo "  $(BOLD)make stop$(RESET)        Shut down everything"
	@echo "  $(BOLD)make restart$(RESET)     stop + start"
	@echo ""
	@echo "$(CYAN)Docker (backend only)$(RESET)"
	@echo "  $(BOLD)make up$(RESET)          Start backend containers (detached)"
	@echo "  $(BOLD)make up-build$(RESET)    Force rebuild then start"
	@echo "  $(BOLD)make down$(RESET)        Stop backend containers"
	@echo "  $(BOLD)make logs$(RESET)        Tail all container logs"
	@echo "  $(BOLD)make logs-api$(RESET)    Tail API logs only"
	@echo "  $(BOLD)make logs-mcp$(RESET)    Tail MCP logs only"
	@echo "  $(BOLD)make ps$(RESET)          Show running containers"
	@echo ""
	@echo "$(CYAN)Local dev (no Docker)$(RESET)"
	@echo "  $(BOLD)make install$(RESET)     Install Python deps via Poetry"
	@echo "  $(BOLD)make dev$(RESET)         FastAPI backend on :8000"
	@echo "  $(BOLD)make dev-mcp$(RESET)     MCP server on :8100"
	@echo "  $(BOLD)make dev-ui$(RESET)      React frontend on :3000"
	@echo ""
	@echo "$(CYAN)Quality$(RESET)"
	@echo "  $(BOLD)make test$(RESET)        Run pytest suite"
	@echo "  $(BOLD)make lint$(RESET)        Lint with ruff"
	@echo "  $(BOLD)make format$(RESET)      Auto-format with ruff"
	@echo "  $(BOLD)make typecheck$(RESET)   Type-check with mypy"
	@echo ""
	@echo "$(CYAN)Utilities$(RESET)"
	@echo "  $(BOLD)make shell$(RESET)       Open Poetry shell"
	@echo "  $(BOLD)make clean$(RESET)       Remove cache / build artefacts"
	@echo ""

# ── ★ ONE COMMAND ─────────────────────────────────────────────────────────────

.PHONY: start
start:
	@echo ""
	@echo "$(BOLD)$(GREEN)Starting everything...$(RESET)"
	@echo ""
	docker compose up -d --build
	@echo ""
	@echo "$(GREEN)Backend containers running.$(RESET)"
	@echo "  API:  http://localhost:8000/docs"
	@echo "  MCP:  http://localhost:8100/docs"
	@echo ""
	@if [ ! -d "copilot-ui/node_modules" ]; then \
		echo "$(YELLOW)Installing frontend dependencies...$(RESET)"; \
		cd copilot-ui && npm install; \
	fi
	@echo "$(GREEN)Launching React frontend on http://localhost:3000$(RESET)"
	@echo "$(YELLOW)(Press Ctrl+C to stop the frontend; run 'make stop' to stop the backend)$(RESET)"
	@echo ""
	cd copilot-ui && npm start

.PHONY: stop
stop:
	@echo "$(BOLD)Stopping all backend containers...$(RESET)"
	docker compose down
	@echo "$(GREEN)Backend stopped.$(RESET)"

.PHONY: restart
restart: stop start

# ── Docker (backend) ──────────────────────────────────────────────────────────

.PHONY: up
up:
	docker compose up -d
	@echo ""
	@echo "$(GREEN)Backend started.$(RESET)"
	@echo "  API:  http://localhost:8000/docs"
	@echo "  MCP:  http://localhost:8100/docs"
	@echo ""

.PHONY: up-build
up-build:
	docker compose up -d --build
	@echo ""
	@echo "$(GREEN)Backend rebuilt and started.$(RESET)"
	@echo "  API:  http://localhost:8000/docs"
	@echo "  MCP:  http://localhost:8100/docs"
	@echo ""

.PHONY: down
down:
	docker compose down

.PHONY: logs
logs:
	docker compose logs -f

.PHONY: logs-api
logs-api:
	docker compose logs -f api

.PHONY: logs-mcp
logs-mcp:
	docker compose logs -f mcp

.PHONY: ps
ps:
	docker compose ps

# ── Local dev (no Docker) ─────────────────────────────────────────────────────

.PHONY: install
install:
	poetry install

.PHONY: dev
dev:
	poetry run python infra/run.py

.PHONY: dev-mcp
dev-mcp:
	poetry run python ai_copilot_infra/mcp_server/run.py

.PHONY: dev-ui
dev-ui:
	cd copilot-ui && npm start

# ── Quality ───────────────────────────────────────────────────────────────────

.PHONY: test
test:
	poetry run pytest tests/ -v

.PHONY: lint
lint:
	poetry run ruff check .

.PHONY: format
format:
	poetry run ruff format .

.PHONY: typecheck
typecheck:
	poetry run mypy ai_copilot_infra/

# ── Utilities ─────────────────────────────────────────────────────────────────

.PHONY: shell
shell:
	poetry shell

.PHONY: clean
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@echo "$(GREEN)Cleaned.$(RESET)"
