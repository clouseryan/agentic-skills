#!/usr/bin/env python3
"""SQL Server read-only database access helper for Claude Code.

Supports schema inspection and read-only SQL query execution.
All connections use ApplicationIntent=ReadOnly and
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED.
"""

import argparse
import json
import os
import sys
import textwrap

try:
    import pyodbc
except ImportError:
    print("ERROR: pyodbc is not installed. Install it with:\n  pip install pyodbc", file=sys.stderr)
    sys.exit(1)


DEFAULT_ROW_LIMIT = 1000


def find_odbc_driver():
    """Auto-detect an installed SQL Server ODBC driver."""
    drivers = pyodbc.drivers()
    # Prefer newer driver versions
    preferred = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server",
    ]
    for driver in preferred:
        if driver in drivers:
            return driver
    # Fall back to any driver with "SQL Server" in the name
    for driver in drivers:
        if "sql server" in driver.lower():
            return driver
    return None


def get_connection(args):
    """Create a read-only SQL Server connection."""
    conn_string = args.connection_string or os.environ.get("MSSQL_CONNSTR")

    if conn_string:
        conn = pyodbc.connect(conn_string)
    else:
        driver = args.driver or os.environ.get("MSSQL_DRIVER") or find_odbc_driver()
        if not driver:
            print("ERROR: No SQL Server ODBC driver found. Install one:\n"
                  "  macOS: brew install microsoft/mssql-release/msodbcsql18\n"
                  "  Linux: See https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server",
                  file=sys.stderr)
            sys.exit(1)

        host = args.host or os.environ.get("MSSQL_HOST", "localhost")
        port = args.port or os.environ.get("MSSQL_PORT", "1433")
        database = args.database or os.environ.get("MSSQL_DATABASE", "master")
        user = args.user or os.environ.get("MSSQL_USER")
        password = args.password or os.environ.get("MSSQL_PASSWORD")

        parts = [
            f"DRIVER={{{driver}}}",
            f"SERVER={host},{port}",
            f"DATABASE={database}",
            "ApplicationIntent=ReadOnly",
            "TrustServerCertificate=yes",
        ]

        if args.trusted:
            parts.append("Trusted_Connection=yes")
        else:
            if not user:
                print("ERROR: --user is required (or set MSSQL_USER env var). Use --trusted for Windows auth.", file=sys.stderr)
                sys.exit(1)
            parts.append(f"UID={user}")
            parts.append(f"PWD={password or ''}")

        conn_string = ";".join(parts)
        conn = pyodbc.connect(conn_string)

    # Set read-only isolation level
    cursor = conn.cursor()
    cursor.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
    cursor.close()

    return conn


# ---------------------------------------------------------------------------
# Schema inspection
# ---------------------------------------------------------------------------

def list_databases(conn):
    """List all databases on the server."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name, state_desc, recovery_model_desc
        FROM sys.databases
        ORDER BY name
    """)
    rows = cursor.fetchall()
    cursor.close()

    print(f"\n{'Database':<30} {'State':<15} {'Recovery Model':<20}")
    print("-" * 65)
    for row in rows:
        print(f"{row[0]:<30} {row[1]:<15} {row[2]:<20}")
    print(f"\n({len(rows)} databases)")


def list_tables(conn, schema_filter=None):
    """List all tables and views in the database."""
    cursor = conn.cursor()
    query = """
        SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE IN ('BASE TABLE', 'VIEW')
    """
    params = []
    if schema_filter:
        query += " AND TABLE_SCHEMA = ?"
        params.append(schema_filter)
    query += " ORDER BY TABLE_SCHEMA, TABLE_TYPE, TABLE_NAME"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()

    if not rows:
        print("No tables or views found.")
        return

    print(f"\n{'Schema':<20} {'Name':<40} {'Type':<15}")
    print("-" * 75)
    for row in rows:
        print(f"{row[0]:<20} {row[1]:<40} {row[2]:<15}")
    print(f"\n({len(rows)} objects)")


def describe_table(conn, table_name, schema_filter=None):
    """Show detailed information about a specific table."""
    schema = schema_filter or "dbo"

    # Resolve schema if table_name contains a dot
    if "." in table_name:
        schema, table_name = table_name.split(".", 1)

    cursor = conn.cursor()

    # --- Columns ---
    cursor.execute("""
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
               IS_NULLABLE, COLUMN_DEFAULT
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
    """, (schema, table_name))
    columns = cursor.fetchall()

    if not columns:
        print(f"Table '{schema}.{table_name}' not found.")
        cursor.close()
        return

    print(f"\n=== {schema}.{table_name} — Columns ===\n")
    print(f"{'Column':<30} {'Type':<25} {'Nullable':<10} {'Default':<30}")
    print("-" * 95)
    for col in columns:
        col_type = col[1]
        if col[2] and col[2] > 0:
            col_type += f"({col[2]})"
        default = str(col[4]) if col[4] else ""
        if len(default) > 28:
            default = default[:25] + "..."
        print(f"{col[0]:<30} {col_type:<25} {col[3]:<10} {default:<30}")

    # --- Primary key ---
    cursor.execute("""
        SELECT kcu.COLUMN_NAME
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
            ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
            AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
        WHERE tc.TABLE_SCHEMA = ? AND tc.TABLE_NAME = ?
            AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
        ORDER BY kcu.ORDINAL_POSITION
    """, (schema, table_name))
    pk_cols = [r[0] for r in cursor.fetchall()]

    if pk_cols:
        print(f"\n=== Primary Key ===\n")
        print(", ".join(pk_cols))

    # --- Indexes ---
    cursor.execute("""
        SELECT
            i.name AS index_name,
            i.type_desc,
            i.is_unique,
            STRING_AGG(c.name, ', ') WITHIN GROUP (ORDER BY ic.key_ordinal) AS columns
        FROM sys.indexes i
        JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
        JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
        JOIN sys.tables t ON i.object_id = t.object_id
        JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ? AND t.name = ?
        GROUP BY i.name, i.type_desc, i.is_unique
        ORDER BY i.name
    """, (schema, table_name))
    indexes = cursor.fetchall()

    if indexes:
        print(f"\n=== Indexes ===\n")
        for idx in indexes:
            unique = "UNIQUE " if idx[2] else ""
            print(f"  {idx[0]} ({unique}{idx[1]})")
            print(f"    Columns: {idx[3]}")

    # --- Foreign keys ---
    cursor.execute("""
        SELECT
            fk.name AS fk_name,
            cp.name AS parent_column,
            rs.name AS ref_schema,
            rt.name AS ref_table,
            cr.name AS ref_column
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
        JOIN sys.columns cp ON fkc.parent_object_id = cp.object_id AND fkc.parent_column_id = cp.column_id
        JOIN sys.columns cr ON fkc.referenced_object_id = cr.object_id AND fkc.referenced_column_id = cr.column_id
        JOIN sys.tables pt ON fk.parent_object_id = pt.object_id
        JOIN sys.schemas ps ON pt.schema_id = ps.schema_id
        JOIN sys.tables rt ON fk.referenced_object_id = rt.object_id
        JOIN sys.schemas rs ON rt.schema_id = rs.schema_id
        WHERE ps.name = ? AND pt.name = ?
        ORDER BY fk.name
    """, (schema, table_name))
    fks = cursor.fetchall()

    if fks:
        print(f"\n=== Foreign Keys ===\n")
        for fk in fks:
            print(f"  {fk[0]}: {fk[1]} -> {fk[2]}.{fk[3]}({fk[4]})")

    # --- Row count ---
    cursor.execute("""
        SELECT SUM(p.rows) AS row_count
        FROM sys.partitions p
        JOIN sys.tables t ON p.object_id = t.object_id
        JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ? AND t.name = ? AND p.index_id IN (0, 1)
    """, (schema, table_name))
    result = cursor.fetchone()
    if result and result[0]:
        print(f"\n=== Row Count ===\n")
        print(f"  {result[0]:,} rows")

    cursor.close()


def cmd_schema(args):
    """Handle the 'schema' subcommand."""
    conn = get_connection(args)
    try:
        if args.list_databases:
            list_databases(conn)
        elif args.table:
            describe_table(conn, args.table, args.schema)
        else:
            list_tables(conn, args.schema)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------

def cmd_query(args):
    """Handle the 'query' subcommand."""
    sql = args.sql
    if not sql:
        print("ERROR: No SQL query provided.", file=sys.stderr)
        sys.exit(1)

    limit = args.limit or DEFAULT_ROW_LIMIT

    conn = get_connection(args)
    try:
        cursor = conn.cursor()
        cursor.execute(sql)

        if cursor.description is None:
            print("Query executed successfully (no result set returned).")
            cursor.close()
            return

        col_names = [desc[0] for desc in cursor.description]
        rows = cursor.fetchmany(limit + 1)
        truncated = len(rows) > limit
        if truncated:
            rows = rows[:limit]

        if args.format == "json":
            output = [dict(zip(col_names, row)) for row in rows]
            print(json.dumps(output, indent=2, default=str))
        else:
            if not rows:
                print("(0 rows)")
                cursor.close()
                return

            # Calculate column widths
            widths = {col: len(col) for col in col_names}
            str_rows = []
            for row in rows:
                str_row = {}
                for i, col in enumerate(col_names):
                    val = str(row[i]) if row[i] is not None else "NULL"
                    if len(val) > 60:
                        val = val[:57] + "..."
                    str_row[col] = val
                    widths[col] = max(widths[col], len(val))
                str_rows.append(str_row)

            # Print header
            header = " | ".join(col.ljust(widths[col]) for col in col_names)
            separator = "-+-".join("-" * widths[col] for col in col_names)
            print(header)
            print(separator)

            for str_row in str_rows:
                line = " | ".join(str_row[col].ljust(widths[col]) for col in col_names)
                print(line)

        row_count = len(rows)
        if truncated:
            print(f"\n({row_count} rows shown, results truncated at limit={limit})")
        else:
            print(f"\n({row_count} rows)")

        cursor.close()

    except pyodbc.Error as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description="SQL Server read-only database access helper.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s --host localhost --database mydb --user sa --password Pass123 schema
              %(prog)s --host localhost --database mydb --user sa --password Pass123 schema --table users
              %(prog)s --host localhost --database mydb --user sa --password Pass123 query "SELECT TOP 10 * FROM users"
              %(prog)s --trusted --host myserver --database mydb schema
        """),
    )

    # Connection arguments
    conn_group = parser.add_argument_group("connection")
    conn_group.add_argument("--host", help="Database host (env: MSSQL_HOST)")
    conn_group.add_argument("--port", help="Database port (env: MSSQL_PORT)")
    conn_group.add_argument("--database", help="Database name (env: MSSQL_DATABASE)")
    conn_group.add_argument("--user", help="Username (env: MSSQL_USER)")
    conn_group.add_argument("--password", help="Password (env: MSSQL_PASSWORD)")
    conn_group.add_argument("--driver", help="ODBC driver name (env: MSSQL_DRIVER, auto-detected if omitted)")
    conn_group.add_argument("--connection-string", help="Full ODBC connection string (env: MSSQL_CONNSTR)")
    conn_group.add_argument("--trusted", action="store_true", help="Use Windows/Kerberos trusted authentication")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Schema subcommand
    schema_parser = subparsers.add_parser("schema", help="Inspect database schema")
    schema_parser.add_argument("--list-databases", action="store_true", help="List all databases")
    schema_parser.add_argument("--schema", help="Filter by schema name")
    schema_parser.add_argument("--table", help="Describe a specific table")
    schema_parser.set_defaults(func=cmd_schema)

    # Query subcommand
    query_parser = subparsers.add_parser("query", help="Execute a read-only SQL query")
    query_parser.add_argument("sql", help="SQL query to execute")
    query_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format (default: table)")
    query_parser.add_argument("--limit", type=int, default=DEFAULT_ROW_LIMIT, help=f"Max rows to return (default: {DEFAULT_ROW_LIMIT})")
    query_parser.set_defaults(func=cmd_query)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
