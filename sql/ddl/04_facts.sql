/* 04_facts.sql - grain: one row per sales transaction line. */
IF OBJECT_ID('dw.fact_sales', 'U') IS NULL
CREATE TABLE dw.fact_sales
(
    sale_sk         BIGINT IDENTITY(1,1) NOT NULL,
    date_key        INT              NOT NULL,
    product_sk      INT              NOT NULL,
    store_sk        INT              NOT NULL,
    txn_id          VARCHAR(50)      NOT NULL,
    qty             INT              NOT NULL,
    unit_price      DECIMAL(18,4)    NOT NULL,
    discount_pct    DECIMAL(9,4)     NOT NULL,
    gross_amount    DECIMAL(18,4)    NOT NULL,
    discount_amount DECIMAL(18,4)    NOT NULL,
    net_amount      DECIMAL(18,4)    NOT NULL,
    channel         VARCHAR(20)      NULL,
    batch_id        BIGINT           NOT NULL,
    load_ts         DATETIME2(3)     NOT NULL CONSTRAINT DF_fact_sales_load_ts DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_fact_sales PRIMARY KEY NONCLUSTERED (sale_sk)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'CIX_fact_sales_date_store' AND object_id = OBJECT_ID('dw.fact_sales'))
    CREATE CLUSTERED INDEX CIX_fact_sales_date_store ON dw.fact_sales (date_key, store_sk);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_fact_sales_product' AND object_id = OBJECT_ID('dw.fact_sales'))
    CREATE NONCLUSTERED INDEX IX_fact_sales_product ON dw.fact_sales (product_sk);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UQ_fact_sales_txn' AND object_id = OBJECT_ID('dw.fact_sales'))
    CREATE UNIQUE NONCLUSTERED INDEX UQ_fact_sales_txn ON dw.fact_sales (txn_id);
GO

/* Grain: one row per (business date, product, store) daily inventory position. */
IF OBJECT_ID('dw.fact_inventory_snapshot', 'U') IS NULL
CREATE TABLE dw.fact_inventory_snapshot
(
    snapshot_sk  BIGINT IDENTITY(1,1) NOT NULL,
    date_key     INT              NOT NULL,
    product_sk   INT              NOT NULL,
    store_sk     INT              NOT NULL,
    on_hand_qty  INT              NOT NULL,
    is_stockout  BIT              NOT NULL,
    batch_id     BIGINT           NOT NULL,
    load_ts      DATETIME2(3)     NOT NULL CONSTRAINT DF_fact_inv_load_ts DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_fact_inventory_snapshot PRIMARY KEY NONCLUSTERED (snapshot_sk)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'CIX_fact_inv_date' AND object_id = OBJECT_ID('dw.fact_inventory_snapshot'))
    CREATE CLUSTERED INDEX CIX_fact_inv_date ON dw.fact_inventory_snapshot (date_key, store_sk, product_sk);
GO
