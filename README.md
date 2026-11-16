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
│       ├── chrisbloom7-development/
│       │   ├── .claude-plugin/plugin.json
│       │   └── skills/
│       │       ├── worktree-start
│       │       ├── parallel-workstreams
│       │       ├── release
│       │       └── vhs-demo
│       └── chrisbloom7-design/
│           ├── .claude-plugin/plugin.json
│           └── skills/
│               └── logo-package/     # SKILL.md and scripts/ (Python, run with uv)
└── ...                   # Future ecosystems (ChatGPT, Copilot, etc.)
```

## Claude Code

A Claude Code marketplace with development workflow and design skills.

**Install:**
```
/plugin marketplace add chrisbloom7/ai-tools
```

### `chrisbloom7-development` plugin

Worktree, release and demo workflow tools.

| Skill | Description |
|-------|-------------|
| `chrisbloom7-development:worktree-start` | On explicit request: plan a single task, create a worktree, write context, bootstrap a session |
| `chrisbloom7-development:parallel-workstreams` | On explicit request: plan and orchestrate multiple parallel worktree sessions |
| `chrisbloom7-development:release` | Cut a release: validate, rotate the CHANGELOG, open the release PR, then tag after the owner merges. Project specifics come from a per-project overlay |
| `chrisbloom7-development:vhs-demo` | Write a short VHS tape (commented commands, blank-line separated), render the GIF and embed it in the README |

> Requires [worktrunk CLI](https://worktrunk.dev). `release` opens its PR with `gh` or the GitHub MCP; with neither you get a compare URL. `vhs-demo` needs the [vhs CLI](https://github.com/charmbracelet/vhs).

### `chrisbloom7-design` plugin

Logo and brand asset tools.

| Skill | Description |
|-------|-------------|
| `chrisbloom7-design:logo-package` | Convert raster logo art (PNG) into a brand asset package: SVG lockups and marks, vector PDFs, PNGs, favicons and app icons, with a preflight grade and a conversion report. Does not design or redraw logos |

> Requires [uv](https://docs.astral.sh/uv/), [potrace](https://potrace.sourceforge.net/) and Google Chrome (`brew install uv potrace`). Tested on macOS; Linux is untested (Chrome or Chromium on `PATH` or via `LOGO_PIPELINE_CHROME`); Windows is unsupported. Tests: `cd claude-code/plugins/chrisbloom7-design/skills/logo-package/scripts && uv run pytest`.
