# ai-tools

A collection of AI assistant tools and skills, organized by ecosystem.

## Structure

```
ai-tools/
├── claude-code/          # Claude Code marketplace plugins
│   └── plugins/
│       └── chrisbloom7-development/
│           └── skills/
│               ├── worktree-start
│               ├── parallel-workstreams
│               └── release
└── ...                   # Future ecosystems (ChatGPT, Copilot, etc.)
```

## Claude Code

A marketplace plugin for Claude Code providing development workflow skills.

**Install:**
```
/plugin marketplace add chrisbloom7/ai-tools
```

### `chrisbloom7-development` plugin

Worktree and release workflow tools.

| Skill | Description |
|-------|-------------|
| `chrisbloom7-development:worktree-start` | On explicit request: plan a single task, create a worktree, write context, bootstrap a session |
| `chrisbloom7-development:parallel-workstreams` | On explicit request: plan and orchestrate multiple parallel worktree sessions |
| `chrisbloom7-development:release` | Cut a release: validate, rotate the CHANGELOG, open the release PR, then tag after the owner merges. Project specifics come from a per-project overlay |

> Requires [worktrunk CLI](https://worktrunk.dev). `release` works best with `gh` (it opens the PR; without it you get a compare URL).
