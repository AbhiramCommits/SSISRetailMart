/* 03_load_dim_store.sql - SCD Type 1 MERGE of stores for one batch. */
CREATE OR ALTER PROCEDURE dw.sp_load_dim_store
    @batch_id BIGINT
AS
BEGIN
    SET NOCOUNT ON;

    MERGE dw.dim_store AS tgt
    USING
    (
        SELECT
            clean_store_code AS store_code,
            MAX(clean_store_name) AS store_name,
            MAX(clean_region) AS region,
            MAX(country) AS country,
            MAX(open_date) AS open_date
        FROM stg.stores_raw
        WHERE batch_id = @batch_id AND is_valid = 1 AND clean_store_code IS NOT NULL
        GROUP BY clean_store_code
    ) AS src
        ON tgt.store_code = src.store_code
    WHEN MATCHED AND
    (
        ISNULL(tgt.store_name, '') <> ISNULL(src.store_name, '')
        OR ISNULL(tgt.region, '') <> ISNULL(src.region, '')
        OR ISNULL(tgt.country, '') <> ISNULL(src.country, '')
        OR ISNULL(tgt.open_date, '1900-01-01') <> ISNULL(src.open_date, '1900-01-01')
    )
    THEN
        UPDATE SET store_name = src.store_name, region = src.region,
                   country = src.country, open_date = src.open_date,
                   updated_at = SYSUTCDATETIME()
    WHEN NOT MATCHED THEN
        INSERT (store_code, store_name, region, country, open_date, is_unknown)
        VALUES (src.store_code, src.store_name, src.region, src.country, src.open_date, 0);

    DECLARE @affected BIGINT = @@ROWCOUNT;
    SELECT @affected AS rows_affected;
END
GO
