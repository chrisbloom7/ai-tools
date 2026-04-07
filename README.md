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
│               └── parallel-workstreams
└── ...                   # Future ecosystems (ChatGPT, Copilot, etc.)
```

## Claude Code

A marketplace plugin for Claude Code providing development workflow skills.

**Install:**
```
/plugin marketplace add chrisbloom7/ai-tools
```

### `chrisbloom7-development` plugin

Development workflow tools for worktree-based feature development.

| Skill | Description |
|-------|-------------|
| `chrisbloom7-development:worktree-start` | Start development on a single task: plan, create worktree, write context, bootstrap session |
| `chrisbloom7-development:parallel-workstreams` | Plan and orchestrate multiple parallel worktree sessions |

> Requires [worktrunk CLI](https://worktrunk.dev).
