"""Static integrity checks for the Airflow DAG (no scheduler required)."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAGS_DIR = ROOT / "airflow" / "dags"

os.environ["AIRFLOW_HOME"] = str(ROOT / "airflow")
os.environ["AIRFLOW__CORE__LOAD_EXAMPLES"] = "False"
os.environ["AIRFLOW__CORE__DAGS_FOLDER"] = str(DAGS_DIR)
os.environ["AIRFLOW__CORE__XCOM_BACKEND"] = "airflow.models.xcom.BaseXCom"
os.environ["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"] = (
    f"sqlite:///{ROOT / 'airflow' / 'airflow.db'}"
)
os.environ["AIRFLOW__WEBSERVER__SECRET_KEY"] = "retailmart-test"

from airflow.models.dagbag import DagBag  # noqa: E402

EXPECTED_TASKS = {
    "start_batch",
    "load_stores",
    "load_sales_csv",
    "load_products_rest",
    "load_dimensions",
    "load_fact_sales",
    "build_inventory_snapshot",
    "run_dq_assertions",
    "publish_load_health",
    "end_batch",
}


_BAG: DagBag | None = None


def _bag() -> DagBag:
    global _BAG
    if _BAG is None:
        _BAG = DagBag(dag_folder=str(DAGS_DIR), include_examples=False)
    return _BAG


def _dag():
    bag = _bag()
    assert bag.import_errors == {}, bag.import_errors
    assert "retail_mart_etl" in bag.dags
    return bag.dags["retail_mart_etl"]


def test_dag_imports_without_errors():
    assert _bag().import_errors == {}


def test_exact_task_set_and_count():
    dag = _dag()
    assert {t.task_id for t in dag.tasks} == EXPECTED_TASKS
    assert len(dag.tasks) == 10


def test_dependencies():
    dag = _dag()
    assert dag.get_task("start_batch").downstream_task_ids == {
        "load_stores",
        "load_sales_csv",
        "load_products_rest",
    }
    assert dag.get_task("load_dimensions").upstream_task_ids == {
        "load_stores",
        "load_sales_csv",
        "load_products_rest",
    }
    assert dag.get_task("load_fact_sales").upstream_task_ids == {"load_dimensions"}
    assert dag.get_task("build_inventory_snapshot").upstream_task_ids == {"load_fact_sales"}
    assert dag.get_task("run_dq_assertions").upstream_task_ids == {"build_inventory_snapshot"}
    assert dag.get_task("publish_load_health").upstream_task_ids == {"run_dq_assertions"}
    assert dag.get_task("end_batch").upstream_task_ids == {"publish_load_health"}


def test_end_batch_is_all_done_cleanup():
    dag = _dag()
    assert dag.get_task("end_batch").trigger_rule == "all_done"


def test_schedule_and_retries():
    dag = _dag()
    assert dag.schedule_interval == "0 2 * * *"
    assert dag.catchup is False
    assert dag.max_active_runs == 1
    for task_id in EXPECTED_TASKS:
        task = dag.get_task(task_id)
        assert task.retries == 2
        assert task.retry_delay == timedelta(minutes=1)


def test_no_cycles():
    dag = _dag()
    order = [t.task_id for t in dag.topological_sort()]
    assert len(order) == len(EXPECTED_TASKS)
    assert order[0] == "start_batch"
    assert order[-1] == "end_batch"
