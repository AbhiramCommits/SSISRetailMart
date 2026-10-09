/* 02_populate_dim_date.sql - fill dw.dim_date 2019-01-01 .. 2027-12-31. */
CREATE OR ALTER PROCEDURE dw.sp_populate_dim_date
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (SELECT 1 FROM dw.dim_date)
        RETURN;

    ;WITH dates AS
    (
        SELECT CAST('2019-01-01' AS DATE) AS dt
        UNION ALL
        SELECT DATEADD(DAY, 1, dt)
        FROM dates
        WHERE dt < '2027-12-31'
    )
    INSERT INTO dw.dim_date
    (
        date_key, full_date, year, quarter, month, month_name, day_of_month,
        day_of_week, day_name, week_of_year, fiscal_year, fiscal_period,
        is_weekend, is_holiday_us
    )
    SELECT
        YEAR(dt) * 10000 + MONTH(dt) * 100 + DAY(dt) AS date_key,
        dt,
        YEAR(dt),
        DATEPART(QUARTER, dt),
        MONTH(dt),
        DATENAME(MONTH, dt),
        DAY(dt),
        DATEPART(WEEKDAY, dt),
        DATENAME(WEEKDAY, dt),
        DATEPART(ISO_WEEK, dt),
        YEAR(dt),
        MONTH(dt),
        CASE WHEN DATEPART(WEEKDAY, dt) IN (1, 7) THEN 1 ELSE 0 END,
        CASE WHEN (MONTH(dt) = 1 AND DAY(dt) = 1)
               OR (MONTH(dt) = 6 AND DAY(dt) = 19)
               OR (MONTH(dt) = 7 AND DAY(dt) = 4)
               OR (MONTH(dt) = 11 AND DAY(dt) = 11)
               OR (MONTH(dt) = 12 AND DAY(dt) = 25)
             THEN 1 ELSE 0 END
    FROM dates
    OPTION (MAXRECURSION 0);
END
GO
