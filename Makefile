.PHONY: help install env redis api worker test-upload clean

# ── Setup ─────────────────────────────────────────────────────────────────────

help:
	@echo "ClipAssist MVP — local dev commands"
	@echo ""
	@echo "  make install      Install Python dependencies"
	@echo "  make env          Copy .env.example to .env (fill in OPENAI_API_KEY)"
	@echo "  make redis        Start Redis via Docker Compose"
	@echo "  make api          Start FastAPI dev server  (localhost:8000)"
	@echo "  make worker       Start Celery worker"
	@echo "  make test-upload  Upload a test video  (requires TEST_VIDEO=path/to/file.mp4)"
	@echo "  make clean        Remove generated data directory"

install:
	pip install -r requirements.txt

env:
	@if [ ! -f .env ]; then cp .env.example .env; echo ".env created — add your OPENAI_API_KEY"; \
	 else echo ".env already exists"; fi

# ── Services ──────────────────────────────────────────────────────────────────

redis:
	docker compose up -d redis
	@echo "Redis running on localhost:6379"

api:
	uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

worker:
	celery -A workers.celery_app.celery_app worker --loglevel=info --concurrency=2

# ── Dev helpers ───────────────────────────────────────────────────────────────

test-upload:
	@if [ -z "$(TEST_VIDEO)" ]; then echo "Usage: make test-upload TEST_VIDEO=path/to/video.mp4"; exit 1; fi
	curl -s -X POST http://localhost:8000/upload \
	     -F "file=@$(TEST_VIDEO)" | python3 -m json.tool

clean:
	rm -rf data/
	rm -f app.db

# ── Quick smoke test (no real video needed) ───────────────────────────────────
check-env:
	python3 -c "from core.config import OPENAI_API_KEY; print('Config OK — key starts with', OPENAI_API_KEY[:8])"
