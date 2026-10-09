/* 06_build_inventory_snapshot.sql - derived daily on-hand / stockout snapshot.

   On-hand = a per (date, product, store) safety stock minus units sold that
   day; anything at or below zero is a stockout.  The safety stock varies 9..13
   so the snapshot produces a realistic non-zero stockout rate.

   Rows are derived from the fact transactions staged in @batch_id (matched by
   txn_id) so the procedure is idempotent across re-runs of the same extract.
   The loaded date range is cleared before re-inserting. */
CREATE OR ALTER PROCEDURE dw.sp_build_inventory_snapshot
    @batch_id BIGINT
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @min_date INT, @max_date INT;
    SELECT @min_date = MIN(f.date_key), @max_date = MAX(f.date_key)
    FROM dw.fact_sales f
    WHERE EXISTS (SELECT 1 FROM stg.sales_raw s
                  WHERE s.batch_id = @batch_id AND s.is_valid = 1 AND s.txn_id = f.txn_id);

    IF @min_date IS NULL
    BEGIN
        SELECT CAST(0 AS BIGINT) AS rows_inserted;
        RETURN;
    END

    DELETE FROM dw.fact_inventory_snapshot
    WHERE date_key BETWEEN @min_date AND @max_date;

    INSERT INTO dw.fact_inventory_snapshot
        (date_key, product_sk, store_sk, on_hand_qty, is_stockout, batch_id)
    SELECT
        date_key, product_sk, store_sk,
        CASE WHEN base_stock - sold < 0 THEN 0 ELSE base_stock - sold END,
        CASE WHEN base_stock - sold <= 0 THEN 1 ELSE 0 END,
        @batch_id
    FROM
    (
        SELECT
            f.date_key, f.product_sk, f.store_sk, SUM(f.qty) AS sold,
            9 + ((f.product_sk * 7 + f.store_sk * 3 + f.date_key) % 5) AS base_stock
        FROM dw.fact_sales f
        WHERE f.date_key BETWEEN @min_date AND @max_date
          AND EXISTS (SELECT 1 FROM stg.sales_raw s
                      WHERE s.batch_id = @batch_id AND s.is_valid = 1 AND s.txn_id = f.txn_id)
        GROUP BY f.date_key, f.product_sk, f.store_sk
    ) AS agg;

    SELECT CAST(@@ROWCOUNT AS BIGINT) AS rows_inserted;
END
GO
