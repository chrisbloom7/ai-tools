---
name: parallel-workstreams
description: Plan and orchestrate several parallel worktree sessions. Use ONLY when the user explicitly asks for parallel workstreams or multiple worktrees at once (for example "set up parallel workstreams for these tickets"), or invokes this skill by name. Do not use it just because several tasks were mentioned. Requires worktrunk CLI.
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

The user's own worktree rules, and the defaults in `worktree-start` ("The user's own worktree rules
come first"), apply to every workstream here. Do not restate them per task.

**Worktree setup check** — confirm worktrunk is installed and `wt config show` has a `worktree-path`
template (see `worktree-start` Prerequisites). If not, say so before proceeding and stop if the user
declines to fix it.

Then run the following checks:

1. **Base branch currency** — Run the stale-base check from `worktree-start` Step 3 once, before
   creating any worktrees (including its `--ff-only` update and its question to the user). If the user
   chooses not to update, note in the Step 5 report that all worktrees were created from a stale base.

2. **Project prerequisites** — Check for project-specific companion skills (same extensibility mechanism as `worktree-start`). If one exists, invoke it for pre-flight checks: services that need to be running, authentication that needs to be valid, etc. Run these once, not per-worktree.

3. **Independence validation** — Confirm the tasks are genuinely independent. For each pair of tasks, check:
   - Do they touch the same files or areas of the codebase?
   - Does one depend on the output of another?
   - Are there database migrations that could conflict?

   If tasks overlap, flag them and ask the user whether to:
   - Proceed anyway (accepting potential merge conflicts)
   - Sequence the overlapping tasks (one after the other)
   - Regroup (combine overlapping tasks into one workstream)

4. **Ordering constraints** — Note any merge ordering dependencies. Example: "Task A introduces a new API that Task B consumes — Task A must merge first." Record these for inclusion in each `WORKTREE_CONTEXT.md`.

### Step 3 — Plan All Workstreams

For each task, produce the implementation plan that `worktree-start` Step 2 would generate. This means:

- Identifying files/areas to be touched
- Outlining the approach
- Noting risks or open questions
- Referencing relevant skills

**Present all plans together** in a single summary for user review. Format as a table or numbered list showing each workstream with its plan summary, estimated scope, and any noted constraints.

Wait for user approval before proceeding to execution.

**Stacked workstreams:** If any tasks form a stack (B depends on A's output merging
first), do not plan them as branches within a single worktree. Each level is its own
workstream with its own worktree. The base branch for the dependent worktree is the
branch from the upstream task, not main. Note this in both `WORKTREE_CONTEXT.md` files
under Key Constraints.

### Step 4 — Execute

After approval, create each workstream sequentially using the `worktree-start` workflow:

1. Create worktree via `wt switch --create`
2. Write `WORKTREE_CONTEXT.md` — include ordering constraints from Step 2 if applicable, and include a **"Before You Begin"** section as the first action item for the worktree agent:
   > Validate this context file and the implementation plan. Check for incorrect assumptions that may have introduced gaps or could lead to errors in production. Do not make any changes to either document. Report your findings, then stop. Do not start work until given explicit approval.

   After writing the file, check whether it is auto-loaded (see `worktree-start` Step 4 for the
   exact grep command). If not, set `auto_load=false` for this worktree — item 4 will adjust the
   kickoff prompt accordingly.
3. Open the session window using the multiplexer (see `worktree-start` Step 5 for the exact tmux/zellij/fallback commands, session name, and path conventions).
4. **Send the kickoff prompt** — this is the step most commonly missed. Immediately after creating the window, send `claude <kickoff-prompt>` via `send-keys` (tmux) or equivalent. Do not skip this step. Verify the first window received the prompt before creating the remaining worktrees.

   **Kickoff prompt:** Use `"Hey Claude, do you know what we're working on?"` when
   auto-load is configured. If `auto_load=false` for this worktree, use:
   `"Please read WORKTREE_CONTEXT.md first to understand the task, then confirm what we're working on."`
5. Return to main worktree before creating the next one.

**tmux note:** When creating multiple windows, derive unique window names from task IDs or short slugs. Test window creation **and** the send-keys command on the first worktree before proceeding to the others — a bad escape or wrong target pane is easy to spot early, but a silent failure (window created, Claude never started) is easy to miss when creating many at once.

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
- Reminder that sessions with auto-load configured will load `WORKTREE_CONTEXT.md`
  automatically; others received an explicit read instruction in the kickoff prompt

---

## What This Skill Does NOT Do

- **Execute the actual development work** — each worktree session handles its own task independently
- **Manage PRs or merges** — use project-specific PR/merge skills
- **Monitor progress across streams** — the user manages each session independently
- **Worktree cleanup** — follow the user's removal rules or the project's cleanup skill (see
  `worktree-start`)

## Periodic Review

This workflow reflects current automation capabilities. When starting a new round of parallel streams, consider whether new capabilities (e.g., spawning sessions, monitoring progress) could shift the automation boundary. If something feels manual that shouldn't be, revisit.
