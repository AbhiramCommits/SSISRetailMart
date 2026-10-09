SHELL := /bin/bash
PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
SA_PASSWORD ?= Str0ng!Passw0rd
MSSQL_PORT ?= 11433
export SA_PASSWORD
export MSSQL_PORT

.PHONY: help venv up down wait seed db-init etl dq test lint clean psql

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

venv: ## Create the python virtualenv and install pinned requirements
	/opt/homebrew/bin/python3.11 -m venv .venv || python3.11 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

up: ## Start SQL Server 2022 in Docker (host port 11433)
	docker compose up -d mssql
	$(PY) scripts/wait_for_sql.py

down: ## Stop the SQL Server container
	docker compose down

wait: ## Block until SQL Server accepts connections
	$(PY) scripts/wait_for_sql.py

seed: ## Generate the deterministic multi-source extracts into data/landing
	$(PY) data/generator/gen_sources.py

db-init: ## Apply all sql/ files to the container (idempotent)
	$(PY) scripts/apply_sql.py

etl: db-init ## Run all five SSIS packages in order via the dtexec-compatible CLI
	$(PY) scripts/run_etl.py

dq: ## Run the data-quality assertions standalone
	$(PY) scripts/run_dq.py

test: ## Run the full pytest suite
	$(PY) -m pytest -q

lint: ## Static checks
	$(PY) -m ruff check .

clean: ## Tear down containers, volumes, venv and generated artifacts
	-docker compose down -v
	-rm -rf .venv
	-rm -rf data/landing/*.csv data/landing/*.txt data/landing/*.json
	-rm -rf results/*.json results/*.md
	-rm -rf .pytest_cache .ruff_cache
	-find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	-rm -rf airflow/airflow.cfg airflow/airflow.db airflow/logs airflow/webserver_config.py

psql: ## Open sqlcmd against the running container
	docker compose exec mssql /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$(SA_PASSWORD)" -C -d RetailMart
