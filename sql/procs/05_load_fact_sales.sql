/* 05_load_fact_sales.sql - load one batch into dw.fact_sales.

   * loads only rows for @batch_id that passed validation
   * substitutes the unknown member (-1) for unmatched dimension keys
   * picks the dim_product version valid on the sale date (SCD-aware)
   * idempotent: a txn_id already present is never re-inserted */
CREATE OR ALTER PROCEDURE dw.sp_load_fact_sales_incremental
    @batch_id BIGINT
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO dw.fact_sales
        (date_key, product_sk, store_sk, txn_id, qty, unit_price, discount_pct,
         gross_amount, discount_amount, net_amount, channel, batch_id)
    SELECT
        s.date_key,
        ISNULL(p.product_sk, -1) AS product_sk,
        ISNULL(st.store_sk, -1) AS store_sk,
        s.txn_id,
        s.qty,
        s.unit_price,
        s.discount_pct,
        s.gross_amount,
        s.discount_amount,
        s.net_amount,
        s.channel,
        s.batch_id
    FROM stg.sales_raw AS s
    OUTER APPLY
    (
        SELECT TOP (1) d.product_sk
        FROM dw.dim_product AS d
        WHERE d.sku = s.sku
          AND d.valid_from <= TRY_CAST(s.txn_ts_raw AS DATE)
          AND (d.valid_to IS NULL OR d.valid_to >= TRY_CAST(s.txn_ts_raw AS DATE))
        ORDER BY d.valid_from DESC
    ) AS p
    LEFT JOIN dw.dim_store AS st
        ON st.store_code = s.store_code
    WHERE s.batch_id = @batch_id
      AND s.is_valid = 1
      AND s.date_key IS NOT NULL
      AND s.qty IS NOT NULL
      AND TRY_CAST(s.txn_ts_raw AS DATE) IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM dw.fact_sales AS f WHERE f.txn_id = s.txn_id);

    SELECT CAST(@@ROWCOUNT AS BIGINT) AS rows_inserted;
END
GO
