/* 05_audit.sql - ETL batch, row-count, checksum, failed-row and DQ tables. */
IF OBJECT_ID('audit.etl_batch', 'U') IS NULL
CREATE TABLE audit.etl_batch
(
    etl_batch_sk   BIGINT IDENTITY(1,1) NOT NULL,
    batch_id       BIGINT           NOT NULL,
    package_name   VARCHAR(200)     NOT NULL,
    started_at     DATETIME2(3)     NULL,
    ended_at       DATETIME2(3)     NULL,
    status         VARCHAR(20)      NULL,
    rows_read      BIGINT           NOT NULL CONSTRAINT DF_etl_batch_read DEFAULT (0),
    rows_inserted  BIGINT           NOT NULL CONSTRAINT DF_etl_batch_inserted DEFAULT (0),
    rows_updated   BIGINT           NOT NULL CONSTRAINT DF_etl_batch_updated DEFAULT (0),
    rows_rejected  BIGINT           NOT NULL CONSTRAINT DF_etl_batch_rejected DEFAULT (0),
    duration_ms    BIGINT           NULL,
    CONSTRAINT PK_etl_batch PRIMARY KEY (etl_batch_sk),
    CONSTRAINT UQ_etl_batch_batch_pkg UNIQUE (batch_id, package_name)
);
GO

IF OBJECT_ID('audit.row_count_check', 'U') IS NULL
CREATE TABLE audit.row_count_check
(
    check_sk    BIGINT IDENTITY(1,1) NOT NULL,
    batch_id    BIGINT       NOT NULL,
    table_name  VARCHAR(200) NOT NULL,
    source_rows BIGINT       NULL,
    target_rows BIGINT       NULL,
    delta       BIGINT       NULL,
    checked_at  DATETIME2(3) NOT NULL CONSTRAINT DF_row_count_checked DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_row_count_check PRIMARY KEY (check_sk)
);
GO

IF OBJECT_ID('audit.checksum_check', 'U') IS NULL
CREATE TABLE audit.checksum_check
(
    check_sk        BIGINT IDENTITY(1,1) NOT NULL,
    batch_id        BIGINT       NOT NULL,
    table_name      VARCHAR(200) NOT NULL,
    column_name     VARCHAR(200) NOT NULL,
    source_checksum DECIMAL(38,4) NULL,
    target_checksum DECIMAL(38,4) NULL,
    matched         BIT          NOT NULL,
    checked_at      DATETIME2(3) NOT NULL CONSTRAINT DF_checksum_checked DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_checksum_check PRIMARY KEY (check_sk)
);
GO

IF OBJECT_ID('audit.failed_rows', 'U') IS NULL
CREATE TABLE audit.failed_rows
(
    failed_row_sk     BIGINT IDENTITY(1,1) NOT NULL,
    batch_id          BIGINT        NOT NULL,
    package_name      VARCHAR(200)  NULL,
    component         VARCHAR(200)  NULL,
    error_code        INT           NULL,
    error_column      VARCHAR(200)  NULL,
    raw_row           NVARCHAR(4000) NULL,
    error_description NVARCHAR(1000) NULL,
    created_at        DATETIME2(3)  NOT NULL CONSTRAINT DF_failed_rows_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_failed_rows PRIMARY KEY (failed_row_sk)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_failed_rows_batch' AND object_id = OBJECT_ID('audit.failed_rows'))
    CREATE INDEX IX_failed_rows_batch ON audit.failed_rows (batch_id);
GO

IF OBJECT_ID('dq.assertion_result', 'U') IS NULL
CREATE TABLE dq.assertion_result
(
    assertion_id   BIGINT IDENTITY(1,1) NOT NULL,
    assertion_name VARCHAR(200)  NOT NULL,
    status         VARCHAR(10)   NOT NULL,
    observed_value DECIMAL(38,4) NULL,
    threshold      DECIMAL(38,4) NULL,
    batch_id       BIGINT        NULL,
    run_ts         DATETIME2(3)  NOT NULL CONSTRAINT DF_assertion_run_ts DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_assertion_result PRIMARY KEY (assertion_id)
);
GO
