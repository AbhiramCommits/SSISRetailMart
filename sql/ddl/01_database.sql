/* 01_database.sql - create the warehouse database and its schemas. */
IF DB_ID('RetailMart') IS NULL
BEGIN
    CREATE DATABASE RetailMart;
END
GO

USE RetailMart;
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'stg')
    EXEC('CREATE SCHEMA stg AUTHORIZATION dbo');
GO
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'dw')
    EXEC('CREATE SCHEMA dw AUTHORIZATION dbo');
GO
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'audit')
    EXEC('CREATE SCHEMA audit AUTHORIZATION dbo');
GO
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'dq')
    EXEC('CREATE SCHEMA dq AUTHORIZATION dbo');
GO
