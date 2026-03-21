#!/usr/bin/env python3
"""
Store — Dev Team Shared State Backend

Provides a unified key-value and queue interface backed by Redis when available,
falling back to JSON files when Redis is not configured. This keeps live pipeline
state fast and atomic without requiring Redis as a hard dependency.

Redis usage (volatile, real-time):
  - Pipeline status and agent states
  - Agent feedback queue
  - Security verdict
  - Dependency manifest
  - Execution log (stage checkpoints)

JSON file usage (persistent, human-readable, git-committable):
  - ADRs, requirements docs, context.md, patterns.json

Environment variables:
  DEV_TEAM_REDIS_URL   Redis connection URL (e.g. redis://localhost:6379/0)
                       If unset, falls back to JSON files automatically.
  DEV_TEAM_REDIS_TTL   Key TTL in seconds for pipeline state (default: 86400 = 24h)

Usage:
  from store import Store
  s = Store(workspace_dir)
  s.set_status('developer', 'implementing', 'Writing auth middleware')
  s.push_feedback('architect', 'developer', 'Please use dependency injection here')
  s.set_security_verdict('BLOCKED', ['SQL injection in login endpoint'])
  s.add_dependency('requests', '2.31.0', 'developer')
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ─── Redis detection ───────────────────────────────────────────────────────────

_redis_client = None
_redis_available = None


def _get_redis():
    """Return a Redis client if configured, else None."""
    global _redis_client, _redis_available

    if _redis_available is not None:
        return _redis_client if _redis_available else None

    redis_url = os.environ.get('DEV_TEAM_REDIS_URL')
    if not redis_url:
        _redis_available = False
        return None

    try:
        import redis
        client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        _redis_client = client
        _redis_available = True
        return _redis_client
    except Exception:
        _redis_available = False
        return None


# ─── Store ─────────────────────────────────────────────────────────────────────

class Store:
    """
    Unified state store. Redis-backed when DEV_TEAM_REDIS_URL is set,
    JSON file-backed otherwise.
    """

    # Key names
    STATUS_KEY = 'dev-team:status'
    FEEDBACK_KEY = 'dev-team:feedback'
    SECURITY_KEY = 'dev-team:security-verdict'
    DEPS_KEY = 'dev-team:dependencies'
    EXEC_LOG_KEY = 'dev-team:execution-log'

    def __init__(self, workspace_dir: Path):
        self.workspace = workspace_dir
        self.redis = _get_redis()
        self.ttl = int(os.environ.get('DEV_TEAM_REDIS_TTL', 86400))

        # JSON fallback file paths
        self._status_file = workspace_dir / 'status.json'
        self._feedback_file = workspace_dir / 'feedback.json'
        self._security_file = workspace_dir / 'security_verdict.json'
        self._deps_file = workspace_dir / 'dependencies_manifest.json'
        self._exec_log_file = workspace_dir / 'execution_log.json'

    @property
    def backend(self) -> str:
        return 'redis' if self.redis else 'json'

    # ─── Status ───────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        if self.redis:
            raw = self.redis.get(self.STATUS_KEY)
            return json.loads(raw) if raw else self._default_status()
        return self._read_json(self._status_file, self._default_status())

    def set_status(self, agent: str, phase: str, detail: str = '') -> None:
        status = self.get_status()
        status['last_updated'] = datetime.now().isoformat()
        status['current_phase'] = phase
        status['agents'][agent] = {
            'status': phase,
            'detail': detail,
            'updated': datetime.now().isoformat(),
        }
        self._write_status(status)

    def set_phase(self, phase: str) -> None:
        status = self.get_status()
        status['current_phase'] = phase
        status['last_updated'] = datetime.now().isoformat()
        self._write_status(status)

    def add_task(self, description: str, agent: str = 'unassigned') -> int:
        status = self.get_status()
        task_id = len(status.get('tasks', [])) + 1
        status.setdefault('tasks', []).append({
            'id': task_id,
            'description': description,
            'agent': agent,
            'done': False,
            'created': datetime.now().isoformat(),
        })
        status['last_updated'] = datetime.now().isoformat()
        self._write_status(status)
        return task_id

    def complete_task(self, task_id: int) -> bool:
        status = self.get_status()
        for task in status.get('tasks', []):
            if task['id'] == task_id:
                task['done'] = True
                task['completed'] = datetime.now().isoformat()
                status['last_updated'] = datetime.now().isoformat()
                self._write_status(status)
                return True
        return False

    def _default_status(self) -> dict:
        return {
            'last_updated': None,
            'current_phase': 'idle',
            'agents': {},
            'tasks': [],
        }

    def _write_status(self, data: dict) -> None:
        if self.redis:
            self.redis.set(self.STATUS_KEY, json.dumps(data), ex=self.ttl)
        # Always mirror to file for human readability and persistence
        self._write_json(self._status_file, data)

    # ─── Feedback Queue ───────────────────────────────────────────────────────

    def push_feedback(self, from_agent: str, to_agent: str, message: str,
                      severity: str = 'INFO', stage: int | None = None) -> None:
        """Push a feedback message from one agent to another."""
        entry = {
            'id': int(time.time() * 1000),
            'from': from_agent,
            'to': to_agent,
            'message': message,
            'severity': severity,  # INFO / WARNING / BLOCKING
            'stage': stage,
            'timestamp': datetime.now().isoformat(),
            'resolved': False,
        }

        if self.redis:
            self.redis.rpush(self.FEEDBACK_KEY, json.dumps(entry))
            self.redis.expire(self.FEEDBACK_KEY, self.ttl)
        else:
            items = self._read_json(self._feedback_file, [])
            items.append(entry)
            self._write_json(self._feedback_file, items)

    def get_feedback(self, to_agent: str | None = None,
                     unresolved_only: bool = True) -> list[dict]:
        """Get feedback messages, optionally filtered by recipient."""
        if self.redis:
            raw = self.redis.lrange(self.FEEDBACK_KEY, 0, -1)
            items = [json.loads(r) for r in raw]
        else:
            items = self._read_json(self._feedback_file, [])

        if to_agent:
            items = [i for i in items if i.get('to') == to_agent]
        if unresolved_only:
            items = [i for i in items if not i.get('resolved')]
        return items

    def resolve_feedback(self, feedback_id: int) -> bool:
        """Mark a feedback item as resolved."""
        if self.redis:
            raw = self.redis.lrange(self.FEEDBACK_KEY, 0, -1)
            items = [json.loads(r) for r in raw]
            updated = False
            for item in items:
                if item.get('id') == feedback_id:
                    item['resolved'] = True
                    updated = True
            if updated:
                self.redis.delete(self.FEEDBACK_KEY)
                for item in items:
                    self.redis.rpush(self.FEEDBACK_KEY, json.dumps(item))
                self.redis.expire(self.FEEDBACK_KEY, self.ttl)
            return updated
        else:
            items = self._read_json(self._feedback_file, [])
            for item in items:
                if item.get('id') == feedback_id:
                    item['resolved'] = True
                    self._write_json(self._feedback_file, items)
                    return True
        return False

    def has_blocking_feedback(self) -> bool:
        """Return True if any unresolved BLOCKING feedback exists."""
        return any(
            f.get('severity') == 'BLOCKING'
            for f in self.get_feedback(unresolved_only=True)
        )

    # ─── Security Verdict ─────────────────────────────────────────────────────

    def set_security_verdict(self, verdict: str, findings: list[str],
                              critical_count: int = 0, high_count: int = 0) -> None:
        """
        Record the security agent's verdict.

        verdict: CLEAR | WARNINGS | REMEDIATION_REQUIRED | BLOCKED
        """
        data = {
            'verdict': verdict,  # CLEAR / WARNINGS / REMEDIATION_REQUIRED / BLOCKED
            'findings': findings,
            'critical_count': critical_count,
            'high_count': high_count,
            'timestamp': datetime.now().isoformat(),
        }
        if self.redis:
            self.redis.set(self.SECURITY_KEY, json.dumps(data), ex=self.ttl)
        self._write_json(self._security_file, data)

    def get_security_verdict(self) -> dict | None:
        if self.redis:
            raw = self.redis.get(self.SECURITY_KEY)
            return json.loads(raw) if raw else None
        if self._security_file.exists():
            return self._read_json(self._security_file, None)
        return None

    def is_security_blocked(self) -> bool:
        """Return True if the security agent has issued a BLOCKED verdict."""
        verdict = self.get_security_verdict()
        return verdict is not None and verdict.get('verdict') == 'BLOCKED'

    def clear_security_verdict(self) -> None:
        if self.redis:
            self.redis.delete(self.SECURITY_KEY)
        if self._security_file.exists():
            self._security_file.unlink()

    # ─── Dependency Manifest ──────────────────────────────────────────────────

    def add_dependency(self, name: str, version: str, added_by: str,
                       ecosystem: str = 'unknown') -> None:
        """Record a dependency added by an agent."""
        manifest = self._get_deps_manifest()
        key = f"{ecosystem}:{name}"

        if key in manifest and manifest[key]['version'] != version:
            manifest[key]['conflicts'] = manifest[key].get('conflicts', [])
            manifest[key]['conflicts'].append({
                'version': version,
                'added_by': added_by,
                'timestamp': datetime.now().isoformat(),
            })
        else:
            manifest[key] = {
                'name': name,
                'version': version,
                'ecosystem': ecosystem,
                'added_by': added_by,
                'timestamp': datetime.now().isoformat(),
                'conflicts': [],
            }

        self._write_deps_manifest(manifest)

    def get_dependency_conflicts(self) -> list[dict]:
        """Return all dependencies with version conflicts."""
        manifest = self._get_deps_manifest()
        return [
            dep for dep in manifest.values()
            if dep.get('conflicts')
        ]

    def get_all_dependencies(self) -> dict:
        return self._get_deps_manifest()

    def _get_deps_manifest(self) -> dict:
        if self.redis:
            raw = self.redis.get(self.DEPS_KEY)
            return json.loads(raw) if raw else {}
        return self._read_json(self._deps_file, {})

    def _write_deps_manifest(self, data: dict) -> None:
        if self.redis:
            self.redis.set(self.DEPS_KEY, json.dumps(data), ex=self.ttl)
        self._write_json(self._deps_file, data)

    # ─── Execution Log (Stage Checkpoints) ───────────────────────────────────

    def log_stage_start(self, stage_num: int, agents: list[str]) -> None:
        """Record the start of a pipeline stage for rollback purposes."""
        entry = {
            'type': 'stage_start',
            'stage': stage_num,
            'agents': agents,
            'timestamp': datetime.now().isoformat(),
        }
        self._append_exec_log(entry)

    def log_stage_complete(self, stage_num: int, agents: list[str],
                            success: bool = True) -> None:
        """Record successful completion of a stage."""
        entry = {
            'type': 'stage_complete',
            'stage': stage_num,
            'agents': agents,
            'success': success,
            'timestamp': datetime.now().isoformat(),
        }
        self._append_exec_log(entry)

    def log_file_snapshot(self, file_path: str, before: str | None,
                           stage: int) -> None:
        """Record a before-snapshot of a file for potential rollback."""
        entry = {
            'type': 'file_snapshot',
            'stage': stage,
            'path': file_path,
            'before': before,  # None means file didn't exist
            'timestamp': datetime.now().isoformat(),
        }
        self._append_exec_log(entry)

    def get_stage_snapshots(self, stage: int) -> list[dict]:
        """Get all file snapshots from a given stage."""
        log = self._get_exec_log()
        return [
            e for e in log
            if e.get('type') == 'file_snapshot' and e.get('stage') == stage
        ]

    def get_last_successful_stage(self) -> int:
        """Return the highest stage number that completed successfully."""
        log = self._get_exec_log()
        completed = [
            e['stage'] for e in log
            if e.get('type') == 'stage_complete' and e.get('success')
        ]
        return max(completed) if completed else 0

    def get_execution_log(self) -> list[dict]:
        return self._get_exec_log()

    def clear_execution_log(self) -> None:
        if self.redis:
            self.redis.delete(self.EXEC_LOG_KEY)
        if self._exec_log_file.exists():
            self._exec_log_file.unlink()

    def _get_exec_log(self) -> list:
        if self.redis:
            raw = self.redis.lrange(self.EXEC_LOG_KEY, 0, -1)
            return [json.loads(r) for r in raw]
        return self._read_json(self._exec_log_file, [])

    def _append_exec_log(self, entry: dict) -> None:
        if self.redis:
            self.redis.rpush(self.EXEC_LOG_KEY, json.dumps(entry))
            self.redis.expire(self.EXEC_LOG_KEY, self.ttl)
        else:
            log = self._read_json(self._exec_log_file, [])
            log.append(entry)
            self._write_json(self._exec_log_file, log)

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            if path.exists():
                return json.loads(path.read_text())
        except Exception:
            pass
        return default

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    def info(self) -> dict:
        """Return store backend info for diagnostics."""
        return {
            'backend': self.backend,
            'redis_url': os.environ.get('DEV_TEAM_REDIS_URL', 'not set'),
            'workspace': str(self.workspace),
            'ttl_seconds': self.ttl,
        }


# ─── CLI (for workspace.py to invoke) ─────────────────────────────────────────

def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description='Dev Team Store — state backend')
    parser.add_argument('--workspace', default='.dev-team', help='Workspace directory')
    sub = parser.add_subparsers(dest='cmd')

    sub.add_parser('info', help='Show backend info')

    p = sub.add_parser('push-feedback', help='Push feedback between agents')
    p.add_argument('--from', dest='from_agent', required=True)
    p.add_argument('--to', dest='to_agent', required=True)
    p.add_argument('--message', required=True)
    p.add_argument('--severity', default='INFO', choices=['INFO', 'WARNING', 'BLOCKING'])
    p.add_argument('--stage', type=int, default=None)

    p = sub.add_parser('get-feedback', help='Get feedback messages')
    p.add_argument('--to', dest='to_agent', default=None)
    p.add_argument('--all', dest='show_all', action='store_true')

    p = sub.add_parser('set-security-verdict', help='Record security verdict')
    p.add_argument('--verdict', required=True,
                   choices=['CLEAR', 'WARNINGS', 'REMEDIATION_REQUIRED', 'BLOCKED'])
    p.add_argument('--findings', default='', help='Comma-separated list of findings')
    p.add_argument('--critical', type=int, default=0)
    p.add_argument('--high', type=int, default=0)

    sub.add_parser('get-security-verdict', help='Show current security verdict')

    p = sub.add_parser('add-dependency', help='Record a dependency')
    p.add_argument('--name', required=True)
    p.add_argument('--version', required=True)
    p.add_argument('--added-by', required=True)
    p.add_argument('--ecosystem', default='unknown')

    sub.add_parser('list-dependencies', help='List all recorded dependencies')
    sub.add_parser('check-conflicts', help='List dependency version conflicts')
    sub.add_parser('show-log', help='Show execution log')

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    store = Store(Path(args.workspace))

    if args.cmd == 'info':
        info = store.info()
        print(f"Backend:   {info['backend']}")
        print(f"Redis URL: {info['redis_url']}")
        print(f"Workspace: {info['workspace']}")
        print(f"Key TTL:   {info['ttl_seconds']}s")

    elif args.cmd == 'push-feedback':
        store.push_feedback(args.from_agent, args.to_agent, args.message,
                            args.severity, args.stage)
        print(f"Feedback pushed: [{args.severity}] {args.from_agent} → {args.to_agent}")

    elif args.cmd == 'get-feedback':
        items = store.get_feedback(
            to_agent=args.to_agent,
            unresolved_only=not args.show_all,
        )
        if not items:
            print("No feedback messages.")
        for f in items:
            resolved = '[resolved]' if f.get('resolved') else ''
            print(f"[{f['severity']}] {f['from']} → {f.get('to','all')}: {f['message']} {resolved}")

    elif args.cmd == 'set-security-verdict':
        findings = [x.strip() for x in args.findings.split(',') if x.strip()]
        store.set_security_verdict(args.verdict, findings, args.critical, args.high)
        print(f"Security verdict set: {args.verdict}")

    elif args.cmd == 'get-security-verdict':
        v = store.get_security_verdict()
        if not v:
            print("No security verdict recorded.")
        else:
            print(f"Verdict:  {v['verdict']}")
            print(f"Critical: {v.get('critical_count', 0)}")
            print(f"High:     {v.get('high_count', 0)}")
            print(f"Recorded: {v.get('timestamp', 'unknown')}")
            if v.get('findings'):
                print("Findings:")
                for f in v['findings']:
                    print(f"  - {f}")

    elif args.cmd == 'add-dependency':
        store.add_dependency(args.name, args.version, args.added_by, args.ecosystem)
        print(f"Dependency recorded: {args.ecosystem}:{args.name}@{args.version}")

    elif args.cmd == 'list-dependencies':
        deps = store.get_all_dependencies()
        if not deps:
            print("No dependencies recorded.")
        for key, dep in deps.items():
            conflicts = f" ⚠️  {len(dep['conflicts'])} conflict(s)" if dep.get('conflicts') else ''
            print(f"  {key}@{dep['version']} (added by {dep['added_by']}){conflicts}")

    elif args.cmd == 'check-conflicts':
        conflicts = store.get_dependency_conflicts()
        if not conflicts:
            print("No version conflicts detected.")
        for dep in conflicts:
            print(f"CONFLICT: {dep['ecosystem']}:{dep['name']}")
            print(f"  Primary:  {dep['version']} (by {dep['added_by']})")
            for c in dep['conflicts']:
                print(f"  Conflict: {c['version']} (by {c['added_by']})")

    elif args.cmd == 'show-log':
        log = store.get_execution_log()
        if not log:
            print("Execution log is empty.")
        for entry in log:
            if entry['type'] == 'stage_start':
                print(f"  STAGE {entry['stage']} START: {', '.join(entry['agents'])}")
            elif entry['type'] == 'stage_complete':
                ok = '✓' if entry.get('success') else '✗'
                print(f"  STAGE {entry['stage']} COMPLETE [{ok}]: {', '.join(entry['agents'])}")
            elif entry['type'] == 'file_snapshot':
                exists = 'existed' if entry.get('before') else 'new file'
                print(f"  SNAPSHOT stage={entry['stage']}: {entry['path']} ({exists})")


if __name__ == '__main__':
    main()
