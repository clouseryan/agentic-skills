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

Requirements:
  pip install anthropic
  ANTHROPIC_API_KEY must be set
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

# Ensure sibling modules are importable
sys.path.insert(0, str(Path(__file__).parent))

from agents import AGENTS
from pipelines import DEFAULT_PIPELINE, STAGED_PIPELINE
from context import build_context_block, build_selective_context
from gates import check_security_gate, check_feedback_gate, snapshot_files


def _load_store(workspace_dir):
    """Return a Store instance or None if store.py is unavailable."""
    try:
        from store import Store
        return Store(workspace_dir)
    except Exception:
        return None


# ─── Orchestrator ─────────────────────────────────────────────────────────────

class DevTeamOrchestrator:
    def __init__(self, model: str = 'claude-sonnet-4-6', dry_run: bool = False,
                 workspace_root: str | None = None):
        self.client = anthropic.Anthropic() if not dry_run else None
        self.model = model
        self.dry_run = dry_run
        self.context: dict[str, str] = {}  # agent_key → full output
        self.results: dict[str, str] = {}
        self.start_time = datetime.now()
        self.workspace_root = workspace_root  # explicit workspace dir override (multi-repo)
        self._store = None  # initialized lazily in run_* methods

    def _resolve_workspace(self, project_root: str) -> Path:
        """Resolve the workspace directory from explicit override or project root."""
        if self.workspace_root:
            return Path(self.workspace_root)
        return Path(project_root) / '.dev-team'

    def _init_store(self, project_root: str):
        """Initialize the store backend for the given project root."""
        self._store = _load_store(self._resolve_workspace(project_root))

    def status(self, phase: str, agent: str, detail: str = ''):
        """Print a status update."""
        elapsed = (datetime.now() - self.start_time).seconds
        emoji = AGENTS.get(agent, {}).get('emoji', '▸')
        name = AGENTS.get(agent, {}).get('name', agent)
        print(f"\n{'━' * 60}")
        print(f"[DEV-TEAM] {elapsed}s | Phase: {phase}")
        print(f"  Agent: {emoji} {name}")
        if detail:
            print(f"  Status: {detail}")
        print(f"{'━' * 60}")
        sys.stdout.flush()

    def run_agent(self, agent_key: str, task: str, context_override: str = '') -> str:
        """Run a single agent with the given task and accumulated context."""
        if agent_key not in AGENTS:
            raise ValueError(f"Unknown agent: '{agent_key}'. Available: {', '.join(AGENTS.keys())}")

        agent = AGENTS[agent_key]
        self.status('running', agent_key, 'Processing task...')

        if self.dry_run:
            result = f"[DRY RUN] {agent['name']} would process: {task[:100]}..."
            print(result)
            return result

        context_str = context_override or build_selective_context(
            self.context, agent_key, self.client, self.model
        )

        user_message = f"""Task: {task}

{context_str}

Please proceed with your analysis and output. Report status as you work."""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=agent['system'],
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

    def _check_gates(self, agent_keys: list[str], stage_num: int) -> bool:
        """
        Run security and feedback gates before a stage.
        Returns True if the pipeline should stop.
        """
        # Security gate: block before lead stage
        if 'lead' in agent_keys:
            blocked, reason = check_security_gate(self._store)
            if blocked:
                print(f"\n{'═' * 60}")
                print(f"PIPELINE BLOCKED at stage {stage_num} — Security verdict: BLOCKED")
                print(reason)
                print("Fix the reported security issues, clear the verdict, and re-run.")
                print(f"{'═' * 60}")
                return True

        # Feedback gate: pause on any blocking feedback
        has_blocking, blocking = check_feedback_gate(self._store, stage_num)
        if has_blocking:
            print(f"\n{'═' * 60}")
            print(f"PIPELINE PAUSED at stage {stage_num} — {len(blocking)} blocking feedback item(s):")
            for f in blocking:
                print(f"  [{f['from']} → {f.get('to','all')}] {f['message']}")
            print("Resolve via: workspace.py push-feedback (clear the blocking message)")
            print(f"{'═' * 60}")
            return True

        return False

    def _check_dependency_conflicts(self, agent_keys: list[str]):
        """Surface dependency conflicts after dev/database stages."""
        if not self._store:
            return
        if not any(a in ('developer', 'database') for a in agent_keys):
            return
        conflicts = self._store.get_dependency_conflicts()
        if conflicts:
            print(f"\nDEPENDENCY CONFLICTS ({len(conflicts)}) — review before proceeding:")
            for c in conflicts:
                print(f"  {c['ecosystem']}:{c['name']} — {len(c['conflicts'])} conflicting version(s)")

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
        print(f"Task:    {task}")
        print(f"Agents:  {' → '.join(pipeline)}")
        print(f"Model:   {self.model}")
        print(f"Root:    {project_root}")
        print(f"{'═' * 60}")

        enriched_task = self._enrich_task(task, project_root)
        self._init_store(project_root)

        for agent_key in pipeline:
            if agent_key not in AGENTS:
                print(f"WARNING: Unknown agent '{agent_key}', skipping", file=sys.stderr)
                continue

            if self._check_gates([agent_key], stage_num=0):
                break

            self.run_agent(agent_key, enriched_task)
            self._check_dependency_conflicts([agent_key])

            time.sleep(0.5)

        self._print_completion_summary()
        return self.results

    def run_staged_pipeline(
        self,
        task: str,
        stages: list[list[str]] | None = None,
        project_root: str = '.',
    ) -> dict:
        """
        Run a staged pipeline with fan-out/fan-in.
        Within each stage, agents run in parallel. Stages run sequentially,
        with each stage receiving the accumulated context from all prior stages.
        """
        pipeline = stages or STAGED_PIPELINE

        print(f"\n{'═' * 60}")
        print(f"DEV TEAM ORCHESTRATOR — Staged Pipeline (fan-out/fan-in)")
        print(f"{'═' * 60}")
        print(f"Task:    {task}")
        for i, stage in enumerate(pipeline, 1):
            print(f"Stage {i}: {' ‖ '.join(stage)}")
        print(f"Model:   {self.model}")
        print(f"Root:    {project_root}")
        print(f"{'═' * 60}")

        enriched_task = self._enrich_task(task, project_root)
        self._init_store(project_root)

        for stage_num, stage_agents in enumerate(pipeline, 1):
            # Filter out unknown agents
            valid_agents = [a for a in stage_agents if a in AGENTS]
            unknown = [a for a in stage_agents if a not in AGENTS]
            if unknown:
                print(f"WARNING: Skipping unknown agents in stage {stage_num}: {unknown}", file=sys.stderr)
            if not valid_agents:
                continue

            if self._check_gates(valid_agents, stage_num):
                break

            print(f"\n{'─' * 60}")
            print(f"STAGE {stage_num}: {' ‖ '.join(AGENTS[a]['name'] for a in valid_agents)}")
            print(f"{'─' * 60}")

            # Log stage start for rollback
            if self._store:
                self._store.log_stage_start(stage_num, valid_agents)

            if len(valid_agents) == 1:
                self.run_agent(valid_agents[0], enriched_task)
            else:
                self._run_stage_parallel(valid_agents, enriched_task)

            # Log stage completion checkpoint
            if self._store:
                self._store.log_stage_complete(stage_num, valid_agents, success=True)

            self._check_dependency_conflicts(valid_agents)

            time.sleep(0.3)

        self._print_completion_summary()
        return self.results

    def _run_stage_parallel(self, agent_keys: list[str], task: str) -> None:
        """Run a set of agents in parallel, all sharing the current context snapshot."""
        # Snapshot context before the stage (all parallel agents see the same prior context)
        context_snapshot = build_context_block(
            self.context, self.client, self.model, summarize=True
        )

        stage_results: dict[str, str] = {}
        errors: dict[str, str] = {}
        lock = threading.Lock()

        def run_one(agent_key: str):
            agent = AGENTS[agent_key]
            self.status('running (parallel)', agent_key, 'Processing in parallel...')

            if self.dry_run:
                result = f"[DRY RUN] {agent['name']} would process task..."
                print(result)
                with lock:
                    stage_results[agent_key] = result
                return

            user_message = f"""Task: {task}

{context_snapshot}

Please proceed with your analysis and output. Report status as you work."""

            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=agent['system'],
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

        # Merge all stage results into shared context and results
        for key, result in stage_results.items():
            self.results[key] = result
            self.context[key] = result

        if errors:
            for key, err in errors.items():
                print(f"Stage error in {key}: {err}", file=sys.stderr)

    def run_parallel(
        self,
        task: str,
        parallel_agents: list[str],
        project_root: str = '.',
    ) -> dict:
        """Run multiple agents concurrently with no shared context (independent analysis)."""
        print(f"\n{'═' * 60}")
        print(f"DEV TEAM ORCHESTRATOR — Parallel (no context sharing)")
        print(f"{'═' * 60}")

        enriched_task = self._enrich_task(task, project_root)
        self._run_stage_parallel(parallel_agents, enriched_task)

        self._print_completion_summary()
        return self.results

    def _enrich_task(self, task: str, project_root: str) -> str:
        """Load workspace context and prepend it to the task description."""
        workspace = self._resolve_workspace(project_root)
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
                        workspace_context += '\n\n## Known Patterns\n' + '\n'.join(f'- {p}' for p in summary[:20])
                except Exception:
                    pass

            requirements_dir = workspace / 'requirements'
            if requirements_dir.exists():
                req_files = sorted(requirements_dir.glob('*.md'))
                if req_files:
                    workspace_context += '\n\n## Prior Requirements Documents\n'
                    for f in req_files[:3]:
                        workspace_context += f'\n### {f.name}\n{f.read_text()[:1000]}\n'

        # Inject relevant domain patterns from the pattern library
        try:
            from domain_patterns import get_relevant_patterns
            domain_hints = get_relevant_patterns(task)
            if domain_hints:
                workspace_context += '\n\n## Relevant Architecture Patterns\n'
                workspace_context += '\n'.join(f'- {p}' for p in domain_hints)
        except Exception:
            pass

        return f"{task}{workspace_context}"

    def _print_completion_summary(self):
        elapsed = (datetime.now() - self.start_time).seconds
        print(f"\n{'═' * 60}")
        print(f"DEV TEAM PIPELINE COMPLETE")
        print(f"Elapsed: {elapsed}s")
        print(f"Agents run: {', '.join(self.results.keys())}")
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

Examples:
  %(prog)s --task "add user auth" --root .
  %(prog)s --task "add user auth" --staged
  %(prog)s --task "analyze payment module" --agents research,security,architect
  %(prog)s --task "..." --dry-run
        """
    )
    parser.add_argument('--task', required=True, help='The task or goal to accomplish')
    parser.add_argument('--root', default='.', help='Project root directory')
    parser.add_argument('--workspace-root', default=None,
                        help='Override workspace directory directly (multi-repo: point multiple projects at a shared .dev-team/)')
    parser.add_argument(
        '--agents',
        help=f'Comma-separated agent pipeline. Available: {available_agents}',
    )
    parser.add_argument(
        '--staged',
        action='store_true',
        help='Use the staged fan-out/fan-in pipeline (parallel within stages)',
    )
    parser.add_argument(
        '--parallel',
        action='store_true',
        help='Run agents in parallel with no context sharing (requires --agents)',
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

    orchestrator = DevTeamOrchestrator(model=args.model, dry_run=args.dry_run,
                                        workspace_root=args.workspace_root)

    if args.parallel and agent_list:
        results = orchestrator.run_parallel(args.task, agent_list, args.root)
    elif args.staged:
        results = orchestrator.run_staged_pipeline(args.task, project_root=args.root)
    else:
        results = orchestrator.run_pipeline(args.task, agent_list, args.root)

    if args.output:
        output_data = {
            'task': args.task,
            'timestamp': datetime.now().isoformat(),
            'agents': list(results.keys()),
            'results': results,
        }
        Path(args.output).write_text(json.dumps(output_data, indent=2))
        print(f"\nResults saved to {args.output}")


if __name__ == '__main__':
    main()
