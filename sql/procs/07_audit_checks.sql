/* 07_audit_checks.sql - row-count and checksum parity recorders. */
CREATE OR ALTER PROCEDURE audit.sp_record_row_counts
    @batch_id BIGINT
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO audit.row_count_check (batch_id, table_name, source_rows, target_rows, delta)
    SELECT @batch_id, 'stg.sales_raw -> dw.fact_sales',
           (SELECT COUNT_BIG(*) FROM stg.sales_raw WHERE batch_id = @batch_id AND is_valid = 1),
           (SELECT COUNT_BIG(*) FROM dw.fact_sales WHERE batch_id = @batch_id),
           (SELECT COUNT_BIG(*) FROM stg.sales_raw WHERE batch_id = @batch_id AND is_valid = 1)
             - (SELECT COUNT_BIG(*) FROM dw.fact_sales WHERE batch_id = @batch_id);

    INSERT INTO audit.row_count_check (batch_id, table_name, source_rows, target_rows, delta)
    SELECT @batch_id, 'stg.stores_raw -> dw.dim_store',
           (SELECT COUNT_BIG(*) FROM stg.stores_raw WHERE batch_id = @batch_id AND is_valid = 1),
           (SELECT COUNT_BIG(*) FROM dw.dim_store WHERE is_unknown = 0),
           (SELECT COUNT_BIG(*) FROM stg.stores_raw WHERE batch_id = @batch_id AND is_valid = 1)
             - (SELECT COUNT_BIG(*) FROM dw.dim_store WHERE is_unknown = 0);

    INSERT INTO audit.row_count_check (batch_id, table_name, source_rows, target_rows, delta)
    SELECT @batch_id, 'stg.products_raw -> dw.dim_product',
           (SELECT COUNT_BIG(*) FROM stg.products_raw WHERE batch_id = @batch_id),
           (SELECT COUNT_BIG(*) FROM dw.dim_product WHERE product_sk <> -1),
           (SELECT COUNT_BIG(*) FROM stg.products_raw WHERE batch_id = @batch_id)
             - (SELECT COUNT_BIG(*) FROM dw.dim_product WHERE product_sk <> -1);
END
GO

CREATE OR ALTER PROCEDURE audit.sp_record_checksums
    @batch_id BIGINT
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @src_qty_sum DECIMAL(38,4), @tgt_qty_sum DECIMAL(38,4),
            @src_net_sum DECIMAL(38,4), @tgt_net_sum DECIMAL(38,4),
            @src_qty_chk INT, @tgt_qty_chk INT,
            @src_net_chk INT, @tgt_net_chk INT;

    SELECT @src_qty_sum = SUM(qty), @src_net_sum = SUM(net_amount)
    FROM stg.sales_raw WHERE batch_id = @batch_id AND is_valid = 1;

    SELECT @tgt_qty_sum = SUM(qty), @tgt_net_sum = SUM(net_amount)
    FROM dw.fact_sales WHERE batch_id = @batch_id;

    SELECT @src_qty_chk = CHECKSUM_AGG(BINARY_CHECKSUM(qty)),
           @src_net_chk = CHECKSUM_AGG(BINARY_CHECKSUM(net_amount))
    FROM stg.sales_raw WHERE batch_id = @batch_id AND is_valid = 1;

    SELECT @tgt_qty_chk = CHECKSUM_AGG(BINARY_CHECKSUM(qty)),
           @tgt_net_chk = CHECKSUM_AGG(BINARY_CHECKSUM(net_amount))
    FROM dw.fact_sales WHERE batch_id = @batch_id;

    INSERT INTO audit.checksum_check
        (batch_id, table_name, column_name, source_checksum, target_checksum, matched)
    VALUES
        (@batch_id, 'dw.fact_sales', 'qty[SUM]', @src_qty_sum, @tgt_qty_sum,
         CASE WHEN @src_qty_sum = @tgt_qty_sum THEN 1 ELSE 0 END),
        (@batch_id, 'dw.fact_sales', 'qty[CHECKSUM_AGG]', @src_qty_chk, @tgt_qty_chk,
         CASE WHEN @src_qty_chk = @tgt_qty_chk THEN 1 ELSE 0 END),
        (@batch_id, 'dw.fact_sales', 'net_amount[SUM]', @src_net_sum, @tgt_net_sum,
         CASE WHEN @src_net_sum = @tgt_net_sum THEN 1 ELSE 0 END),
        (@batch_id, 'dw.fact_sales', 'net_amount[CHECKSUM_AGG]', @src_net_chk, @tgt_net_chk,
         CASE WHEN @src_net_chk = @tgt_net_chk THEN 1 ELSE 0 END);
END
GO
