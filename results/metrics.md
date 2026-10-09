# RetailMart load metrics

_Generated 2026-10-09T16:07:42 from batch `20240603000000`._

## Warehouse

| Metric | Value |
| --- | --- |
| fact_sales rows | 717,120 |
| distinct SKUs (fact) | 5,000 |
| distinct stores (fact) | 200 |
| distinct days (fact) | 90 |
| dim_product rows | 5,000 |
| dim_store rows | 200 |
| SCD2 version rows | 5,120 |
| products with >1 version | 120 |
| rejected rows | 2,883 |
| rejected-row rate | 0.3975% |
| checksum matches | 4/4 |
| DQ assertions passed | 7/7 |
| end-to-end wall clock | 439 s |

## Packages

| Package | Status | Rows read | Inserted | Rejected | Duration (ms) | Rows/sec |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| LoadStores | SUCCESS | 203 | 200 | 3 | 338 | 600.6 |
| LoadSalesCsv | SUCCESS | 720,000 | 717,120 | 2,880 | 410,745 | 1,752.9 |
| LoadProductsRest | SUCCESS | 5,120 | 5,120 | 0 | 3,099 | 1,652.1 |
| LoadDimensions | SUCCESS | 0 | 5,320 | 0 | 3,992 | 0.0 |
| LoadFactSales | SUCCESS | 0 | 1,431,365 | 0 | 20,245 | 0.0 |

## Measures (all-time)

| Measure | Value |
| --- | --- |
| Net Sales | 1,692,895,443.6335 |
| Gross Sales | 1,798,934,075.0300 |
| Discount % | 0.0589 |
| Units Sold | 3,946,371.0000 |
| Avg Order Value | 2,360.6864 |
| Net Sales LY | n/a |
| Net Sales YoY % | n/a |
| Net Sales MTD | 55,930,336.5140 |
| Stockout Days | 90.0000 |
| Stockout Rate % | 0.0619 |
| Lost Sales Estimate | 18,874,531.7785 |
| Active SKU Count | 5,000.0000 |
| Rejected Row Rate % | 0.0040 |
| Load Success Rate % | 1.0000 |

## Failed rows

| Component | Error column | Rows |
| --- | --- | ---: |
| Conditional Split | - | 1,921 |
| Derived Column | qty | 960 |
| Stores Flat File Source | open_date_raw | 1 |
| Derived Column | open_date | 1 |
