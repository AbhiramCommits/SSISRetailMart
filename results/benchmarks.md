# RetailMart load benchmarks

_Batch `20240603000000`._

## Cold full load

Wall clock: **539.713 s**

| Package | Duration (ms) | Rows read | Rows/sec |
| --- | ---: | ---: | ---: |
| LoadStores | 445 | 203 | 456.2 |
| LoadSalesCsv | 499,496 | 720,000 | 1,441.5 |
| LoadProductsRest | 2,281 | 5,120 | 2,244.6 |
| LoadDimensions | 5,676 | 0 | 0.0 |
| LoadFactSales | 31,806 | 0 | 0.0 |

## Warm incremental fact load

Re-running `LoadFactSales` on an already-loaded batch: **10,343 ms** (0 rows inserted).

## Fact insert: indexes on vs off

| Indexes | Duration (ms) | Rows/sec | Rows |
| --- | ---: | ---: | ---: |
| ON | 10,782 | 66,510.9 | 717,120 |
| OFF | 2,317 | 309,503.7 | 717,120 |
