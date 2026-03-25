#!/usr/bin/env python3
"""
Multi-Agent Orchestrator — Dev Team Helper Script

Programmatic orchestration using the Anthropic SDK. Runs multiple specialized
agent conversations, passes context between them, and aggregates results.

This script powers the /dev-team skill's ability to coordinate multiple
Claude agents for complex tasks.

Usage:
  python3 orchestrator.py --task "add user authentication" --root .
  python3 orchestrator.py --agents research,architect,developer --task "..."
  python3 orchestrator.py --staged --task "..."   # fan-out/fan-in pipeline
  python3 orchestrator.py --dry-run --task "..."
  python3 orchestrator.py --platform azure-devops --staged --task "..."

Requirements:
  pip install anthropic
  ANTHROPIC_API_KEY must be set

Platform support:
  --platform github        Use GitHub CLI (gh) for PR/issue operations (default)
  --platform azure-devops  Use Azure DevOps CLI (az) for PR/work-item operations
"""

import argparse
import json
import os
import sys
import time
import threading
from pathlib import Path
from datetime import datetime

try:
    import anthropic
except ImportError:
    print("Error: anthropic package not installed.")
    print("Run: pip install anthropic")
    sys.exit(1)

# Agent definitions and pipeline configs live in agents.py
sys.path.insert(0, str(Path(__file__).parent))
from agents import (
    AGENTS,
    DEFAULT_PIPELINE,
    STAGED_PIPELINE,
    RELEVANT_PRIOR,
    get_platform_note,
)


# ─── Store backend ─────────────────────────────────────────────────────────────

def _load_store(workspace_dir):
    """Return a Store instance or None if store.py is unavailable."""
    try:
        from store import Store
        return Store(workspace_dir)
    except Exception:
        return None


# ─── Pipeline gates ─────────────────────────────────────────────────────────────

def _check_security_gate(store) -> tuple[bool, str]:
    """Return (blocked, reason). Blocks if security verdict is BLOCKED."""
    if store is None:
        return False, ''
    verdict = store.get_security_verdict()
    if verdict and verdict.get('verdict') == 'BLOCKED':
        critical = verdict.get('critical_count', 0)
        high = verdict.get('high_count', 0)
        findings = verdict.get('findings', [])
        reason = (
            f"Security verdict: BLOCKED (critical={critical}, high={high})\n"
            + '\n'.join(f"  - {f}" for f in findings[:5])
        )
        return True, reason
    return False, ''


def _check_feedback_gate(store, stage_num: int) -> tuple[bool, list]:
    """Return (has_blocking, blocking_items) for the current stage."""
    if store is None:
        return False, []
    blocking = [
        f for f in store.get_feedback(unresolved_only=True)
        if f.get('severity') == 'BLOCKING'
    ]
    return bool(blocking), blocking


def _snapshot_files(store, file_paths: list, stage_num: int, project_root: Path) -> None:
    """Record before-snapshots of files for rollback purposes."""
    if store is None:
        return
    for rel_path in file_paths:
        abs_path = project_root / rel_path
        before = abs_path.read_text(errors='replace') if abs_path.exists() else None
        store.log_file_snapshot(rel_path, before, stage_num)


# ─── Context management ─────────────────────────────────────────────────────────

def _resolve_system(agent_key: str, platform: str) -> str:
    """Return the agent's system prompt with platform note injected."""
    system = AGENTS[agent_key]['system']
    return system.replace('{platform_note}', get_platform_note(platform))


def summarize_agent_output(client, model: str, agent_name: str, output: str) -> str:
    """
    Produce a concise summary of an agent's output for downstream agents.
    Falls back to smart truncation if the API call fails.
    """
    if len(output) <= 3000:
        return output

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1000,
            system=(
                "You are a technical summarizer. Extract the most important findings, "
                "decisions, and action items from agent output. Be concise but preserve "
                "all critical technical details, file paths, and specific recommendations."
            ),
            messages=[{
                'role': 'user',
                'content': (
                    f"Summarize this {agent_name} output, preserving all critical "
                    f"technical details:\n\n{output[:8000]}"
                ),
            }],
        )
        return f"[SUMMARY of {agent_name} output]\n{response.content[0].text}"
    except Exception:
        half = 1400
        return (
            f"[TRUNCATED {agent_name} output — {len(output)} chars total]\n"
            f"{output[:half]}\n\n... [middle omitted] ...\n\n{output[-half:]}"
        )


def build_context_block(context: dict, client, model: str, summarize: bool = True) -> str:
    """Build the prior-agent-outputs block to inject into the next agent's prompt."""
    if not context:
        return ''

    parts = ['\n\n---\n## Prior Agent Outputs\n']
    for agent_key, output in context.items():
        agent_name = AGENTS.get(agent_key, {}).get('name', agent_key)
        if summarize and client and len(output) > 3000:
            summary = summarize_agent_output(client, model, agent_name, output)
            parts.append(f'\n### {agent_name} Output:\n{summary}\n')
        else:
            parts.append(f'\n### {agent_name} Output:\n{output[:4000]}\n')

    return ''.join(parts)


def _build_selective_context(context: dict, agent_key: str, client, model: str) -> str:
    """
    Build a context block with only the outputs most relevant to this agent.
    Keeps prompts focused and token-efficient.
    """
    relevant_keys = RELEVANT_PRIOR.get(agent_key, list(context.keys()))
    filtered = {k: v for k, v in context.items() if k in relevant_keys}
    return build_context_block(filtered, client, model, summarize=True)


# ─── Orchestrator ──────────────────────────────────────────────────────────────

class DevTeamOrchestrator:
    def __init__(
        self,
        model: str = 'claude-sonnet-4-6',
        dry_run: bool = False,
        workspace_root: str | None = None,
        platform: str = 'github',
    ):
        self.client = anthropic.Anthropic() if not dry_run else None
        self.model = model
        self.dry_run = dry_run
        self.platform = platform
        self.context: dict[str, str] = {}   # agent_key → full output
        self.results: dict[str, str] = {}
        self.start_time = datetime.now()
        self.workspace_root = workspace_root
        self._store = None  # lazily initialized in run_* methods

    # ── Status ──────────────────────────────────────────────────────────────────

    def status(self, phase: str, agent_key: str, detail: str = '') -> None:
        elapsed = (datetime.now() - self.start_time).seconds
        emoji = AGENTS.get(agent_key, {}).get('emoji', '▸')
        name = AGENTS.get(agent_key, {}).get('name', agent_key)
        print(f"\n{'━' * 60}")
        print(f"[DEV-TEAM] {elapsed}s | Phase: {phase}")
        print(f"  Agent: {emoji} {name}")
        if detail:
            print(f"  Status: {detail}")
        print(f"{'━' * 60}")
        sys.stdout.flush()

    # ── Single agent ────────────────────────────────────────────────────────────

    def run_agent(self, agent_key: str, task: str, context_override: str = '') -> str:
        """Run a single agent with the given task and accumulated context."""
        if agent_key not in AGENTS:
            raise ValueError(
                f"Unknown agent: '{agent_key}'. Available: {', '.join(AGENTS.keys())}"
            )

        self.status('running', agent_key, 'Processing task...')

        if self.dry_run:
            result = f"[DRY RUN] {AGENTS[agent_key]['name']} would process: {task[:100]}..."
            print(result)
            return result

        context_str = context_override or _build_selective_context(
            self.context, agent_key, self.client, self.model
        )

        user_message = (
            f"Task: {task}\n\n"
            f"{context_str}\n\n"
            "Please proceed with your analysis and output. Report status as you work."
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=_resolve_system(agent_key, self.platform),
                messages=[{'role': 'user', 'content': user_message}],
            )
            result = response.content[0].text
            self.results[agent_key] = result
            self.context[agent_key] = result
            print(f"\n{result}")
            return result

        except Exception as e:
            error = f"Agent {agent_key} failed: {str(e)}"
            print(f"ERROR: {error}", file=sys.stderr)
            return error

    # ── Sequential pipeline ─────────────────────────────────────────────────────

    def run_pipeline(
        self,
        task: str,
        agents: list[str] | None = None,
        project_root: str = '.',
    ) -> dict:
        """Run a sequential agent pipeline."""
        pipeline = agents or DEFAULT_PIPELINE

        print(f"\n{'═' * 60}")
        print(f"DEV TEAM ORCHESTRATOR — Sequential Pipeline")
        print(f"{'═' * 60}")
        print(f"Task:     {task}")
        print(f"Agents:   {' → '.join(pipeline)}")
        print(f"Model:    {self.model}")
        print(f"Platform: {self.platform}")
        print(f"Root:     {project_root}")
        print(f"{'═' * 60}")

        enriched_task = self._enrich_task(task, project_root)
        workspace_dir = self._workspace_dir(project_root)
        self._store = _load_store(workspace_dir)

        for agent_key in pipeline:
            if agent_key not in AGENTS:
                print(f"WARNING: Unknown agent '{agent_key}', skipping", file=sys.stderr)
                continue

            if agent_key == 'lead':
                blocked, reason = _check_security_gate(self._store)
                if blocked:
                    print(
                        f"\nPIPELINE BLOCKED — Security verdict requires remediation:\n{reason}",
                        file=sys.stderr,
                    )
                    print("Resolve security findings and re-run from the lead stage.")
                    break

            has_blocking, blocking = _check_feedback_gate(self._store, stage_num=0)
            if has_blocking:
                print(
                    f"\nPIPELINE PAUSED — {len(blocking)} blocking feedback item(s):",
                    file=sys.stderr,
                )
                for f in blocking:
                    print(f"  [{f['from']} → {f.get('to','all')}] {f['message']}", file=sys.stderr)
                print(
                    "Resolve blocking feedback via: workspace.py push-feedback --severity INFO (to clear)",
                    file=sys.stderr,
                )
                break

            self.run_agent(agent_key, enriched_task)
            self._surface_dependency_conflicts(agent_key)
            time.sleep(0.5)

        self._print_completion_summary()
        return self.results

    # ── Staged pipeline ─────────────────────────────────────────────────────────

    def run_staged_pipeline(
        self,
        task: str,
        stages: list[list[str]] | None = None,
        project_root: str = '.',
    ) -> dict:
        """
        Run a staged pipeline with fan-out/fan-in.
        Agents within each stage run in parallel; stages run sequentially.
        """
        pipeline = stages or STAGED_PIPELINE

        print(f"\n{'═' * 60}")
        print(f"DEV TEAM ORCHESTRATOR — Staged Pipeline (fan-out/fan-in)")
        print(f"{'═' * 60}")
        print(f"Task:     {task}")
        for i, stage in enumerate(pipeline, 1):
            print(f"Stage {i}: {' ‖ '.join(stage)}")
        print(f"Model:    {self.model}")
        print(f"Platform: {self.platform}")
        print(f"Root:     {project_root}")
        print(f"{'═' * 60}")

        enriched_task = self._enrich_task(task, project_root)
        workspace_dir = self._workspace_dir(project_root)
        self._store = _load_store(workspace_dir)

        for stage_num, stage_agents in enumerate(pipeline, 1):
            valid_agents = [a for a in stage_agents if a in AGENTS]
            unknown = [a for a in stage_agents if a not in AGENTS]
            if unknown:
                print(
                    f"WARNING: Skipping unknown agents in stage {stage_num}: {unknown}",
                    file=sys.stderr,
                )
            if not valid_agents:
                continue

            if 'lead' in valid_agents:
                blocked, reason = _check_security_gate(self._store)
                if blocked:
                    print(f"\n{'═' * 60}")
                    print(f"PIPELINE BLOCKED at stage {stage_num} — Security verdict: BLOCKED")
                    print(reason)
                    print("Fix the reported security issues, clear the verdict, and re-run.")
                    print(f"{'═' * 60}")
                    break

            has_blocking, blocking = _check_feedback_gate(self._store, stage_num)
            if has_blocking:
                print(f"\n{'═' * 60}")
                print(
                    f"PIPELINE PAUSED at stage {stage_num} — "
                    f"{len(blocking)} blocking feedback item(s):"
                )
                for f in blocking:
                    print(f"  [{f['from']} → {f.get('to','all')}] {f['message']}")
                print("Resolve via: workspace.py push-feedback (clear the blocking message)")
                print(f"{'═' * 60}")
                break

            print(f"\n{'─' * 60}")
            print(f"STAGE {stage_num}: {' ‖ '.join(AGENTS[a]['name'] for a in valid_agents)}")
            print(f"{'─' * 60}")

            if self._store:
                self._store.log_stage_start(stage_num, valid_agents)

            if len(valid_agents) == 1:
                self.run_agent(valid_agents[0], enriched_task)
            else:
                self._run_stage_parallel(valid_agents, enriched_task)

            if self._store:
                self._store.log_stage_complete(stage_num, valid_agents, success=True)

            for a in valid_agents:
                self._surface_dependency_conflicts(a)

            time.sleep(0.3)

        self._print_completion_summary()
        return self.results

    # ── Parallel (no context sharing) ───────────────────────────────────────────

    def run_parallel(
        self,
        task: str,
        parallel_agents: list[str],
        project_root: str = '.',
    ) -> dict:
        """Run multiple agents concurrently with no shared context."""
        print(f"\n{'═' * 60}")
        print(f"DEV TEAM ORCHESTRATOR — Parallel (no context sharing)")
        print(f"Platform: {self.platform}")
        print(f"{'═' * 60}")

        enriched_task = self._enrich_task(task, project_root)
        self._run_stage_parallel(parallel_agents, enriched_task)
        self._print_completion_summary()
        return self.results

    # ── Internals ───────────────────────────────────────────────────────────────

    def _run_stage_parallel(self, agent_keys: list[str], task: str) -> None:
        """Run a set of agents in parallel, all sharing the current context snapshot."""
        context_snapshot = build_context_block(
            self.context, self.client, self.model, summarize=True
        )

        stage_results: dict[str, str] = {}
        errors: dict[str, str] = {}
        lock = threading.Lock()

        def run_one(agent_key: str):
            self.status('running (parallel)', agent_key, 'Processing in parallel...')

            if self.dry_run:
                result = f"[DRY RUN] {AGENTS[agent_key]['name']} would process task..."
                print(result)
                with lock:
                    stage_results[agent_key] = result
                return

            user_message = (
                f"Task: {task}\n\n"
                f"{context_snapshot}\n\n"
                "Please proceed with your analysis and output. Report status as you work."
            )

            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=_resolve_system(agent_key, self.platform),
                    messages=[{'role': 'user', 'content': user_message}],
                )
                result = response.content[0].text
                print(f"\n{result}")
                with lock:
                    stage_results[agent_key] = result
            except Exception as e:
                error = f"Agent {agent_key} failed: {str(e)}"
                print(f"ERROR: {error}", file=sys.stderr)
                with lock:
                    errors[agent_key] = error
                    stage_results[agent_key] = error

        threads = [threading.Thread(target=run_one, args=(k,)) for k in agent_keys]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for key, result in stage_results.items():
            self.results[key] = result
            self.context[key] = result

        for key, err in errors.items():
            print(f"Stage error in {key}: {err}", file=sys.stderr)

    def _workspace_dir(self, project_root: str) -> Path:
        if self.workspace_root:
            return Path(self.workspace_root)
        return Path(project_root) / '.dev-team'

    def _surface_dependency_conflicts(self, agent_key: str) -> None:
        if agent_key in ('developer', 'database') and self._store:
            conflicts = self._store.get_dependency_conflicts()
            if conflicts:
                print(f"\nDEPENDENCY CONFLICTS ({len(conflicts)}) — review before proceeding:")
                for c in conflicts:
                    print(f"  {c['ecosystem']}:{c['name']} — {len(c['conflicts'])} conflicting version(s)")

    def _enrich_task(self, task: str, project_root: str) -> str:
        """Prepend workspace context (patterns, prior requirements) to the task."""
        workspace = self._workspace_dir(project_root)
        workspace_context = ''

        if workspace.exists():
            context_file = workspace / 'context.md'
            if context_file.exists():
                workspace_context += f"\n\n## Project Context\n{context_file.read_text()[:4000]}"

            patterns_file = workspace / 'patterns.json'
            if patterns_file.exists():
                try:
                    patterns = json.loads(patterns_file.read_text())
                    summary = patterns.get('summary', [])
                    if summary:
                        workspace_context += (
                            '\n\n## Known Patterns\n'
                            + '\n'.join(f'- {p}' for p in summary[:20])
                        )
                except Exception:
                    pass

            requirements_dir = workspace / 'requirements'
            if requirements_dir.exists():
                req_files = sorted(requirements_dir.glob('*.md'))
                if req_files:
                    workspace_context += '\n\n## Prior Requirements Documents\n'
                    for f in req_files[:3]:
                        workspace_context += f'\n### {f.name}\n{f.read_text()[:1000]}\n'

        # Inject domain patterns if available
        try:
            from domain_patterns import get_relevant_patterns
            domain_hints = get_relevant_patterns(task)
            if domain_hints:
                workspace_context += '\n\n## Relevant Architecture Patterns\n'
                workspace_context += '\n'.join(f'- {p}' for p in domain_hints)
        except Exception:
            pass

        return f"{task}{workspace_context}"

    def _print_completion_summary(self) -> None:
        elapsed = (datetime.now() - self.start_time).seconds
        print(f"\n{'═' * 60}")
        print(f"DEV TEAM PIPELINE COMPLETE")
        print(f"Elapsed:  {elapsed}s")
        print(f"Platform: {self.platform}")
        print(f"Agents:   {', '.join(self.results.keys())}")
        print(f"{'═' * 60}")


# ─── CLI ───────────────────────────────────────────────────────────────────────

def main():
    available_agents = ', '.join(AGENTS.keys())
    parser = argparse.ArgumentParser(
        description='Dev Team Orchestrator — coordinate multiple Claude agents',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Available agents: {available_agents}

Pipeline modes:
  (default)   Sequential pipeline: ba → research → architect → developer → reviewer → qa → docs
  --staged    Staged fan-out/fan-in pipeline with parallel stages (recommended for full runs)
  --parallel  All specified agents run in parallel with no context sharing
  --agents    Custom sequential pipeline (comma-separated agent names)

Platform:
  --platform github        GitHub CLI (gh) for PRs and issues (default)
  --platform azure-devops  Azure DevOps CLI (az) for PRs and work items

Examples:
  %(prog)s --task "add user auth" --root .
  %(prog)s --task "add user auth" --staged
  %(prog)s --task "add user auth" --staged --platform azure-devops
  %(prog)s --task "analyze payment module" --agents research,security,architect
  %(prog)s --task "..." --dry-run
        """,
    )
    parser.add_argument('--task', required=True, help='The task or goal to accomplish')
    parser.add_argument('--root', default='.', help='Project root directory')
    parser.add_argument(
        '--workspace-root', default=None,
        help='Override workspace directory (multi-repo: point multiple projects at a shared .dev-team/)',
    )
    parser.add_argument(
        '--agents',
        help=f'Comma-separated agent pipeline. Available: {available_agents}',
    )
    parser.add_argument(
        '--staged', action='store_true',
        help='Use the staged fan-out/fan-in pipeline (parallel within stages)',
    )
    parser.add_argument(
        '--parallel', action='store_true',
        help='Run agents in parallel with no context sharing (requires --agents)',
    )
    parser.add_argument(
        '--platform', default='github', choices=['github', 'azure-devops'],
        help='Repository platform for PR/issue operations (default: github)',
    )
    parser.add_argument('--model', default='claude-sonnet-4-6', help='Claude model to use')
    parser.add_argument('--dry-run', action='store_true', help='Print plan without calling API')
    parser.add_argument('--output', help='Save results to JSON file')
    args = parser.parse_args()

    if not args.dry_run and not os.environ.get('ANTHROPIC_API_KEY'):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        print("Set it with: export ANTHROPIC_API_KEY=your-key")
        sys.exit(1)

    if args.parallel and not args.agents:
        print("Error: --parallel requires --agents to specify which agents to run")
        sys.exit(1)

    agent_list = [a.strip() for a in args.agents.split(',')] if args.agents else None

    orchestrator = DevTeamOrchestrator(
        model=args.model,
        dry_run=args.dry_run,
        workspace_root=args.workspace_root,
        platform=args.platform,
    )

    if args.parallel and agent_list:
        results = orchestrator.run_parallel(args.task, agent_list, args.root)
    elif args.staged:
        results = orchestrator.run_staged_pipeline(args.task, project_root=args.root)
    else:
        results = orchestrator.run_pipeline(args.task, agent_list, args.root)

    if args.output:
        output_data = {
            'task': args.task,
            'platform': args.platform,
            'timestamp': datetime.now().isoformat(),
            'agents': list(results.keys()),
            'results': results,
        }
        Path(args.output).write_text(json.dumps(output_data, indent=2))
        print(f"\nResults saved to {args.output}")


if __name__ == '__main__':
    main()
