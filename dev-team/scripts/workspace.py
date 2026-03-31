#!/usr/bin/env python3
"""
Workspace Manager — Dev Team Helper Script

Manages the .dev-team/ shared workspace: initialization, context updates,
status tracking, Architectural Decision Records (ADRs), feedback queues,
security verdicts, dependency manifest, and pipeline rollback.

Usage:
  python3 workspace.py init --project-root .
  python3 workspace.py status
  python3 workspace.py update-context --key "research" --value "..."
  python3 workspace.py new-adr --title "Use Redis for caching" --content "..."
  python3 workspace.py list-adrs
  python3 workspace.py set-status --agent "dev-agent" --phase "implementing" --detail "..."
  python3 workspace.py get-context
  python3 workspace.py push-feedback --from sec-agent --to lead-agent --message "..." --severity BLOCKING
  python3 workspace.py get-feedback [--to agent] [--all]
  python3 workspace.py set-security-verdict --verdict BLOCKED --findings "SQL injection,secrets"
  python3 workspace.py get-security-verdict
  python3 workspace.py add-dependency --name requests --version 2.31.0 --added-by dev-agent
  python3 workspace.py check-conflicts
  python3 workspace.py rollback --to-stage N
  python3 workspace.py show-log
  python3 workspace.py new-requirement --title "Auth Feature" --feature auth --tags auth,users
  python3 workspace.py query --type adr --status accepted --tags auth
  python3 workspace.py search --text "JWT"
  python3 workspace.py migrate-frontmatter [--dry-run]

Environment:
  DEV_TEAM_REDIS_URL   Redis connection URL for real-time state (optional)
  DEV_TEAM_REDIS_TTL   Key TTL in seconds (default: 86400)
  python3 workspace.py new-requirement --title "Auth Feature" --feature auth --tags auth,users
  python3 workspace.py query --type adr --status accepted --tags auth
  python3 workspace.py search --text "JWT"
  python3 workspace.py migrate-frontmatter [--dry-run]
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# ─── Constants ─────────────────────────────────────────────────────────────────

WORKSPACE_DIR = '.dev-team'
PATTERNS_FILE = 'patterns.json'
CONTEXT_FILE = 'context.md'
STATUS_FILE = 'status.json'
DECISIONS_DIR = 'decisions'
REQUIREMENTS_DIR = 'requirements'
CONTEXT_HISTORY_DIR = 'context-history'


# ─── Frontmatter utilities ─────────────────────────────────────────────────────

def parse_frontmatter(text: str) -> tuple:
    """Parse YAML frontmatter from markdown text.

    Returns (frontmatter_dict, body_text). Returns ({}, full_text) when no
    frontmatter block is present, preserving backward compatibility.
    """
    match = re.match(r'^---\n(.*?)\n---\n', text, re.DOTALL)
    if not match:
        return {}, text

    fm = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line:
            continue
        key, _, raw_value = line.partition(':')
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value == 'null':
            fm[key] = None
        elif raw_value.startswith('[') and raw_value.endswith(']'):
            inner = raw_value[1:-1]
            fm[key] = [v.strip().strip('"\'') for v in inner.split(',') if v.strip()]
        else:
            fm[key] = raw_value

    body = text[match.end():]
    return fm, body


def render_frontmatter(data: dict) -> str:
    """Serialize a dict to a YAML frontmatter block string."""
    lines = ['---']
    for key, value in data.items():
        if value is None:
            lines.append(f'{key}: null')
        elif isinstance(value, list):
            items = ', '.join(str(v) for v in value)
            lines.append(f'{key}: [{items}]')
        else:
            lines.append(f'{key}: {value}')
    lines.append('---')
    return '\n'.join(lines) + '\n'


def load_artifact(path: Path) -> tuple:
    """Load frontmatter and body from a markdown artifact file.

    Falls back to extracting **Status** from bold markdown headers for legacy
    files. Sets fm['_legacy'] = True when no YAML frontmatter was found.
    """
    text = path.read_text()
    fm, body = parse_frontmatter(text)
    if not fm:
        m = re.search(r'\*\*Status\*\*:\s*(\w+)', body)
        if m:
            fm['status'] = m.group(1).lower()
        # Extract title from first heading
        m_title = re.search(r'^#\s+(.+)', body, re.MULTILINE)
        if m_title:
            fm['title'] = m_title.group(1).strip()
        fm['_legacy'] = True
    return fm, body


def _extract_snippet(text: str, search_term: str, context_lines: int = 1) -> str:
    """Return a short snippet of text around the first match of search_term."""
    lines = text.splitlines()
    term_lower = search_term.lower()
    for i, line in enumerate(lines):
        if term_lower in line.lower():
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            return ' | '.join(lines[start:end]).strip()
    return ''


# ─── Workspace resolution ──────────────────────────────────────────────────────

def find_workspace(project_root: str | None = None,
                   workspace_root: str | None = None) -> Path:
    """
    Resolve the .dev-team/ workspace directory.

    workspace_root  — explicit override for multi-repo setups
    project_root    — project root (workspace will be <root>/.dev-team)
    (neither)       — search upward from cwd
    """
    if workspace_root:
        return Path(workspace_root)

    if project_root:
        return Path(project_root) / WORKSPACE_DIR

    # Search upward from cwd
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        candidate = parent / WORKSPACE_DIR
        if candidate.exists():
            return candidate

    return cwd / WORKSPACE_DIR


def get_store(workspace: Path):
    """Return a Store instance for the workspace."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from store import Store
        return Store(workspace)
    except ImportError:
        return None


# ─── Commands ──────────────────────────────────────────────────────────────────

def cmd_init(args):
    """Initialize the .dev-team workspace."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / DECISIONS_DIR).mkdir(exist_ok=True)
    (workspace / REQUIREMENTS_DIR).mkdir(exist_ok=True)
    (workspace / CONTEXT_HISTORY_DIR).mkdir(exist_ok=True)

    # Initialize patterns.json if missing
    patterns_file = workspace / PATTERNS_FILE
    if not patterns_file.exists():
        patterns_file.write_text(json.dumps({
            'generated_at': None,
            'root': None,
            'summary': [],
            'languages': {},
            'testing': {},
            'file_naming': {},
        }, indent=2))

    # Initialize context.md if missing
    context_file = workspace / CONTEXT_FILE
    if not context_file.exists():
        project_name = Path(getattr(args, 'project_root', None) or '.').resolve().name
        context_file.write_text(f"""# Dev Team Workspace: {project_name}

Initialized: {datetime.now().strftime('%Y-%m-%d %H:%M')}

## Project Overview

_(Run `/research-agent` to populate this section)_

## Patterns Identified

_(Run `analyze_patterns.py` to populate this section)_

## Current Task Context

_(Updated by the orchestrator as work progresses)_

## Agent Notes

_(Each agent appends findings here)_
""")

    # Initialize status.json if missing (also initializes store)
    store = get_store(workspace)
    if store:
        status = store.get_status()
        if not status.get('last_updated'):
            store.set_phase('idle')

    status_file = workspace / STATUS_FILE
    if not status_file.exists():
        status_file.write_text(json.dumps({
            'last_updated': None,
            'current_phase': 'idle',
            'agents': {},
            'tasks': [],
        }, indent=2))

    # Show backend info
    backend = 'redis' if (store and store.backend == 'redis') else 'json files'
    print(f"Workspace initialized at {workspace}")
    print(f"  State backend:  {backend}")
    print(f"  {workspace / PATTERNS_FILE}")
    print(f"  {workspace / CONTEXT_FILE}")
    print(f"  {workspace / STATUS_FILE}")
    print(f"  {workspace / DECISIONS_DIR}/")
    print(f"  {workspace / REQUIREMENTS_DIR}/")
    print(f"  {workspace / CONTEXT_HISTORY_DIR}/")


def cmd_status(args):
    """Show current workspace status."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )

    store = get_store(workspace)
    if store:
        status = store.get_status()
        backend = store.backend
    else:
        status_file = workspace / STATUS_FILE
        if not status_file.exists():
            print("No workspace found. Run: workspace.py init")
            sys.exit(1)
        status = json.loads(status_file.read_text())
        backend = 'json'

    print(f"\n{'━' * 55}")
    print(f"DEV TEAM WORKSPACE STATUS")
    print(f"{'━' * 55}")
    print(f"Backend:      {backend}")
    print(f"Phase:        {status.get('current_phase', 'idle')}")
    print(f"Last updated: {status.get('last_updated', 'never')}")
    print()

    agents = status.get('agents', {})
    if agents:
        print("AGENTS:")
        for agent, info in agents.items():
            print(f"  {agent:<20} {info.get('status', 'unknown')} — {info.get('detail', '')}")
        print()

    tasks = status.get('tasks', [])
    if tasks:
        print("TASKS:")
        for task in tasks:
            icon = '✓' if task.get('done') else '○'
            print(f"  [{icon}] {task.get('description', '')}  [{task.get('agent', '?')}]")
        print()

    # Show security verdict summary
    if store:
        verdict = store.get_security_verdict()
        if verdict:
            emoji = {'CLEAR': '✅', 'WARNINGS': '⚠️', 'REMEDIATION_REQUIRED': '🔄', 'BLOCKED': '❌'}
            v = verdict['verdict']
            print(f"SECURITY: {emoji.get(v, '?')} {v} (critical={verdict.get('critical_count', 0)}, high={verdict.get('high_count', 0)})")
            print()

        # Show unresolved feedback
        feedback = store.get_feedback(unresolved_only=True)
        if feedback:
            blocking = [f for f in feedback if f.get('severity') == 'BLOCKING']
            print(f"FEEDBACK: {len(feedback)} unresolved ({len(blocking)} blocking)")
            for f in blocking[:3]:
                print(f"  BLOCKING {f['from']} → {f.get('to','all')}: {f['message'][:60]}")
            print()

        # Show dependency conflicts
        conflicts = store.get_dependency_conflicts()
        if conflicts:
            print(f"DEPENDENCY CONFLICTS: {len(conflicts)}")
            for c in conflicts:
                print(f"  {c['ecosystem']}:{c['name']} — {len(c['conflicts'])} conflicting version(s)")
            print()

    print(f"{'━' * 55}")


def cmd_update_context(args):
    """Update a section of context.md."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    context_file = workspace / CONTEXT_FILE

    if not context_file.exists():
        print("No workspace found. Run: workspace.py init")
        sys.exit(1)

    content = context_file.read_text()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    new_entry = f"\n### {args.key} — {timestamp}\n\n{args.value}\n"

    if '## Agent Notes' in content:
        content = content.replace('_(Each agent appends findings here)_', '')
        content += new_entry
    else:
        content += f"\n## Agent Notes\n{new_entry}"

    context_file.write_text(content)
    print(f"Context updated: {args.key}")


def cmd_get_context(args):
    """Print the current context."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    context_file = workspace / CONTEXT_FILE

    if not context_file.exists():
        print("No workspace found. Run: workspace.py init")
        sys.exit(1)

    print(context_file.read_text())


def cmd_new_adr(args):
    """Create a new Architectural Decision Record."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    decisions_dir = workspace / DECISIONS_DIR
    decisions_dir.mkdir(parents=True, exist_ok=True)

    existing = list(decisions_dir.glob('ADR-*.md'))
    next_num = len(existing) + 1
    adr_num = f"{next_num:03d}"

    slug = re.sub(r'[^a-z0-9]+', '-', args.title.lower()).strip('-')[:50]
    filename = f"ADR-{adr_num}-{slug}.md"
    filepath = decisions_dir / filename

    tag_list = [t.strip() for t in getattr(args, 'tags', '').split(',') if t.strip()]
    decider_list = [d.strip() for d in getattr(args, 'deciders', '').split(',') if d.strip()]
    fm = {
        'id': f'ADR-{adr_num}',
        'title': args.title,
        'type': 'adr',
        'status': 'proposed',
        'date': datetime.now().strftime('%Y-%m-%d'),
        'tags': tag_list,
        'deciders': decider_list,
        'supersedes': getattr(args, 'supersedes', None),
        'related': [],
    }

    if args.content:
        content = render_frontmatter(fm) + args.content
    else:
        body = f"""# ADR-{adr_num}: {args.title}

**Date**: {datetime.now().strftime('%Y-%m-%d')}
**Status**: Proposed
**Deciders**: {', '.join(decider_list) if decider_list else 'Dev Team'}

## Context

_(Describe the problem and why a decision is needed)_

## Decision

_(State the decision clearly)_

## Consequences

- **Positive**:
- **Negative**:
- **Risks**:
"""
        content = render_frontmatter(fm) + body

    filepath.write_text(content)
    print(f"ADR created: {filepath}")
    return str(filepath)


def cmd_list_adrs(args):
    """List all ADRs."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    decisions_dir = workspace / DECISIONS_DIR

    if not decisions_dir.exists():
        print("No decisions directory found.")
        return

    adrs = sorted(decisions_dir.glob('ADR-*.md'))
    if not adrs:
        print("No ADRs found.")
        return

    print(f"\nARCHITECTURAL DECISION RECORDS ({len(adrs)})")
    print(f"{'─' * 55}")
    for adr in adrs:
        try:
            fm, _ = load_artifact(adr)
            status = fm.get('status', 'unknown')
            tags_str = ', '.join(fm.get('tags', []))
            tags_display = f" [{tags_str}]" if tags_str else ''
        except Exception:
            status = 'unknown'
            tags_display = ''
        print(f"  {adr.name:<50} [{status}]{tags_display}")
    print()


def cmd_new_requirement(args):
    """Create a new requirements document."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    requirements_dir = workspace / REQUIREMENTS_DIR
    requirements_dir.mkdir(parents=True, exist_ok=True)

    existing = list(requirements_dir.glob('REQ-*.md'))
    next_num = len(existing) + 1
    req_num = f"{next_num:03d}"

    slug = re.sub(r'[^a-z0-9]+', '-', args.feature.lower()).strip('-')[:50]
    filename = f"REQ-{req_num}-{slug}.md"
    filepath = requirements_dir / filename

    tag_list = [t.strip() for t in getattr(args, 'tags', '').split(',') if t.strip()]
    agent_list = [a.strip() for a in getattr(args, 'agents', '').split(',') if a.strip()]
    status = getattr(args, 'status', 'draft')
    fm = {
        'id': f'REQ-{req_num}',
        'title': args.title,
        'type': 'requirement',
        'status': status,
        'date': datetime.now().strftime('%Y-%m-%d'),
        'feature': args.feature,
        'tags': tag_list,
        'agents': agent_list,
    }

    if args.content:
        content = render_frontmatter(fm) + args.content
    else:
        body = f"""# REQ-{req_num}: {args.title}

**Feature**: {args.feature}
**Status**: {status.capitalize()}
**Date**: {datetime.now().strftime('%Y-%m-%d')}

## Problem Statement

_(Describe the user need or problem being solved)_

## Functional Requirements

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| FR-1 | ... | Must Have | ... |

## Non-Functional Requirements

| ID | Category | Requirement |
|----|----------|-------------|
| NFR-1 | ... | ... |

## Out of Scope

- ...

## Open Questions

| Question | Owner |
|----------|-------|
| ... | ... |
"""
        content = render_frontmatter(fm) + body

    filepath.write_text(content)
    print(f"Requirement created: {filepath}")
    return str(filepath)


def cmd_query(args):
    """Query artifacts by frontmatter fields."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )

    artifact_type = getattr(args, 'type', None)
    filter_status = getattr(args, 'status', None)
    filter_tags_raw = getattr(args, 'tags', None)
    filter_tags = set(t.strip() for t in filter_tags_raw.split(',') if t.strip()) if filter_tags_raw else set()
    filter_related = getattr(args, 'related', None)
    filter_supersedes = getattr(args, 'supersedes', None)
    fmt = getattr(args, 'format', 'json')

    paths = []
    if not artifact_type or artifact_type == 'adr':
        decisions_dir = workspace / DECISIONS_DIR
        if decisions_dir.exists():
            paths.extend(sorted(decisions_dir.glob('ADR-*.md')))
    if not artifact_type or artifact_type == 'requirement':
        requirements_dir = workspace / REQUIREMENTS_DIR
        if requirements_dir.exists():
            paths.extend(sorted(requirements_dir.glob('*.md')))

    results = []
    for path in paths:
        try:
            fm, _ = load_artifact(path)
        except Exception:
            continue

        if filter_status and fm.get('status', '').lower() != filter_status.lower():
            continue
        if filter_tags and not (filter_tags & set(fm.get('tags', []))):
            continue
        if filter_related and filter_related not in fm.get('related', []):
            continue
        if filter_supersedes and fm.get('supersedes') != filter_supersedes:
            continue

        results.append({
            'id': fm.get('id', path.stem),
            'title': fm.get('title', ''),
            'type': fm.get('type', 'unknown'),
            'status': fm.get('status', 'unknown'),
            'date': fm.get('date', ''),
            'tags': fm.get('tags', []),
            'file': str(path),
            'legacy': fm.get('_legacy', False),
        })

    if fmt == 'table':
        if not results:
            print("No matching artifacts.")
            return
        print(f"\n{'ID':<12} {'TYPE':<12} {'STATUS':<12} {'TAGS':<30} TITLE")
        print('─' * 90)
        for r in results:
            tags_str = ', '.join(r['tags'])
            print(f"  {r['id']:<10} {r['type']:<12} {r['status']:<12} {tags_str:<30} {r['title']}")
        print()
    else:
        print(json.dumps(results, indent=2))


def cmd_search(args):
    """Full-text search across artifact bodies."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )

    artifact_type = getattr(args, 'type', None)
    search_text = args.text
    fmt = getattr(args, 'format', 'json')

    paths = []
    if not artifact_type or artifact_type == 'adr':
        decisions_dir = workspace / DECISIONS_DIR
        if decisions_dir.exists():
            paths.extend(sorted(decisions_dir.glob('ADR-*.md')))
    if not artifact_type or artifact_type == 'requirement':
        requirements_dir = workspace / REQUIREMENTS_DIR
        if requirements_dir.exists():
            paths.extend(sorted(requirements_dir.glob('*.md')))

    results = []
    for path in paths:
        try:
            full_text = path.read_text()
            fm, _ = load_artifact(path)
        except Exception:
            continue

        if search_text.lower() not in full_text.lower():
            continue

        results.append({
            'id': fm.get('id', path.stem),
            'title': fm.get('title', ''),
            'type': fm.get('type', 'unknown'),
            'status': fm.get('status', 'unknown'),
            'tags': fm.get('tags', []),
            'file': str(path),
            'snippet': _extract_snippet(full_text, search_text),
        })

    if fmt == 'table':
        if not results:
            print(f"No matches for '{search_text}'.")
            return
        print(f"\nSearch results for '{search_text}' ({len(results)} match{'es' if len(results) != 1 else ''}):")
        print('─' * 80)
        for r in results:
            print(f"  [{r['id']}] {r['title']}")
            print(f"    {r['file']}")
            if r['snippet']:
                print(f"    ...{r['snippet']}...")
            print()
    else:
        print(json.dumps(results, indent=2))


def cmd_migrate_frontmatter(args):
    """Backfill YAML frontmatter on existing legacy artifacts."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )

    artifact_type = getattr(args, 'type', 'all')
    dry_run = getattr(args, 'dry_run', False)

    paths = []
    if artifact_type in ('adr', 'all'):
        decisions_dir = workspace / DECISIONS_DIR
        if decisions_dir.exists():
            paths.extend(sorted(decisions_dir.glob('ADR-*.md')))
    if artifact_type in ('requirement', 'all'):
        requirements_dir = workspace / REQUIREMENTS_DIR
        if requirements_dir.exists():
            paths.extend(sorted(requirements_dir.glob('*.md')))

    migrated = 0
    skipped = 0
    for path in paths:
        try:
            fm, body = load_artifact(path)
        except Exception as e:
            print(f"  SKIP  {path.name}: read error ({e})")
            continue

        if not fm.get('_legacy'):
            skipped += 1
            continue

        # Reconstruct frontmatter from body fields
        stem = path.stem  # e.g. ADR-001-use-jwt
        parts = stem.split('-', 2)
        artifact_id = f"{parts[0]}-{parts[1]}" if len(parts) >= 2 else stem

        m_title = re.search(r'^#\s+(?:ADR-\d+:\s*|REQ-\d+:\s*)?(.+)', body, re.MULTILINE)
        title = m_title.group(1).strip() if m_title else fm.get('title', stem)

        m_date = re.search(r'\*\*Date\*\*:\s*(\S+)', body)
        m_deciders = re.search(r'\*\*Deciders\*\*:\s*(.+)', body)

        guessed_type = 'adr' if artifact_id.startswith('ADR') else 'requirement'
        new_fm = {
            'id': artifact_id,
            'title': title,
            'type': guessed_type,
            'status': fm.get('status', 'proposed'),
            'date': m_date.group(1) if m_date else datetime.now().strftime('%Y-%m-%d'),
        }
        if guessed_type == 'adr':
            deciders_raw = m_deciders.group(1).strip() if m_deciders else ''
            new_fm['tags'] = []
            new_fm['deciders'] = [d.strip() for d in deciders_raw.split(',') if d.strip()]
            new_fm['supersedes'] = None
            new_fm['related'] = []
        else:
            new_fm['feature'] = parts[2].replace('-', ' ') if len(parts) >= 3 else ''
            new_fm['tags'] = []
            new_fm['agents'] = []

        new_content = render_frontmatter(new_fm) + body

        if dry_run:
            print(f"  DRY-RUN  {path.name}")
            print(render_frontmatter(new_fm))
        else:
            path.write_text(new_content)
            print(f"  MIGRATED  {path.name}")

        migrated += 1

    action = "Would migrate" if dry_run else "Migrated"
    print(f"\n{action} {migrated} file(s). {skipped} already had frontmatter.")


def cmd_set_status(args):
    """Update agent status."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    store = get_store(workspace)

    if store:
        store.set_status(args.agent or 'unknown', args.phase, args.detail or '')
    else:
        status_file = workspace / STATUS_FILE
        if not status_file.exists():
            cmd_init(args)
        status = json.loads(status_file.read_text())
        status['last_updated'] = datetime.now().isoformat()
        if args.agent:
            status['agents'][args.agent] = {
                'status': args.phase,
                'detail': args.detail or '',
                'updated': datetime.now().isoformat(),
            }
        if args.phase:
            status['current_phase'] = args.phase
        status_file.write_text(json.dumps(status, indent=2))

    print(f"Status updated: {args.agent} → {args.phase}")


def cmd_add_task(args):
    """Add a task to the status tracker."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    store = get_store(workspace)

    if store:
        task_id = store.add_task(args.description, args.agent or 'unassigned')
        print(f"Task added: [{task_id}] {args.description}")
    else:
        status_file = workspace / STATUS_FILE
        if not status_file.exists():
            cmd_init(args)
        status = json.loads(status_file.read_text())
        task = {
            'id': len(status.get('tasks', [])) + 1,
            'description': args.description,
            'agent': args.agent or 'unassigned',
            'done': False,
            'created': datetime.now().isoformat(),
        }
        status.setdefault('tasks', []).append(task)
        status['last_updated'] = datetime.now().isoformat()
        status_file.write_text(json.dumps(status, indent=2))
        print(f"Task added: [{task['id']}] {args.description}")


def cmd_complete_task(args):
    """Mark a task as complete."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    store = get_store(workspace)
    task_id = int(args.task_id)

    if store:
        if store.complete_task(task_id):
            print(f"Task {task_id} completed.")
        else:
            print(f"Task {task_id} not found.")
            sys.exit(1)
    else:
        status_file = workspace / STATUS_FILE
        if not status_file.exists():
            print("No workspace found.")
            sys.exit(1)
        status = json.loads(status_file.read_text())
        for task in status.get('tasks', []):
            if task['id'] == task_id:
                task['done'] = True
                task['completed'] = datetime.now().isoformat()
                status_file.write_text(json.dumps(status, indent=2))
                print(f"Task {task_id} completed: {task['description']}")
                return
        print(f"Task {task_id} not found.")
        sys.exit(1)


def cmd_compress_context(args):
    """Summarize and compress context.md."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    context_file = workspace / CONTEXT_FILE
    history_dir = workspace / CONTEXT_HISTORY_DIR

    if not context_file.exists():
        print("No context.md found. Run: workspace.py init")
        sys.exit(1)

    content = context_file.read_text()
    original_size = len(content)

    if original_size < 4000:
        print(f"Context is only {original_size} chars — compression not needed yet.")
        return

    history_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    archive_path = history_dir / f'context-{timestamp}.md'
    archive_path.write_text(content)
    print(f"Archived original context to {archive_path}")

    compressed = None
    try:
        import anthropic as _anthropic
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if api_key:
            client = _anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=2000,
                system=(
                    "You are a technical summarizer for a software development team workspace. "
                    "Compress this context document by: "
                    "1) Keeping the Project Overview and Patterns sections intact. "
                    "2) Summarizing the Agent Notes section into a concise bullet list of key decisions, "
                    "findings, and current state — removing redundant or superseded entries. "
                    "3) Preserving all file paths, ADR references, and specific technical decisions. "
                    "Output clean markdown."
                ),
                messages=[{'role': 'user', 'content': f"Compress this workspace context:\n\n{content[:12000]}"}],
            )
            compressed = response.content[0].text
            print("Used Claude to intelligently compress context")
        else:
            print("Note: ANTHROPIC_API_KEY not set — falling back to truncation")
    except ImportError:
        print("Note: anthropic package not installed — falling back to truncation")
    except Exception as e:
        print(f"Note: Claude summarization failed ({e}) — falling back to truncation")

    if compressed is None:
        lines = content.splitlines()
        cutoff = max(0, len(lines) - 80)
        compressed = (
            f"# Dev Team Workspace (Compressed {timestamp})\n\n"
            f"_Original archived to {archive_path.name}. Showing recent entries only._\n\n"
            + '\n'.join(lines[cutoff:])
        )

    header = (
        f"\n\n---\n_Context compressed {datetime.now().strftime('%Y-%m-%d %H:%M')}. "
        f"Full history in {CONTEXT_HISTORY_DIR}/._\n\n---\n\n"
    )
    context_file.write_text(compressed + header)

    new_size = len(context_file.read_text())
    reduction = round((1 - new_size / original_size) * 100)
    print(f"Context compressed: {original_size} → {new_size} chars ({reduction}% reduction)")


# ─── New commands: feedback, security, dependencies, rollback ──────────────────

def cmd_push_feedback(args):
    """Push feedback from one agent to another."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    store = get_store(workspace)
    if not store:
        print("Error: store.py not found. Cannot push feedback.")
        sys.exit(1)

    store.push_feedback(
        from_agent=args.from_agent,
        to_agent=args.to_agent,
        message=args.message,
        severity=args.severity,
        stage=getattr(args, 'stage', None),
    )
    print(f"Feedback [{args.severity}] pushed: {args.from_agent} → {args.to_agent}")
    if args.severity == 'BLOCKING':
        print("  WARNING: This is a BLOCKING message — the pipeline will pause.")


def cmd_get_feedback(args):
    """Show feedback messages."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    store = get_store(workspace)
    if not store:
        print("Error: store.py not found.")
        sys.exit(1)

    items = store.get_feedback(
        to_agent=getattr(args, 'to_agent', None),
        unresolved_only=not getattr(args, 'show_all', False),
    )

    if not items:
        print("No feedback messages.")
        return

    print(f"\nFEEDBACK MESSAGES ({len(items)})")
    print('─' * 55)
    for f in items:
        resolved = ' [resolved]' if f.get('resolved') else ''
        stage_str = f" (stage {f['stage']})" if f.get('stage') else ''
        print(f"  [{f['severity']}]{stage_str} {f['from']} → {f.get('to', 'all')}{resolved}")
        print(f"    {f['message']}")
    print()


def cmd_set_security_verdict(args):
    """Record the security agent's verdict."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    store = get_store(workspace)
    if not store:
        print("Error: store.py not found.")
        sys.exit(1)

    findings = [x.strip() for x in args.findings.split(',') if x.strip()] if args.findings else []
    store.set_security_verdict(
        verdict=args.verdict,
        findings=findings,
        critical_count=getattr(args, 'critical', 0) or 0,
        high_count=getattr(args, 'high', 0) or 0,
    )
    print(f"Security verdict recorded: {args.verdict}")
    if args.verdict == 'BLOCKED':
        print("  PIPELINE BLOCKED — lead-agent will not proceed until this is cleared.")


def cmd_get_security_verdict(args):
    """Show current security verdict."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    store = get_store(workspace)
    if not store:
        print("Error: store.py not found.")
        sys.exit(1)

    v = store.get_security_verdict()
    if not v:
        print("No security verdict recorded.")
        return

    emoji = {'CLEAR': '✅', 'WARNINGS': '⚠️', 'REMEDIATION_REQUIRED': '🔄', 'BLOCKED': '❌'}
    verdict = v['verdict']
    print(f"\nSECURITY VERDICT: {emoji.get(verdict, '?')} {verdict}")
    print(f"  Critical: {v.get('critical_count', 0)}")
    print(f"  High:     {v.get('high_count', 0)}")
    print(f"  Recorded: {v.get('timestamp', 'unknown')}")
    if v.get('findings'):
        print("  Findings:")
        for f in v['findings']:
            print(f"    - {f}")
    print()


def cmd_add_dependency(args):
    """Record a dependency added by an agent."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    store = get_store(workspace)
    if not store:
        print("Error: store.py not found.")
        sys.exit(1)

    store.add_dependency(args.name, args.version, args.added_by,
                         getattr(args, 'ecosystem', 'unknown') or 'unknown')
    print(f"Dependency recorded: {args.name}@{args.version}")

    conflicts = store.get_dependency_conflicts()
    if conflicts:
        print(f"  WARNING: {len(conflicts)} version conflict(s) detected — run check-conflicts")


def cmd_check_conflicts(args):
    """List dependency version conflicts."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    store = get_store(workspace)
    if not store:
        print("Error: store.py not found.")
        sys.exit(1)

    conflicts = store.get_dependency_conflicts()
    if not conflicts:
        print("No dependency version conflicts detected.")
        return

    print(f"\nDEPENDENCY CONFLICTS ({len(conflicts)})")
    print('─' * 55)
    for dep in conflicts:
        print(f"  CONFLICT: {dep['ecosystem']}:{dep['name']}")
        print(f"    Registered: {dep['version']} (by {dep['added_by']})")
        for c in dep['conflicts']:
            print(f"    Conflict:   {c['version']} (by {c['added_by']})")
    print()


def cmd_rollback(args):
    """
    Rollback pipeline to the state before a given stage.

    Reads file snapshots from the execution log and restores files
    to their pre-stage contents. This undoes all changes made in
    stages >= the specified stage number.
    """
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    store = get_store(workspace)
    if not store:
        print("Error: store.py not found. Cannot rollback.")
        sys.exit(1)

    target_stage = int(args.to_stage)
    last_ok = store.get_last_successful_stage()

    print(f"\nROLLBACK: reverting to state before stage {target_stage}")
    print(f"  Last successful stage: {last_ok}")

    if target_stage > last_ok:
        print(f"  Nothing to rollback — stage {target_stage} was not reached or did not complete.")
        return

    # Collect all snapshots for stages >= target_stage, in reverse order
    log = store.get_execution_log()
    snapshots = [
        e for e in log
        if e.get('type') == 'file_snapshot' and e.get('stage', 0) >= target_stage
    ]

    # Sort by timestamp desc so we restore in reverse-chronological order
    snapshots.sort(key=lambda e: e.get('timestamp', ''), reverse=True)

    # Deduplicate: only keep the earliest snapshot per file
    # (the earliest = state before any modification in this range)
    seen_files: set[str] = set()
    to_restore = []
    for snap in reversed(snapshots):
        path = snap['path']
        if path not in seen_files:
            seen_files.add(path)
            to_restore.append(snap)

    if not to_restore:
        print("  No file snapshots found for that stage range — nothing to restore.")
        return

    restored = 0
    deleted = 0
    project_root = workspace.parent  # workspace is <project>/.dev-team

    for snap in to_restore:
        file_path = project_root / snap['path']
        before = snap.get('before')

        if before is None:
            # File didn't exist before this stage — delete it
            if file_path.exists():
                file_path.unlink()
                print(f"  DELETED:  {snap['path']}")
                deleted += 1
        else:
            # Restore original contents
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(before)
            print(f"  RESTORED: {snap['path']}")
            restored += 1

    print(f"\nRollback complete: {restored} file(s) restored, {deleted} file(s) deleted")
    print(f"Pipeline state reset to before stage {target_stage}.")


def cmd_show_log(args):
    """Show the pipeline execution log."""
    workspace = find_workspace(
        getattr(args, 'project_root', None),
        getattr(args, 'workspace_root', None),
    )
    store = get_store(workspace)
    if not store:
        print("Error: store.py not found.")
        sys.exit(1)

    log = store.get_execution_log()
    if not log:
        print("Execution log is empty.")
        return

    print(f"\nEXECUTION LOG ({len(log)} entries)")
    print('─' * 55)
    for entry in log:
        t = entry.get('timestamp', '')[:19].replace('T', ' ')
        if entry['type'] == 'stage_start':
            print(f"  {t}  STAGE {entry['stage']} START  → {', '.join(entry['agents'])}")
        elif entry['type'] == 'stage_complete':
            ok = '✓' if entry.get('success') else '✗'
            print(f"  {t}  STAGE {entry['stage']} DONE [{ok}] → {', '.join(entry['agents'])}")
        elif entry['type'] == 'file_snapshot':
            exists = 'existed' if entry.get('before') is not None else 'new'
            print(f"  {t}  SNAPSHOT  stage={entry['stage']}  {entry['path']} ({exists})")
    print()


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Dev Team Workspace Manager'
    )
    parser.add_argument('--project-root', default=None,
                        help='Project root (workspace will be <root>/.dev-team)')
    parser.add_argument('--workspace-root', default=None,
                        help='Override workspace directory directly (multi-repo use)')

    subparsers = parser.add_subparsers(dest='command')

    # init
    p = subparsers.add_parser('init', help='Initialize the workspace')
    p.set_defaults(func=cmd_init)

    # status
    p = subparsers.add_parser('status', help='Show workspace status')
    p.set_defaults(func=cmd_status)

    # get-context
    p = subparsers.add_parser('get-context', help='Print context.md')
    p.set_defaults(func=cmd_get_context)

    # update-context
    p = subparsers.add_parser('update-context', help='Update context.md with a new entry')
    p.add_argument('--key', required=True)
    p.add_argument('--value', required=True)
    p.set_defaults(func=cmd_update_context)

    # new-adr
    p = subparsers.add_parser('new-adr', help='Create a new ADR')
    p.add_argument('--title', required=True)
    p.add_argument('--content', help='ADR content (uses template if omitted)')
    p.add_argument('--tags', default='', help='Comma-separated tags (e.g. auth,security)')
    p.add_argument('--deciders', default='', help='Comma-separated decider names')
    p.add_argument('--supersedes', default=None, help='ADR ID this supersedes (e.g. ADR-001)')
    p.set_defaults(func=cmd_new_adr)

    # list-adrs
    p = subparsers.add_parser('list-adrs', help='List all ADRs')
    p.set_defaults(func=cmd_list_adrs)

    # new-requirement
    p = subparsers.add_parser('new-requirement', help='Create a new requirements document')
    p.add_argument('--title', required=True)
    p.add_argument('--feature', required=True, help='Feature slug (used for filename)')
    p.add_argument('--status', default='draft',
                   choices=['draft', 'approved', 'implemented', 'deprecated'])
    p.add_argument('--tags', default='', help='Comma-separated tags')
    p.add_argument('--agents', default='', help='Comma-separated agent names')
    p.add_argument('--content', help='Full content (uses template if omitted)')
    p.set_defaults(func=cmd_new_requirement)

    # query
    p = subparsers.add_parser('query', help='Query artifacts by frontmatter fields')
    p.add_argument('--type', choices=['adr', 'requirement'], help='Filter by artifact type')
    p.add_argument('--status', help='Filter by status (e.g. proposed, accepted, draft)')
    p.add_argument('--tags', help='Comma-separated tags (any match)')
    p.add_argument('--related', help='Find artifacts referencing this ID')
    p.add_argument('--supersedes', help='Find artifacts that supersede this ID')
    p.add_argument('--format', choices=['json', 'table'], default='json')
    p.set_defaults(func=cmd_query)

    # search
    p = subparsers.add_parser('search', help='Full-text search across artifact bodies')
    p.add_argument('--text', required=True, help='Text to search for')
    p.add_argument('--type', choices=['adr', 'requirement'], help='Limit search to artifact type')
    p.add_argument('--format', choices=['json', 'table'], default='json')
    p.set_defaults(func=cmd_search)

    # migrate-frontmatter
    p = subparsers.add_parser('migrate-frontmatter',
                               help='Backfill YAML frontmatter on existing artifacts')
    p.add_argument('--type', choices=['adr', 'requirement', 'all'], default='all')
    p.add_argument('--dry-run', action='store_true', help='Print changes without writing')
    p.set_defaults(func=cmd_migrate_frontmatter)

    # set-status
    p = subparsers.add_parser('set-status', help='Update agent status')
    p.add_argument('--agent', help='Agent name')
    p.add_argument('--phase', required=True)
    p.add_argument('--detail', help='Additional detail')
    p.set_defaults(func=cmd_set_status)

    # add-task
    p = subparsers.add_parser('add-task', help='Add a task to the tracker')
    p.add_argument('--description', required=True)
    p.add_argument('--agent', help='Assigned agent')
    p.set_defaults(func=cmd_add_task)

    # complete-task
    p = subparsers.add_parser('complete-task', help='Mark a task as done')
    p.add_argument('--task-id', required=True)
    p.set_defaults(func=cmd_complete_task)

    # compress-context
    p = subparsers.add_parser('compress-context', help='Compress context.md (archives full history first)')
    p.set_defaults(func=cmd_compress_context)

    # push-feedback
    p = subparsers.add_parser('push-feedback', help='Push feedback from one agent to another')
    p.add_argument('--from', dest='from_agent', required=True, help='Sender agent name')
    p.add_argument('--to', dest='to_agent', required=True, help='Recipient agent name')
    p.add_argument('--message', required=True, help='Feedback message')
    p.add_argument('--severity', default='INFO', choices=['INFO', 'WARNING', 'BLOCKING'])
    p.add_argument('--stage', type=int, default=None, help='Pipeline stage number')
    p.set_defaults(func=cmd_push_feedback)

    # get-feedback
    p = subparsers.add_parser('get-feedback', help='Show feedback messages')
    p.add_argument('--to', dest='to_agent', default=None, help='Filter by recipient agent')
    p.add_argument('--all', dest='show_all', action='store_true', help='Show resolved too')
    p.set_defaults(func=cmd_get_feedback)

    # set-security-verdict
    p = subparsers.add_parser('set-security-verdict', help='Record security verdict')
    p.add_argument('--verdict', required=True,
                   choices=['CLEAR', 'WARNINGS', 'REMEDIATION_REQUIRED', 'BLOCKED'])
    p.add_argument('--findings', default='', help='Comma-separated findings list')
    p.add_argument('--critical', type=int, default=0, help='Number of critical findings')
    p.add_argument('--high', type=int, default=0, help='Number of high findings')
    p.set_defaults(func=cmd_set_security_verdict)

    # get-security-verdict
    p = subparsers.add_parser('get-security-verdict', help='Show current security verdict')
    p.set_defaults(func=cmd_get_security_verdict)

    # add-dependency
    p = subparsers.add_parser('add-dependency', help='Record a dependency added by an agent')
    p.add_argument('--name', required=True, help='Package name')
    p.add_argument('--version', required=True, help='Package version')
    p.add_argument('--added-by', required=True, dest='added_by', help='Agent that added it')
    p.add_argument('--ecosystem', default='unknown', help='Package ecosystem (npm, pip, cargo, etc.)')
    p.set_defaults(func=cmd_add_dependency)

    # check-conflicts
    p = subparsers.add_parser('check-conflicts', help='Check for dependency version conflicts')
    p.set_defaults(func=cmd_check_conflicts)

    # rollback
    p = subparsers.add_parser('rollback', help='Roll back pipeline to before a given stage')
    p.add_argument('--to-stage', required=True, metavar='N',
                   help='Revert all changes from stage N onward')
    p.set_defaults(func=cmd_rollback)

    # show-log
    p = subparsers.add_parser('show-log', help='Show pipeline execution log')
    p.set_defaults(func=cmd_show_log)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == '__main__':
    main()
