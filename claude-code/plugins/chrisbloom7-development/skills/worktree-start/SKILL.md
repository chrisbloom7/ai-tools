---
name: worktree-start
description: Start development on a new task using an isolated worktree. Use this skill when the user explicitly requests a worktree ("spin up a worktree", "start a worktree for..."), or when they ask to start work on a task AND the repo shows worktree signals (worktrunk config present, .worktrees/ directory exists, or CLAUDE.md mentions worktrees). Do NOT trigger automatically just because the user wants to start development — check first. Requires worktrunk CLI.
compatibility: Requires worktrunk CLI (https://worktrunk.dev) and git
---

# Worktree Start

Start development on a single task by creating an isolated worktree, writing structured context for the new session, and bootstrapping a Claude session in that worktree.

This skill builds on top of worktrunk (`wt` CLI) for worktree management. It adds the workflow layer: planning, context writing, and session bootstrapping.

## Prerequisites

- **worktrunk CLI** (`wt`) must be installed and configured
- **`worktree-path` template configured** in `~/.config/worktrunk/config.toml` — run `wt config show` to verify. If missing, run `wt config create` and set the template before continuing. Without it, `wt switch --create` will prompt interactively for a location.
- **git** repository with a clean working tree on the main branch (or a primary worktree)
- A task to work on (issue tracker ID, URL, description, or verbal explanation)

## Workflow

Work through these steps in order. Do not skip steps.

### Step 0 — Decide Whether a Worktree Is Appropriate

Before proceeding, confirm a worktree is the right approach. Check in order:

1. **Explicit request** — did the user say "worktree", "spin up", "isolated session", or similar? If yes, proceed.

2. **Repo signals** — does the repo show worktree usage?
   - `~/.config/worktrunk/config.toml` exists (worktrunk is configured)
   - `.worktrees/` directory exists at the repo root
   - `CLAUDE.md` mentions worktrees or worktrunk

   If any signal is present and the user is starting non-trivial work, proceed.

3. **Ask if uncertain** — if neither of the above, do not assume. Ask the user, surfacing relevant context:
   - Is this a multi-step feature or a quick fix?
   - Does the task have an issue tracker ID (suggesting tracked, non-trivial work)?
   - Is the repo branch-heavy (many open branches visible in `git branch -r`)?

   Frame the question helpfully: "This looks like [quick fix / tracked feature]. Would you like a worktree for isolation, or work directly on this branch?"

   If the user declines, stop — do not proceed with this skill.

### Step 1 — Gather Task Details

Collect enough information to plan the work:

1. If the user provided an issue tracker ID or URL, fetch the task details using the appropriate skill or tool (e.g., a project management integration). Extract: title, description, acceptance criteria, checklist items.
2. If the user described the task verbally, confirm your understanding before proceeding.
3. Note any constraints: dependencies on other work, merge ordering, related tasks.

### Step 2 — Plan the Implementation

Enter plan mode (`EnterPlanMode`). Produce a brief implementation plan covering:

- What files/areas of the codebase will be touched
- The approach (high-level steps)
- Any risks or open questions
- Relevant skills or documentation to reference during implementation

**Check for project-specific worktree configuration skills.** Some projects provide a companion skill that adds project-specific pre-flight checks, branch naming conventions, context enrichments, and skill references. If one is available, invoke it now to incorporate its requirements into your plan.

Present the plan and wait for user approval before continuing.

### Step 3 — Create the Worktree

**Check that the main branch is current before branching.** Run:

```bash
git fetch --quiet
behind=$(git rev-list --count HEAD..@{u} 2>/dev/null)
```

- If `behind` is `0` (or the command errors because there is no upstream), proceed.
- If `behind` is non-zero, **stop and ask the user:**
  > "Your main branch is `$behind` commit(s) behind its remote. Pull in the upstream
  > changes before creating the worktree? (Recommended — skipping may cause unnecessary
  > merge conflicts.)"
  - If yes: run `git pull` and verify it succeeds before continuing.
  - If no: proceed, but note in the Step 6 report that the worktree was created from a
    stale base.

Use worktrunk to create and switch to a new worktree:

```bash
wt switch --create <branch-name> --yes
```

**Branch naming:** Follow the project's branch naming conventions. If a project-specific configuration skill provides a convention, use it. Otherwise, derive a reasonable branch name from the task (e.g., `feature/add-user-auth`, `fix/login-timeout`).

Verify that any post-create hooks ran successfully. If any fail, stop and report before continuing.

### Step 4 — Write WORKTREE_CONTEXT.md

Write a `WORKTREE_CONTEXT.md` file in the new worktree root. This file is the primary mechanism for transferring context to the new session. Structure it as follows:

```markdown
# Task: [Title]

## Source
[Issue tracker link or "Verbal request from user"]

## Description
[Task description and acceptance criteria]

## Implementation Plan
[The plan from Step 2]

## Key Constraints
- [Any dependencies, merge ordering, or blockers]
- [Relevant skills to invoke during implementation]

## Notes
[Design decisions, context from related work, anything the new session needs to know]
```

The new session loads this file automatically via `CLAUDE.local.md` containing `@WORKTREE_CONTEXT.md`. If the project doesn't have this auto-load mechanism set up, note that in your report (Step 6).

### Step 5 — Open a Session in the Worktree

Detect the terminal environment and open a new Claude session in the worktree:

#### tmux (preferred — fully automated)

If `$TMUX` is set, create a new window in the current tmux session:

```bash
# Derive window name from branch or task ID
window_name="<short-identifier>"
worktree_path="<absolute-path-to-worktree>"

# Create window and cd into worktree
/opt/homebrew/bin/tmux new-window -c "$worktree_path" -n "$window_name"

# Send kickoff prompt — MUST escape with printf %q to handle
# apostrophes, ?, $, and other special characters safely
kickoff="Hey Claude, do you know what we're working on?"
escaped=$(printf %q "$kickoff")
/opt/homebrew/bin/tmux send-keys -t "$window_name" "claude $escaped" Enter
```

**Critical tmux caveats:**
- Claude Code's bash shell has a restricted PATH — always use full paths: `/opt/homebrew/bin/tmux`, `/bin/cat`, `/usr/bin/tr`
- **Always use `printf %q`** to escape the kickoff prompt before `send-keys`. Apostrophes in the prompt (e.g., "we're") break single-quoted strings and expose `?` as a zsh glob pattern.
- Multi-line prompts must be flattened before send-keys — newlines cause premature Enter: `prompt=$(/bin/cat /tmp/kickoff.txt | /usr/bin/tr '\n' ' ')`
- Test on one window before looping when creating multiple windows

#### zellij

If `$ZELLIJ` is set:

```bash
zellij run -- bash -c "cd '$worktree_path' && claude 'Hey Claude, do you know what we are working on?'"
```

Note: avoid contractions in zellij prompts to sidestep quoting issues.

#### No multiplexer (fallback)

If neither tmux nor zellij is detected:

1. Open the worktree in the user's editor: `$EDITOR <worktree-path>`
2. Instruct the user to start Claude Code in that directory and send the kickoff prompt: **"Hey Claude, do you know what we're working on?"**

### Step 6 — Report

Confirm the setup:

| Detail | Value |
|--------|-------|
| Worktree | `<path>` |
| Branch | `<branch-name>` |
| Task | `<title or ID>` |
| Session | opened in tmux/zellij / manual instructions provided |
| Context | `WORKTREE_CONTEXT.md` written |
| Auto-load | confirmed / not configured (manual load needed) |

If there are merge ordering constraints or dependencies on other work, remind the user here.

---

## Stacked PRs

When work requires stacked PRs (PR B builds on PR A), each level of the stack gets its
own worktree. Do **not** create a second branch inside an existing worktree.

**Correct pattern:**
1. Create worktree A from main: `wt switch --create feature/pr-a`
2. When PR A is ready and you need PR B, create worktree B from A's branch:
   ```bash
   # From the main worktree, with feature/pr-a as the base
   wt switch --create feature/pr-b --base feature/pr-a
   ```
3. Each worktree contains only the changes for its own PR.

**Why:** A worktree's working tree reflects one branch. If you create `feature/pr-b`
inside `feature/pr-a`'s worktree, both sets of changes are visible simultaneously —
you lose isolation and git operations (diff, status, review) become confusing.

## What This Skill Does NOT Do

- **Merge or PR management** — use `wt merge` or your project's PR skill for that
- **Project-specific pre-flight** (Docker, services, auth) — handled by project-specific companion skills
- **Worktree cleanup** — use worktrunk directly (`wt remove`) or a finishing skill

## Extensibility

This skill supports project-specific companion skills that provide:
- Pre-flight checks (services, auth, dependencies)
- Branch naming conventions
- Issue tracker integration
- Additional `WORKTREE_CONTEXT.md` content
- Skill references for the new session

If your project has a companion skill, it will be invoked during Step 2 planning. To create one for your project, model it after this pattern: provide a skill that triggers alongside `worktree-start` and returns project-specific configuration.
