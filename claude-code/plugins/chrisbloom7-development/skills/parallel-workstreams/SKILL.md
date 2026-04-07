---
name: parallel-workstreams
description: Plan and orchestrate multiple parallel worktree development sessions. Use this skill when the user wants to work on multiple features, issues, stories, or tasks simultaneously — e.g., "let's work on these 3 stories in parallel", "spin up workstreams for these tickets", "I want to parallelize this work", or provides multiple issue IDs and expects concurrent development. Also use when they mention "parallel development", "multiple worktrees at once", or "batch these tasks". Requires worktrunk CLI.
compatibility: Requires worktrunk CLI (https://worktrunk.dev), git, and the worktree-start skill
---

# Parallel Workstreams

Plan and orchestrate multiple parallel worktree development sessions. This skill coordinates several instances of the `worktree-start` workflow, adding pre-flight validation, independence checking, and a unified planning phase.

Running 3-5 independent workstreams simultaneously recaptures time lost to CI queues, PR review waits, and context switching. The key is ensuring tasks are genuinely independent before parallelizing them.

## Prerequisites

- **worktree-start** skill must be available (same plugin)
- **worktrunk CLI** (`wt`) installed and configured
- Clean main worktree as the orchestration point
- Multiple tasks to parallelize (issue IDs, URLs, or descriptions)

## Workflow

### Step 1 — Collect Tasks

Gather all tasks the user wants to parallelize:

1. If the user provided issue tracker IDs or URLs, fetch details for each using the appropriate skill or tool.
2. If described verbally, list them back for confirmation.
3. For each task, capture: ID/title, brief description, key files or areas likely to be touched.

### Step 2 — Pre-flight Checks

Before creating any worktrees:

1. **Project prerequisites** — Check for project-specific companion skills (same extensibility mechanism as `worktree-start`). If one exists, invoke it for pre-flight checks: services that need to be running, authentication that needs to be valid, etc. Run these once, not per-worktree.

2. **Independence validation** — Confirm the tasks are genuinely independent. For each pair of tasks, check:
   - Do they touch the same files or areas of the codebase?
   - Does one depend on the output of another?
   - Are there database migrations that could conflict?

   If tasks overlap, flag them and ask the user whether to:
   - Proceed anyway (accepting potential merge conflicts)
   - Sequence the overlapping tasks (one after the other)
   - Regroup (combine overlapping tasks into one workstream)

3. **Ordering constraints** — Note any merge ordering dependencies. Example: "Task A introduces a new API that Task B consumes — Task A must merge first." Record these for inclusion in each `WORKTREE_CONTEXT.md`.

### Step 3 — Plan All Workstreams

For each task, produce the implementation plan that `worktree-start` Step 2 would generate. This means:

- Identifying files/areas to be touched
- Outlining the approach
- Noting risks or open questions
- Referencing relevant skills

**Present all plans together** in a single summary for user review. Format as a table or numbered list showing each workstream with its plan summary, estimated scope, and any noted constraints.

Wait for user approval before proceeding to execution.

### Step 4 — Execute

After approval, create each workstream sequentially using the `worktree-start` workflow:

1. Create worktree via `wt switch --create`
2. Write `WORKTREE_CONTEXT.md` (include ordering constraints from Step 2 if applicable)
3. Open session (tmux window, zellij pane, or editor)
4. Return to main worktree before creating the next one

**tmux note:** When creating multiple windows, derive unique window names from task IDs or short slugs. Test the first window before looping — mistakes create duplicate windows that must be manually killed.

### Step 5 — Report

Present a summary table of all workstreams:

| # | Task | Branch | Worktree Path | Session | Constraints |
|---|------|--------|---------------|---------|-------------|
| 1 | [title] | `branch-name` | `/path/to/wt` | tmux: `window-name` | None |
| 2 | [title] | `branch-name` | `/path/to/wt` | tmux: `window-name` | Merges after #1 |
| 3 | [title] | `branch-name` | `/path/to/wt` | tmux: `window-name` | None |

Include:
- Any merge ordering constraints (repeated here for visibility)
- How to switch between sessions (e.g., tmux window navigation)
- Reminder that each session auto-loads its `WORKTREE_CONTEXT.md` on first prompt

---

## What This Skill Does NOT Do

- **Execute the actual development work** — each worktree session handles its own task independently
- **Manage PRs or merges** — use project-specific PR/merge skills
- **Monitor progress across streams** — the user manages each session independently
- **Worktree cleanup** — use worktrunk directly or a finishing skill

## Periodic Review

This workflow reflects current automation capabilities. When starting a new round of parallel streams, consider whether new capabilities (e.g., spawning sessions, monitoring progress) could shift the automation boundary. If something feels manual that shouldn't be, revisit.
