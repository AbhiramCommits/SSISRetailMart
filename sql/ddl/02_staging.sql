/* 02_staging.sql - untyped landing tables. Source columns stay VARCHAR on
   purpose; the SSIS pipeline performs all typing and writes a small set of
   derived (typed) columns alongside the raw string for auditability. */
IF OBJECT_ID('stg.stores_raw', 'U') IS NULL
CREATE TABLE stg.stores_raw
(
    store_raw_id    BIGINT IDENTITY(1,1) NOT NULL,
    batch_id        BIGINT           NOT NULL,
    source_file     NVARCHAR(260)    NULL,
    row_num         INT              NULL,
    store_code      VARCHAR(50)      NULL,
    store_name      VARCHAR(200)     NULL,
    region          VARCHAR(100)     NULL,
    country         VARCHAR(50)      NULL,
    open_date_raw   VARCHAR(50)      NULL,
    clean_store_code VARCHAR(50)     NULL,
    clean_store_name VARCHAR(200)    NULL,
    clean_region    VARCHAR(100)     NULL,
    open_date       DATE             NULL,
    is_valid        BIT              NULL,
    load_ts         DATETIME2(3)     NOT NULL CONSTRAINT DF_stores_raw_load_ts DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_stores_raw PRIMARY KEY (store_raw_id)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_stores_raw_batch' AND object_id = OBJECT_ID('stg.stores_raw'))
    CREATE INDEX IX_stores_raw_batch ON stg.stores_raw (batch_id);
GO

IF OBJECT_ID('stg.sales_raw', 'U') IS NULL
CREATE TABLE stg.sales_raw
(
    sales_raw_id    BIGINT IDENTITY(1,1) NOT NULL,
    batch_id        BIGINT           NOT NULL,
    source_file     NVARCHAR(260)    NULL,
    row_num         INT              NULL,
    txn_id          VARCHAR(50)      NULL,
    txn_ts_raw      VARCHAR(50)      NULL,
    store_code      VARCHAR(50)      NULL,
    sku             VARCHAR(50)      NULL,
    qty_raw         VARCHAR(50)      NULL,
    unit_price_raw  VARCHAR(50)      NULL,
    discount_pct_raw VARCHAR(50)     NULL,
    channel         VARCHAR(50)      NULL,
    qty             INT              NULL,
    unit_price      DECIMAL(18,4)    NULL,
    discount_pct    DECIMAL(9,4)     NULL,
    date_key        INT              NULL,
    gross_amount    DECIMAL(18,4)    NULL,
    discount_amount DECIMAL(18,4)    NULL,
    net_amount      DECIMAL(18,4)    NULL,
    is_valid        BIT              NULL,
    load_ts         DATETIME2(3)     NOT NULL CONSTRAINT DF_sales_raw_load_ts DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_sales_raw PRIMARY KEY (sales_raw_id)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_sales_raw_batch' AND object_id = OBJECT_ID('stg.sales_raw'))
    CREATE INDEX IX_sales_raw_batch ON stg.sales_raw (batch_id);
GO

IF OBJECT_ID('stg.products_raw', 'U') IS NULL
CREATE TABLE stg.products_raw
(
    product_raw_id  BIGINT IDENTITY(1,1) NOT NULL,
    batch_id        BIGINT           NOT NULL,
    source_file     NVARCHAR(260)    NULL,
    row_num         INT              NULL,
    sku             VARCHAR(50)      NULL,
    name            VARCHAR(200)     NULL,
    category        VARCHAR(100)     NULL,
    subcategory     VARCHAR(100)     NULL,
    brand           VARCHAR(100)     NULL,
    list_price      VARCHAR(50)      NULL,
    is_active       VARCHAR(10)      NULL,
    effective_date  DATE             NULL,
    row_hash        CHAR(64)         NULL,
    load_ts         DATETIME2(3)     NOT NULL CONSTRAINT DF_products_raw_load_ts DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_products_raw PRIMARY KEY (product_raw_id)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_products_raw_batch' AND object_id = OBJECT_ID('stg.products_raw'))
    CREATE INDEX IX_products_raw_batch ON stg.products_raw (batch_id);
GO
