---
name: vhs-demo
description: Create a short VHS demo tape for a project and embed the resulting GIF in its README. Use when the user asks for a "vhs demo", "vhs tape", a terminal demo GIF, or to add a demo GIF to the README. Requires the vhs CLI.
compatibility: Requires the vhs CLI (https://github.com/charmbracelet/vhs), which needs ttyd and ffmpeg (brew install vhs installs both)
---

# VHS demo

Write a short [VHS](https://github.com/charmbracelet/vhs) tape that demos the project's CLI, render it to a GIF and embed the GIF in the README. The [vhs examples](https://github.com/charmbracelet/vhs/tree/main/examples) show more settings and styles.

## Ask first

Ask these together, with the defaults, before writing anything. Skip a question the user already answered.

1. **Comment style.** Default: **on screen**, typed into the terminal as `# ...` shell comments before each command, so the person reading the README sees them. Alternative: **in file**, `#` comments in the tape only, above each command; they do not appear in the GIF.
2. **Theme.** Default: `Catppuccin Mocha`. `Dracula` has the most clearly separated colors (good for colorful output such as `jq`, `git log` and diffs); `TokyoNight` is the other dark option. `vhs themes` lists all of them.
3. **Title card.** Default: **yes**. A banner with the project name and a one-line tagline, shown at the start and again at the end, so the GIF loops without a jump.
4. **Window decorations.** Default: **no**. Alternative: `Set WindowBar Colorful`, `Set Margin 30` with `Set MarginFill "#674EFF"`, `Set BorderRadius 8`.

## Tape format (required)

- **Cover the workflow.** List the commands in the README's first usage block. Every one appears in the tape, unless the user agrees to drop it. Show both halves of paired features (for example `add` and `remove`).
- **Short:** 4-8 visible commands, about 30 seconds in total including the title card.
- **One blank line between commands.** Each command is a group of lines (comment, `Type`, `Enter`, `Sleep`); groups are separated by exactly one empty line.
- **A comment before every command** explaining what it does, in plain words, in the chosen style. With in-file comments, the settings and the `Hide`/`Show` setup get a `#` comment too.
- **A header comment** at the top of the file: what the demo shows, any stubbed programs, how to regenerate it (`vhs docs/demo.tape`, run from the repo root, re-render whenever the CLI output it shows changes) and what it avoids touching.
- **Clear the screen** with `Ctrl+L` before each step after the first, so output does not scroll off and the GIF stays small.
- **`Sleep 500ms` before `Enter`** after each typed command, then a `Sleep` long enough to read the output.

This example is adapted from a tape rendered with vhs 0.12.1. `banner.txt` is written by the setup (a seed script, or a `printf` in the `Hide` block):

```tape
# README demo: find a past session by one word, read it in context, resume it. Needs `vhs`.
# `claude` is stubbed (see seed.py), so `resume` prints its command instead of launching Claude Code.
#
#   python3 docs/demo/seed.py     # builds the throwaway home at /tmp/mytool-demo
#   vhs docs/demo/demo.tape       # run from the repo root; rewrites docs/demo/demo.gif (committed:
#                                 re-render it whenever the CLI output it shows changes)
#
# It runs against synthetic data under /tmp/mytool-demo and never touches your own files.
# The GIF opens and ends on the same title card, so it loops cleanly.

Output docs/demo/demo.gif

Require python3

Set Shell "bash"
Set FontSize 15
Set Width 1400
Set Height 580
Set Padding 24
Set TypingSpeed 40ms
Set Theme "Catppuccin Mocha"

# Hidden setup: demo home, stubs first on the PATH, and a banner() that draws the title card
Env HOME "/tmp/mytool-demo"
Hide
Type "export PATH=$PWD/bin:/tmp/mytool-demo/bin:$PATH && cd /tmp/mytool-demo/work"
Enter
Type `banner() { clear; printf '%b' "$(cat /tmp/mytool-demo/banner.txt)"; }`
Enter
Type "PS1= && banner"
Enter
Show

# Title card
Sleep 2500ms

Hide
Type "PS1='$ ' && clear"
Enter
Show

Type@25ms "# Where did we settle webhook retries? I remember one word: jitter."
Enter
Type "mytool search jitter; echo"
Sleep 500ms
Enter
Sleep 4s

Ctrl+L
Type@25ms "# Pick that conversation back up in Claude Code."
Enter
Type "mytool resume 7fac4752"
Sleep 500ms
Enter
Sleep 3s

# Back to the title card, so the loop restarts on the frame it began with
Hide
Type "PS1= && banner"
Enter
Show
Sleep 2500ms
```

For in-file comments, drop the `Type@25ms "# ..."` lines and put a `#` comment above each group instead. For a banner, use big-letter art from `figlet` or `toilet` if either is installed; otherwise a box with the name and tagline, padded in the seed script so the right border lines up. Set `PS1=` for the title card so no prompt shows below it. `Type` accepts backticks around text that contains double quotes; `\"` is not valid.

## Steps

1. **Check for vhs.** Run `which vhs ttyd ffmpeg`. If any is missing, tell the user to run `brew install vhs` and stop.
2. **Ask first** (see above).
3. **List the commands.** Read the README and the CLI's `--help`. Write down the main workflow commands (the first usage block) and note which ones are unsafe to run for real: they need secrets, the network, or have destructive or interactive effects (launching an editor or an AI session, installing or deleting packages).
4. **Prepare the data and stubs.** Isolate the demo (see below). For every unsafe command that is part of the workflow, add a stub instead of dropping the step: a one-line script in a directory at the front of the `PATH`, such as `#!/bin/sh` then `echo "claude $*"`, or a script that prints canned output. Name each stub in the tape's header comment. If the demo needs more than a file or two of sample data, write a seed script next to the tape. If no stub is faithful, ask the user before dropping a step.
5. **Write the tape** following the format above, with `Require <program>` near the top for a program the demo needs that is already installed (if the project's own CLI is only put on the PATH during setup, require a program it uses instead, for example `git`). Place it at `docs/demo.tape` (or `docs/demo/demo.tape` when there is a seed script, or `demo.tape` if the repo has no `docs/`).
6. **Validate and render from the repo root.** `Output` paths are relative to where `vhs` runs, not to the tape. Run `vhs validate <tape>` (it only checks the syntax), then `vhs <tape>`. Report the GIF size and length.
7. **Check the frames.** While checking, add a `Screenshot "<dir>/stepN.png"` line (a directory outside the repo) at the end of each step, then read the PNGs. Look for output that runs into the next prompt (end `cat` with `; echo` if the file lacks a trailing newline), wrapped lines, cut-off output, errors, a misaligned banner, and machine-specific text such as a home directory or `/private/tmp` (macOS resolves `/tmp` to that; use a directory without a symlink). Fix the tape and re-render. Remove the `Screenshot` lines before committing. Also confirm the last frame equals the first when there is a title card.
8. **Check coverage.** Compare the README's usage commands with the tape's. Report any that are missing, with the reason.
9. **Embed in the README.** Add `![<alt>](docs/demo.gif)` near the top, after the project description. The alt text describes what the GIF shows ("A terminal recording: brewfile add puts two packages in a Brewfile and commits them"), not just "Demo". Keep the existing README style.
10. **Report** the files added. Commit the tape (and seed script) together with the GIF so it can be regenerated, following the project's own commit rules.

## Settings that matter

| Setting | Use |
|---------|-----|
| `Require <program>` | Fail early when a program is not on the PATH |
| `Env <NAME> "<value>"` | Set an environment variable for the shell (for example `HOME`); no `$VAR` expansion |
| `Hide` / `Show` | Run setup (`cd`, `export PS1`, build) without it appearing in the GIF |
| `Set Width` / `Height` / `FontSize` / `Padding` | A wide terminal (about 1000-1400), font 15-16 and padding 20-24 stay legible at README width |
| `Set TypingSpeed 40ms`, `Type@<time>` | Typing pace; default is 50ms. Use `Type@25ms` for on-screen comments |
| `Set Theme` | The user's choice; default `Catppuccin Mocha` |
| `Set WindowBar` / `Margin` / `MarginFill` / `BorderRadius` | Optional decorations (colored margin, window dots, rounded corners) |
| `Set LoopOffset <n>%` | Start the GIF part-way through the recording, so the first frame (the one shown before it loads) is a useful one. It does not hide the jump at the loop point; the title card does |
| `Screenshot "<path>.png"` | Save the current frame as a PNG, for the frame check |
| `Output x.mp4` / `x.webm` | Smaller than a GIF; use when the GIF is too large (GitHub READMEs only render a GIF inline) |
| `Ctrl+L`, `Ctrl+C`, `Tab`, `Up`, `Down` | Clear the screen between steps; keys for interactive demos |

## Deterministic and safe demos

- Isolate state. Redirect the tool's home or config directories (`Env HOME "/tmp/<project>-demo"`, or `cd $(mktemp -d)` for a scratch git repo) so a render never reads or changes the user's real data. Prefer this to just running from a clean directory.
- Stub, do not skip, commands that launch other programs. vhs runs a real shell, so an unstubbed `claude`, `vim` or `brew install` would really run during the render.
- Use sample input. Avoid timestamps, home-directory paths and other machine-specific output.
- Set a clean prompt with `Hide`, `export PS1='$ '` and `Show`.
- Never put credentials, tokens or real user data in a tape or seed script. Both the tape and the GIF are committed and public.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Dropping an important command because it launches another program | Stub the program and name the stub in the header comment |
| Comment missing for a command, or placed after it | Put the comment directly before every command group |
| In-file comments when the viewer should see them | Default to on-screen comments; ask |
| No blank line between commands | Separate every command group with one empty line |
| Output scrolls off or runs into the next prompt | `Ctrl+L` before each step; end `cat` with `; echo` |
| GIF jumps when it repeats | Open and end on the same title card |
| Banner border misaligned, or a prompt shows under it | Pad the box in the seed script; set `PS1=` for the title card |
| GIF written to the wrong place | Run `vhs` from the repo root; `Output` is relative to the working directory |
| GIF too large for the README | Fewer commands, `Ctrl+L` between steps, smaller `Set Width`/`Set Height`, shorter `Sleep`s |
| Alt text just says "Demo" | Describe what the GIF shows |
