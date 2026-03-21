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

# Optional store backend (Redis or JSON fallback)
def _load_store(workspace_dir):
    """Return a Store instance or None if store.py is unavailable."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from store import Store
        return Store(workspace_dir)
    except Exception:
        return None


def _check_security_gate(store) -> tuple[bool, str]:
    """
    Return (blocked, reason). Blocks the pipeline if the security agent
    issued a BLOCKED verdict that hasn't been cleared.
    """
    if store is None:
        return False, ''
    verdict = store.get_security_verdict()
    if verdict and verdict.get('verdict') == 'BLOCKED':
        critical = verdict.get('critical_count', 0)
        high = verdict.get('high_count', 0)
        findings = verdict.get('findings', [])
        reason = (
            f"Security verdict: BLOCKED "
            f"(critical={critical}, high={high})\n"
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


def _build_selective_context(context: dict, agent_key: str, client, model: str) -> str:
    """
    Build a context block with only the outputs most relevant to this agent.
    Each agent type gets the specific upstream outputs it needs rather than
    the entire accumulated context, keeping prompts focused and token-efficient.
    """
    # Define which prior agents each agent actually needs
    RELEVANT_PRIOR = {
        'research':  [],
        'security':  ['ba'],
        'architect': ['ba', 'research', 'security'],
        'developer': ['architect', 'research'],
        'database':  ['architect', 'research'],
        'qa':        ['developer', 'database', 'architect'],
        'e2e':       ['developer', 'database'],
        'docs':      ['developer', 'database', 'architect', 'ba'],
        'devops':    ['developer', 'database', 'architect'],
        'reviewer':  ['developer', 'database', 'qa', 'security'],
        'lead':      ['reviewer', 'security'],
    }
    relevant_keys = RELEVANT_PRIOR.get(agent_key, list(context.keys()))
    filtered = {k: v for k, v in context.items() if k in relevant_keys}
    return build_context_block(filtered, client, model, summarize=True)


# ─── Agent Definitions ─────────────────────────────────────────────────────────

AGENTS = {
    'ba': {
        'name': 'Business Analyst',
        'emoji': '📋',
        'system': """You are the Business Analyst on an agentic software development team.
Your role is to deeply understand the problem being solved before any design or code is written.

When given a task, you will:
1. Frame the problem: who has it, what pain it causes, what success looks like
2. Research the domain: industry standards, competitive approaches, UX patterns
3. Identify what already exists in the codebase related to this problem
4. Produce a structured requirements document (functional + non-functional + out of scope)
5. Write a concise specification brief for the architect

Key rules:
- Requirements describe user needs, not implementation choices
- Out of scope is as important as in scope
- Every requirement must have an acceptance criterion

Output format: Problem Statement → Domain Summary → Requirements Table → Architect Handoff Brief""",
    },
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

When given research findings, BA requirements, and a task, you will:
1. Analyze how the request fits with existing patterns
2. Design the minimal solution that achieves the goal
3. Identify exactly which files to create and modify
4. Define interfaces and data contracts
5. Create an implementation checklist for the developer

Prefer existing patterns. Only introduce new patterns with explicit justification.
Output a concrete implementation brief the developer can follow exactly.""",
    },
    'security': {
        'name': 'Security Agent',
        'emoji': '🔐',
        'system': """You are the Security Agent on an agentic software development team.
Your role is to assess security risks proactively — both before design and after implementation.

When given a task or codebase to review, you will:
1. Identify the attack surface (entry points, trust boundaries, data assets)
2. Apply STRIDE threat modeling to key components
3. Scan for dependency vulnerabilities (CVEs in package.json, requirements.txt, etc.)
4. Detect hardcoded secrets or credentials
5. Flag compliance implications (GDPR, SOC2, HIPAA, PCI-DSS)
6. Rate every finding: CRITICAL / HIGH / MEDIUM / LOW
7. Provide specific remediation for every finding

CRITICAL: After completing your assessment, write your verdict to the workspace:
  python3 .dev-team/../scripts/workspace.py set-security-verdict \\
    --verdict <CLEAR|WARNINGS|REMEDIATION_REQUIRED|BLOCKED> \\
    --findings "<finding1>,<finding2>" \\
    --critical <N> --high <N>

Verdict rules:
  BLOCKED           — any CRITICAL finding or hardcoded secret in git history
  REMEDIATION_REQUIRED — any HIGH finding
  WARNINGS          — only MEDIUM/LOW findings
  CLEAR             — no findings

Output: threat model → dependency findings → static analysis → compliance flags → verdict""",
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
    'qa': {
        'name': 'QA Engineer',
        'emoji': '🧪',
        'system': """You are the QA Engineer on an agentic software development team.
Your role is to write tests that verify implemented features AND confirm they pass.

When given implementation details, you will:
1. Detect the test framework (pytest, jest, vitest, go test, etc.) from config files
2. Read 2-3 existing test files to match the exact style
3. Write tests covering happy paths, edge cases, and error cases
4. RUN the tests immediately after writing them using the project's test command
5. Fix any failing tests before reporting completion
6. Report exact pass/fail counts and coverage delta

CRITICAL: Always run tests after writing them. Never leave failing tests.
Use the Bash tool to execute: pytest / npm test / go test ./... / etc.

Output format:
  TESTS WRITTEN: <file> — <N> tests
  TEST RUN: <N> passing / <M> failing
  COVERAGE: <before>% → <after>%
  REGRESSIONS: none | <list any broken existing tests>""",
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
    'e2e': {
        'name': 'E2E Tester',
        'emoji': '🌐',
        'system': """You are the E2E Tester on an agentic software development team.
Your role is to spin up the application and test real user workflows end-to-end using browser and mobile automation.

When given implementation details or a feature to validate, you will:
1. Detect how to start the application (npm scripts, docker-compose, manage.py, etc.)
2. Start the app and verify it is running
3. Install Playwright (web) or use Detox/Appium (mobile) if not already present
4. Write and run test scenarios covering critical user workflows (happy paths + error cases)
5. Report each bug found with reproduction steps, severity, and a screenshot reference
6. Stop background processes after testing

Key rules:
- Test workflows, not components — validate real user journeys
- Use data-testid selectors where possible; fall back to ARIA roles
- Always take screenshots on failure
- Cover at least one mobile viewport for web apps
- Don't duplicate what unit tests already cover

Output: app startup confirmation → test plan → test results (pass/fail per workflow) → structured bug reports for any failures""",
    },
    'triage': {
        'name': 'Issue Triage Agent',
        'emoji': '🎯',
        'system': """You are the Issue Triage Agent on an agentic software development team.
Your role is to read GitHub issues, classify them, estimate complexity, and route them to the right agents.

When given an issue or set of issues, you will:
1. Read the full issue content (title, body, comments)
2. Classify the type: bug / feature / tech-debt / question / security / epic
3. Estimate complexity: small / medium / large / epic
4. Identify which dev team agents should handle the work
5. Post a structured triage comment on the issue via gh CLI
6. Apply appropriate labels

For security issues: escalate immediately regardless of apparent severity.
For epics: produce a breakdown into smaller issues before routing to implementation agents.

Use the `gh` CLI for all GitHub operations.""",
    },
    'lead': {
        'name': 'Lead Engineer',
        'emoji': '🚀',
        'system': """You are the Lead Engineer on an agentic software development team.
Your role is to manage the full GitHub pull request lifecycle.

FIRST: Before doing anything else, check the security verdict:
  python3 scripts/workspace.py get-security-verdict
  If verdict is BLOCKED, do NOT create or merge a PR. Post the security findings
  as a comment on the relevant issue and stop. Report: PIPELINE BLOCKED — security issues must be resolved.

When given a task (and security is not blocked), you will:
1. Create pull requests with well-structured descriptions (summary, changes, testing checklist)
2. Review PRs using the full security/performance/correctness/pattern checklist
3. Post structured inline comments with severity ratings and specific fix suggestions
4. Approve PRs when no blockers are found
5. Request changes with a clear list of required fixes
6. Merge approved PRs (prefer squash merge to keep history clean)

Use `gh pr create`, `gh pr review`, and `gh pr merge` for all GitHub operations.
Nothing merges without passing CI and a clean review. CRITICAL findings always block.""",
    },
}

# ─── Pipeline Definitions ──────────────────────────────────────────────────────

# Simple sequential pipeline (default for --agents flag)
DEFAULT_PIPELINE = ['ba', 'research', 'architect', 'developer', 'reviewer', 'qa', 'docs']

# Staged pipeline with fan-out/fan-in (used with --staged flag)
# Each stage is a list of agents that run in parallel within that stage.
# Agents in later stages receive the combined output of all prior stages.
STAGED_PIPELINE = [
    ['ba'],                          # Stage 1: Requirements
    ['research', 'security'],        # Stage 2: Research + threat model (parallel)
    ['architect'],                   # Stage 3: Architecture (needs both stage 2 outputs)
    ['developer', 'database'],       # Stage 4: Implementation (parallel where applicable)
    ['qa', 'e2e', 'docs', 'devops'],  # Stage 5: Quality + docs (parallel)
    ['reviewer'],                    # Stage 6: Code review (needs all stage 5 outputs)
    ['lead'],                        # Stage 7: PR creation and merge
]


# ─── Context Management ────────────────────────────────────────────────────────

def summarize_agent_output(client, model: str, agent_name: str, output: str) -> str:
    """
    Produce a concise summary of an agent's output for passing to downstream agents.
    Falls back to truncation if the API call fails.
    """
    if len(output) <= 3000:
        return output

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1000,
            system="You are a technical summarizer. Extract the most important findings, decisions, and action items from agent output. Be concise but preserve all critical technical details, file paths, and specific recommendations.",
            messages=[{
                'role': 'user',
                'content': f"Summarize this {agent_name} output, preserving all critical technical details:\n\n{output[:8000]}"
            }],
        )
        return f"[SUMMARY of {agent_name} output]\n{response.content[0].text}"
    except Exception:
        # Fallback: smart truncation keeping first and last portions
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

        context_str = context_override or _build_selective_context(
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

        workspace_dir = Path(project_root) / '.dev-team' if not self.workspace_root else Path(self.workspace_root)
        self._store = _load_store(workspace_dir)

        for agent_key in pipeline:
            if agent_key not in AGENTS:
                print(f"WARNING: Unknown agent '{agent_key}', skipping", file=sys.stderr)
                continue

            # Security gate before lead agent
            if agent_key == 'lead':
                blocked, reason = _check_security_gate(self._store)
                if blocked:
                    print(f"\nPIPELINE BLOCKED — Security verdict requires remediation:\n{reason}", file=sys.stderr)
                    print("Resolve security findings and re-run from the lead stage.")
                    break

            # Feedback gate — pause on blocking feedback
            has_blocking, blocking = _check_feedback_gate(self._store, stage_num=0)
            if has_blocking:
                print(f"\nPIPELINE PAUSED — {len(blocking)} blocking feedback item(s):", file=sys.stderr)
                for f in blocking:
                    print(f"  [{f['from']} → {f.get('to','all')}] {f['message']}", file=sys.stderr)
                print("Resolve blocking feedback via: workspace.py push-feedback --severity INFO (to clear)", file=sys.stderr)
                break

            self.run_agent(agent_key, enriched_task)

            # After dev/database stages, check for dependency conflicts
            if agent_key in ('developer', 'database') and self._store:
                conflicts = self._store.get_dependency_conflicts()
                if conflicts:
                    print(f"\nDEPENDENCY CONFLICTS DETECTED ({len(conflicts)}):", file=sys.stderr)
                    for c in conflicts:
                        print(f"  {c['ecosystem']}:{c['name']} — {len(c['conflicts'])} conflict(s)", file=sys.stderr)

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

        workspace_dir = Path(project_root) / '.dev-team' if not self.workspace_root else Path(self.workspace_root)
        self._store = _load_store(workspace_dir)

        for stage_num, stage_agents in enumerate(pipeline, 1):
            # Filter out unknown agents
            valid_agents = [a for a in stage_agents if a in AGENTS]
            unknown = [a for a in stage_agents if a not in AGENTS]
            if unknown:
                print(f"WARNING: Skipping unknown agents in stage {stage_num}: {unknown}", file=sys.stderr)
            if not valid_agents:
                continue

            # Security gate: block before lead stage
            if 'lead' in valid_agents:
                blocked, reason = _check_security_gate(self._store)
                if blocked:
                    print(f"\n{'═' * 60}")
                    print(f"PIPELINE BLOCKED at stage {stage_num} — Security verdict: BLOCKED")
                    print(reason)
                    print("Fix the reported security issues, clear the verdict, and re-run.")
                    print(f"{'═' * 60}")
                    break

            # Feedback gate: pause on any blocking feedback before this stage
            has_blocking, blocking = _check_feedback_gate(self._store, stage_num)
            if has_blocking:
                print(f"\n{'═' * 60}")
                print(f"PIPELINE PAUSED at stage {stage_num} — {len(blocking)} blocking feedback item(s):")
                for f in blocking:
                    print(f"  [{f['from']} → {f.get('to','all')}] {f['message']}")
                print("Resolve via: workspace.py push-feedback (clear the blocking message)")
                print(f"{'═' * 60}")
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

            # After dev/database stages, surface dependency conflicts
            if any(a in ('developer', 'database') for a in valid_agents) and self._store:
                conflicts = self._store.get_dependency_conflicts()
                if conflicts:
                    print(f"\nDEPENDENCY CONFLICTS ({len(conflicts)}) — review before proceeding:")
                    for c in conflicts:
                        print(f"  {c['ecosystem']}:{c['name']} — {len(c['conflicts'])} conflicting version(s)")

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
        workspace = Path(self.workspace_root) if self.workspace_root else Path(project_root) / '.dev-team'
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
