/* 01_batch_control.sql - start/end ETL batch bookkeeping. */
CREATE OR ALTER PROCEDURE audit.sp_start_batch
    @batch_id     BIGINT,
    @package_name VARCHAR(200)
AS
BEGIN
    SET NOCOUNT ON;
    MERGE audit.etl_batch AS t
    USING (SELECT @batch_id AS batch_id, @package_name AS package_name) AS s
        ON t.batch_id = s.batch_id AND t.package_name = s.package_name
    WHEN MATCHED THEN
        UPDATE SET started_at = SYSUTCDATETIME(), ended_at = NULL, status = 'RUNNING',
                   rows_read = 0, rows_inserted = 0, rows_updated = 0, rows_rejected = 0,
                   duration_ms = NULL
    WHEN NOT MATCHED THEN
        INSERT (batch_id, package_name, started_at, status)
        VALUES (@batch_id, @package_name, SYSUTCDATETIME(), 'RUNNING');
END
GO

CREATE OR ALTER PROCEDURE audit.sp_end_batch
    @batch_id      BIGINT,
    @package_name  VARCHAR(200),
    @status        VARCHAR(20),
    @rows_read     BIGINT = 0,
    @rows_inserted BIGINT = 0,
    @rows_updated  BIGINT = 0,
    @rows_rejected BIGINT = 0
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE audit.etl_batch
    SET ended_at = SYSUTCDATETIME(),
        status = @status,
        rows_read = @rows_read,
        rows_inserted = @rows_inserted,
        rows_updated = @rows_updated,
        rows_rejected = @rows_rejected,
        duration_ms = DATEDIFF_BIG(millisecond, started_at, SYSUTCDATETIME())
    WHERE batch_id = @batch_id AND package_name = @package_name;
END
GO
