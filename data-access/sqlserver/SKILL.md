---
name: query-sqlserver
description: Connect to a Microsoft SQL Server database to inspect its schema (tables, columns, indexes, foreign keys, views) and execute read-only SQL queries. Use when the user needs to explore or retrieve data from a SQL Server database.
allowed-tools: Bash(python3 *), Bash(pip install *), Bash(pip3 install *)
---

# SQL Server Database Access (Read-Only)

Inspect schemas and run read-only queries against a Microsoft SQL Server database using the bundled helper script.

## Prerequisites

Before first use, ensure the `pyodbc` Python package is installed:

```bash
pip install pyodbc
```

You also need an ODBC driver for SQL Server installed on the system. The script auto-detects installed drivers. Common drivers:
- **macOS**: `brew install microsoft/mssql-release/msodbcsql18`
- **Ubuntu/Debian**: Follow [Microsoft's Linux ODBC docs](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server)
- **Windows**: Usually pre-installed, or download from Microsoft.

## Helper Script Location

```
${CLAUDE_SKILL_DIR}/scripts/query_sqlserver.py
```

## Connection Parameters

| Argument                | Env Variable      | Default     | Description                     |
|-------------------------|-------------------|-------------|---------------------------------|
| `--host`                | `MSSQL_HOST`      | `localhost` | Database host                   |
| `--port`                | `MSSQL_PORT`      | `1433`      | Database port                   |
| `--database`            | `MSSQL_DATABASE`  | `master`    | Database name                   |
| `--user`                | `MSSQL_USER`      | *(none)*    | Username                        |
| `--password`            | `MSSQL_PASSWORD`  | *(none)*    | Password                        |
| `--driver`              | `MSSQL_DRIVER`    | *(auto)*    | ODBC driver name                |
| `--connection-string`   | `MSSQL_CONNSTR`   | *(none)*    | Full ODBC connection string     |
| `--trusted`             | *(flag)*          | `false`     | Use Windows/Kerberos trusted auth |

**Ask the user for connection details before running the script.** Never guess or assume credentials.

## Usage

### Inspect Schema

List all tables and views:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_sqlserver.py --host <host> --database <db> --user <user> --password <pass> schema
```

Inspect a specific table:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_sqlserver.py --host <host> --database <db> --user <user> --password <pass> schema --table <table_name>
```

Filter by schema:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_sqlserver.py --host <host> --database <db> --user <user> --password <pass> schema --schema dbo
```

List all databases on the server:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_sqlserver.py --host <host> --user <user> --password <pass> schema --list-databases
```

### Execute a Query

Run a read-only SQL query:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_sqlserver.py --host <host> --database <db> --user <user> --password <pass> query "SELECT TOP 10 * FROM users"
```

Output as JSON:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_sqlserver.py --host <host> --database <db> --user <user> --password <pass> query --format json "SELECT TOP 10 * FROM users"
```

## Safety

- The script executes `SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED` on every connection.
- The connection string includes `ApplicationIntent=ReadOnly` where supported.
- Results are limited to **1000 rows** by default. Use `--limit <N>` to change this.

## Guidelines

1. **Always ask the user for connection details** before attempting to connect.
2. **Start with schema inspection** to understand the database structure before writing queries.
3. **Use `--limit`** to avoid returning excessively large result sets.
4. **Use `TOP N`** in SQL Server queries instead of `LIMIT N` (SQL Server syntax).
5. **Present results clearly** — format output as markdown tables when displaying to the user.
