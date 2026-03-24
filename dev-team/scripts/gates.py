"""
Pipeline Gates — Dev Team Orchestrator

Security and feedback gates that can block or pause the pipeline.
"""

from pathlib import Path


def check_security_gate(store) -> tuple[bool, str]:
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


def check_feedback_gate(store, stage_num: int) -> tuple[bool, list]:
    """Return (has_blocking, blocking_items) for the current stage."""
    if store is None:
        return False, []
    blocking = [
        f for f in store.get_feedback(unresolved_only=True)
        if f.get('severity') == 'BLOCKING'
    ]
    return bool(blocking), blocking


def snapshot_files(store, file_paths: list, stage_num: int, project_root: Path) -> None:
    """Record before-snapshots of files for rollback purposes."""
    if store is None:
        return
    for rel_path in file_paths:
        abs_path = project_root / rel_path
        before = abs_path.read_text(errors='replace') if abs_path.exists() else None
        store.log_file_snapshot(rel_path, before, stage_num)
