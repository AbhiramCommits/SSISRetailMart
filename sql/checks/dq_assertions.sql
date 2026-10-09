/* dq_assertions.sql - named data-quality assertions.

   Each ``dq.v_*`` view exposes (assertion_name, observed_value, threshold) and
   is a hard-fail when observed_value > threshold.  ``dq.sp_run_assertions``
   persists one row per assertion into dq.assertion_result for a batch. */

CREATE OR ALTER VIEW dq.v_no_orphan_product_keys AS
SELECT 'no_orphan_product_keys' AS assertion_name,
       CAST(COUNT_BIG(*) AS DECIMAL(38,4)) AS observed_value,
       CAST(0 AS DECIMAL(38,4)) AS threshold
FROM dw.fact_sales f
WHERE NOT EXISTS (SELECT 1 FROM dw.dim_product d WHERE d.product_sk = f.product_sk);
GO

CREATE OR ALTER VIEW dq.v_no_orphan_store_keys AS
SELECT 'no_orphan_store_keys' AS assertion_name,
       CAST(COUNT_BIG(*) AS DECIMAL(38,4)) AS observed_value,
       CAST(0 AS DECIMAL(38,4)) AS threshold
FROM dw.fact_sales f
WHERE NOT EXISTS (SELECT 1 FROM dw.dim_store d WHERE d.store_sk = f.store_sk);
GO

CREATE OR ALTER VIEW dq.v_no_duplicate_txn_id AS
SELECT 'no_duplicate_txn_id' AS assertion_name,
       CAST(COUNT_BIG(*) AS DECIMAL(38,4)) AS observed_value,
       CAST(0 AS DECIMAL(38,4)) AS threshold
FROM (SELECT txn_id FROM dw.fact_sales GROUP BY txn_id HAVING COUNT_BIG(*) > 1) x;
GO

CREATE OR ALTER VIEW dq.v_net_amount_consistency AS
SELECT 'net_amount_consistency' AS assertion_name,
       CAST(COUNT_BIG(*) AS DECIMAL(38,4)) AS observed_value,
       CAST(0 AS DECIMAL(38,4)) AS threshold
FROM dw.fact_sales
WHERE ABS(net_amount - (gross_amount - discount_amount)) > 0.01;
GO

CREATE OR ALTER VIEW dq.v_fact_dates_in_dim_date AS
SELECT 'fact_dates_in_dim_date' AS assertion_name,
       CAST(COUNT_BIG(*) AS DECIMAL(38,4)) AS observed_value,
       CAST(0 AS DECIMAL(38,4)) AS threshold
FROM dw.fact_sales f
WHERE NOT EXISTS (SELECT 1 FROM dw.dim_date d WHERE d.date_key = f.date_key);
GO

CREATE OR ALTER VIEW dq.v_one_current_row_per_sku AS
SELECT 'one_current_row_per_sku' AS assertion_name,
       CAST(COUNT_BIG(*) AS DECIMAL(38,4)) AS observed_value,
       CAST(0 AS DECIMAL(38,4)) AS threshold
FROM (SELECT sku FROM dw.dim_product WHERE is_current = 1 GROUP BY sku HAVING COUNT_BIG(*) > 1) x;
GO

CREATE OR ALTER PROCEDURE dq.sp_run_assertions
    @batch_id BIGINT = NULL,
    @rejected_rate_threshold DECIMAL(38,4) = 0.05
AS
BEGIN
    SET NOCOUNT ON;

    IF @batch_id IS NOT NULL
        DELETE FROM dq.assertion_result WHERE batch_id = @batch_id;

    INSERT INTO dq.assertion_result (assertion_name, status, observed_value, threshold, batch_id)
    SELECT assertion_name,
           CASE WHEN observed_value <= threshold THEN 'PASS' ELSE 'FAIL' END,
           observed_value, threshold, @batch_id
    FROM
    (
        SELECT assertion_name, observed_value, threshold FROM dq.v_no_orphan_product_keys
        UNION ALL SELECT assertion_name, observed_value, threshold FROM dq.v_no_orphan_store_keys
        UNION ALL SELECT assertion_name, observed_value, threshold FROM dq.v_no_duplicate_txn_id
        UNION ALL SELECT assertion_name, observed_value, threshold FROM dq.v_net_amount_consistency
        UNION ALL SELECT assertion_name, observed_value, threshold FROM dq.v_fact_dates_in_dim_date
        UNION ALL SELECT assertion_name, observed_value, threshold FROM dq.v_one_current_row_per_sku
    ) AS a;

    DECLARE @rows_read BIGINT = 0, @rows_rejected BIGINT = 0;
    SELECT @rows_read = ISNULL(SUM(rows_read), 0), @rows_rejected = ISNULL(SUM(rows_rejected), 0)
    FROM audit.etl_batch WHERE batch_id = @batch_id;

    DECLARE @rate DECIMAL(38,4) = CASE WHEN @rows_read = 0 THEN 0
                                       ELSE CAST(@rows_rejected AS DECIMAL(38,4)) / @rows_read END;

    INSERT INTO dq.assertion_result (assertion_name, status, observed_value, threshold, batch_id)
    SELECT 'rejected_row_rate',
           CASE WHEN @rate <= @rejected_rate_threshold THEN 'PASS' ELSE 'FAIL' END,
           @rate, @rejected_rate_threshold, @batch_id;

    SELECT assertion_name, status, observed_value, threshold
    FROM dq.assertion_result
    WHERE batch_id = @batch_id OR (@batch_id IS NULL AND batch_id IS NULL)
    ORDER BY assertion_name;
END
GO
