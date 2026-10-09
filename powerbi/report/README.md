# RetailMart Power BI report

Open `powerbi/model.bim` with **Tabular Editor** (or as a Power BI Desktop
`model.bim` source), point the `Sql.Database("localhost,11433", "RetailMart")`
partition sources at your SQL Server, then import `powerbi/measures.tmdl` and use
`powerbi/report/layout.json` as the page blueprint.

The report has three pages.

## Page 1 — Sales Trends
- Net Sales by month with **Net Sales YoY %** line (time intelligence over
  `dim_date`, which is marked as the date table).
- Top 10 products by **Net Sales**.
- **Net Sales** by region (map / bar).
- Channel mix donut (`Store` / `Online` / `App`).
- **Avg Order Value** card.

## Page 2 — Stockouts & Inventory
- **Stockout Rate %** by product category.
- **Lost Sales Estimate** card.
- Worst 20 store/SKU pairs by **Stockout Days**.
- **Stockout Days** card.

## Page 3 — Load Health
- Package durations (ms) from `audit_load_health`.
- Rows read vs inserted vs rejected per package.
- Checksum match matrix (`audit.checksum_check`).
- Assertion / load success rate gauge (**Load Success Rate %**).

All measures are defined in `powerbi/measures.tmdl` and verified without Power BI
Desktop by `tests/test_dax_parity.py`, which compares the SQL equivalents in
`sql/checks/measure_parity.sql` against a Python reimplementation of the DAX
semantics over the same filter contexts.
