/* 06_build_inventory_snapshot.sql - derived daily on-hand / stockout snapshot.

   On-hand = a per (date, product, store) safety stock minus units sold that
   day; anything at or below zero is a stockout.  The safety stock varies 1..4
   so the snapshot produces a realistic non-zero stockout rate.
   Idempotent: the loaded date range is cleared before re-inserting. */
CREATE OR ALTER PROCEDURE dw.sp_build_inventory_snapshot
    @batch_id BIGINT
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @min_date INT, @max_date INT;
    SELECT @min_date = MIN(date_key), @max_date = MAX(date_key)
    FROM dw.fact_sales WHERE batch_id = @batch_id;

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
            date_key, product_sk, store_sk, SUM(qty) AS sold,
            9 + ((product_sk * 7 + store_sk * 3 + date_key) % 5) AS base_stock
        FROM dw.fact_sales
        WHERE date_key BETWEEN @min_date AND @max_date
        GROUP BY date_key, product_sk, store_sk
    ) AS agg;

    SELECT CAST(@@ROWCOUNT AS BIGINT) AS rows_inserted;
END
GO
