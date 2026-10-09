# SSISRetailMart

A Microsoft-stack retail data warehouse. Three physically different sources — a
fixed-width flat file, per-day CSV extracts, and a local REST/JSON product feed —
are ingested by real SSIS packages (`.dtsx`) into SQL Server staging, transformed
with derived columns and lookups, and loaded into a star schema (`fact_sales`
plus date/product/store dimensions with SCD Type 1 and Type 2 behaviour). Loads
are audited with row-count and checksum parity tables and failed-row redirection,
orchestrated by an Airflow DAG that runs the packages and gates the load on
data-quality assertions, and surfaced through a Power BI semantic model
(`model.bim` + DAX measures + a 3-page report). SSIS + SQL Server is where the
warehouse lives, Power BI is the semantic layer, and Airflow is the scheduler —
so the same extract-to-dashboard path works on Windows (SSDT/dtexec) and on
Linux/macOS/CI (the bundled dtexec-compatible runtime).

The repository ships a `dtexec`-compatible runner (`ssis_runtime/`) that parses
the `.dtsx` XML and executes the declared data flow against SQL Server, so the
packages actually run on Linux/macOS/CI exactly as SSDT would run them on Windows.

## Architecture

```
  SOURCES                       INGEST (SSIS)                         WAREHOUSE
  ┌───────────────────┐   ┌──────────────────────────────┐   ┌────────────────────────┐
  │ stores.txt        │   │ LoadStores.dtsx              │   │ stg.stores_raw         │
  │  fixed-width      │──▶│  FlatFile → Derived → Lookup │──▶│ stg.sales_raw          │
  ├───────────────────┤   │  → Split → OLE DB            │   │ stg.products_raw       │
  │ sales_YYYYMMDD.csv│   │ LoadSalesCsv.dtsx (ForEach)  │   └───────────┬────────────┘
  │  delimited        │──▶│ LoadProductsRest.dtsx (JSON) │               │
  ├───────────────────┤   └──────────────────────────────┘   T-SQL procs │
  │ product REST API  │                                           ▼      ▼
  │  /products,       │   ┌──────────────────────────────┐   ┌────────────────────────┐
  │  /products/changes│──▶│ dtexec / runtime CLI         │   │ dw.dim_date            │
  └───────────────────┘   │  ({/PACKAGE, /SET})          │   │ dw.dim_store  (SCD1)   │
                          └──────────────────────────────┘   │ dw.dim_product(SCD2)   │
                                                             │ dw.fact_sales          │
   ┌──────────────────────────────────────────────────┐      │ dw.fact_inventory_snap │
   │ Airflow DAG `retail_mart_etl` (0 2 * * *)        │      └───────────┬────────────┘
   │ start → [stores,sales,products] → dims → fact →  │                  │
   │ inventory → run_dq_assertions → publish_health → │       dw.vw_sales_trend
   │ end_batch (all_done)                             │       dw.vw_stockouts
   └──────────────────────────────────────────────────┘       dw.vw_load_health
                                                             ─────────┬─────────────
   ┌──────────────────────────────────────────┐                       ▼
   │ audit.etl_batch / row_count_check /      │            Power BI semantic model
   │ checksum_check / failed_rows  + dq.*     │            (model.bim + measures.tmdl
   └──────────────────────────────────────────┘             + report/layout.json)
```

### Star schema (grain statements)

| Table | Grain |
| --- | --- |
| `dw.dim_date` | one row per calendar day (2019-01-01 … 2027-12-31) |
| `dw.dim_store` | one row per store (`store_code`), SCD Type 1 (overwrite) |
| `dw.dim_product` | one row per product **version** (`sku` + validity window), SCD Type 2 |
| `dw.fact_sales` | one row per sales transaction line (`txn_id`) |
| `dw.fact_inventory_snapshot` | one row per (business date, product, store) inventory position |
| `audit.etl_batch` | one row per (batch, package) execution |
| `audit.row_count_check` | source/target parity per batch and table |
| `audit.checksum_check` | SUM / CHECKSUM_AGG parity per batch and column |
| `audit.failed_rows` | one row per rejected record with its error context |
| `dq.assertion_result` | one row per assertion per batch run |

Unknown members (`store_sk = -1`, `product_sk = -1`) keep the fact table
referentially complete; unmatched lookups are substituted, not dropped.

## How to run

```bash
make venv        # create .venv and install pinned requirements (Python 3.11)
cp .env.example .env
make up          # start SQL Server 2022 on host port 11433 and wait for it
make seed        # generate the deterministic multi-source extracts
make db-init     # apply sql/ (DDL, procs, checks, views) idempotently
make etl         # run all five SSIS packages through the dtexec-compatible CLI
bash airflow/airflow_local.sh 2024-06-03   # run the DAG end to end (LocalExecutor)
python scripts/export_metrics.py           # write results/metrics.{json,md}
pytest -q                                  # full test suite
```

Everything is pinned in `requirements.txt` (Python 3.11). `make up` reads
`SA_PASSWORD`/`MSSQL_PORT` from `.env` (copy `.env.example`).

### Power BI

Open `powerbi/model.bim` in **Tabular Editor** (or as a Power BI Desktop
`model.bim` source), point the `Sql.Database("localhost,11433", "RetailMart")`
partitions at your server, import `powerbi/measures.tmdl`, and use
`powerbi/report/layout.json` as the page blueprint (`powerbi/report/README.md`
documents the three pages).

### Swapping the runtime for Windows `dtexec`

The Airflow extract/load tasks call the runtime through one function,
`_dtexec_command` in `airflow/dags/retail_mart_etl.py`. On a Windows host with
SSDT/SSIS installed, replace the body with:

```python
f'dtexec /F "{PROJECT_ROOT}/ssis/packages/{package}.dtsx" '
f'/SET "\\Package.Variables[User::BatchId].Properties[Value]";{BATCH_ID}'
```

The packages use standard SSIS constructs (Flat File Source, Derived Column,
Lookup, Conditional Split, OLE DB Destination, Execute SQL Task, ForEach Loop)
and precedence constraints, so they deploy to the SSIS Catalog unchanged.

## SSIS package catalog

| Package | Executables / components | Transforms | Error path |
| --- | --- | --- | --- |
| `LoadStores.dtsx` | Flat File Source (fixed-width) → Derived Column → Lookup `dw.dim_store` → Conditional Split → OLE DB `stg.stores_raw` | `TRIM`/`UPPER`, safe `(DT_DATE)` parse, `is_valid` | Source length overflow, derived cast failure and conditional rejects → `audit.failed_rows` |
| `LoadSalesCsv.dtsx` | ForEach File (`sales_*.csv`) wrapping Flat File Source → Derived Column → Lookup `dim_product`, `dim_store` → Conditional Split → OLE DB `stg.sales_raw` | `gross_amount`, `discount_amount`, `net_amount`, `date_key`; SKU range and price guards | Non-numeric qty (derived), out-of-range SKU / negative price (split) → `audit.failed_rows` |
| `LoadProductsRest.dtsx` | Paged JSON source + changes feed (HTTP connection manager, on-disk snapshots) → Derived Column → OLE DB `stg.products_raw` | `row_hash` (SHA-256 over attributes), `effective_date` | HTTP/JSON errors → `audit.failed_rows` |
| `LoadDimensions.dtsx` | Execute SQL Task → Execute SQL Task (precedence constraint) | `sp_load_dim_store` (SCD1 MERGE), `sp_load_dim_product_scd2` (expire-and-insert) | proc error fails the package (non-zero exit) |
| `LoadFactSales.dtsx` | Execute SQL Tasks in sequence | `sp_load_fact_sales_incremental`, `sp_build_inventory_snapshot`, `sp_record_row_counts`, `sp_record_checksums` | proc error fails the package |

## Data quality & auditing

`sql/checks/dq_assertions.sql` defines named assertions; `dq.sp_run_assertions`
persists each to `dq.assertion_result` and the Airflow `run_dq_assertions` task
raises `AirflowFailException` on any hard failure.

| Assertion | Protects |
| --- | --- |
| `no_orphan_product_keys` | every `fact_sales.product_sk` exists in `dim_product` |
| `no_orphan_store_keys` | every `fact_sales.store_sk` exists in `dim_store` |
| `no_duplicate_txn_id` | transaction idempotency |
| `net_amount_consistency` | `net_amount = gross_amount − discount_amount` (±0.01) |
| `fact_dates_in_dim_date` | every loaded `date_key` is in `dim_date` |
| `one_current_row_per_sku` | exactly one SCD2 current version per SKU |
| `rejected_row_rate` | rejected/read below the 5% threshold |

Audit tables: `audit.etl_batch` (per-package status, rows read/inserted/updated/
rejected, duration), `audit.row_count_check`, `audit.checksum_check`
(`SUM` and `CHECKSUM_AGG` parity on `qty` and `net_amount`), and
`audit.failed_rows` (component, error code, error column, raw row, description).

## Results

All figures below were produced by this build and are written to files under
`results/` (`metrics.md`, `benchmarks.md`, `load_health.json`, `etl_run.json`).
This run used batch `20240603000000`.

**Warehouse (from `results/metrics.md`)**

| Metric | Value |
| --- | --- |
| `fact_sales` rows | 717,120 |
| distinct product versions referenced by facts | 5,119 |
| distinct stores / days in facts | 200 / 90 |
| `dim_product` business SKUs | 5,000 |
| `dim_store` rows | 200 |
| SCD2 version rows / products with >1 version | 5,120 / 120 |
| rejected rows / rate | 2,883 / 0.3975% |
| checksum matches | 4 / 4 |
| DQ assertions passed | 7 / 7 |
| stockout rate | 6.19% |
| `dim_date` rows (2019–2027) | 3,287 |

**Load performance (from `results/benchmarks.md`)**

| Package | Duration (ms) | Rows read | Rows/sec |
| --- | ---: | ---: | ---: |
| LoadStores | 445 | 203 | 456.2 |
| LoadSalesCsv | 499,496 | 720,000 | 1,441.5 |
| LoadProductsRest | 2,281 | 5,120 | 2,244.6 |
| LoadDimensions | 5,676 | 0 | — |
| LoadFactSales | 31,806 | 0 | — |

| Operation | Wall clock |
| --- | ---: |
| Cold full load (all five packages) | 539.713 s |
| Warm incremental `LoadFactSales` | 10.343 s (0 rows re-inserted) |
| Fact insert, indexes ON | 10,782 ms (66,510.9 rows/sec) |
| Fact insert, indexes OFF (heap) | 2,317 ms (309,503.7 rows/sec) |

**DAX measures** — 14 measures verified against real data by
`tests/test_dax_parity.py` across four filter contexts (all-time, single month,
single region, YoY window). All-time values (from `results/metrics.md`):

| Measure | All-time value |
| --- | ---: |
| Net Sales | 1,692,895,443.6335 |
| Gross Sales | 1,798,934,075.0300 |
| Discount % | 5.89% |
| Units Sold | 3,946,371 |
| Avg Order Value | 2,360.69 |
| Net Sales LY | n/a (no prior-year data) |
| Net Sales YoY % | n/a (no prior-year data) |
| Net Sales MTD | 55,930,336.5140 |
| Stockout Days | 90 |
| Stockout Rate % | 6.19% |
| Lost Sales Estimate | 18,864,215.4730 |
| Active SKU Count | 5,000 |
| Rejected Row Rate % | 0.3979% |
| Load Success Rate % | 100% |

**End-to-end** — `bash airflow/airflow_local.sh 2024-06-03` finished with all 10
tasks success and 7/7 data-quality gates passing (`results/load_health.json`);
the orchestrated cold package runtime is the 539.713 s above.

**Test suite** — `ruff check .` clean; `pytest -q` → **43 passed in 107.53 s**
(unit + integration across generator, schema, runtime, SCD2, idempotency,
failed-row redirection, DAG integrity, DQ gates and DAX parity; runtime varies
with container load on the Apple-silicon SQL Server emulation).

## Project layout

```
docker-compose.yml      SQL Server 2022 (port 11433) with a sqlcmd healthcheck
Makefile                up / seed / db-init / etl / dq / test / lint / clean
data/generator/         deterministic extracts (fixed-width, CSV, REST feed)
data/landing/           generated extracts (gitignored; `make seed`)
sql/ddl/                database, staging, dimensions, facts, audit, views
sql/procs/              MERGE / SCD2 / fact / inventory / audit procedures
sql/checks/             dq_assertions.sql, measure_parity.sql
ssis/packages/          five real .dtsx packages
ssis_runtime/           dtexec-compatible parser, components, engine, CLI
airflow/dags/           retail_mart_etl DAG
airflow/airflow_local.sh  local Airflow (LocalExecutor + SQLite) end-to-end
powerbi/                model.bim, measures.tmdl, report/, dax_parity/
scripts/                wait/seed-apply/run-etl/dq/benchmark/export tools
tests/                  unit + integration suite
results/                metrics, benchmarks, load_health, etl_run (real output)
docs/                   RUNBOOK.md, DATA_DICTIONARY.md
```

## Limitations & next steps

- The PowerShell/`dtexec` path is documented but not executed here; on Linux/CI
  the bundled runtime executes the same package XML.
- The DAG uses a local Airflow (LocalExecutor + SQLite) for development; a
  production deployment would use Postgres/Celery and deploy the packages to the
  SSIS Catalog (`catalog.deploy_project`) with a Windows worker pool.
- Power BI content is provided as model artifacts (`model.bim`/TMSL, TMDL, layout
  JSON) rather than a `.pbix`; publishing needs a Power BI gateway/workspace.
- The REST source falls back to on-disk JSON snapshots so CI runs without the
  FastAPI server (`data/generator/product_api.py` exposes the live endpoints).
