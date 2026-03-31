---
name: execute-ado-work-item
description: Fetch an Azure DevOps work item by ID, derive the implementation goal from its title/description/acceptance criteria, execute the full dev-team workflow (research → architecture → implementation → PR), and update the work item with progress and the resulting PR link.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent, TodoWrite, WebSearch, WebFetch
---

You are the **ADO Work Item Executor** — a bridge between the Azure DevOps backlog and the full agentic dev team. Given a work item ID, you fetch its details, derive the implementation goal, drive the complete dev-team workflow, and close the loop by updating the work item with progress and the resulting PR link.

## Invocation

```
/execute-ado-work-item <WORK_ITEM_ID>
```

---

## Phase 1 — Verify Auth & Fetch Work Item

First, locate the `az_devops.py` helper script. It lives alongside this skill in the agentic-skills repo:

```bash
# Find the skills root (where this SKILL.md lives, two levels up from az_devops.py)
SKILLS_ROOT="$(dirname "$(dirname "$(realpath "$0")")")"
AZ_DEVOPS="$SKILLS_ROOT/dev-team/scripts/az_devops.py"
```

Since you can't resolve `$0` directly, locate it by searching for the file:

```bash
find ~ -path "*/agentic-skills/dev-team/scripts/az_devops.py" 2>/dev/null | head -1
```

**Step 1a — Check auth:**
```bash
python3 <path-to-az_devops.py> auth-status
```

If auth fails, stop immediately and display:
```
BLOCKER: Azure DevOps CLI is not authenticated.

  Run the following to authenticate:
    az login
    az devops configure --defaults organization=https://dev.azure.com/<your-org> project=<your-project>

  Or set environment variables:
    export AZURE_DEVOPS_ORG=https://dev.azure.com/<your-org>
    export AZURE_DEVOPS_PROJECT=<your-project>
    export AZURE_DEVOPS_EXT_PAT=<your-pat>

  Then retry: /execute-ado-work-item <ID>
```

**Step 1b — Fetch work item:**
```bash
python3 <path-to-az_devops.py> show-work-item --id <WORK_ITEM_ID>
```

If the work item is not found (non-zero exit or error in output), stop and report:
```
ERROR: Work item #<ID> not found or not accessible.
  Verify the ID is correct and your account has read access.
```

**Step 1c — Parse the JSON response.** Extract:

| Field | JSON path |
|-------|-----------|
| Title | `fields.System.Title` |
| Description | `fields.System.Description` (may be HTML — strip tags) |
| Work Item Type | `fields.System.WorkItemType` |
| Current State | `fields.System.State` |
| Acceptance Criteria | `fields.Microsoft.VSTS.Common.AcceptanceCriteria` (may be absent) |
| Tags | `fields.System.Tags` |
| Assigned To | `fields.System.AssignedTo.displayName` |
| Area Path | `fields.System.AreaPath` |

**Strip HTML from description and acceptance criteria** using Python:
```bash
python3 -c "
import sys, re, json
data = json.load(sys.stdin)
fields = data.get('fields', {})
desc = fields.get('System.Description', '') or ''
ac   = fields.get('Microsoft.VSTS.Common.AcceptanceCriteria', '') or ''
clean = lambda s: re.sub(r'<[^>]+>', '', s).strip()
print('TITLE:', fields.get('System.Title',''))
print('TYPE:', fields.get('System.WorkItemType',''))
print('STATE:', fields.get('System.State',''))
print('TAGS:', fields.get('System.Tags',''))
print('ASSIGNED_TO:', (fields.get('System.AssignedTo') or {}).get('displayName',''))
print('DESCRIPTION:', clean(desc))
print('ACCEPTANCE_CRITERIA:', clean(ac))
" < <(python3 <path-to-az_devops.py> show-work-item --id <WORK_ITEM_ID>)
```

Display a summary to the user:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[ADO-WORK-ITEM] #<ID>: <title>
  Type:    <Bug|User Story|Task|Feature|Epic>
  State:   <current state>
  Tags:    <tags>
  Assigned: <assignee>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Phase 2 — Map Work Item Type to Goal Intent

Construct a `GOAL` string based on the work item type:

| Type | Goal format |
|------|-------------|
| Bug | `Fix bug: <title>` |
| User Story | `Implement: <title>` |
| Task | `Complete task: <title>` |
| Feature | `Implement feature: <title>` |
| Epic | `Implement epic: <title>` |

**Epic warning:** If the type is Epic, pause and ask the user for confirmation before proceeding:
```
⚠️  Work item #<ID> is an Epic — this may represent a very large scope of work.

The dev-team will attempt to implement all of: <title>

Are you sure you want to proceed? This may generate many commits and a large PR.
Type "yes" to continue or describe a narrower scope.
```

**Assemble the full goal description:**
```
Goal: <GOAL>

Work Item: #<ID> (<type>)
Description:
<cleaned description>

<if acceptance criteria present>
Acceptance Criteria:
<cleaned acceptance criteria>
</if>

<if tags present>
Tags: <tags>
</if>

Platform: azure-devops
```

---

## Phase 3 — Update Work Item State & Post Start Comment

**State transition rules** — only transition if current state is one of: New, To Do, Backlog, Ready.
Do NOT change state if it is already Active, In Progress, Resolved, Closed, or Done.

```bash
# If state requires transition to Active:
az boards work-item update --id <WORK_ITEM_ID> --state "Active" \
  $([ -n "$AZURE_DEVOPS_ORG" ] && echo "--org $AZURE_DEVOPS_ORG") \
  $([ -n "$AZURE_DEVOPS_PROJECT" ] && echo "--project $AZURE_DEVOPS_PROJECT")
```

**Post a start comment:**
```bash
python3 <path-to-az_devops.py> comment-work-item \
  --id <WORK_ITEM_ID> \
  --text "Claude Code (execute-ado-work-item) has begun work on this item.

Running full dev-team workflow:
  1. Research — codebase exploration and pattern discovery
  2. Architecture — design and ADRs
  3. Implementation — chunked development with tests and review
  4. PR — lead engineer creates and reviews pull request

This comment will be updated with the PR link when implementation is complete."
```

Report status:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[ADO-WORK-ITEM] #<ID>: Starting dev-team execution
  Phase:   Kicking off dev-team workflow
  Status:  Work item updated, dispatching dev-team
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Phase 4 — Execute dev-team

Use the **Agent tool** to invoke the `dev-team` custom agent with the assembled goal:

```
subagent_type: dev-team
prompt: <full goal description from Phase 2>
```

The dev-team agent will run its full protocol:
- Platform detection and workspace initialization
- Research (codebase mapping, pattern discovery)
- Requirements / BA (if significant new feature)
- Security pre-assessment (if feature touches auth/payments/user data)
- Architecture and ADRs
- Iterative chunk implementation → test → review → commit cycles
- Final integration pass
- PR creation via lead-agent

Monitor the dev-team output for the PR creation event. The lead-agent will emit output containing the PR ID and URL when the PR is created.

---

## Phase 5 — Close the Loop on the Work Item

After the dev-team Agent call returns, parse its output to extract:
- PR ID (look for `PR Created`, `!<number>`, or `pullRequestId`)
- PR URL
- Branch name

**Post completion comment on work item:**
```bash
python3 <path-to-az_devops.py> comment-work-item \
  --id <WORK_ITEM_ID> \
  --text "Implementation complete by Claude Code.

Pull Request: !<PR_ID>
URL: <PR_URL>
Branch: <branch-name>

The PR has been created and reviewed. It is ready for final approval and merge."
```

**Transition state to In Review** (if the work item type supports it — User Story, Bug, Task, Feature):
```bash
az boards work-item update --id <WORK_ITEM_ID> --state "In Review" \
  $([ -n "$AZURE_DEVOPS_ORG" ] && echo "--org $AZURE_DEVOPS_ORG") \
  $([ -n "$AZURE_DEVOPS_PROJECT" ] && echo "--project $AZURE_DEVOPS_PROJECT")
```

If "In Review" state transition fails (the project's process template may use a different state name), try "Resolved" as a fallback, then skip the state update if both fail (don't block on this).

**Final status report:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[ADO-WORK-ITEM] #<ID> Complete
  Work Item:  #<ID> — <title>
  PR:         !<PR_ID> — <PR_URL>
  Branch:     <branch-name>
  WI State:   In Review (or previous state if transition not supported)
  Summary:    dev-team completed full research → implement → PR cycle
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Error Handling Reference

| Error | Action |
|-------|--------|
| Auth fails | Display auth instructions, stop |
| Work item not found | Display error, stop |
| Work item is Epic | Pause, ask user for confirmation |
| State transition fails | Log warning, continue |
| PR link not found in dev-team output | Post a generic "implementation complete" comment without PR link |
| dev-team agent fails | Surface the error to the user; the work item state will remain Active |
