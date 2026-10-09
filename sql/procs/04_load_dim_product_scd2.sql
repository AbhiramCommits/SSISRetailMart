/* 04_load_dim_product_scd2.sql - expire-and-insert SCD Type 2 using row_hash. */
CREATE OR ALTER PROCEDURE dw.sp_load_dim_product_scd2
    @batch_id BIGINT
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE
        @ins BIGINT = 0,
        @upd BIGINT = 0,
        @sku VARCHAR(50),
        @name VARCHAR(200),
        @cat VARCHAR(100),
        @sub VARCHAR(100),
        @brand VARCHAR(100),
        @price DECIMAL(18,4),
        @active BIT,
        @eff DATE,
        @hash CHAR(64);

    DECLARE staged CURSOR LOCAL FAST_FORWARD FOR
        SELECT
            sku, name, category, subcategory, brand,
            TRY_CAST(list_price AS DECIMAL(18,4)),
            CASE WHEN is_active IN ('1', 'true', 'True', 'TRUE') THEN 1 ELSE 0 END,
            ISNULL(effective_date, CAST('2024-01-01' AS DATE)),
            ISNULL(row_hash, REPLICATE('0', 64))
        FROM stg.products_raw
        WHERE batch_id = @batch_id AND sku IS NOT NULL
        ORDER BY effective_date, row_num;

    OPEN staged;
    FETCH NEXT FROM staged INTO @sku, @name, @cat, @sub, @brand, @price, @active, @eff, @hash;

    WHILE @@FETCH_STATUS = 0
    BEGIN
        DECLARE @cur_sk INT, @cur_hash CHAR(64);
        SELECT @cur_sk = product_sk, @cur_hash = row_hash
        FROM dw.dim_product
        WHERE sku = @sku AND is_current = 1;

        IF @cur_sk IS NULL
        BEGIN
            INSERT INTO dw.dim_product
                (sku, name, category, subcategory, brand, list_price, is_active,
                 valid_from, valid_to, is_current, row_hash)
            VALUES
                (@sku, @name, @cat, @sub, @brand, @price, @active,
                 @eff, NULL, 1, @hash);
            SET @ins = @ins + 1;
        END
        ELSE IF ISNULL(@cur_hash, REPLICATE('0', 64)) <> @hash
        BEGIN
            UPDATE dw.dim_product
            SET is_current = 0,
                valid_to = CASE WHEN DATEADD(DAY, -1, @eff) < valid_from
                                THEN valid_from ELSE DATEADD(DAY, -1, @eff) END
            WHERE product_sk = @cur_sk;

            INSERT INTO dw.dim_product
                (sku, name, category, subcategory, brand, list_price, is_active,
                 valid_from, valid_to, is_current, row_hash)
            VALUES
                (@sku, @name, @cat, @sub, @brand, @price, @active,
                 @eff, NULL, 1, @hash);
            SET @ins = @ins + 1;
            SET @upd = @upd + 1;
        END

        FETCH NEXT FROM staged INTO @sku, @name, @cat, @sub, @brand, @price, @active, @eff, @hash;
    END

    CLOSE staged;
    DEALLOCATE staged;

    SELECT @ins AS rows_inserted, @upd AS rows_updated;
END
GO
