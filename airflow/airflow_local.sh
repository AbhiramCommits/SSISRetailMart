#!/usr/bin/env bash
# Run the retail_mart_etl DAG end to end on a local Airflow (LocalExecutor + SQLite).
#
#   bash airflow/airflow_local.sh [logical_date]
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export AIRFLOW_HOME="$ROOT/airflow"
export AIRFLOW__CORE__EXECUTOR="LocalExecutor"
export AIRFLOW__CORE__LOAD_EXAMPLES="False"
export AIRFLOW__CORE__DAGS_FOLDER="$ROOT/airflow/dags"
export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="sqlite:///$AIRFLOW_HOME/airflow.db"
export AIRFLOW__WEBSERVER__SECRET_KEY="retailmart-local"
export AIRFLOW__CORE__FERNET_KEY="${AIRFLOW__CORE__FERNET_KEY:-$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')}"
export PYTHONPATH="$ROOT"

LOGICAL_DATE="${1:-2024-06-03}"
AIRFLOW_BIN="$ROOT/.venv/bin/airflow"

"$AIRFLOW_BIN" db migrate
"$AIRFLOW_BIN" dags test retail_mart_etl "$LOGICAL_DATE"
