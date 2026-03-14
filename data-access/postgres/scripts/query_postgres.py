#!/usr/bin/env python3
"""PostgreSQL read-only database access helper for Claude Code.

Supports schema inspection and read-only SQL query execution.
All connections enforce read-only mode via SET default_transaction_read_only = true.
"""

import argparse
import json
import os
import sys
import textwrap

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 is not installed. Install it with:\n  pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)


DEFAULT_ROW_LIMIT = 1000


def get_connection(args):
    """Create a read-only PostgreSQL connection."""
    conn_string = args.connection_string or os.environ.get("DATABASE_URL")

    if conn_string:
        conn = psycopg2.connect(conn_string)
    else:
        conn = psycopg2.connect(
            host=args.host or os.environ.get("PGHOST", "localhost"),
            port=args.port or os.environ.get("PGPORT", "5432"),
            dbname=args.database or os.environ.get("PGDATABASE", "postgres"),
            user=args.user or os.environ.get("PGUSER", "postgres"),
            password=args.password or os.environ.get("PGPASSWORD", ""),
        )

    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SET default_transaction_read_only = true;")
    return conn


# ---------------------------------------------------------------------------
# Schema inspection
# ---------------------------------------------------------------------------

def list_databases(conn):
    """List all databases on the server."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT datname, pg_catalog.pg_get_userbyid(datdba) AS owner,
                   pg_catalog.pg_encoding_to_char(encoding) AS encoding
            FROM pg_catalog.pg_database
            WHERE datistemplate = false
            ORDER BY datname;
        """)
        rows = cur.fetchall()

    print(f"\n{'Database':<30} {'Owner':<20} {'Encoding':<15}")
    print("-" * 65)
    for row in rows:
        print(f"{row[0]:<30} {row[1]:<20} {row[2]:<15}")
    print(f"\n({len(rows)} databases)")


def list_tables(conn, schema_filter=None):
    """List all tables and views in the database."""
    with conn.cursor() as cur:
        query = """
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
        """
        params = []
        if schema_filter:
            query += " AND table_schema = %s"
            params.append(schema_filter)
        query += " ORDER BY table_schema, table_type, table_name;"

        cur.execute(query, params)
        rows = cur.fetchall()

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
    schema = schema_filter or "public"

    # Resolve schema if table_name contains a dot
    if "." in table_name:
        schema, table_name = table_name.split(".", 1)

    # --- Columns ---
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type, character_maximum_length,
                   is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position;
        """, (schema, table_name))
        columns = cur.fetchall()

    if not columns:
        print(f"Table '{schema}.{table_name}' not found.")
        return

    print(f"\n=== {schema}.{table_name} — Columns ===\n")
    print(f"{'Column':<30} {'Type':<25} {'Nullable':<10} {'Default':<30}")
    print("-" * 95)
    for col in columns:
        col_type = col[1]
        if col[2]:
            col_type += f"({col[2]})"
        default = col[4] or ""
        if len(default) > 28:
            default = default[:25] + "..."
        print(f"{col[0]:<30} {col_type:<25} {col[3]:<10} {default:<30}")

    # --- Primary key ---
    with conn.cursor() as cur:
        cur.execute("""
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = %s AND tc.table_name = %s
                AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY kcu.ordinal_position;
        """, (schema, table_name))
        pk_cols = [r[0] for r in cur.fetchall()]

    if pk_cols:
        print(f"\n=== Primary Key ===\n")
        print(", ".join(pk_cols))

    # --- Indexes ---
    with conn.cursor() as cur:
        cur.execute("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = %s AND tablename = %s
            ORDER BY indexname;
        """, (schema, table_name))
        indexes = cur.fetchall()

    if indexes:
        print(f"\n=== Indexes ===\n")
        for idx in indexes:
            print(f"  {idx[0]}")
            print(f"    {idx[1]}")

    # --- Foreign keys ---
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                tc.constraint_name,
                kcu.column_name,
                ccu.table_schema AS ref_schema,
                ccu.table_name AS ref_table,
                ccu.column_name AS ref_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
                AND tc.table_schema = ccu.table_schema
            WHERE tc.table_schema = %s AND tc.table_name = %s
                AND tc.constraint_type = 'FOREIGN KEY'
            ORDER BY tc.constraint_name;
        """, (schema, table_name))
        fks = cur.fetchall()

    if fks:
        print(f"\n=== Foreign Keys ===\n")
        for fk in fks:
            print(f"  {fk[0]}: {fk[1]} -> {fk[2]}.{fk[3]}({fk[4]})")

    # --- Row count estimate ---
    with conn.cursor() as cur:
        cur.execute("""
            SELECT reltuples::bigint
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s;
        """, (schema, table_name))
        result = cur.fetchone()
        if result:
            print(f"\n=== Estimated Row Count ===\n")
            print(f"  ~{result[0]:,} rows (from pg_class.reltuples)")


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
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)

            if cur.description is None:
                print("Query executed successfully (no result set returned).")
                return

            rows = cur.fetchmany(limit + 1)
            truncated = len(rows) > limit
            if truncated:
                rows = rows[:limit]

            col_names = [desc[0] for desc in cur.description]

            if args.format == "json":
                output = [dict(row) for row in rows]
                print(json.dumps(output, indent=2, default=str))
            else:
                # Table format
                if not rows:
                    print("(0 rows)")
                    return

                # Calculate column widths
                widths = {col: len(col) for col in col_names}
                str_rows = []
                for row in rows:
                    str_row = {}
                    for col in col_names:
                        val = str(row[col]) if row[col] is not None else "NULL"
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

                # Print rows
                for str_row in str_rows:
                    line = " | ".join(str_row[col].ljust(widths[col]) for col in col_names)
                    print(line)

            row_count = len(rows)
            if truncated:
                print(f"\n({row_count} rows shown, results truncated at limit={limit})")
            else:
                print(f"\n({row_count} rows)")

    except psycopg2.errors.ReadOnlySqlTransaction as e:
        print(f"ERROR: Write operations are not permitted. This is a read-only connection.\n{e}", file=sys.stderr)
        sys.exit(1)
    except psycopg2.Error as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description="PostgreSQL read-only database access helper.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s --host localhost --database mydb schema
              %(prog)s --host localhost --database mydb schema --table users
              %(prog)s --host localhost --database mydb query "SELECT * FROM users LIMIT 10"
              %(prog)s --connection-string "postgresql://user:pass@host/db" query "SELECT 1"
        """),
    )

    # Connection arguments
    conn_group = parser.add_argument_group("connection")
    conn_group.add_argument("--host", help="Database host (env: PGHOST)")
    conn_group.add_argument("--port", help="Database port (env: PGPORT)")
    conn_group.add_argument("--database", help="Database name (env: PGDATABASE)")
    conn_group.add_argument("--user", help="Username (env: PGUSER)")
    conn_group.add_argument("--password", help="Password (env: PGPASSWORD)")
    conn_group.add_argument("--connection-string", help="Full connection URI (env: DATABASE_URL)")

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
