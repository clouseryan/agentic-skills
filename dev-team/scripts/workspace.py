#!/usr/bin/env python3
"""
Workspace Manager — Dev Team Helper Script

Manages the .dev-team/ shared workspace: initialization, context updates,
status tracking, and Architectural Decision Records (ADRs).

Usage:
  python3 workspace.py init --project-root .
  python3 workspace.py status
  python3 workspace.py update-context --key "research" --value "..."
  python3 workspace.py new-adr --title "Use Redis for caching" --content "..."
  python3 workspace.py list-adrs
  python3 workspace.py set-status --agent "dev-agent" --phase "implementing" --detail "..."
  python3 workspace.py get-context
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


WORKSPACE_DIR = '.dev-team'
PATTERNS_FILE = 'patterns.json'
CONTEXT_FILE = 'context.md'
STATUS_FILE = 'status.json'
DECISIONS_DIR = 'decisions'


def find_workspace(project_root: str | None = None) -> Path:
    """Find or create the workspace directory."""
    if project_root:
        workspace = Path(project_root) / WORKSPACE_DIR
    else:
        # Search upward from cwd
        cwd = Path.cwd()
        for parent in [cwd] + list(cwd.parents):
            candidate = parent / WORKSPACE_DIR
            if candidate.exists():
                return candidate
        workspace = cwd / WORKSPACE_DIR

    return workspace


def cmd_init(args):
    """Initialize the .dev-team workspace."""
    workspace = find_workspace(args.project_root)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / DECISIONS_DIR).mkdir(exist_ok=True)

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
        project_name = Path(args.project_root or '.').resolve().name
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

    # Initialize status.json if missing
    status_file = workspace / STATUS_FILE
    if not status_file.exists():
        status_file.write_text(json.dumps({
            'last_updated': None,
            'current_phase': 'idle',
            'agents': {},
            'tasks': [],
        }, indent=2))

    print(f"✓ Workspace initialized at {workspace}")
    print(f"  {workspace / PATTERNS_FILE}")
    print(f"  {workspace / CONTEXT_FILE}")
    print(f"  {workspace / STATUS_FILE}")
    print(f"  {workspace / DECISIONS_DIR}/")


def cmd_status(args):
    """Show current workspace status."""
    workspace = find_workspace(args.project_root)
    status_file = workspace / STATUS_FILE

    if not status_file.exists():
        print("No workspace found. Run: workspace.py init")
        sys.exit(1)

    status = json.loads(status_file.read_text())

    print(f"\n{'━' * 50}")
    print(f"DEV TEAM WORKSPACE STATUS")
    print(f"{'━' * 50}")
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

    print(f"{'━' * 50}")


def cmd_update_context(args):
    """Update a section of context.md."""
    workspace = find_workspace(args.project_root)
    context_file = workspace / CONTEXT_FILE

    if not context_file.exists():
        print("No workspace found. Run: workspace.py init")
        sys.exit(1)

    content = context_file.read_text()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')

    # Add an agent notes section
    new_entry = f"\n### {args.key} — {timestamp}\n\n{args.value}\n"

    # Append to Agent Notes section
    if '## Agent Notes' in content:
        content = content.replace(
            '_(Each agent appends findings here)_',
            ''
        )
        content += new_entry
    else:
        content += f"\n## Agent Notes\n{new_entry}"

    context_file.write_text(content)
    print(f"✓ Context updated: {args.key}")


def cmd_get_context(args):
    """Print the current context."""
    workspace = find_workspace(args.project_root)
    context_file = workspace / CONTEXT_FILE

    if not context_file.exists():
        print("No workspace found. Run: workspace.py init")
        sys.exit(1)

    print(context_file.read_text())


def cmd_new_adr(args):
    """Create a new Architectural Decision Record."""
    workspace = find_workspace(args.project_root)
    decisions_dir = workspace / DECISIONS_DIR
    decisions_dir.mkdir(parents=True, exist_ok=True)

    # Find next ADR number
    existing = list(decisions_dir.glob('ADR-*.md'))
    next_num = len(existing) + 1
    adr_num = f"{next_num:03d}"

    # Create slug from title
    slug = re.sub(r'[^a-z0-9]+', '-', args.title.lower()).strip('-')[:50]
    filename = f"ADR-{adr_num}-{slug}.md"
    filepath = decisions_dir / filename

    if args.content:
        content = args.content
    else:
        content = f"""# ADR-{adr_num}: {args.title}

**Date**: {datetime.now().strftime('%Y-%m-%d')}
**Status**: Proposed
**Deciders**: Dev Team

## Context

_(Describe the problem and why a decision is needed)_

## Decision

_(State the decision clearly)_

## Consequences

- **Positive**:
- **Negative**:
- **Risks**:
"""

    filepath.write_text(content)
    print(f"✓ ADR created: {filepath}")
    return str(filepath)


def cmd_list_adrs(args):
    """List all ADRs."""
    workspace = find_workspace(args.project_root)
    decisions_dir = workspace / DECISIONS_DIR

    if not decisions_dir.exists():
        print("No decisions directory found.")
        return

    adrs = sorted(decisions_dir.glob('ADR-*.md'))
    if not adrs:
        print("No ADRs found.")
        return

    print(f"\nARCHITECTURAL DECISION RECORDS ({len(adrs)})")
    print(f"{'─' * 50}")
    for adr in adrs:
        # Try to extract status from content
        try:
            content = adr.read_text()
            status_match = re.search(r'\*\*Status\*\*:\s*(\w+)', content)
            status = status_match.group(1) if status_match else 'unknown'
        except Exception:
            status = 'unknown'
        print(f"  {adr.name:<50} [{status}]")
    print()


def cmd_set_status(args):
    """Update agent status in status.json."""
    workspace = find_workspace(args.project_root)
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
    print(f"✓ Status updated: {args.agent} → {args.phase}")


def cmd_add_task(args):
    """Add a task to the status tracker."""
    workspace = find_workspace(args.project_root)
    status_file = workspace / STATUS_FILE

    if not status_file.exists():
        cmd_init(args)

    status = json.loads(status_file.read_text())
    status['last_updated'] = datetime.now().isoformat()

    task = {
        'id': len(status.get('tasks', [])) + 1,
        'description': args.description,
        'agent': args.agent or 'unassigned',
        'done': False,
        'created': datetime.now().isoformat(),
    }

    status.setdefault('tasks', []).append(task)
    status_file.write_text(json.dumps(status, indent=2))
    print(f"✓ Task added: [{task['id']}] {args.description}")


def cmd_complete_task(args):
    """Mark a task as complete."""
    workspace = find_workspace(args.project_root)
    status_file = workspace / STATUS_FILE

    if not status_file.exists():
        print("No workspace found.")
        sys.exit(1)

    status = json.loads(status_file.read_text())
    task_id = int(args.task_id)

    for task in status.get('tasks', []):
        if task['id'] == task_id:
            task['done'] = True
            task['completed'] = datetime.now().isoformat()
            status_file.write_text(json.dumps(status, indent=2))
            print(f"✓ Task {task_id} completed: {task['description']}")
            return

    print(f"Task {task_id} not found.")
    sys.exit(1)


# Import re for slug generation (needed by cmd_new_adr)
import re


def main():
    parser = argparse.ArgumentParser(
        description='Dev Team Workspace Manager'
    )
    parser.add_argument('--project-root', default=None,
                        help='Project root directory (default: search upward from cwd)')

    subparsers = parser.add_subparsers(dest='command')

    # init
    p_init = subparsers.add_parser('init', help='Initialize the workspace')
    p_init.set_defaults(func=cmd_init)

    # status
    p_status = subparsers.add_parser('status', help='Show workspace status')
    p_status.set_defaults(func=cmd_status)

    # get-context
    p_get = subparsers.add_parser('get-context', help='Print context.md')
    p_get.set_defaults(func=cmd_get_context)

    # update-context
    p_update = subparsers.add_parser('update-context', help='Update context.md with a new entry')
    p_update.add_argument('--key', required=True, help='Section/key name')
    p_update.add_argument('--value', required=True, help='Content to add')
    p_update.set_defaults(func=cmd_update_context)

    # new-adr
    p_adr = subparsers.add_parser('new-adr', help='Create a new ADR')
    p_adr.add_argument('--title', required=True, help='ADR title')
    p_adr.add_argument('--content', help='ADR content (optional — uses template if omitted)')
    p_adr.set_defaults(func=cmd_new_adr)

    # list-adrs
    p_list = subparsers.add_parser('list-adrs', help='List all ADRs')
    p_list.set_defaults(func=cmd_list_adrs)

    # set-status
    p_set_status = subparsers.add_parser('set-status', help='Update agent status')
    p_set_status.add_argument('--agent', help='Agent name')
    p_set_status.add_argument('--phase', required=True, help='Current phase/status')
    p_set_status.add_argument('--detail', help='Additional detail')
    p_set_status.set_defaults(func=cmd_set_status)

    # add-task
    p_add_task = subparsers.add_parser('add-task', help='Add a task to the tracker')
    p_add_task.add_argument('--description', required=True, help='Task description')
    p_add_task.add_argument('--agent', help='Assigned agent')
    p_add_task.set_defaults(func=cmd_add_task)

    # complete-task
    p_complete = subparsers.add_parser('complete-task', help='Mark a task as done')
    p_complete.add_argument('--task-id', required=True, help='Task ID to complete')
    p_complete.set_defaults(func=cmd_complete_task)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == '__main__':
    main()
