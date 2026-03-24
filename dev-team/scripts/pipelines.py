"""
Pipeline Definitions — Dev Team Orchestrator

Defines the execution order and parallelism for agent pipelines.
"""

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
