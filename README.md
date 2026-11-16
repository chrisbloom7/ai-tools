# ai-tools

A collection of AI assistant tools and skills, organized by ecosystem.

## Structure

```
ai-tools/
├── .claude/              # Claude Code project settings and hook
│   ├── settings.json
│   └── hooks/validate-manifest.sh
├── .claude-plugin/       # Marketplace manifest (marketplace.json)
├── .github/              # CI workflow, validation script, CODEOWNERS, Dependabot
├── claude-code/          # Claude Code marketplace plugins
│   └── plugins/
│       └── chrisbloom7-development/
│           ├── .claude-plugin/plugin.json
│           └── skills/
│               ├── worktree-start
│               ├── parallel-workstreams
│               ├── release
│               └── vhs-demo
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
| `chrisbloom7-development:vhs-demo` | Write a short VHS tape (commented commands, blank-line separated), render the GIF and embed it in the README |

> Requires [worktrunk CLI](https://worktrunk.dev). `release` opens its PR with `gh` or the GitHub MCP; with neither you get a compare URL. `vhs-demo` needs the [vhs CLI](https://github.com/charmbracelet/vhs).
