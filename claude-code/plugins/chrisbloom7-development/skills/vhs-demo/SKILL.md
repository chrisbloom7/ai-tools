---
name: vhs-demo
description: Create a short VHS demo tape for a project and embed the resulting GIF in its README. Use when the user asks for a "vhs demo", "vhs tape", a terminal demo GIF, or to add a demo GIF to the README. Requires the vhs CLI.
compatibility: Requires the vhs CLI (https://github.com/charmbracelet/vhs), which needs ttyd and ffmpeg (brew install vhs installs both)
---

# VHS demo

Write a short [VHS](https://github.com/charmbracelet/vhs) tape that demos the project's CLI, render it to a GIF and embed the GIF in the README.

## Ask first

Ask these two questions together, with the defaults, before writing anything. Skip a question the user already answered.

1. **Comment style.** Default: **on screen**, typed into the terminal as `# ...` shell comments before each command, so the person reading the README sees them. The alternative is **in file**: `#` comments in the tape file only, above each command, which do not appear in the GIF.
2. **Theme.** Default: `Catppuccin Mocha`. `vhs themes` lists the others.

## Tape format (required)

- **Short:** 4-8 visible commands, about 25 seconds at most. Show every main feature of the project (for example both `add` and `remove`).
- **One blank line between commands.** Each command is a group of lines (comment, `Type`, `Enter`, `Sleep`); groups are separated by exactly one empty line.
- **A comment before every command** explaining what it does, in plain words, in the chosen style. With in-file comments, the settings and the `Hide`/`Show` setup get a `#` comment too.
- **A header comment** at the top of the file: what the demo shows, how to regenerate it (`vhs docs/demo.tape`, run from the repo root, re-render whenever the CLI output it shows changes) and what it avoids touching.
- **Clear the screen** with `Ctrl+L` before each step after the first, so output does not scroll off and the GIF stays small.
- **`Sleep 500ms` before `Enter`** after each typed command, then a `Sleep` long enough to read the output.

This example (on-screen style) was rendered with vhs 0.12.1, with `echo` standing in for `mytool`:

```tape
# README demo: show the main commands of mytool. Needs `vhs`.
#
#   vhs docs/demo.tape     # run from the repo root; rewrites docs/demo.gif (committed: re-render
#                          it whenever the CLI output it shows changes)
#
# It runs against the sample input in examples/ and never touches your own files or settings.

Output docs/demo.gif

Require git

Set Shell "bash"
Set FontSize 16
Set Width 1000
Set Height 560
Set Padding 20
Set TypingSpeed 40ms
Set Theme "Catppuccin Mocha"

Hide
Type "export PS1='$ ' && clear"
Enter
Show

Sleep 500ms
Type@25ms "# Show what the tool can do."
Enter
Type "mytool --help"
Sleep 500ms
Enter
Sleep 3s

Ctrl+L
Type@25ms "# Run it on the sample input."
Enter
Type "mytool run examples/sample.txt; echo"
Sleep 500ms
Enter
Sleep 3s
```

For in-file comments, drop the `Type@25ms "# ..."` lines and put a `#` comment above each group instead.

## Steps

1. **Check for vhs.** Run `which vhs ttyd ffmpeg`. If any is missing, tell the user to run `brew install vhs` and stop.
2. **Ask first** (see above).
3. **Pick the commands.** Read the README and the CLI's `--help` to choose the commands that best show the project. Use only commands that run without secrets, network access or destructive effects. Ask the user if nothing safe is obvious.
4. **Prepare the data.** Isolate the demo (see "Deterministic and safe demos"). If it needs more than a file or two of sample data, write a seed script next to the tape.
5. **Write the tape** following the format above, with `Require <program>` near the top for a program the demo needs that is already installed. If the project's own CLI is only put on the PATH during the hidden setup, require a program it uses instead (for example `git`). Place it at `docs/demo.tape` (or `docs/demo/demo.tape` when there is a seed script, or `demo.tape` if the repo has no `docs/`).
6. **Validate and render from the repo root.** `Output` paths are relative to where `vhs` runs, not to the tape. Run `vhs validate <tape>` (it only checks the syntax), then `vhs <tape>`. Report the GIF size.
7. **Check the frames.** Extract the last frame of each step (`ffmpeg -sseof -0.3 -i <gif> -frames:v 1 <png>`, or step through it) and read them. Look for output that runs into the next prompt (end `cat` with `; echo` if the file lacks a trailing newline), wrapped lines, cut-off output and errors. Fix the tape and re-render.
8. **Embed in the README.** Add `![<alt>](docs/demo.gif)` near the top, after the project description. The alt text describes what the GIF shows ("A terminal recording: brewfile add puts two packages in a Brewfile and commits them"), not just "Demo". Keep the existing README style.
9. **Report** the files added. Commit the tape (and seed script) together with the GIF so it can be regenerated, following the project's own commit rules.

## Settings that matter

| Setting | Use |
|---------|-----|
| `Require <program>` | Fail early when a program is not on the PATH |
| `Hide` / `Show` | Run setup (`cd`, `export PS1`, build) without it appearing in the GIF |
| `Set Width` / `Height` / `FontSize` / `Padding` | A wide terminal (about 1000-1400), font 15-16 and padding 20-24 stay legible at README width |
| `Set TypingSpeed 40ms`, `Type@<time>` | Typing pace; default is 50ms. Use `Type@25ms` for on-screen comments |
| `Set Theme` | The user's choice; default `Catppuccin Mocha` |
| `Output x.mp4` / `x.webm` | Smaller than a GIF; use when the GIF is too large (GitHub READMEs only render a GIF inline) |
| `Ctrl+L`, `Ctrl+C`, `Tab`, `Up`, `Down` | Clear the screen between steps; keys for interactive demos |

## Deterministic and safe demos

- Isolate state. Redirect the tool's home or config directories (for example `export HOME=/tmp/<project>-demo`, or `cd $(mktemp -d)` for a scratch git repo) so a render never reads or changes the user's real data. Prefer this to just running from a clean directory.
- Use sample input. Avoid timestamps, home-directory paths and other machine-specific output.
- Set a clean prompt with `Hide`, `export PS1='$ '` and `Show`.
- Never put credentials, tokens or real user data in a tape or seed script. Both the tape and the GIF are committed and public.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Comment missing for a command, or placed after it | Put the comment directly before every command group |
| In-file comments when the viewer should see them | Default to on-screen comments; ask |
| No blank line between commands | Separate every command group with one empty line |
| Output scrolls off or runs into the next prompt | `Ctrl+L` before each step; end `cat` with `; echo` |
| GIF written to the wrong place | Run `vhs` from the repo root; `Output` is relative to the working directory |
| GIF too large for the README | Fewer commands, `Ctrl+L` between steps, smaller `Set Width`/`Set Height`, shorter `Sleep`s |
| Alt text just says "Demo" | Describe what the GIF shows |
