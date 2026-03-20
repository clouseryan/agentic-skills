# Dev Team — Agentic Software Development System

A full-scale agentic development team for rapid, pattern-aware changes to any codebase. Works in **Claude Code** (via skills) and **GitHub Copilot** (via agent personas).

## The Team

| Agent | Skill Command | Role |
|-------|--------------|------|
| Orchestrator | `/dev-team` | Coordinates the whole team, tracks progress |
| Research Analyst | `/research-agent` | Explores codebases, discovers patterns |
| Software Architect | `/architect-agent` | Designs solutions, writes ADRs |
| Developer | `/dev-agent` | Implements features and fixes |
| Database Engineer | `/db-agent` | Schema design, migrations, query optimization |
| QA Engineer | `/qa-agent` | Test planning, test writing, coverage |
| Code Reviewer | `/review-agent` | Security, performance, pattern compliance |
| Documentation Writer | `/docs-agent` | READMEs, API docs, changelogs |
| DevOps Engineer | `/devops-agent` | CI/CD, containers, infrastructure |

## Setup

### Claude Code

Add this directory to Claude Code:

```bash
# Option 1: Add the parent directory
claude --add-dir /path/to/agentic-skills

# Option 2: Symlink just the dev-team skills
ln -s /path/to/agentic-skills/dev-team ~/.claude/skills/dev-team
```

Then use skills in any Claude Code session:
```
/dev-team add a user authentication system to this project
/research-agent how is error handling done in this codebase?
/architect-agent design a caching layer for the API
/dev-agent implement the auth middleware per the architect brief
/db-agent design the users and sessions schema
/qa-agent write tests for the new auth service
/review-agent security audit the auth module
/docs-agent write a README for the auth module
/devops-agent add the ANTHROPIC_API_KEY to the CI pipeline
```

### GitHub Copilot

Read `.github/copilot-instructions.md` to use agent personas in Copilot Chat:

```
"Act as the research analyst. Explore all authentication-related code in this project."
"Act as the software architect. Design how to add OAuth to this system."
"Act as the developer. Implement the auth changes in src/middleware/auth.ts."
```

### Programmatic Orchestration (Claude API)

Use the orchestrator script to run multi-agent pipelines via the Anthropic API:

```bash
export ANTHROPIC_API_KEY=your-key

# Run the full pipeline
python3 dev-team/scripts/orchestrator.py \
  --task "add user authentication with JWT" \
  --root /path/to/project

# Run specific agents only
python3 dev-team/scripts/orchestrator.py \
  --task "analyze the payment module" \
  --agents research,architect \
  --root /path/to/project

# Dry run — see plan without API calls
python3 dev-team/scripts/orchestrator.py \
  --task "..." \
  --dry-run
```

## Shared Workspace

The team uses `.dev-team/` in the project root to share context between sessions. Initialize it once per project:

```bash
# Initialize workspace
python3 /path/to/agentic-skills/dev-team/scripts/workspace.py init --project-root .

# Explore codebase structure (populates .dev-team/context.md)
python3 /path/to/agentic-skills/dev-team/scripts/explore_codebase.py \
  --root . --output .dev-team/context.md

# Analyze patterns (populates .dev-team/patterns.json)
python3 /path/to/agentic-skills/dev-team/scripts/analyze_patterns.py \
  --root . --output .dev-team/patterns.json

# Check team status
python3 /path/to/agentic-skills/dev-team/scripts/workspace.py status
```

Workspace structure:
```
.dev-team/
├── context.md          # Project overview and accumulated findings
├── patterns.json       # Detected code patterns (auto-generated)
├── status.json         # Live task and agent status
└── decisions/          # Architectural Decision Records (ADRs)
    ├── ADR-001-*.md
    └── ADR-002-*.md
```

Add `.dev-team/` to your `.gitignore` (workspace is session state) or commit it to share context with your team.

## How It Works

### Pattern-First Philosophy

Every agent reads the existing codebase before acting:
1. The research agent discovers patterns and documents them
2. All other agents consult `patterns.json` before writing code
3. New patterns require explicit justification and an ADR
4. The code reviewer validates pattern compliance

This ensures new code feels native, not foreign.

### Status Reporting

Every agent reports status at each major milestone:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[RESEARCH] Structural survey complete
  Languages:   TypeScript, SQL
  Framework:   Next.js 14
  Test runner: Jest + testing-library
  Patterns:    8 patterns documented
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Typical Workflow

```
User: /dev-team add a notifications feature

Orchestrator → checks workspace, asks for clarification
      ↓
Research Agent → explores codebase, finds similar features, documents patterns
      ↓
Architect → designs notification system using existing patterns, writes ADR
      ↓
DB Agent → designs notification schema, writes migration
      ↓
Developer → implements service, hooks, and API routes
      ↓
QA Agent → writes tests following existing test patterns
      ↓
Reviewer → security + pattern audit, issues verdict
      ↓
Docs Agent → updates README and API docs
      ↓
Orchestrator → final summary with all changes
```

## Helper Scripts

### `explore_codebase.py`
Generates a project overview: directory tree, file type distribution, entry points, config files.

```bash
python3 dev-team/scripts/explore_codebase.py --root . --output .dev-team/context.md
python3 dev-team/scripts/explore_codebase.py --root . --json  # JSON output
```

### `analyze_patterns.py`
Detects code patterns using AST analysis: naming conventions, test framework, error handling patterns, top dependencies.

```bash
python3 dev-team/scripts/analyze_patterns.py --root . --output .dev-team/patterns.json
python3 dev-team/scripts/analyze_patterns.py --root . --summary  # Quick summary only
```

### `workspace.py`
Manages the `.dev-team/` shared workspace.

```bash
python3 dev-team/scripts/workspace.py init
python3 dev-team/scripts/workspace.py status
python3 dev-team/scripts/workspace.py new-adr --title "Use Redis for caching"
python3 dev-team/scripts/workspace.py list-adrs
python3 dev-team/scripts/workspace.py update-context --key "auth" --value "JWT with refresh tokens"
```

### `orchestrator.py`
Programmatic multi-agent pipeline via the Anthropic SDK.

```bash
python3 dev-team/scripts/orchestrator.py --task "..." [--agents a,b,c] [--root .] [--dry-run]
```

## Design Principles

1. **Read before writing** — every agent reads existing code before writing new code
2. **Patterns over preferences** — match what's there, justify deviations explicitly
3. **Minimal changes** — do exactly what's asked, scope creep is a bug
4. **Frequent reporting** — status updates at every major milestone, no silent work
5. **Blockers surface immediately** — never guess, never silently work around ambiguity
6. **Security first** — the reviewer always checks for OWASP Top 10 before approval
