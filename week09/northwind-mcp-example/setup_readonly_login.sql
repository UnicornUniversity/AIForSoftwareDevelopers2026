-- Northwind MCP server: dedicated read-only SQL login.
-- Run this ONCE in SSMS (or sqlcmd) as a user with permission to create logins.
-- Change the password before running in any shared environment.

USE master;
GO

IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = 'northwind_ro')
BEGIN
    CREATE LOGIN northwind_ro WITH PASSWORD = 'ChangeMe!Local42',
        CHECK_POLICY = OFF,   -- local-dev convenience; enable in production
        CHECK_EXPIRATION = OFF;
END
GO

USE Northwind;
GO

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'northwind_ro')
BEGIN
    CREATE USER northwind_ro FOR LOGIN northwind_ro;
END
GO

ALTER ROLE db_datareader ADD MEMBER northwind_ro;
GO

-- Belt-and-braces: explicit denies on every mutating verb.
-- Do NOT add CONTROL here: it is a covering permission, and a DENY on a covering
-- permission overrides the SELECT granted by db_datareader (the login then cannot
-- read anything, not even to test that writes fail).
DENY INSERT, UPDATE, DELETE, EXECUTE, ALTER ON SCHEMA::dbo TO northwind_ro;
GO

-- Verify. As the read-only user:
--   SELECT COUNT(*) FROM Customers;    -- should work
--   UPDATE Customers SET CompanyName='x' WHERE CustomerID='ALFKI';  -- MUST fail
