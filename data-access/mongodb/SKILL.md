---
name: query-mongodb
description: Connect to a MongoDB database to inspect its schema (databases, collections, indexes, document structure) and execute read-only queries (find, aggregate). Use when the user needs to explore or retrieve data from a MongoDB database.
allowed-tools: Bash(python3 *), Bash(pip install *), Bash(pip3 install *)
---

# MongoDB Database Access (Read-Only)

Inspect schemas and run read-only queries against a MongoDB database using the bundled helper script.

## Prerequisites

Before first use, ensure the `pymongo` Python package is installed:

```bash
pip install pymongo
```

## Helper Script Location

```
${CLAUDE_SKILL_DIR}/scripts/query_mongodb.py
```

## Connection Parameters

| Argument                | Env Variable     | Default                        | Description                     |
|-------------------------|------------------|--------------------------------|---------------------------------|
| `--uri`                 | `MONGO_URI`      | `mongodb://localhost:27017`    | MongoDB connection URI          |
| `--host`                | `MONGO_HOST`     | `localhost`                    | Database host (if no URI)       |
| `--port`                | `MONGO_PORT`     | `27017`                       | Database port (if no URI)       |
| `--database`            | `MONGO_DATABASE` | *(none)*                       | Database name                   |
| `--user`                | `MONGO_USER`     | *(none)*                       | Username (if no URI)            |
| `--password`            | `MONGO_PASSWORD` | *(none)*                       | Password (if no URI)            |
| `--auth-db`             | `MONGO_AUTH_DB`  | `admin`                        | Authentication database         |

**Ask the user for connection details before running the script.** Never guess or assume credentials.

## Usage

### Inspect Schema

List all databases:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_mongodb.py --uri <uri> schema --list-databases
```

List all collections in a database:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_mongodb.py --uri <uri> --database <db> schema
```

Inspect a specific collection (indexes + inferred document structure from a sample):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_mongodb.py --uri <uri> --database <db> schema --collection <collection>
```

### Execute a Find Query

Run a `find()` with an optional filter, projection, sort, and limit:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_mongodb.py --uri <uri> --database <db> find <collection> --filter '{"status": "active"}' --projection '{"name": 1, "email": 1}' --sort '{"created_at": -1}' --limit 10
```

If no filter is provided, returns all documents (up to the limit):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_mongodb.py --uri <uri> --database <db> find <collection>
```

### Execute an Aggregation Pipeline

Run an aggregation pipeline:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/query_mongodb.py --uri <uri> --database <db> aggregate <collection> --pipeline '[{"$match": {"status": "active"}}, {"$group": {"_id": "$category", "count": {"$sum": 1}}}]'
```

## Safety

- All connections use `readPreference=secondaryPreferred`.
- The script **only exposes read operations** (`find`, `aggregate`, schema inspection). No write methods (`insert`, `update`, `delete`) are available.
- Results are limited to **100 documents** by default. Use `--limit <N>` to change this.

## Guidelines

1. **Always ask the user for connection details** before attempting to connect.
2. **Start with schema inspection** to understand the database structure before writing queries.
3. **Use `--limit`** to avoid returning excessively large result sets.
4. **Pass JSON arguments** as single-quoted strings on the command line to avoid shell escaping issues.
5. **Present results clearly** — format output as markdown when displaying to the user.
6. For connection URIs with special characters in username/password, use percent-encoding (e.g., `p%40ss` for `p@ss`).
