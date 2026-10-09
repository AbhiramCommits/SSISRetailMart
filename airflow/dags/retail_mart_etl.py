"""Airflow orchestration for the SSISRetailMart warehouse.

Task graph::

    start_batch
      >> [load_stores, load_sales_csv, load_products_rest]
      >> load_dimensions
      >> load_fact_sales
      >> build_inventory_snapshot
      >> run_dq_assertions
      >> publish_load_health
      >> end_batch            # trigger_rule=all_done, always records final status

Each extract/load task shells out to the dtexec-compatible runtime.  On a
Windows host the same task runs ``dtexec /F <package> /SET BatchId=...``; the
command is built by :func:`_dtexec_command` so the swap is a one-liner.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import airflow_tasks  # noqa: E402

# A numeric BatchId derived from the Airflow run id (ts_nodash is templated).
BATCH_ID = "{{ ts_nodash | replace('T', '') | int }}"
LANDING = "data/landing/"


def _dtexec_command(package: str) -> str:
    """The single place the runtime invocation is defined.

    Swap this for Windows SSIS with::

        f'dtexec /F "{PROJECT_ROOT}/ssis/packages/{package}.dtsx" '
        f'/SET "\\Package.Variables[User::BatchId].Properties[Value]";{BATCH_ID}'
    """
    return (
        f"cd {PROJECT_ROOT} && PYTHONPATH={PROJECT_ROOT} "
        f"{sys.executable} -m ssis_runtime.cli "
        f"/PACKAGE ssis/packages/{package}.dtsx "
        f"/SET BatchId={BATCH_ID} /SET LandingPath={LANDING}"
    )


default_args = {
    "owner": "retailmart",
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
    "depends_on_past": False,
}

with DAG(
    dag_id="retail_mart_etl",
    description="Run the SSIS retail warehouse packages and gate on data quality.",
    default_args=default_args,
    schedule="0 2 * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["retailmart", "ssis", "warehouse"],
) as dag:
    start_batch = PythonOperator(
        task_id="start_batch",
        python_callable=airflow_tasks.start_batch,
    )

    load_stores = BashOperator(
        task_id="load_stores",
        bash_command=_dtexec_command("LoadStores"),
    )
    load_sales_csv = BashOperator(
        task_id="load_sales_csv",
        bash_command=_dtexec_command("LoadSalesCsv"),
    )
    load_products_rest = BashOperator(
        task_id="load_products_rest",
        bash_command=_dtexec_command("LoadProductsRest"),
    )
    load_dimensions = BashOperator(
        task_id="load_dimensions",
        bash_command=_dtexec_command("LoadDimensions"),
    )
    load_fact_sales = BashOperator(
        task_id="load_fact_sales",
        bash_command=_dtexec_command("LoadFactSales"),
    )

    build_inventory_snapshot = PythonOperator(
        task_id="build_inventory_snapshot",
        python_callable=airflow_tasks.build_inventory_snapshot,
    )

    run_dq_assertions = PythonOperator(
        task_id="run_dq_assertions",
        python_callable=airflow_tasks.run_dq_assertions,
    )

    publish_load_health = PythonOperator(
        task_id="publish_load_health",
        python_callable=airflow_tasks.publish_load_health,
    )

    end_batch = PythonOperator(
        task_id="end_batch",
        python_callable=airflow_tasks.end_batch,
        trigger_rule=TriggerRule.ALL_DONE,
    )

    start_batch >> [load_stores, load_sales_csv, load_products_rest]
    [load_stores, load_sales_csv, load_products_rest] >> load_dimensions
    load_dimensions >> load_fact_sales >> build_inventory_snapshot
    build_inventory_snapshot >> run_dq_assertions >> publish_load_health >> end_batch
