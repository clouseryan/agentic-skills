#!/usr/bin/env python3
"""
Azure DevOps CLI Helper — Dev Team Helper Script

Wraps the Azure CLI (`az`) with the azure-devops extension to provide
repository, work-item, pipeline, and pull-request operations that mirror
the GitHub CLI (`gh`) operations used elsewhere in the dev team.

Prerequisites:
  pip install azure-cli
  az extension add --name azure-devops
  az login                        # or use AZURE_DEVOPS_EXT_PAT env var
  az devops configure --defaults organization=<org> project=<project>

Environment variables (optional — override az devops defaults):
  AZURE_DEVOPS_ORG       Azure DevOps organization URL, e.g. https://dev.azure.com/myorg
  AZURE_DEVOPS_PROJECT   Project name or ID
  AZURE_DEVOPS_EXT_PAT   Personal Access Token (alternative to `az login`)

Usage:
  python3 az_devops.py auth-status
  python3 az_devops.py list-work-items [--state Active] [--type Bug]
  python3 az_devops.py show-work-item --id 42
  python3 az_devops.py comment-work-item --id 42 --text "Triage report..."
  python3 az_devops.py list-prs [--status active]
  python3 az_devops.py show-pr --id 7
  python3 az_devops.py create-pr --title "..." --desc "..." --source <branch> --target main
  python3 az_devops.py approve-pr --id 7
  python3 az_devops.py request-changes-pr --id 7 --comment "..."
  python3 az_devops.py merge-pr --id 7 [--strategy squash|rebase|no-ff]
  python3 az_devops.py comment-pr --id 7 --text "..."
  python3 az_devops.py list-pipelines
  python3 az_devops.py run-pipeline --id <pipeline-id> [--branch main]
  python3 az_devops.py pipeline-status --run-id <run-id>
"""

import argparse
import json
import os
import subprocess
import sys
from typing import Any


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: list[str], capture: bool = True, check: bool = True) -> subprocess.CompletedProcess:
    """Run an az CLI command, returning the CompletedProcess."""
    env = os.environ.copy()
    result = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        env=env,
        check=False,
    )
    if check and result.returncode != 0:
        print(f"ERROR: Command failed: {' '.join(cmd)}", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)
    return result


def _az(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
    """Run `az <args>` and return the result."""
    return _run(['az', *args], capture=capture)


def _az_json(*args: str) -> Any:
    """Run an az CLI command and parse its JSON output."""
    result = _az(*args, '--output', 'json')
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"ERROR: Could not parse JSON from az output:\n{result.stdout}", file=sys.stderr)
        sys.exit(1)


def _org_project_flags() -> list[str]:
    """Return org/project flags if set via environment variables."""
    flags: list[str] = []
    org = os.environ.get('AZURE_DEVOPS_ORG')
    project = os.environ.get('AZURE_DEVOPS_PROJECT')
    if org:
        flags += ['--org', org]
    if project:
        flags += ['--project', project]
    return flags


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


# ─── Auth ──────────────────────────────────────────────────────────────────────

def auth_status() -> None:
    """Check Azure CLI authentication and devops extension status."""
    # Check az login
    result = _az('account', 'show', '--output', 'json', capture=True)
    if result.returncode != 0:
        print("NOT AUTHENTICATED — run: az login", file=sys.stderr)
        sys.exit(1)

    account = json.loads(result.stdout)
    print(f"Logged in as: {account.get('user', {}).get('name', 'unknown')}")
    print(f"Subscription: {account.get('name', 'unknown')} ({account.get('id', '')})")

    # Check azure-devops extension
    ext_result = _az('extension', 'list', '--output', 'json', capture=True)
    extensions = json.loads(ext_result.stdout) if ext_result.returncode == 0 else []
    has_devops = any(e.get('name') == 'azure-devops' for e in extensions)
    if not has_devops:
        print("WARNING: azure-devops extension not installed.", file=sys.stderr)
        print("  Run: az extension add --name azure-devops", file=sys.stderr)
    else:
        print("azure-devops extension: installed")

    # Show configured defaults
    cfg = _az('devops', 'configure', '--list', '--output', 'json', capture=True)
    if cfg.returncode == 0:
        try:
            defaults = json.loads(cfg.stdout)
            print(f"Default org:     {defaults.get('organization', '(not set)')}")
            print(f"Default project: {defaults.get('project', '(not set)')}")
        except Exception:
            pass

    print("\nStatus: AUTHENTICATED")


# ─── Work Items (Azure Boards) ─────────────────────────────────────────────────

def list_work_items(state: str | None = None, work_type: str | None = None,
                    limit: int = 50) -> None:
    """List work items (analogous to `gh issue list`)."""
    wiql = "SELECT [System.Id],[System.Title],[System.State],[System.WorkItemType] FROM WorkItems WHERE [System.TeamProject] = @project"
    if state:
        wiql += f" AND [System.State] = '{state}'"
    if work_type:
        wiql += f" AND [System.WorkItemType] = '{work_type}'"
    wiql += f" ORDER BY [System.ChangedDate] DESC"

    flags = _org_project_flags()
    data = _az_json('boards', 'query', '--wiql', wiql, *flags)
    items = data.get('workItems', []) if isinstance(data, dict) else data

    # Fetch details for each (up to limit)
    for item in items[:limit]:
        wi_id = item.get('id') or item.get('fields', {}).get('System.Id')
        if wi_id:
            detail = _az_json('boards', 'work-item', 'show', '--id', str(wi_id), *flags)
            fields = detail.get('fields', {})
            print(f"  #{wi_id}  [{fields.get('System.WorkItemType', '')}]  "
                  f"{fields.get('System.State', '')}  "
                  f"— {fields.get('System.Title', '')}")


def show_work_item(item_id: int) -> None:
    """Show details of a single work item (analogous to `gh issue view`)."""
    flags = _org_project_flags()
    data = _az_json('boards', 'work-item', 'show', '--id', str(item_id), *flags)
    _print_json(data)


def comment_work_item(item_id: int, text: str) -> None:
    """Post a comment on a work item (analogous to `gh issue comment`)."""
    flags = _org_project_flags()
    data = _az_json('boards', 'work-item', 'update', '--id', str(item_id),
                    '--discussion', text, *flags)
    print(f"Comment added to work item #{item_id}")
    _print_json(data)


def add_work_item_tag(item_id: int, tags: list[str]) -> None:
    """Add tags to a work item (analogous to `gh issue edit --add-label`)."""
    flags = _org_project_flags()
    # Tags in Azure DevOps are semicolon-separated
    tag_str = '; '.join(tags)
    _az_json('boards', 'work-item', 'update', '--id', str(item_id),
             '--fields', f'System.Tags={tag_str}', *flags)
    print(f"Tags '{tag_str}' applied to work item #{item_id}")


# ─── Pull Requests (Azure Repos) ───────────────────────────────────────────────

def list_prs(status: str = 'active') -> None:
    """List pull requests (analogous to `gh pr list`)."""
    flags = _org_project_flags()
    data = _az_json('repos', 'pr', 'list', '--status', status, *flags)
    for pr in data:
        print(f"  !{pr['pullRequestId']}  [{pr.get('status', '')}]  "
              f"{pr.get('sourceRefName', '').replace('refs/heads/', '')} → "
              f"{pr.get('targetRefName', '').replace('refs/heads/', '')}  "
              f"— {pr.get('title', '')}")


def show_pr(pr_id: int) -> None:
    """Show details of a pull request (analogous to `gh pr view`)."""
    flags = _org_project_flags()
    data = _az_json('repos', 'pr', 'show', '--id', str(pr_id), *flags)
    _print_json(data)


def create_pr(title: str, description: str, source_branch: str,
              target_branch: str = 'main', draft: bool = False) -> None:
    """Create a pull request (analogous to `gh pr create`)."""
    flags = _org_project_flags()
    cmd = [
        'repos', 'pr', 'create',
        '--title', title,
        '--description', description,
        '--source-branch', source_branch,
        '--target-branch', target_branch,
        '--output', 'json',
        *flags,
    ]
    if draft:
        cmd.append('--draft')

    result = _az(*cmd)
    data = json.loads(result.stdout)
    pr_id = data.get('pullRequestId')
    url = data.get('url', '')
    print(f"\n{'━' * 60}")
    print(f"[LEAD] PR Created")
    print(f"  PR:     !{pr_id} — {title}")
    print(f"  URL:    {url}")
    print(f"  Base:   {target_branch}")
    print(f"  Head:   {source_branch}")
    print(f"  Status: {'Draft' if draft else 'Open, awaiting review'}")
    print(f"{'━' * 60}")


def approve_pr(pr_id: int) -> None:
    """Approve a pull request (analogous to `gh pr review --approve`)."""
    flags = _org_project_flags()
    _az_json('repos', 'pr', 'set-vote', '--id', str(pr_id), '--vote', 'approve', *flags)
    print(f"PR !{pr_id} approved.")


def request_changes_pr(pr_id: int, comment: str) -> None:
    """Request changes on a pull request (analogous to `gh pr review --request-changes`)."""
    flags = _org_project_flags()
    _az_json('repos', 'pr', 'set-vote', '--id', str(pr_id), '--vote', 'wait-for-author', *flags)
    # Post the comment as a thread on the PR
    _az_json('repos', 'pr', 'update', '--id', str(pr_id),
             '--description', comment, *flags)
    comment_pr(pr_id, comment)
    print(f"Changes requested on PR !{pr_id}.")


def merge_pr(pr_id: int, strategy: str = 'squash', delete_source: bool = True) -> None:
    """
    Complete (merge) a pull request.

    strategy: squash | rebase | no-ff
      squash  — squash all commits into one (default; clean history)
      rebase  — rebase source commits onto target
      no-ff   — merge commit (preserves full history)
    """
    flags = _org_project_flags()
    merge_strategy_map = {
        'squash':  'squash',
        'rebase':  'rebase',
        'no-ff':   'no-fast-forward',
    }
    az_strategy = merge_strategy_map.get(strategy, 'squash')

    cmd = [
        'repos', 'pr', 'update',
        '--id', str(pr_id),
        '--status', 'completed',
        '--merge-strategy', az_strategy,
        *flags,
    ]
    if delete_source:
        cmd += ['--delete-source-branch', 'true']

    data = _az_json(*cmd)
    print(f"PR !{pr_id} merged (strategy: {strategy}).")
    _print_json(data)


def comment_pr(pr_id: int, text: str) -> None:
    """Post a comment thread on a pull request (analogous to `gh pr comment`)."""
    flags = _org_project_flags()
    data = _az_json(
        'repos', 'pr', 'reviewer', 'list',  # reuse connection test
        *flags,
    )
    # Post via the threads API
    _az_json(
        'repos', 'pr', 'thread', 'create',
        '--id', str(pr_id),
        '--comments', json.dumps([{'content': text, 'parentCommentId': 0, 'commentType': 1}]),
        *flags,
    )
    print(f"Comment posted on PR !{pr_id}.")


def pr_checks(pr_id: int) -> None:
    """Show CI/build statuses for a pull request (analogous to `gh pr checks`)."""
    flags = _org_project_flags()
    data = _az_json('repos', 'pr', 'show', '--id', str(pr_id), *flags)
    statuses = data.get('statuses', [])
    if not statuses:
        print(f"No build statuses found for PR !{pr_id}.")
        return
    for s in statuses:
        context = s.get('context', {})
        print(f"  [{s.get('state', '?').upper()}]  {context.get('genre', '')}/{context.get('name', '')}  "
              f"— {s.get('description', '')}")


# ─── Pipelines ─────────────────────────────────────────────────────────────────

def list_pipelines() -> None:
    """List Azure Pipelines (analogous to `gh workflow list`)."""
    flags = _org_project_flags()
    data = _az_json('pipelines', 'list', *flags)
    for p in data:
        print(f"  [{p.get('id')}]  {p.get('name')}  — {p.get('path', '')}")


def run_pipeline(pipeline_id: int, branch: str = 'main',
                 variables: dict | None = None) -> None:
    """Trigger a pipeline run (analogous to `gh workflow run`)."""
    flags = _org_project_flags()
    cmd = [
        'pipelines', 'run',
        '--id', str(pipeline_id),
        '--branch', branch,
        *flags,
    ]
    if variables:
        for k, v in variables.items():
            cmd += ['--variables', f'{k}={v}']

    data = _az_json(*cmd)
    run_id = data.get('id')
    print(f"Pipeline run triggered: run ID {run_id} (pipeline {pipeline_id}, branch: {branch})")
    _print_json(data)


def pipeline_status(run_id: int) -> None:
    """Show the status of a pipeline run."""
    flags = _org_project_flags()
    data = _az_json('pipelines', 'runs', 'show', '--id', str(run_id), *flags)
    result = data.get('result', 'unknown')
    status = data.get('status', 'unknown')
    print(f"Run {run_id}:  status={status}  result={result}")
    _print_json(data)


# ─── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Azure DevOps CLI Helper — wraps az devops/repos/boards/pipelines',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # auth-status
    sub.add_parser('auth-status', help='Check Azure CLI auth and devops extension')

    # list-work-items
    p = sub.add_parser('list-work-items', help='List Azure Boards work items')
    p.add_argument('--state', help='Filter by state, e.g. Active, Resolved, Closed')
    p.add_argument('--type', dest='work_type', help='Filter by type, e.g. Bug, Task, User Story')
    p.add_argument('--limit', type=int, default=50)

    # show-work-item
    p = sub.add_parser('show-work-item', help='Show a work item')
    p.add_argument('--id', type=int, required=True)

    # comment-work-item
    p = sub.add_parser('comment-work-item', help='Add a comment to a work item')
    p.add_argument('--id', type=int, required=True)
    p.add_argument('--text', required=True)

    # list-prs
    p = sub.add_parser('list-prs', help='List pull requests')
    p.add_argument('--status', default='active', choices=['active', 'abandoned', 'completed', 'all'])

    # show-pr
    p = sub.add_parser('show-pr', help='Show a pull request')
    p.add_argument('--id', type=int, required=True)

    # create-pr
    p = sub.add_parser('create-pr', help='Create a pull request')
    p.add_argument('--title', required=True)
    p.add_argument('--desc', default='', help='PR description / body')
    p.add_argument('--source', required=True, help='Source (feature) branch')
    p.add_argument('--target', default='main', help='Target branch (default: main)')
    p.add_argument('--draft', action='store_true')

    # approve-pr
    p = sub.add_parser('approve-pr', help='Approve a pull request')
    p.add_argument('--id', type=int, required=True)

    # request-changes-pr
    p = sub.add_parser('request-changes-pr', help='Request changes on a pull request')
    p.add_argument('--id', type=int, required=True)
    p.add_argument('--comment', required=True)

    # merge-pr
    p = sub.add_parser('merge-pr', help='Complete (merge) a pull request')
    p.add_argument('--id', type=int, required=True)
    p.add_argument('--strategy', default='squash', choices=['squash', 'rebase', 'no-ff'])
    p.add_argument('--keep-source', action='store_true', help='Do not delete source branch after merge')

    # comment-pr
    p = sub.add_parser('comment-pr', help='Post a comment on a pull request')
    p.add_argument('--id', type=int, required=True)
    p.add_argument('--text', required=True)

    # pr-checks
    p = sub.add_parser('pr-checks', help='Show CI statuses for a pull request')
    p.add_argument('--id', type=int, required=True)

    # list-pipelines
    sub.add_parser('list-pipelines', help='List Azure Pipelines')

    # run-pipeline
    p = sub.add_parser('run-pipeline', help='Trigger a pipeline run')
    p.add_argument('--id', type=int, required=True)
    p.add_argument('--branch', default='main')
    p.add_argument('--var', action='append', metavar='KEY=VALUE',
                   help='Pipeline variables (repeatable)')

    # pipeline-status
    p = sub.add_parser('pipeline-status', help='Show status of a pipeline run')
    p.add_argument('--run-id', type=int, required=True)

    args = parser.parse_args()

    if args.command == 'auth-status':
        auth_status()
    elif args.command == 'list-work-items':
        list_work_items(state=args.state, work_type=args.work_type, limit=args.limit)
    elif args.command == 'show-work-item':
        show_work_item(args.id)
    elif args.command == 'comment-work-item':
        comment_work_item(args.id, args.text)
    elif args.command == 'list-prs':
        list_prs(status=args.status)
    elif args.command == 'show-pr':
        show_pr(args.id)
    elif args.command == 'create-pr':
        create_pr(args.title, args.desc, args.source, args.target, args.draft)
    elif args.command == 'approve-pr':
        approve_pr(args.id)
    elif args.command == 'request-changes-pr':
        request_changes_pr(args.id, args.comment)
    elif args.command == 'merge-pr':
        merge_pr(args.id, strategy=args.strategy, delete_source=not args.keep_source)
    elif args.command == 'comment-pr':
        comment_pr(args.id, args.text)
    elif args.command == 'pr-checks':
        pr_checks(args.id)
    elif args.command == 'list-pipelines':
        list_pipelines()
    elif args.command == 'run-pipeline':
        variables = {}
        for v in (args.var or []):
            if '=' in v:
                k, val = v.split('=', 1)
                variables[k] = val
        run_pipeline(args.id, branch=args.branch, variables=variables or None)
    elif args.command == 'pipeline-status':
        pipeline_status(args.run_id)


if __name__ == '__main__':
    main()
