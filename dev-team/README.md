# Dev Team — Agentic Software Development System

A full-scale agentic development team for rapid, pattern-aware changes to any codebase. Works in **Claude Code** (via skills), **GitHub Copilot** (via agent personas), and **programmatically** via the Anthropic API.

## Getting Started

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (for skill commands) or [GitHub Copilot](https://github.com/features/copilot) (for agent personas)
- Python 3.10+ (for helper scripts)
- `pip install anthropic` (for `orchestrator.py` and `workspace.py compress-context`)
- `gh` CLI authenticated (`gh auth login`) for `/lead-agent`

### 1. Install the Skills

**Claude Code — add this directory:**

```bash
# Add the parent repo as an additional directory (exposes all skills)
claude --add-dir /path/to/agentic-skills

# Or symlink just the dev-team directory into your Claude skills folder
ln -s /path/to/agentic-skills/dev-team ~/.claude/skills/dev-team
```

**GitHub Copilot — copy the instructions file:**

The `.github/copilot-instructions.md` file in this repo provides agent personas for Copilot Chat. Copy or symlink it into your project's `.github/` directory.

### 2. Initialize the Workspace

Run once per project to set up the shared `.dev-team/` context directory:

```bash
# Initialize workspace directories and files
python3 /path/to/agentic-skills/dev-team/scripts/workspace.py init --project-root .

# Populate context with project structure
python3 /path/to/agentic-skills/dev-team/scripts/explore_codebase.py \
  --root . --output .dev-team/context.md

# Detect code patterns (naming, testing, error handling, imports)
python3 /path/to/agentic-skills/dev-team/scripts/analyze_patterns.py \
  --root . --output .dev-team/patterns.json
```

This creates:
```
.dev-team/
├── context.md          # Project overview and accumulated team findings
├── patterns.json       # Detected code patterns (auto-generated)
├── status.json         # Live task and agent status
├── decisions/          # Architectural Decision Records (ADRs)
├── requirements/       # BA-produced feature requirement documents
└── context-history/    # Archived context snapshots (from compress-context)
```

> **Tip**: Add `.dev-team/` to `.gitignore` to keep it as local session state, or commit it to share context with your team.

### 3. Use the Skills

**Claude Code:**

```bash
# Let the orchestrator coordinate the whole team
/dev-team add a user authentication system

# Or invoke individual agents directly
/ba-agent gather requirements for a notifications feature
/research-agent how is error handling done in this codebase?
/sec-agent threat model the new payment feature
/architect-agent design a caching layer for the API
/dev-agent implement the auth middleware per the architect brief
/db-agent design the users and sessions schema
/qa-agent write tests for the new auth service
/e2e-agent spin up the app and test the login and registration workflows
/review-agent security audit the auth module
/docs-agent write a README for the auth module
/devops-agent add the auth service to the CI pipeline
/lead-agent create a PR for all auth changes
```

**GitHub Copilot Chat:**

```
"Act as the business analyst. Gather requirements for adding OAuth to this app."
"Act as the security agent. Threat model the new payment feature."
"Act as the research analyst. Explore all authentication-related code."
"Act as the software architect. Design how to add OAuth using existing patterns."
"Act as the developer. Implement the OAuth callback in src/auth/callback.ts."
"Act as the lead engineer. Create a PR for this work and review it."
```

**Programmatic (Anthropic API):**

```bash
export ANTHROPIC_API_KEY=your-key

# Full staged pipeline (recommended — runs parallel stages for speed)
python3 dev-team/scripts/orchestrator.py \
  --task "add user authentication with JWT" \
  --root /path/to/project \
  --staged

# Custom sequential pipeline
python3 dev-team/scripts/orchestrator.py \
  --task "analyze the payment module for security issues" \
  --agents security,research,reviewer

# Dry run — see the plan without making API calls
python3 dev-team/scripts/orchestrator.py \
  --task "add notifications" \
  --staged \
  --dry-run
```

---

## The Team

| Agent | Skill Command | Role |
|-------|--------------|------|
| Orchestrator | `/dev-team` | Coordinates the whole team, tracks progress |
| Business Analyst | `/ba-agent` | Requirements gathering, domain research, specs |
| Research Analyst | `/research-agent` | Explores codebases, discovers patterns |
| Security Agent | `/sec-agent` | Threat modeling, CVE scanning, secrets detection |
| Software Architect | `/architect-agent` | Designs solutions, writes ADRs |
| Developer | `/dev-agent` | Implements features and fixes |
| Database Engineer | `/db-agent` | Schema design, migrations, query optimization |
| QA Engineer | `/qa-agent` | Test planning, test writing, coverage |
| E2E Tester | `/e2e-agent` | Live browser testing via MCP (Claude Preview/Chrome), Playwright, mobile automation |
| Code Reviewer | `/review-agent` | Security, performance, pattern compliance |
| Documentation Writer | `/docs-agent` | READMEs, API docs, changelogs |
| DevOps Engineer | `/devops-agent` | CI/CD, containers, infrastructure |
| Lead Engineer | `/lead-agent` | PR creation, review, approval, merge |

---

## Workflow

### Standard Feature Workflow (Iterative Chunk-Based)

The orchestrator breaks work into small, independently testable chunks. Each chunk goes through a full dev → test → review cycle before moving to the next.

```
Business Problem / GitHub Issue
     ↓
Phase 1: Intake — parse goal, detect platform, check prior context
     ↓
Phase 2: Business Analyst → frames problem, researches domain, writes requirements
     ↓
Phase 3: Research Analyst ‖ Security Agent  (parallel)
         (codebase patterns)  (threat model)
     ↓
Phase 4: Software Architect → designs solution, produces CHUNKED WORK PLAN
         (ordered list of small implementation chunks, 3-5 files each)
     ↓
Phase 5: Iterative Chunk Loop
     ┌─────────────────────────────────────────────┐
     │  FOR EACH CHUNK:                            │
     │    Developer → implements chunk              │
     │    QA Agent → writes + runs tests            │
     │    E2E Tester → browser testing via MCP      │
     │      (only if chunk is UI-visible)           │
     │    Code Reviewer → reviews chunk             │
     │      ↓                                       │
     │    IF changes requested:                     │
     │      → route findings back to Developer      │
     │      → re-implement → re-test → re-review    │
     │      (max 2 rework cycles, then escalate)    │
     │      ↓                                       │
     │    Commit chunk                              │
     └─────────────────────────────────────────────┘
     ↓
Phase 6: Final Integration
     Run full test suite + full E2E browser validation + comprehensive review
     ↓
Phase 7: Lead Engineer → create PR (MANDATORY) → final review → merge
     IF changes requested: route back to Developer → fix → re-review
     (max 3 cycles, then escalate)
     ↓
Phase 8: Completion — summary, context update
```

### Bug Fix Workflow

```
GitHub Issue (bug)
     ↓
Research Analyst → finds root cause and related code
     ↓
Developer → implements fix following existing patterns
     ↓
QA Agent → writes regression test
     ↓
Code Reviewer → verifies fix, checks for regressions
     ↓
Lead Engineer → PR + merge (ALWAYS)
```

### Security Issue Workflow

```
GitHub Issue (security)
     ↓
Security Agent → assesses severity, produces STRIDE analysis
     ↓
Developer → applies remediation
     ↓
Security Agent → verifies fix, runs final dep scan
     ↓
Lead Engineer → PR + merge (ALWAYS, on private branch if needed)
```

### Key Workflow Features

- **Chunk-based execution**: Work is broken into small, independently testable pieces
- **Feedback loops**: Reviewer and lead can route changes back to the developer
- **Escalation protocol**: Max 2 rework cycles per chunk, 3 per PR before asking for human guidance
- **MCP browser testing**: E2E agent uses Claude Preview or Claude in Chrome for real browser interaction
- **Mandatory PR**: Lead always creates a PR — no implementation completes without one

---

## Shared Workspace

All agents read and write to `.dev-team/` to share context across sessions:

```
.dev-team/
├── context.md            # Project overview + accumulated agent findings
├── patterns.json         # AST-detected code patterns
├── status.json           # Live task and agent status
├── chunks.md             # Architect's chunked work plan (created per feature)
├── chunks-status.json    # Chunk execution tracking (progress, rework counts)
├── decisions/            # Architectural Decision Records
│   ├── ADR-001-*.md
│   └── ADR-002-*.md
├── requirements/         # Feature requirement specs (written by BA agent)
│   └── <feature>.md
└── context-history/      # Compressed context archives
    └── context-<timestamp>.md
```

### Workspace Management

```bash
# Initialize (run once per project)
python3 dev-team/scripts/workspace.py init

# Check current status
python3 dev-team/scripts/workspace.py status

# Compress context.md when it gets too large (archives full history first)
python3 dev-team/scripts/workspace.py compress-context

# Create a new ADR manually
python3 dev-team/scripts/workspace.py new-adr --title "Use Redis for session storage"

# List all ADRs
python3 dev-team/scripts/workspace.py list-adrs

# Add a context note
python3 dev-team/scripts/workspace.py update-context \
  --key "auth-decision" --value "Using JWT with 24h expiry, refresh tokens in httpOnly cookie"
```

---

## Helper Scripts

### `explore_codebase.py`
Generates a project overview: directory tree, file type distribution, entry points, config files, language detection.

```bash
python3 dev-team/scripts/explore_codebase.py --root . --output .dev-team/context.md
python3 dev-team/scripts/explore_codebase.py --root . --json   # JSON output
```

### `analyze_patterns.py`
Detects code patterns using AST analysis: naming conventions, test framework, error handling, import style, top dependencies.

```bash
python3 dev-team/scripts/analyze_patterns.py --root . --output .dev-team/patterns.json
python3 dev-team/scripts/analyze_patterns.py --root . --summary  # Quick summary only
```

### `workspace.py`
Manages the `.dev-team/` shared workspace: initialization, context updates, ADR management, status tracking, context compression.

```bash
python3 dev-team/scripts/workspace.py init
python3 dev-team/scripts/workspace.py status
python3 dev-team/scripts/workspace.py compress-context   # Summarizes + archives context.md
python3 dev-team/scripts/workspace.py new-adr --title "..."
python3 dev-team/scripts/workspace.py list-adrs
python3 dev-team/scripts/workspace.py update-context --key "..." --value "..."
python3 dev-team/scripts/workspace.py add-task --description "..." --agent "dev-agent"
python3 dev-team/scripts/workspace.py complete-task --task-id 3
```

### `orchestrator.py`
Programmatic multi-agent pipeline via the Anthropic SDK.

```bash
# Staged pipeline (recommended) — parallel stages, intelligent context summarization
python3 dev-team/scripts/orchestrator.py --task "..." --staged --root .

# Sequential pipeline
python3 dev-team/scripts/orchestrator.py --task "..." --root .

# Custom agent sequence
python3 dev-team/scripts/orchestrator.py --task "..." --agents research,security,architect

# Parallel (no context sharing — for independent analysis)
python3 dev-team/scripts/orchestrator.py --task "..." --agents qa,docs --parallel

# Dry run
python3 dev-team/scripts/orchestrator.py --task "..." --dry-run

# Save results to JSON
python3 dev-team/scripts/orchestrator.py --task "..." --output results.json
```

**Staged pipeline stages** (used with `--staged`):
```
Stage 1: ba                           (requirements)
Stage 2: research ‖ security          (parallel — codebase + threat model)
Stage 3: architect                    (design + chunked work plan)
Stage 4: CHUNK LOOP                   (handled by orchestrator)
         For each chunk: developer → qa → e2e (if UI) → reviewer
         With rework sub-loop (max 2 cycles per chunk)
Stage 5: docs ‖ devops               (parallel — post-implementation)
Stage 6: lead                         (PR creation + final review — MANDATORY)
```

**Chunk execution loop** (used with `--chunks`):
```bash
# Run the chunk loop from a JSON file
python3 dev-team/scripts/orchestrator.py \
  --task "implement user auth" \
  --chunks .dev-team/chunks.json \
  --root .
```

---

## Design Principles

1. **Read before writing** — every agent reads existing code before writing new code
2. **Patterns over preferences** — match what's there, justify deviations with an ADR
3. **Minimal changes** — do exactly what's asked, scope creep is a bug
4. **Security is upstream** — threat model before design, not just checklist at review time
5. **Frequent reporting** — status updates at every major milestone, no silent work
6. **Blockers surface immediately** — never guess or silently work around ambiguity
7. **Complete the lifecycle** — from requirements to merged PR
