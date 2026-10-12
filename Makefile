.PHONY: setup db ingest dev test smoke browser eval quality cleanup audit
setup:
	uv sync --frozen --cache-dir .cache/uv
	cd apps/web && npm ci --no-audit --no-fund --cache ../../.cache/npm
db:
	docker compose -f infra/compose.yaml up -d --wait
ingest: db
	PYTHONPATH=apps/api .venv/bin/python -m app.ingest
dev:
	.venv/bin/python scripts/dev.py
quality:
	.venv/bin/ruff check apps/api scripts evals
	cd apps/web && npm run lint && npm run typecheck && NEXT_TELEMETRY_DISABLED=1 npm run build
test:
	mkdir -p docs/mvp/results
	.venv/bin/pytest -q --junitxml=docs/mvp/results/pytest.xml
	$(MAKE) quality
smoke:
	.venv/bin/python scripts/smoke.py
browser:
	cd apps/web && npm run test:e2e
eval:
	.venv/bin/python evals/run.py
cleanup:
	PYTHONPATH=apps/api .venv/bin/python -m app.cleanup --dry-run

audit:
	.venv/bin/python scripts/audit_verify.py
