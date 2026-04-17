# Local TODOs (not committed)

## worktree-start + parallel-workstreams: prompt agent to read WORKTREE_CONTEXT.md if not referenced in CLAUDE.md

**Files:**
- `claude-code/plugins/chrisbloom7-development/skills/worktree-start/SKILL.md`
- `claude-code/plugins/chrisbloom7-development/skills/parallel-workstreams/SKILL.md`

### Problem

After writing `WORKTREE_CONTEXT.md` into the worktree, the skill assumes the agent will
read it — but there's no guarantee. If neither `CLAUDE.md` nor `CLAUDE.local.md` contains
a `@@WORKTREE_CONTEXT.md` reference (which auto-loads the file), the agent may never read
it and the context is silently ignored.

### What to change

After writing `WORKTREE_CONTEXT.md`, check whether `CLAUDE.md` or `CLAUDE.local.md` in the
worktree root contains a `@@WORKTREE_CONTEXT.md` reference.

- **If a reference exists:** no action needed — the file will be auto-loaded.
- **If no reference exists:**
  - For multiplexer setups: prepend an explicit instruction to the kickoff prompt sent via
    `send-keys`, e.g. `"Read WORKTREE_CONTEXT.md first, then..."`.
  - For non-multiplexer setups (manual): tell the user to instruct the agent to read
    `WORKTREE_CONTEXT.md` as its first step before starting work.

---

## worktree-start + parallel-workstreams: check main worktree is up to date before branching

**Files:**
- `claude-code/plugins/chrisbloom7-development/skills/worktree-start/SKILL.md`
- `claude-code/plugins/chrisbloom7-development/skills/parallel-workstreams/SKILL.md`

### Problem

When creating a new worktree from the main worktree, if the main branch is behind its
remote, the new worktree (and its feature branch) will be based on stale commits. This can
cause unnecessary merge conflicts or missed upstream changes.

### What to change

Before running `wt switch --create <branch>`, check whether the main worktree's current
branch is behind its remote (e.g. `git status -sb` or `git rev-list --count HEAD..@{u}`).

- **If up to date:** proceed normally.
- **If behind remote:** pause and ask the user whether to pull in the upstream changes
  before creating the worktree. Do not pull automatically — let the user decide.

---

## worktree-start + parallel-workstreams: stacked PRs use separate worktrees, not branches within a worktree

**Files:**
- `claude-code/plugins/chrisbloom7-development/skills/worktree-start/SKILL.md`
- `claude-code/plugins/chrisbloom7-development/skills/parallel-workstreams/SKILL.md`

### Problem

When work requires stacked PRs (PR B depends on PR A), an agent might create a second branch
inside the same worktree and push it as a stacked PR. This is incorrect — a worktree should
have exactly one feature branch, and the working tree state will reflect both sets of changes
simultaneously, making isolation impossible.

### What to change

Add explicit guidance that stacked PRs must use separate worktrees:

- Each branch in a stack gets its own worktree, created from the base branch of that stack
  level (not from within the existing worktree).
- Example: if `feature/pr-a` needs a follow-on `feature/pr-b`, create a new worktree from
  `feature/pr-a` as the base, not a second branch inside `feature/pr-a`'s worktree.
- Never create multiple branches inside a single worktree for the purpose of stacking PRs.
