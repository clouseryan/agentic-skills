"""
Context Management — Dev Team Orchestrator

Handles building, filtering, and summarizing context passed between agents.
Keeps prompts focused and token-efficient by giving each agent only the
upstream outputs it needs.
"""

from agents import AGENTS


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


def build_selective_context(context: dict, agent_key: str, client, model: str) -> str:
    """
    Build a context block with only the outputs most relevant to this agent.
    Each agent type gets the specific upstream outputs it needs rather than
    the entire accumulated context, keeping prompts focused and token-efficient.
    """
    relevant_keys = RELEVANT_PRIOR.get(agent_key, list(context.keys()))
    filtered = {k: v for k, v in context.items() if k in relevant_keys}
    return build_context_block(filtered, client, model, summarize=True)
