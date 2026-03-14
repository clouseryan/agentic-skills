#!/usr/bin/env python3
"""MongoDB read-only database access helper for Claude Code.

Supports schema inspection, find queries, and aggregation pipelines.
All connections use readPreference=secondaryPreferred and only expose read operations.
"""

import argparse
import json
import os
import sys
import textwrap
from collections import OrderedDict

try:
    from pymongo import MongoClient, ReadPreference
    from bson import ObjectId
    from bson.json_util import dumps as bson_dumps
except ImportError:
    print("ERROR: pymongo is not installed. Install it with:\n  pip install pymongo", file=sys.stderr)
    sys.exit(1)


DEFAULT_DOC_LIMIT = 100
SCHEMA_SAMPLE_SIZE = 50


class JSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles MongoDB types."""
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        if isinstance(obj, bytes):
            return obj.hex()
        return super().default(obj)


def get_client(args):
    """Create a read-only MongoDB client."""
    uri = args.uri or os.environ.get("MONGO_URI")

    if uri:
        # Ensure readPreference is set
        sep = "&" if "?" in uri else "?"
        if "readPreference" not in uri:
            uri += f"{sep}readPreference=secondaryPreferred"
        client = MongoClient(uri)
    else:
        host = args.host or os.environ.get("MONGO_HOST", "localhost")
        port = int(args.port or os.environ.get("MONGO_PORT", "27017"))
        user = args.user or os.environ.get("MONGO_USER")
        password = args.password or os.environ.get("MONGO_PASSWORD")
        auth_db = args.auth_db or os.environ.get("MONGO_AUTH_DB", "admin")

        kwargs = {
            "host": host,
            "port": port,
            "readPreference": "secondaryPreferred",
        }
        if user:
            kwargs["username"] = user
            kwargs["password"] = password or ""
            kwargs["authSource"] = auth_db

        client = MongoClient(**kwargs)

    return client


def get_database(args, client):
    """Get the target database, or error if not specified."""
    db_name = args.database or os.environ.get("MONGO_DATABASE")
    if not db_name:
        print("ERROR: --database is required (or set MONGO_DATABASE env var).", file=sys.stderr)
        sys.exit(1)
    return client[db_name]


# ---------------------------------------------------------------------------
# Schema inspection
# ---------------------------------------------------------------------------

def infer_field_types(documents):
    """Infer field names and types from a sample of documents."""
    field_info = OrderedDict()

    def process(doc, prefix=""):
        for key, value in doc.items():
            full_key = f"{prefix}.{key}" if prefix else key
            type_name = type(value).__name__
            if isinstance(value, dict):
                type_name = "object"
                process(value, full_key)
            elif isinstance(value, list):
                type_name = "array"
                if value:
                    elem_types = set(type(v).__name__ for v in value[:5])
                    type_name = f"array[{','.join(elem_types)}]"
                    # Recurse into object elements
                    for v in value[:3]:
                        if isinstance(v, dict):
                            process(v, f"{full_key}[]")
                            break
            elif isinstance(value, ObjectId):
                type_name = "ObjectId"
            elif isinstance(value, bool):
                type_name = "bool"
            elif isinstance(value, int):
                type_name = "int"
            elif isinstance(value, float):
                type_name = "float"
            elif value is None:
                type_name = "null"

            if full_key not in field_info:
                field_info[full_key] = {"types": set(), "count": 0}
            field_info[full_key]["types"].add(type_name)
            field_info[full_key]["count"] += 1

    for doc in documents:
        process(doc)

    return field_info


def list_databases(client):
    """List all databases."""
    db_list = client.list_databases()
    rows = []
    for db_info in db_list:
        name = db_info["name"]
        size_mb = db_info.get("sizeOnDisk", 0) / (1024 * 1024)
        rows.append((name, f"{size_mb:.2f} MB", str(db_info.get("empty", False))))

    print(f"\n{'Database':<30} {'Size':<15} {'Empty':<10}")
    print("-" * 55)
    for row in rows:
        print(f"{row[0]:<30} {row[1]:<15} {row[2]:<10}")
    print(f"\n({len(rows)} databases)")


def list_collections(db):
    """List all collections in the database."""
    collections = db.list_collection_names()
    collections.sort()

    if not collections:
        print("No collections found.")
        return

    print(f"\n{'Collection':<40} {'Document Count':<20}")
    print("-" * 60)
    for coll_name in collections:
        try:
            count = db[coll_name].estimated_document_count()
        except Exception:
            count = "?"
        print(f"{coll_name:<40} {str(count):<20}")
    print(f"\n({len(collections)} collections)")


def describe_collection(db, collection_name):
    """Show detailed information about a specific collection."""
    coll = db[collection_name]

    # --- Stats ---
    try:
        count = coll.estimated_document_count()
    except Exception:
        count = "unknown"
    print(f"\n=== {collection_name} ===\n")
    print(f"Estimated document count: {count}")

    # --- Indexes ---
    indexes = list(coll.list_indexes())
    if indexes:
        print(f"\n--- Indexes ({len(indexes)}) ---\n")
        for idx in indexes:
            unique = " (UNIQUE)" if idx.get("unique", False) else ""
            sparse = " (SPARSE)" if idx.get("sparse", False) else ""
            ttl = f" (TTL: {idx['expireAfterSeconds']}s)" if "expireAfterSeconds" in idx else ""
            keys = ", ".join(f"{k}: {v}" for k, v in idx["key"].items())
            print(f"  {idx['name']}{unique}{sparse}{ttl}")
            print(f"    Keys: {{{keys}}}")

    # --- Inferred schema from sample ---
    sample = list(coll.find().limit(SCHEMA_SAMPLE_SIZE))
    if sample:
        field_info = infer_field_types(sample)
        print(f"\n--- Inferred Fields (from {len(sample)} sampled documents) ---\n")
        print(f"{'Field':<40} {'Types':<25} {'Frequency':<15}")
        print("-" * 80)
        for field, info in field_info.items():
            types_str = ", ".join(sorted(info["types"]))
            freq = f"{info['count']}/{len(sample)}"
            print(f"{field:<40} {types_str:<25} {freq:<15}")
    else:
        print("\n(Collection is empty — no schema to infer)")


def cmd_schema(args):
    """Handle the 'schema' subcommand."""
    client = get_client(args)
    try:
        if args.list_databases:
            list_databases(client)
        elif args.collection:
            db = get_database(args, client)
            describe_collection(db, args.collection)
        else:
            db = get_database(args, client)
            list_collections(db)
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Find query
# ---------------------------------------------------------------------------

def cmd_find(args):
    """Handle the 'find' subcommand."""
    client = get_client(args)
    try:
        db = get_database(args, client)
        coll = db[args.collection]

        filter_doc = json.loads(args.filter) if args.filter else {}
        projection = json.loads(args.projection) if args.projection else None
        sort_doc = json.loads(args.sort) if args.sort else None
        limit = args.limit or DEFAULT_DOC_LIMIT

        cursor = coll.find(filter=filter_doc, projection=projection)
        if sort_doc:
            cursor = cursor.sort(list(sort_doc.items()))
        cursor = cursor.limit(limit + 1)

        docs = list(cursor)
        truncated = len(docs) > limit
        if truncated:
            docs = docs[:limit]

        output = json.loads(bson_dumps(docs))
        print(json.dumps(output, indent=2, ensure_ascii=False))

        if truncated:
            print(f"\n({len(docs)} documents shown, results truncated at limit={limit})")
        else:
            print(f"\n({len(docs)} documents)")

    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON argument: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Aggregation pipeline
# ---------------------------------------------------------------------------

def cmd_aggregate(args):
    """Handle the 'aggregate' subcommand."""
    client = get_client(args)
    try:
        db = get_database(args, client)
        coll = db[args.collection]

        pipeline = json.loads(args.pipeline)
        if not isinstance(pipeline, list):
            print("ERROR: Pipeline must be a JSON array of stage objects.", file=sys.stderr)
            sys.exit(1)

        # Add a $limit stage if not already present and limit is set
        limit = args.limit or DEFAULT_DOC_LIMIT
        has_limit = any("$limit" in stage for stage in pipeline)
        if not has_limit:
            pipeline.append({"$limit": limit})

        results = list(coll.aggregate(pipeline))

        output = json.loads(bson_dumps(results))
        print(json.dumps(output, indent=2, ensure_ascii=False))
        print(f"\n({len(results)} documents)")

    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON argument: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        client.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description="MongoDB read-only database access helper.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s --uri mongodb://localhost:27017 schema --list-databases
              %(prog)s --uri mongodb://localhost:27017 --database mydb schema
              %(prog)s --uri mongodb://localhost:27017 --database mydb schema --collection users
              %(prog)s --uri mongodb://localhost:27017 --database mydb find users --filter '{"age": {"$gt": 21}}'
              %(prog)s --uri mongodb://localhost:27017 --database mydb aggregate orders --pipeline '[{"$group": {"_id": "$status", "count": {"$sum": 1}}}]'
        """),
    )

    # Connection arguments
    conn_group = parser.add_argument_group("connection")
    conn_group.add_argument("--uri", help="MongoDB connection URI (env: MONGO_URI)")
    conn_group.add_argument("--host", help="Database host (env: MONGO_HOST)")
    conn_group.add_argument("--port", help="Database port (env: MONGO_PORT)")
    conn_group.add_argument("--database", help="Database name (env: MONGO_DATABASE)")
    conn_group.add_argument("--user", help="Username (env: MONGO_USER)")
    conn_group.add_argument("--password", help="Password (env: MONGO_PASSWORD)")
    conn_group.add_argument("--auth-db", help="Authentication database (env: MONGO_AUTH_DB, default: admin)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Schema subcommand
    schema_parser = subparsers.add_parser("schema", help="Inspect database schema")
    schema_parser.add_argument("--list-databases", action="store_true", help="List all databases")
    schema_parser.add_argument("--collection", help="Describe a specific collection")
    schema_parser.set_defaults(func=cmd_schema)

    # Find subcommand
    find_parser = subparsers.add_parser("find", help="Execute a find query")
    find_parser.add_argument("collection", help="Collection to query")
    find_parser.add_argument("--filter", help="JSON filter document")
    find_parser.add_argument("--projection", help="JSON projection document")
    find_parser.add_argument("--sort", help="JSON sort document")
    find_parser.add_argument("--limit", type=int, default=DEFAULT_DOC_LIMIT, help=f"Max documents to return (default: {DEFAULT_DOC_LIMIT})")
    find_parser.set_defaults(func=cmd_find)

    # Aggregate subcommand
    agg_parser = subparsers.add_parser("aggregate", help="Execute an aggregation pipeline")
    agg_parser.add_argument("collection", help="Collection to aggregate")
    agg_parser.add_argument("--pipeline", required=True, help="JSON aggregation pipeline array")
    agg_parser.add_argument("--limit", type=int, default=DEFAULT_DOC_LIMIT, help=f"Max documents to return (default: {DEFAULT_DOC_LIMIT})")
    agg_parser.set_defaults(func=cmd_aggregate)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
