---
name: release
description: Cut a versioned release of a project - validate preconditions and the version, rotate the CHANGELOG, open a release PR, then (after the owner merges) tag and run post-release steps such as a Homebrew tap bump. Use when the user asks to "cut a release", "release vX.Y.Z", "bump the version", "tag a release", "publish a new version" or "handle the tag". Reads project-specific "release parameters" from a thin per-project overlay (see the Overlay contract). Requires worktrunk CLI and git; a GitHub client (gh or the GitHub MCP) is recommended.
compatibility: Requires worktrunk CLI (https://worktrunk.dev) and git; a GitHub client (gh or the GitHub MCP) is recommended for opening PRs
---

# Release

One shared release workflow. The generic steps live here; everything that differs per project (commands, version location, tag style, post-tag steps) comes from the project's **release parameters** (see Overlay contract). Run the steps in order and do not skip any.

## Safety rules (apply to every step)

- Never run `wt merge`. Never push the default branch. Never merge a PR: the owner reviews and merges every PR, including the release PR.
- Push a tag only after the owner explicitly confirms the PR is merged **and** confirms pushing the tag. Push only the tag (`git push origin <tag>`), never `--tags`.
- Ask before pushing a branch or opening a PR in any other repository (for example a Homebrew tap).
- Create worktrees with `wt switch --create <branch> --yes`, never `git worktree add`. After any `wt` command, verify its hooks succeeded; if one failed, stop, report it and ask how to proceed.
- If any precondition or validation fails, stop and report it. Do not work around it.
- Never ask for or store secrets.
- `cp` and `rm` may be interactive aliases on the owner's machine and silently skip without a TTY: use `command cp -f` and `command rm -f` for manual replacements.

## Step 0 - Find the release parameters

Look for the parameters block in this order: (1) the project's release skill under `.claude/skills/` that handed off to this skill, (2) `.claude/release.md` in the repo. If neither exists, stop and tell the owner which parameters are missing; do not guess them. Read the whole block now and restate the key choices (flow, version pattern, tag style) in one line before continuing.

## Step 1 - Preconditions

Run from the repo's main checkout. All must pass.

Baseline (flow `release-branch`):

```bash
git branch --show-current            # must equal base_branch
git status --porcelain               # must be empty
git fetch origin --prune && git status -sb   # must be neither behind nor ahead of origin/<base_branch>
```

Baseline (flow `promote`): `git status --porcelain` is empty and `git fetch --prune` succeeds; then list `git log origin/<base_branch>..origin/<head_branch>` so the owner sees what ships.

Then run every command in the overlay's `preconditions` (tests, CI status, manifest validation) and treat a failure as a stop. Run the `informational` commands too: they are not gates; report their output and flag anything the overlay says to watch.

## Step 2 - Choose and validate the version

1. Latest tag: `git tag --sort=-version:refname | head -1`.
2. If the owner gave an explicit version, use it. Otherwise ask for the level (major, minor, patch, or a literal version) and compute it, resetting lower components. Where the overlay has `version_rules` (for example pre-release counters), apply them and state the decision with its reason.
3. Validate; stop if any check fails:
   - It matches `version_pattern` (default SemVer 2.0.0 `^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$`; no `v` prefix, no leading zeros).
   - It is strictly greater than the latest tag by SemVer precedence. Plain `sort -V` is right for `X.Y.Z` but ranks `1.0.0-beta.1` above `1.0.0`; for pre-release versions compare by SemVer rules by hand.
   - The tag is unused locally and remotely: `git tag -l <tag>` and `git ls-remote --tags origin <tag>` both print nothing.

The tag is `<tag_prefix><version>` (default prefix `v`).

## Step 3 - Release branch (flow `release-branch` only)

```bash
wt switch --create <branch_name> --yes     # branch_name from the overlay, default chore/release-v<version>
```

Verify the hooks. Do every remaining edit from this worktree, never on the base branch. Flow `promote` has no release branch: the PR head is the existing `head_branch`, so skip to Step 6.

## Step 4 - Audit

Run each item in the overlay's `audit` list (help text vs docs, README, SECURITY, and so on). Fix discrepancies that the overlay marks as blocking before continuing. For docs edits, show a brief audit summary and wait for the owner's approval before editing. If nothing is out of date, say so explicitly.

## Step 5 - Update the CHANGELOG and version file (flow `release-branch` only)

If `changelog` is `keep-a-changelog` (the default):

1. Read `CHANGELOG.md` and confirm there is content under `## [Unreleased]`; if empty, warn the owner before proceeding.
2. Replace the `## [Unreleased]` heading with an empty `## [Unreleased]` followed by `## [X.Y.Z] - YYYY-MM-DD`, moving the existing content under the new heading unchanged. The date is `date +%F`.
3. If the overlay names a `version_file`, write the version there in the exact form the overlay specifies (usually no `v`).

If `changelog` is `none`, skip the CHANGELOG edit.

## Step 6 - Commit and open the PR

Flow `release-branch`: stage only the files changed (CHANGELOG, version file, docs the audit edited) and commit with `commit_message` (default `chore: release v<version>`), ending with the session's attribution line. Then:

```bash
git push -u origin <branch_name>          # never the base branch
gh pr create --base <base_branch> --title "<pr_title>" --body "<body>"
```

Use `gh` if it is installed. Otherwise use the GitHub MCP's pull-request creation tool if one is available, with the same base, title and body. If neither is available, push the branch and give the owner the GitHub compare URL (`https://github.com/<owner>/<repo>/compare/<base_branch>...<branch_name>`) with the title and body to paste.

Flow `promote`: push nothing; open the PR with head `head_branch` and base `base_branch`.

PR body order: summary (the CHANGELOG entry or change list), then "Needs your answer" (only if there are open questions, each with a recommendation), then any overlay-required lines (for example a "Version:" line), then what changed and test results. State the `merge_method` in the body (default: merge commit). End with the session's attribution line.

**STOP.** Tell the owner the PR URL and that it is theirs to review and merge. Do not merge it and do not use `wt merge`.

## Step 7 - Tag (only after the owner confirms the merge)

Wait for the owner to say the PR is merged. If the overlay has a `pre_tag_wait` (CI, a deploy), wait for it and report the result.

From the main checkout (the base branch is checked out there; `git switch` fails in the release worktree):

```bash
git switch <base_branch> && git pull --ff-only
git log -1 --oneline                      # confirm this is the merged release commit
```

Show the commit and ask the owner to confirm pushing the tag. Then tag that commit exactly as `tag_style` says (`lightweight`: `git tag <tag>`; `annotated`: `git tag -a <tag> -m "<tag_message>"`; the message is mandatory when annotated) and push only the tag:

```bash
git push origin <tag>
```

Confirm each command succeeded and report the tag and the commit SHA it points to. If the owner declines to push the tag now, create nothing remote and stop.

## Step 8 - Post-release steps

Run the overlay's `post_tag` steps in order. Common ones, all stated in the overlay rather than assumed here:

- **Homebrew tap bump** (`tap` parameters): in the tap checkout, switch to `main`, `git pull --ff-only`, branch `<formula>-<version>`; run `script/bump-formula <version> --formula <formula> --repo <owner/repo>` from the tap (it rewrites only `url` and `sha256`, never runs git); verify with `brew style`, `brew reinstall` plus `brew test`, `brew audit --strict --online`; show the diff; ask the owner before committing, pushing or opening the tap PR (title and commit `<formula> <version>`); the owner merges it. If a daily autobump already opened the same PR, use that one. After the owner confirms the tap merge, fast-forward the tap's `main`, delete the branch, `brew update && brew upgrade <formula>` and run the overlay's smoke command. If the formula is not yet on the tap's `main`, say the release will not reach Homebrew until the formula's first PR merges.
- **Smoke test** of a deployed environment, **back-merge** of the base branch into another branch, spec or status updates: do exactly what the overlay says, applying the same rules (no pushes to protected branches unless the overlay names the exact command and case).

## Done

Summarize: version and tag, release PR, tag pushed (commit SHA), each post-release step and whether the owner still has a PR to merge, and any docs or help-text changes.

## Overlay contract

The project supplies a short block headed `## Release parameters` (in its own release skill or `.claude/release.md`). Keys with a default may be omitted. The generic steps above never mention a project by name; add a parameter here rather than a conditional there.

| Key | Meaning | Default |
|-----|---------|---------|
| `project` | Display name | repo name |
| `flow` | `release-branch` (new `chore/release-*` branch with CHANGELOG commit) or `promote` (PR from an existing branch, no release commit) | `release-branch` |
| `base_branch` | Branch the release lands on and is tagged from | `main` |
| `head_branch` | Source branch (flow `promote` only) | none |
| `preconditions` | Gate commands (tests, CI status, manifest validation), each with what a pass means | none |
| `informational` | Non-gate commands whose output is reported | none |
| `version_pattern` | Regex a version must match (no tag prefix) | SemVer `X.Y.Z` |
| `version_rules` | How to choose the level (for example pre-release counters) and any text the PR must carry | none |
| `version_file` | File that holds the version and its format | none |
| `tag_prefix` | Prefix before the version in the tag | `v` |
| `tag_style` | `lightweight` or `annotated` | `lightweight` |
| `tag_message` | Annotated tag message template | `<project> <version>` |
| `branch_name` | Release branch name (flow `release-branch`) | `chore/release-v<version>` |
| `commit_message` | Release commit message | `chore: release v<version>` |
| `pr_title` | Release PR title | the commit message |
| `pr_body_extra` | Extra lines (after-merge notes, a "Version:" line) | none |
| `merge_method` | How the owner merges the PR | merge commit |
| `changelog` | `keep-a-changelog` or `none` | `keep-a-changelog` |
| `audit` | Ordered checks, each marked blocking or advisory | none |
| `pre_tag_wait` | What to wait for after the merge (CI, deploy) | none |
| `post_tag` | Ordered post-release steps; for a tap bump give `formula`, upstream `repo` and the smoke command | none |

An overlay may tighten a rule (for example "push the tag only when asked") but may never relax a safety rule above.
