---
name: vhs-demo
description: Create a short VHS demo tape for a project and embed the resulting GIF in its README. Use when the user asks for a "vhs demo", "vhs tape", a terminal demo GIF, or to add a demo GIF to the README. Requires the vhs CLI.
compatibility: Requires the vhs CLI (https://github.com/charmbracelet/vhs), which needs ttyd and ffmpeg (brew install vhs installs both)
---

# VHS demo

Write a short [VHS](https://github.com/charmbracelet/vhs) tape that demos the project's CLI, render it to a GIF and embed the GIF in the README.

## Tape format (required)

- **Short:** 4-8 visible commands and under about 15 seconds in total.
- **One blank line between commands.** Each command is a group of lines (`Type`, `Enter`, `Sleep`); groups are separated by exactly one empty line.
- **A comment before every command** (`# ...`) saying what the command does, in plain words. This includes the settings and the `Hide`/`Show` setup.

This example was validated and rendered with vhs 0.12.1:

```tape
# Write the GIF next to the other docs
Output docs/demo.gif

# Fail early if the tool is not installed
Require mytool

# Keep the recording small and legible at README width
Set Shell "bash"
Set FontSize 18
Set Width 900
Set Height 400
Set TypingSpeed 40ms

# Set a short prompt without showing the setup in the GIF
Hide
Type "export PS1='$ ' && clear"
Enter
Show

# Show the available commands
Type "mytool --help"
Enter
Sleep 2s

# Run the tool on the sample input
Type "mytool run examples/sample.txt"
Enter
Sleep 3s
```

## Steps

1. **Check for vhs.** Run `which vhs ttyd ffmpeg`. If any is missing, tell the user to run `brew install vhs` and stop.
2. **Pick the commands.** Read the README and the CLI's `--help` to choose the commands that best show the project. Use only commands that run without secrets, network access or destructive effects. Ask the user if nothing safe is obvious.
3. **Write the tape** to `docs/demo.tape` (or `demo.tape` if the repo has no `docs/`), following the format above, with `Require <the project's CLI>` near the top.
4. **Validate and render from the repo root.** `Output` paths are relative to where `vhs` runs, not to the tape. Run `vhs validate <tape>` (it only checks the syntax), then `vhs <tape>`. If the render prints errors or the GIF is empty, fix the tape and re-render. Report the GIF size.
5. **Embed in the README.** Add `![Demo](docs/demo.gif)` near the top, after the project description (use the repo's path to the GIF). Keep the existing README style, and add a line saying how to re-render (`vhs docs/demo.tape`).
6. **Report** the files added. Commit the tape together with the GIF so it can be regenerated, following the project's own commit rules.

## Settings that matter

| Setting | Use |
|---------|-----|
| `Require <program>` | Fail early when the tool is not on the PATH |
| `Hide` / `Show` | Run setup (`cd`, `export PS1`, build) without it appearing in the GIF |
| `Set Width` / `Height` / `FontSize` | Narrow window and a large font stay legible at README width |
| `Set TypingSpeed 40ms`, `Type@<time>` | Typing pace; default is 50ms |
| `Set Theme`, `Padding`, `WindowBar` | Looks; run `vhs themes` to list themes |
| `Output x.mp4` / `x.webm` | Smaller than a GIF; use when the GIF is too large (GitHub READMEs only render a GIF inline) |
| `Ctrl+C`, `Tab`, `Up`, `Down` | Keys for interactive demos |

## Deterministic and safe demos

- Use a sample input fixture. Avoid timestamps, home-directory paths and other machine-specific output.
- Set a clean prompt with `Hide`, `export PS1='$ '` and `Show`.
- Never put credentials, tokens or real user data in a tape. Both the tape and the GIF are committed and public.
- Run commands from a clean directory so the output does not depend on local files.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Comment after, or missing for, a command | Put a `#` comment line directly above every command group |
| No blank line between commands | Separate every command group with one empty line |
| GIF written to the wrong place | Run `vhs` from the repo root; `Output` is relative to the working directory |
| Output cut off | `Sleep` long enough after `Enter`, or raise `Set Height` |
| GIF too large for the README | Fewer commands, smaller `Set Width`/`Set Height`, shorter `Sleep`s |
