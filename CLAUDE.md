# CLAUDE.md

`ai-tools` is a marketplace of personal Claude Code plugins. Today it holds one plugin,
`chrisbloom7-development`, with the skills `worktree-start`, `parallel-workstreams` and `release`.

## Layout

- `.claude-plugin/marketplace.json` lists the plugins in the marketplace.
- Each plugin lives in `claude-code/plugins/<name>/` with `.claude-plugin/plugin.json` and
  `skills/<skill>/SKILL.md`.
- `README.md` has the structure diagram and a table of skills.

## Commands

```bash
claude plugin validate .      # validate the marketplace and its plugins
jq empty <file.json>          # quick JSON syntax check
/plugin marketplace add ./    # inside Claude Code: try the marketplace locally
```

## Gotchas

- A new skill goes in `plugin.json`'s `skills` list and in the README skills table.
- No `version` field in the manifests, on purpose (commit c40e1c6). `claude plugin validate` warns
  about it; ignore the warning.
- The skills in `chrisbloom7-development` assume the Worktrunk `wt` CLI and git (`release` also
  prefers `gh` or the GitHub MCP, but falls back to a compare URL). Other plugins may have different
  requirements. The worktree skills carry short inline defaults and defer to the user's own worktree
  rules when those are loaded; rules cannot ship in a plugin, so keep the defaults in `worktree-start`
  self-contained. The stale-base check lives only in `worktree-start` (Step 3); `parallel-workstreams`
  refers to it.
- `worktree-start` and `parallel-workstreams` trigger only on an explicit request. Keep their
  descriptions narrow.
- `docs/superpowers/` and `.claude/settings.local.json` are gitignored.

## Claude Code setup

`.claude/settings.json` allows `jq empty` and `claude plugin validate`, and registers
`validate-manifest.sh`, a hook that runs `jq empty` on an edited `plugin.json` or `marketplace.json`
and checks that an edited `SKILL.md` has frontmatter with `name` and `description`. It skips quietly
when `jq` is missing.

Changes to `.claude/` (hooks and the allowlist) and to this file run or steer Claude Code on the machine
of whoever opens the repo, so `.github/CODEOWNERS` routes them to the maintainer. When reviewing an
outside PR that touches them, read the diff first (`gh pr diff <number> -- .claude CLAUDE.md`) before
checking the branch out and starting Claude Code there.
`.github/`, `.claude-plugin/` and `claude-code/plugins/` are routed to the maintainer too.
