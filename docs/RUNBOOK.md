# RetailMart runbook

## Failure triage

### 1. Package exit codes
Every package is run through the dtexec-compatible CLI, which returns
`0` on success and `1` on failure (matching `dtexec`). The JSON result includes
`status`, `error`, per-package `rows_read` / `rows_inserted` / `rows_rejected`
and `duration_ms`.

```bash
python -m ssis_runtime.cli /PACKAGE ssis/packages/LoadSalesCsv.dtsx /SET BatchId=7
# {"package": "LoadSalesCsv", "status": "FAILED", "exit_code": 1, ...}
```

A package fails fast on a SQL error (`OperationalError`), a missing file, or an
unsupported component. The engine still writes the `audit.etl_batch` row with
status `FAILED` before returning.

### 2. Inspect rejected records
Rows that fail the data flow are redirected to `audit.failed_rows`:

```sql
SELECT component, error_column, COUNT(*) n
FROM audit.failed_rows
WHERE batch_id = 20240603000000
GROUP BY component, error_column
ORDER BY n DESC;

SELECT TOP 20 raw_row, error_description
FROM audit.failed_rows
WHERE batch_id = 20240603000000 AND component = 'Derived Column';
```

`component` names the failing SSIS component, `error_column` the offending
column, `raw_row` the original record, and `error_description` the reason.

### 3. Check batch status, row counts and checksums

```sql
SELECT package_name, status, rows_read, rows_inserted, rows_rejected, duration_ms
FROM audit.etl_batch WHERE batch_id = 20240603000000;

SELECT table_name, source_rows, target_rows, delta
FROM audit.row_count_check WHERE batch_id = 20240603000000;

SELECT column_name, source_checksum, target_checksum, matched
FROM audit.checksum_check WHERE batch_id = 20240603000000;

SELECT assertion_name, status, observed_value, threshold
FROM dq.assertion_result WHERE batch_id = 20240603000000;
```

A non-zero `delta` or `matched = 0` means staging and the warehouse diverged —
replay the affected load (below). A `FAIL` assertion means the DAG gate would
raise `AirflowFailException`; fix the data and re-run.

### 4. Replay a single batch
Re-run one package against an existing batch (the fact load is idempotent on
`txn_id`, so replays never duplicate):

```bash
python -m ssis_runtime.cli /PACKAGE ssis/packages/LoadStores.dtsx /SET BatchId=20240603000000
python -m ssis_runtime.cli /PACKAGE ssis/packages/LoadFactSales.dtsx /SET BatchId=20240603000000
```

Or call a procedure directly:

```sql
EXEC dw.sp_load_fact_sales_incremental @batch_id = 20240603000000;
EXEC audit.sp_record_row_counts       @batch_id = 20240603000000;
EXEC audit.sp_record_checksums        @batch_id = 20240603000000;
EXEC dq.sp_run_assertions             @batch_id = 20240603000000;
```

### 5. Reset the warehouse
Drops and recreates `RetailMart`, then re-applies all SQL:

```bash
python scripts/apply_sql.py --reset      # drop + recreate + apply sql/
# or a full teardown (container volume, venv, generated files):
make clean
```

To reload from scratch after a reset: `make seed && make db-init && make etl`.

### 6. Re-run the DAG
```bash
bash airflow/airflow_local.sh 2024-06-03
# inspect results/load_health.json and results/metrics.md afterwards
```

Beware that re-running the DAG re-stages the same extracts under a new batch;
the fact load is idempotent, but `row_count_check` for the new batch measures
the staged transactions, not a fresh insert.
