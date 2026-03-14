# Agentic Skills

A central repository for sharing reusable AI agent skills. These skills extend AI coding assistants (such as [Claude Code](https://docs.anthropic.com/en/docs/claude-code)) with specialized capabilities via structured instructions and bundled helper scripts.

## Getting Started

To use these skills, add this repository to your agent's skill search path. For Claude Code:

```bash
# Option 1: Add as an additional directory
claude --add-dir /path/to/agentic-skills

# Option 2: Symlink into your personal skills folder
ln -s /path/to/agentic-skills/data-access ~/.claude/skills/data-access
```

---

## Skills

### `data-access/` — Database Access (Read-Only)

Three skills for inspecting database schemas and executing read-only queries. Each skill bundles a Python helper script and enforces read-only connections at the driver/transaction level.

| Skill | Invoke | Database | Python Dependency | Read-Only Mechanism |
|---|---|---|---|---|
| [query-postgres](data-access/postgres/SKILL.md) | `/query-postgres` | PostgreSQL | `psycopg2-binary` | `SET default_transaction_read_only = true` |
| [query-sqlserver](data-access/sqlserver/SKILL.md) | `/query-sqlserver` | SQL Server | `pyodbc` | `ApplicationIntent=ReadOnly` + `READ UNCOMMITTED` isolation |
| [query-mongodb](data-access/mongodb/SKILL.md) | `/query-mongodb` | MongoDB | `pymongo` | `readPreference=secondaryPreferred`, no write APIs exposed |

**Capabilities:**

| Feature | PostgreSQL | SQL Server | MongoDB |
|---|---|---|---|
| List databases | ✅ | ✅ | ✅ |
| List tables/collections | ✅ | ✅ | ✅ |
| Describe table/collection | ✅ | ✅ | ✅ |
| Show columns & types | ✅ | ✅ | ✅ (inferred) |
| Show indexes | ✅ | ✅ | ✅ |
| Show foreign keys | ✅ | ✅ | — |
| Row/document count | ✅ | ✅ | ✅ |
| SQL/find queries | ✅ | ✅ | ✅ |
| Aggregation pipelines | — | — | ✅ |
| JSON output format | ✅ | ✅ | ✅ (default) |

**Read-Only Safety:**

| Database | Mechanism |
|---|---|
| **PostgreSQL** | `SET default_transaction_read_only = true` — server rejects all writes |
| **SQL Server** | `ApplicationIntent=ReadOnly` + `SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED` |
| **MongoDB** | `readPreference=secondaryPreferred`, only `find` and `aggregate` exposed |

All skills accept connection strings, individual parameters (host, port, user, etc.), or environment variables. The model can invoke these skills automatically when it determines database access is relevant, or you can invoke them directly via `/query-postgres`, `/query-sqlserver`, or `/query-mongodb`.
