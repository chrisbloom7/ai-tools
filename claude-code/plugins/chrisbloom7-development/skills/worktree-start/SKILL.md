---
name: worktree-start
description: Start development on a new task in an isolated worktree. Use ONLY when the user explicitly asks for a worktree (for example "spin up a worktree" or "start a worktree for ...") or invokes this skill by name. Do not use it because a task is starting or because the repo has worktree config. Requires worktrunk CLI.
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

## The user's own worktree rules come first

If the user has their own worktree or worktrunk rules (for example in `~/.claude/rules/`, the project's
`CLAUDE.md` or a project rule), follow them wherever they differ from this skill. The defaults below
apply when no such rules are loaded:

- Manage worktrees with `wt`, never raw `git worktree`. Create with `wt switch --create <branch> --yes`.
- Verify any post-create hooks ran. If one failed, stop and report.
- Never run `wt merge`. Open a PR for the owner to merge.
- Update a stale base with `git pull --ff-only`, and only after asking.
- Follow the repo's existing branch naming. Branch from the base the project names (not always the
  default branch).
- Remove a worktree with `wt remove`. If its branch is not merged, ask whether to keep or discard the
  branch first.

## Workflow

Work through these steps in order. Do not skip steps.

### Step 0 — Confirm the Request

This skill runs only when the user explicitly asked for a worktree or invoked it by name. If it was
loaded without such a request, ask once: "Do you want a worktree for this, or should I work on the
current branch?" If the user declines, stop. Do not proceed with this skill.

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

**Check that the base branch is current before branching.** The base is the branch the project says
new work starts from (a project rule or companion skill names it; when none does, it is the default
branch). Run:

```bash
git fetch --quiet
behind=$(git rev-list --count HEAD..@{u} 2>/dev/null)
```

- If `behind` is `0` (or the command errors because there is no upstream), proceed.
- If `behind` is non-zero, **stop and ask the user:**
  > "Your base branch is `$behind` commit(s) behind its remote. Fast-forward it before creating
  > the worktree? (Recommended — skipping may cause unnecessary merge conflicts.)"
  - If yes: run `git pull --ff-only` and verify it succeeds before continuing. If it refuses, the
    branches have diverged: stop and report instead of forcing it.
  - If no: proceed, but note in the Step 6 report that the worktree was created from a
    stale base.

Use worktrunk to create and switch to a new worktree. Add `--base <branch>` when the project's base
is not the default branch (and for stacked work, see below):

```bash
wt switch --create <branch-name> --yes
```

**Branch naming:** Follow the project's branch naming conventions. If a project-specific configuration
skill or rule provides a convention, use it. Otherwise look at how the repo already names branches
(`git branch -r --sort=-committerdate | head`) and match that. Only if there is no pattern, derive a
name from the task (for example `feature/add-user-auth`, `fix/login-timeout`).

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

**After writing the file, check whether it will be auto-loaded.** Start with
`auto_load=true` as the default. Then look for an include of the file (`@WORKTREE_CONTEXT.md`, which
also matches a doubled `@@` variant) in either `CLAUDE.md` or `CLAUDE.local.md` in the worktree root:

```bash
grep -lF "@WORKTREE_CONTEXT.md" CLAUDE.md CLAUDE.local.md 2>/dev/null
```

- **If a match is found:** the file will be auto-loaded. Leave `auto_load=true`; no further
  action is needed here.
- **If no match is found:** set `auto_load=false`, which Step 5 uses to adjust the kickoff
  prompt. Do not create or modify `CLAUDE.md` / `CLAUDE.local.md` yourself — that is the
  user's configuration to own.

### Step 5 — Open a Session in the Worktree

Detect the terminal environment and open a new Claude session in the worktree:

#### tmux (preferred — fully automated)

If `$TMUX` is set, create a new window in the current tmux session.

If `$TMUX` is NOT set but tmux is available (`test -n "$(command -v tmux 2>/dev/null)"`), check if any sessions are currently open with `tmux list` and ask the user which one to use or if a new one should be started. Then stop and wait for input before continuing.

```bash
# Derive window name from branch or task ID
window_name="<short-identifier>"
worktree_path="<absolute-path-to-worktree>"

# Resolve tmux to an absolute path once (Claude Code's shell has a restricted PATH,
# so a bare `tmux` may not resolve; this works on Apple Silicon, Intel macOS and Linux)
tmux_bin=$(command -v tmux 2>/dev/null)
if [ -z "$tmux_bin" ]; then
  for candidate in /opt/homebrew/bin/tmux /usr/local/bin/tmux /usr/bin/tmux /bin/tmux; do
    [ -x "$candidate" ] && tmux_bin=$candidate && break
  done
fi
[ -n "$tmux_bin" ] || { echo "tmux not found" >&2; exit 1; }

# Create window and cd into worktree
"$tmux_bin" new-window -c "$worktree_path" -n "$window_name"

# Send kickoff prompt — MUST escape with printf %q to handle
# apostrophes, ?, $, and other special characters safely
if [ "$auto_load" = "false" ]; then
  kickoff="Please read WORKTREE_CONTEXT.md first to understand the task, then confirm what we're working on."
else
  kickoff="Hey Claude, do you know what we're working on?"
fi
escaped=$(printf %q "$kickoff")
"$tmux_bin" send-keys -t "$window_name" "claude $escaped" Enter
```

**Critical tmux caveats:**
- Claude Code's bash shell has a restricted PATH — always call tmux through the absolute path in `$tmux_bin` (resolved above) and use full paths for other tools, e.g. `/bin/cat`, `/usr/bin/tr`. Reuse `$tmux_bin` in later commands, such as `"$tmux_bin" list-sessions`
- **Always use `printf %q`** to escape the kickoff prompt before `send-keys`. Apostrophes in the prompt (e.g., "we're") break single-quoted strings and expose `?` as a zsh glob pattern.
- Multi-line prompts must be flattened before send-keys — newlines cause premature Enter: `prompt=$(/bin/cat /tmp/kickoff.txt | /usr/bin/tr '\n' ' ')`
- Test on one window before looping when creating multiple windows

#### zellij

If `$ZELLIJ` is set:

```bash
if [ "$auto_load" = "false" ]; then
  zellij run -- bash -c "cd '$worktree_path' && claude 'Please read WORKTREE_CONTEXT.md first to understand the task, then confirm what we are working on.'"
else
  zellij run -- bash -c "cd '$worktree_path' && claude 'Hey Claude, do you know what we are working on?'"
fi
```

Note: avoid contractions in zellij prompts to sidestep quoting issues.

#### No multiplexer (fallback)

If neither tmux nor zellij is detected:

1. Open the worktree in the user's editor: `$EDITOR <worktree-path>`
2. Instruct the user to start Claude Code in that directory. Then:
   - **If auto-load is configured:** tell them to send: *"Hey Claude, do you know what we're working on?"*
   - **If auto-load is NOT configured:** tell them to send: *"Please read `WORKTREE_CONTEXT.md` first to understand the task, then confirm what we're working on."*

### Step 6 — Report

Confirm the setup:

| Detail | Value |
|--------|-------|
| Worktree | `<path>` |
| Branch | `<branch-name>` |
| Task | `<title or ID>` |
| Session | opened in tmux/zellij / manual instructions provided |
| Context | `WORKTREE_CONTEXT.md` written |
| Auto-load | confirmed / not configured — kickoff prompt adjusted to request manual read |

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

- **Merge or PR management** — open a PR for the owner to merge (via your project's PR skill or `gh pr create`); never run `wt merge`
- **Project-specific pre-flight** (Docker, services, auth) — handled by project-specific companion skills
- **Worktree cleanup** — follow the user's removal rules or the project's cleanup skill; the defaults
  above apply otherwise (`wt remove`, asking about an unmerged branch first)

## Extensibility

This skill supports project-specific companion skills that provide:
- Pre-flight checks (services, auth, dependencies)
- Branch naming conventions
- Issue tracker integration
- Additional `WORKTREE_CONTEXT.md` content
- Skill references for the new session

If your project has a companion skill, it will be invoked during Step 2 planning. To create one for your project, model it after this pattern: provide a skill that triggers alongside `worktree-start` and returns project-specific configuration.
