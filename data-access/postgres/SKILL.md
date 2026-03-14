---
name: query-postgres
description: Connect to a PostgreSQL database to inspect its schema (tables, columns, indexes, foreign keys, views) and execute read-only SQL queries. Use when the user needs to explore or retrieve data from a PostgreSQL database.
allowed-tools: Bash(python3 *), Bash(pip install *), Bash(pip3 install *)
---

# PostgreSQL Database Access (Read-Only)

Inspect schemas and run read-only queries against a PostgreSQL database using the bundled helper script.

## Prerequisites

Before first use, ensure the `psycopg2-binary` Python package is installed:

```bash
pip install psycopg2-binary
```

If the import fails when running the script, install the package and retry.

## Helper Script Location

The helper script is located at:

```
${CLAUDE_SKILL_DIR}/scripts/query_postgres.py
```

## Connection Parameters

The script accepts connection details via command-line arguments **or** standard PostgreSQL environment variables. Arguments take precedence over environment variables.

| Argument                | Env Variable  | Default     | Description         |
|-------------------------|---------------|-------------|---------------------|
| `--host`                | `PGHOST`      | `localhost` | Database host       |
| `--port`                | `PGPORT`      | `5432`      | Database port       |
| `--database`            | `PGDATABASE`  | `postgres`  | Database name       |
| `--user`                | `PGUSER`      | `postgres`  | Username            |
| `--password`            | `PGPASSWORD`  | *(empty)*   | Password            |
| `--connection-string`   | `DATABASE_URL` | *(none)*   | Full connection URI (overrides individual params) |

**Ask the user for connection details before running the script.** Never guess or assume credentials.

## Usage

### Inspect Schema

List all tables and views in the database:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_postgres.py --host <host> --database <db> --user <user> --password <pass> schema
```

Inspect a specific table's columns, indexes, and foreign keys:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_postgres.py --host <host> --database <db> --user <user> --password <pass> schema --table <table_name>
```

Optionally filter by schema:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_postgres.py --host <host> --database <db> --user <user> --password <pass> schema --schema <schema_name>
```

List all available databases on the server:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_postgres.py --host <host> --user <user> --password <pass> schema --list-databases
```

### Execute a Query

Run a read-only SQL query:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_postgres.py --host <host> --database <db> --user <user> --password <pass> query "SELECT * FROM users LIMIT 10"
```

Output as JSON instead of a table:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_postgres.py --host <host> --database <db> --user <user> --password <pass> query --format json "SELECT * FROM users LIMIT 10"
```

## Safety

- The script sets `SET default_transaction_read_only = true` on every connection. Any `INSERT`, `UPDATE`, `DELETE`, `DROP`, or `CREATE` statement will be rejected by PostgreSQL.
- Results are limited to **1000 rows** by default. Use `--limit <N>` to change this.

## Guidelines

1. **Always ask the user for connection details** before attempting to connect. Do not hardcode or assume credentials.
2. **Start with schema inspection** to understand the database structure before writing queries.
3. **Use `--limit`** to avoid returning excessively large result sets.
4. **Present results clearly** — format output as markdown tables when displaying to the user.
5. If the user provides a connection string, use `--connection-string` instead of individual parameters.
