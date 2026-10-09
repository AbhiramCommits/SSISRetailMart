/* measure_parity.sql - T-SQL equivalents of the DAX measures.

   dq.sp_measure_parity evaluates every DAX measure's SQL equivalent under one
   filter context (@year / @month / @region).  tests/test_dax_parity.py compares
   these values against a Python reimplementation of the DAX semantics. */
CREATE OR ALTER PROCEDURE dq.sp_measure_parity
    @year   INT = NULL,
    @month  INT = NULL,
    @region VARCHAR(100) = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF OBJECT_ID('tempdb..#f')   IS NOT NULL DROP TABLE #f;
    IF OBJECT_ID('tempdb..#inv') IS NOT NULL DROP TABLE #inv;
    IF OBJECT_ID('tempdb..#av')  IS NOT NULL DROP TABLE #av;

    SELECT s.date_key, s.product_sk, s.store_sk, s.txn_id, s.qty,
           s.gross_amount, s.discount_amount, s.net_amount,
           d.year, d.month, st.region
    INTO #f
    FROM dw.fact_sales s
    JOIN dw.dim_date d  ON d.date_key = s.date_key
    JOIN dw.dim_store st ON st.store_sk = s.store_sk
    WHERE (@year   IS NULL OR d.year = @year)
      AND (@month  IS NULL OR d.month = @month)
      AND (@region IS NULL OR st.region = @region);

    SELECT i.date_key, i.product_sk, i.is_stockout, d.year, d.month, st.region
    INTO #inv
    FROM dw.fact_inventory_snapshot i
    JOIN dw.dim_date d  ON d.date_key = i.date_key
    JOIN dw.dim_store st ON st.store_sk = i.store_sk
    WHERE (@year   IS NULL OR d.year = @year)
      AND (@month  IS NULL OR d.month = @month)
      AND (@region IS NULL OR st.region = @region);

    SELECT product_sk,
           CAST(ROUND(CAST(SUM(net_amount) AS DECIMAL(38,10)) / NULLIF(SUM(qty), 0), 6) AS DECIMAL(18,6)) AS avpu
    INTO #av
    FROM #f
    GROUP BY product_sk;

    DECLARE @max_key INT = (SELECT MAX(date_key) FROM #f);
    DECLARE @max_year INT = @max_key / 10000;
    DECLARE @max_month INT = (@max_key / 100) % 100;
    DECLARE @prev_year INT = ISNULL(@year, 1900) - 1;

    SELECT measure_name, CAST(measure_value AS DECIMAL(38,4)) AS measure_value
    FROM
    (
        SELECT 'Net Sales' AS measure_name,
               (SELECT SUM(net_amount) FROM #f) AS measure_value
        UNION ALL
        SELECT 'Gross Sales', (SELECT SUM(gross_amount) FROM #f)
        UNION ALL
        SELECT 'Units Sold', (SELECT SUM(CAST(qty AS DECIMAL(38,4))) FROM #f)
        UNION ALL
        SELECT 'Discount %', (SELECT CASE WHEN SUM(gross_amount) = 0 THEN NULL
                                         ELSE SUM(discount_amount) / SUM(gross_amount) END FROM #f)
        UNION ALL
        SELECT 'Avg Order Value', (SELECT CASE WHEN COUNT(DISTINCT txn_id) = 0 THEN NULL
                                              ELSE SUM(net_amount) / COUNT(DISTINCT txn_id) END FROM #f)
        UNION ALL
        SELECT 'Net Sales LY', (SELECT SUM(net_amount) FROM #f
                                WHERE year = @prev_year
                                  AND (@month IS NULL OR month = @month))
        UNION ALL
        SELECT 'Net Sales YoY %', (SELECT CASE WHEN SUM(CASE WHEN year = @prev_year AND (@month IS NULL OR month = @month)
                                                            THEN net_amount ELSE 0 END) = 0
                                               THEN NULL
                                               ELSE (SUM(net_amount) - SUM(CASE WHEN year = @prev_year AND (@month IS NULL OR month = @month)
                                                                               THEN net_amount ELSE 0 END))
                                                    / SUM(CASE WHEN year = @prev_year AND (@month IS NULL OR month = @month)
                                                              THEN net_amount ELSE 0 END)
                                          END FROM #f)
        UNION ALL
        SELECT 'Net Sales MTD', (SELECT SUM(net_amount) FROM #f
                                 WHERE year = @max_year AND month = @max_month)
        UNION ALL
        SELECT 'Stockout Days', (SELECT COUNT(DISTINCT date_key) FROM #inv WHERE is_stockout = 1)
        UNION ALL
        SELECT 'Stockout Rate %', (SELECT CASE WHEN COUNT(*) = 0 THEN NULL
                                              ELSE SUM(CAST(is_stockout AS DECIMAL(38,4))) / COUNT(*) END FROM #inv)
        UNION ALL
        SELECT 'Lost Sales Estimate', (SELECT SUM(ISNULL(a.avpu, 0))
                                       FROM #inv i LEFT JOIN #av a ON a.product_sk = i.product_sk
                                       WHERE i.is_stockout = 1)
        UNION ALL
        SELECT 'Active SKU Count', (SELECT COUNT(*) FROM dw.dim_product WHERE is_current = 1 AND product_sk <> -1)
        UNION ALL
        SELECT 'Rejected Row Rate %', (SELECT CASE WHEN SUM(rows_read) = 0 THEN NULL
                                                   ELSE SUM(CAST(rows_rejected AS DECIMAL(38,4))) / SUM(rows_read) END
                                       FROM audit.etl_batch)
        UNION ALL
        SELECT 'Load Success Rate %', (SELECT CASE WHEN COUNT(*) = 0 THEN NULL
                                                   ELSE SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) END
                                       FROM audit.etl_batch)
    ) AS m;
END
GO
