/* 03_dimensions.sql - conformed date/store/product dimensions. */
IF OBJECT_ID('dw.dim_date', 'U') IS NULL
CREATE TABLE dw.dim_date
(
    date_key      INT          NOT NULL,
    full_date     DATE         NOT NULL,
    year          INT          NOT NULL,
    quarter       INT          NOT NULL,
    month         INT          NOT NULL,
    month_name    VARCHAR(20)  NOT NULL,
    day_of_month  INT          NOT NULL,
    day_of_week   INT          NOT NULL,
    day_name      VARCHAR(20)  NOT NULL,
    week_of_year  INT          NOT NULL,
    fiscal_year   INT          NOT NULL,
    fiscal_period INT          NOT NULL,
    is_weekend    BIT          NOT NULL,
    is_holiday_us BIT          NOT NULL,
    CONSTRAINT PK_dim_date PRIMARY KEY CLUSTERED (date_key)
);
GO

IF OBJECT_ID('dw.dim_store', 'U') IS NULL
CREATE TABLE dw.dim_store
(
    store_sk   INT IDENTITY(1,1) NOT NULL,
    store_code VARCHAR(50)   NOT NULL,
    store_name VARCHAR(200)  NULL,
    region     VARCHAR(100)  NULL,
    country    VARCHAR(50)   NULL,
    open_date  DATE          NULL,
    is_unknown BIT           NOT NULL CONSTRAINT DF_dim_store_unknown DEFAULT (0),
    created_at DATETIME2(3)  NOT NULL CONSTRAINT DF_dim_store_created DEFAULT SYSUTCDATETIME(),
    updated_at DATETIME2(3)  NOT NULL CONSTRAINT DF_dim_store_updated DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_dim_store PRIMARY KEY NONCLUSTERED (store_sk),
    CONSTRAINT UQ_dim_store_code UNIQUE (store_code)
);
GO

IF OBJECT_ID('dw.dim_product', 'U') IS NULL
CREATE TABLE dw.dim_product
(
    product_sk   INT IDENTITY(1,1) NOT NULL,
    sku          VARCHAR(50)   NOT NULL,
    name         VARCHAR(200)  NULL,
    category     VARCHAR(100)  NULL,
    subcategory  VARCHAR(100)  NULL,
    brand        VARCHAR(100)  NULL,
    list_price   DECIMAL(18,4) NULL,
    is_active    BIT           NOT NULL CONSTRAINT DF_dim_product_active DEFAULT (1),
    valid_from   DATE          NOT NULL,
    valid_to     DATE          NULL,
    is_current   BIT           NOT NULL CONSTRAINT DF_dim_product_current DEFAULT (1),
    row_hash     CHAR(64)      NULL,
    inserted_at  DATETIME2(3)  NOT NULL CONSTRAINT DF_dim_product_inserted DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_dim_product PRIMARY KEY NONCLUSTERED (product_sk)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_dim_product_sku_current' AND object_id = OBJECT_ID('dw.dim_product'))
    CREATE INDEX IX_dim_product_sku_current ON dw.dim_product (sku, is_current) INCLUDE (valid_from, valid_to);
GO

/* Unknown members (surrogate -1) keep fact loads referentially complete. */
IF NOT EXISTS (SELECT 1 FROM dw.dim_store WHERE store_sk = -1)
BEGIN
    SET IDENTITY_INSERT dw.dim_store ON;
    INSERT INTO dw.dim_store (store_sk, store_code, store_name, region, country, open_date, is_unknown)
    VALUES (-1, 'UNKNOWN', 'Unknown Store', 'Unknown', 'Unknown', NULL, 1);
    SET IDENTITY_INSERT dw.dim_store OFF;
END
GO

IF NOT EXISTS (SELECT 1 FROM dw.dim_product WHERE product_sk = -1)
BEGIN
    SET IDENTITY_INSERT dw.dim_product ON;
    INSERT INTO dw.dim_product (product_sk, sku, name, category, subcategory, brand, list_price, is_active, valid_from, valid_to, is_current, row_hash)
    VALUES (-1, 'UNKNOWN', 'Unknown Product', 'Unknown', 'Unknown', 'Unknown', 0, 0, '1900-01-01', NULL, 1, REPLICATE('0', 64));
    SET IDENTITY_INSERT dw.dim_product OFF;
END
GO
