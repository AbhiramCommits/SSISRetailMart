/* 06_reporting_views.sql - stable read contracts for the Power BI model. */
CREATE OR ALTER VIEW dw.vw_sales_trend
AS
SELECT
    d.date_key,
    d.full_date,
    d.year,
    d.quarter,
    d.month,
    d.month_name,
    d.is_weekend,
    d.is_holiday_us,
    SUM(f.gross_amount)    AS gross_sales,
    SUM(f.discount_amount) AS discount_amount,
    SUM(f.net_amount)      AS net_sales,
    SUM(f.qty)             AS units_sold,
    COUNT_BIG(*)           AS order_lines,
    COUNT(DISTINCT f.txn_id) AS order_count
FROM dw.fact_sales f
JOIN dw.dim_date d ON d.date_key = f.date_key
GROUP BY d.date_key, d.full_date, d.year, d.quarter, d.month, d.month_name,
         d.is_weekend, d.is_holiday_us;
GO

CREATE OR ALTER VIEW dw.vw_stockouts
AS
SELECT
    i.date_key,
    d.full_date,
    d.year,
    d.month,
    p.product_sk,
    p.sku,
    p.category,
    p.subcategory,
    s.store_sk,
    s.store_code,
    s.region,
    i.on_hand_qty,
    i.is_stockout
FROM dw.fact_inventory_snapshot i
JOIN dw.dim_date d    ON d.date_key = i.date_key
JOIN dw.dim_product p ON p.product_sk = i.product_sk
JOIN dw.dim_store s   ON s.store_sk = i.store_sk;
GO

CREATE OR ALTER VIEW dw.vw_load_health
AS
SELECT
    b.batch_id,
    b.package_name,
    b.status,
    b.rows_read,
    b.rows_inserted,
    b.rows_updated,
    b.rows_rejected,
    b.duration_ms,
    b.started_at,
    b.ended_at
FROM audit.etl_batch b;
GO

CREATE OR ALTER VIEW dw.vw_load_health_summary
AS
SELECT
    b.batch_id,
    SUM(b.rows_read)     AS rows_read,
    SUM(b.rows_inserted) AS rows_inserted,
    SUM(b.rows_rejected) AS rows_rejected,
    SUM(b.duration_ms)   AS duration_ms,
    SUM(CASE WHEN b.status = 'SUCCESS' THEN 1 ELSE 0 END) AS packages_succeeded,
    COUNT(*)             AS packages_total,
    DATEDIFF(SECOND, MIN(b.started_at), MAX(b.ended_at)) AS wall_clock_seconds
FROM audit.etl_batch b
GROUP BY b.batch_id;
GO
