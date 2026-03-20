# Agentic Skills

A central repository for sharing reusable AI agent skills. These skills extend AI coding assistants (such as [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and [GitHub Copilot](https://github.com/features/copilot)) with specialized capabilities via structured instructions and bundled helper scripts.

## Getting Started

Add this repository to your agent's skill search path. For Claude Code:

```bash
# Option 1: Add as an additional directory
claude --add-dir /path/to/agentic-skills

# Option 2: Symlink into your personal skills folder
ln -s /path/to/agentic-skills/data-access ~/.claude/skills/data-access
ln -s /path/to/agentic-skills/dev-team ~/.claude/skills/dev-team
```

---

## Skills

### `dev-team/` — Agentic Software Development Team

A full-scale agentic dev team for rapid, pattern-aware changes to any codebase. Eight specialist agents that coordinate to research, design, implement, test, review, document, and deploy changes — all while respecting the codebase's existing patterns and conventions.

Works in both **Claude Code** (skill commands) and **GitHub Copilot** (agent personas via `.github/copilot-instructions.md`).

| Skill | Invoke | Role |
|-------|--------|------|
| [Orchestrator](dev-team/SKILL.md) | `/dev-team` | Coordinates all agents, tracks tasks, reports status |
| [Research Analyst](dev-team/research/SKILL.md) | `/research-agent` | Explores codebases, discovers patterns and conventions |
| [Software Architect](dev-team/architect/SKILL.md) | `/architect-agent` | Designs solutions, writes Architectural Decision Records |
| [Developer](dev-team/developer/SKILL.md) | `/dev-agent` | Implements features following existing patterns exactly |
| [Database Engineer](dev-team/database/SKILL.md) | `/db-agent` | Schema design, migrations, query optimization |
| [QA Engineer](dev-team/qa/SKILL.md) | `/qa-agent` | Test planning, test writing, coverage analysis |
| [Code Reviewer](dev-team/reviewer/SKILL.md) | `/review-agent` | Security, performance, and pattern compliance review |
| [Documentation Writer](dev-team/docs/SKILL.md) | `/docs-agent` | READMEs, API docs, inline comments, changelogs |
| [DevOps Engineer](dev-team/devops/SKILL.md) | `/devops-agent` | CI/CD pipelines, containers, infrastructure-as-code |

**Helper scripts** (in `dev-team/scripts/`):
- `explore_codebase.py` — directory tree, framework detection, entry point mapping
- `analyze_patterns.py` — AST-based pattern detection for naming, testing, imports
- `workspace.py` — manages a shared `.dev-team/` workspace (context, ADRs, status)
- `orchestrator.py` — programmatic multi-agent pipeline via the Anthropic SDK

See [`dev-team/README.md`](dev-team/README.md) for full usage and workflow documentation.

---

### `data-access/` — Database Access (Read-Only)

Three skills for inspecting database schemas and executing read-only queries. Each skill bundles a Python helper script and enforces read-only connections at the driver/transaction level.

| Skill | Invoke | Database | Python Dependency | Read-Only Mechanism |
|-------|--------|----------|-------------------|---------------------|
| [query-postgres](data-access/postgres/SKILL.md) | `/query-postgres` | PostgreSQL | `psycopg2-binary` | `SET default_transaction_read_only = true` |
| [query-sqlserver](data-access/sqlserver/SKILL.md) | `/query-sqlserver` | SQL Server | `pyodbc` | `ApplicationIntent=ReadOnly` + `READ UNCOMMITTED` isolation |
| [query-mongodb](data-access/mongodb/SKILL.md) | `/query-mongodb` | MongoDB | `pymongo` | `readPreference=secondaryPreferred`, no write APIs exposed |

**Capabilities:**

| Feature | PostgreSQL | SQL Server | MongoDB |
|---------|------------|------------|---------|
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

All skills accept connection strings, individual parameters, or environment variables.

---

## Skill Structure

Each skill follows the same structure:

```
<category>/<skill-name>/
├── SKILL.md          # Skill definition (YAML frontmatter + agent instructions)
└── scripts/          # Optional Python helper scripts
    └── *.py
```

The `SKILL.md` file uses YAML frontmatter to declare the skill name, description, and allowed tools — then provides detailed instructions the agent follows when the skill is invoked.
