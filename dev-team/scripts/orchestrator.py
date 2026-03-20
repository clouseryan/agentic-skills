#!/usr/bin/env python3
"""
Multi-Agent Orchestrator — Dev Team Helper Script

Programmatic orchestration using the Anthropic SDK. Runs multiple specialized
agent conversations, passes context between them, and aggregates results.

This script powers the /dev-team skill's ability to coordinate multiple
Claude agents concurrently for complex tasks.

Usage:
  python3 orchestrator.py --task "add user authentication" --root .
  python3 orchestrator.py --agents research,architect,developer --task "..."
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
from pathlib import Path
from datetime import datetime

try:
    import anthropic
except ImportError:
    print("Error: anthropic package not installed.")
    print("Run: pip install anthropic")
    sys.exit(1)


# ─── Agent Definitions ─────────────────────────────────────────────────────────

AGENTS = {
    'research': {
        'name': 'Research Analyst',
        'emoji': '🔍',
        'system': """You are the Research Analyst on an agentic software development team.
Your role is to explore codebases, identify patterns, and build a knowledge base for the team.

When given a task, you will:
1. Survey the project structure and identify key files
2. Detect language, framework, and key dependencies
3. Discover coding patterns (naming, file organization, error handling, testing)
4. Find all files relevant to the given task
5. Report findings in structured format

Always cite specific files and line numbers. Report status frequently.
Format your findings as structured markdown with clear sections.""",
    },
    'architect': {
        'name': 'Software Architect',
        'emoji': '🏗️',
        'system': """You are the Software Architect on an agentic software development team.
Your role is to design implementations that fit the existing codebase.

When given research findings and a task, you will:
1. Analyze how the request fits with existing patterns
2. Design the minimal solution that achieves the goal
3. Identify exactly which files to create and modify
4. Define interfaces and data contracts
5. Create an implementation checklist for the developer

Prefer existing patterns. Only introduce new patterns with explicit justification.
Output a concrete implementation brief the developer can follow exactly.""",
    },
    'developer': {
        'name': 'Developer',
        'emoji': '💻',
        'system': """You are the Developer on an agentic software development team.
Your role is to implement features exactly as specified in the architect's brief.

When given an implementation brief, you will:
1. Follow the specified patterns precisely
2. Write each file completely (no placeholders)
3. Match the existing code style exactly
4. Report completion of each file

Never deviate from existing patterns without flagging it.
Never leave TODOs unless explicitly asked.
Report status after each file is complete.""",
    },
    'reviewer': {
        'name': 'Code Reviewer',
        'emoji': '🔎',
        'system': """You are the Code Reviewer on an agentic software development team.
Your role is to review all code changes before they are considered complete.

When given code to review, you will:
1. Check for security vulnerabilities (injection, hardcoded secrets, auth issues)
2. Check for performance issues (N+1, missing indexes, blocking operations)
3. Verify pattern compliance with the codebase
4. Assess correctness and edge case handling
5. Rate each finding: CRITICAL / HIGH / MEDIUM / LOW

Provide specific file:line references for every finding.
Output a verdict: APPROVED / CHANGES REQUESTED / BLOCKED.""",
    },
    'qa': {
        'name': 'QA Engineer',
        'emoji': '🧪',
        'system': """You are the QA Engineer on an agentic software development team.
Your role is to write tests that verify the implemented features.

When given implementation details, you will:
1. Identify what needs to be tested (happy paths, edge cases, error cases)
2. Write tests following the exact test patterns of the codebase
3. Verify that tests actually run and pass
4. Report coverage of the new code

Match the project's test framework and style exactly.""",
    },
    'docs': {
        'name': 'Documentation Writer',
        'emoji': '📝',
        'system': """You are the Documentation Writer on an agentic software development team.
Your role is to document all changes accurately.

When given implementation details, you will:
1. Update or create README files for affected modules
2. Add or update inline documentation (docstrings, JSDoc)
3. Update CHANGELOG if present
4. Ensure all usage examples are accurate and runnable

Match the existing documentation style. Never document what isn't implemented.""",
    },
    'database': {
        'name': 'Database Engineer',
        'emoji': '🗄️',
        'system': """You are the Database Engineer on an agentic software development team.
Your role is to handle all database-related changes.

When given a task involving data persistence, you will:
1. Design schema changes following existing conventions
2. Write migration files in the project's migration format
3. Identify index requirements based on access patterns
4. Verify migrations are reversible (include down migrations)

Always flag potentially dangerous migrations (drops, large table changes).""",
    },
    'devops': {
        'name': 'DevOps Engineer',
        'emoji': '⚙️',
        'system': """You are the DevOps Engineer on an agentic software development team.
Your role is to handle infrastructure, CI/CD, and deployment concerns.

When given a task with infrastructure implications, you will:
1. Review or create CI/CD pipeline configuration
2. Handle Docker and container configurations
3. Manage environment variable requirements
4. Assess deployment and rollback strategies

Follow existing infrastructure patterns. Flag any security concerns.""",
    },
}

DEFAULT_PIPELINE = ['research', 'architect', 'developer', 'reviewer', 'qa', 'docs']


# ─── Orchestrator ─────────────────────────────────────────────────────────────

class DevTeamOrchestrator:
    def __init__(self, model: str = 'claude-sonnet-4-6', dry_run: bool = False):
        self.client = anthropic.Anthropic() if not dry_run else None
        self.model = model
        self.dry_run = dry_run
        self.context = {}
        self.results = {}
        self.start_time = datetime.now()

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
        agent = AGENTS[agent_key]
        self.status('running', agent_key, f'Processing task...')

        if self.dry_run:
            result = f"[DRY RUN] {agent['name']} would process: {task[:100]}..."
            print(result)
            return result

        # Build the user message with context
        context_str = ''
        if self.context:
            context_str = '\n\n---\n## Prior Agent Outputs\n'
            for key, value in self.context.items():
                context_str += f'\n### {AGENTS.get(key, {}).get("name", key)} Output:\n{value[:2000]}\n'

        user_message = f"""Task: {task}

{context_override or context_str}

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

            # Store in context for next agents
            self.context[agent_key] = result

            # Print result
            print(f"\n{result}")
            return result

        except Exception as e:
            error = f"Agent {agent_key} failed: {str(e)}"
            print(f"ERROR: {error}", file=sys.stderr)
            return error

    def run_pipeline(
        self,
        task: str,
        agents: list[str] | None = None,
        project_root: str = '.',
    ) -> dict:
        """Run the full agent pipeline."""
        pipeline = agents or DEFAULT_PIPELINE

        print(f"\n{'═' * 60}")
        print(f"DEV TEAM ORCHESTRATOR")
        print(f"{'═' * 60}")
        print(f"Task:    {task}")
        print(f"Agents:  {' → '.join(pipeline)}")
        print(f"Model:   {self.model}")
        print(f"Root:    {project_root}")
        print(f"{'═' * 60}")

        # Load workspace context if available
        workspace = Path(project_root) / '.dev-team'
        workspace_context = ''
        if workspace.exists():
            context_file = workspace / 'context.md'
            if context_file.exists():
                workspace_context = f"\n\n## Project Context\n{context_file.read_text()[:3000]}"
            patterns_file = workspace / 'patterns.json'
            if patterns_file.exists():
                try:
                    patterns = json.loads(patterns_file.read_text())
                    summary = patterns.get('summary', [])
                    if summary:
                        workspace_context += '\n\n## Known Patterns\n' + '\n'.join(f'- {p}' for p in summary)
                except Exception:
                    pass

        # Enrich task with workspace context
        enriched_task = f"{task}{workspace_context}"

        # Run pipeline sequentially
        for agent_key in pipeline:
            if agent_key not in AGENTS:
                print(f"WARNING: Unknown agent '{agent_key}', skipping", file=sys.stderr)
                continue

            result = self.run_agent(agent_key, enriched_task)
            time.sleep(0.5)  # Small delay between agents

        # Final summary
        print(f"\n{'═' * 60}")
        print(f"DEV TEAM PIPELINE COMPLETE")
        print(f"Elapsed: {(datetime.now() - self.start_time).seconds}s")
        print(f"Agents run: {', '.join(self.results.keys())}")
        print(f"{'═' * 60}")

        return self.results

    def run_parallel(
        self,
        task: str,
        parallel_agents: list[str],
        project_root: str = '.',
    ) -> dict:
        """Run multiple agents concurrently (requires Python 3.12+ or threading)."""
        import threading

        results = {}
        errors = {}

        def run_agent_thread(agent_key):
            try:
                results[agent_key] = self.run_agent(agent_key, task)
            except Exception as e:
                errors[agent_key] = str(e)

        threads = []
        for agent_key in parallel_agents:
            t = threading.Thread(target=run_agent_thread, args=(agent_key,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        if errors:
            for key, err in errors.items():
                print(f"ERROR in {key}: {err}", file=sys.stderr)

        return results


# ─── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Dev Team Orchestrator — coordinate multiple Claude agents'
    )
    parser.add_argument('--task', required=True, help='The task or goal to accomplish')
    parser.add_argument('--root', default='.', help='Project root directory')
    parser.add_argument(
        '--agents',
        help=f'Comma-separated agent pipeline (default: {",".join(DEFAULT_PIPELINE)})\nAvailable: {", ".join(AGENTS.keys())}',
    )
    parser.add_argument('--model', default='claude-sonnet-4-6', help='Claude model to use')
    parser.add_argument('--dry-run', action='store_true', help='Print plan without calling API')
    parser.add_argument('--parallel', action='store_true', help='Run agents in parallel (no context sharing)')
    parser.add_argument('--output', help='Save results to JSON file')
    args = parser.parse_args()

    # Validate API key
    if not args.dry_run and not os.environ.get('ANTHROPIC_API_KEY'):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        print("Set it with: export ANTHROPIC_API_KEY=your-key")
        sys.exit(1)

    agents = args.agents.split(',') if args.agents else None

    orchestrator = DevTeamOrchestrator(model=args.model, dry_run=args.dry_run)

    if args.parallel and agents:
        results = orchestrator.run_parallel(args.task, agents, args.root)
    else:
        results = orchestrator.run_pipeline(args.task, agents, args.root)

    if args.output:
        output_data = {
            'task': args.task,
            'timestamp': datetime.now().isoformat(),
            'agents': list(results.keys()),
            'results': results,
        }
        Path(args.output).write_text(json.dumps(output_data, indent=2))
        print(f"\n✓ Results saved to {args.output}")


if __name__ == '__main__':
    main()
