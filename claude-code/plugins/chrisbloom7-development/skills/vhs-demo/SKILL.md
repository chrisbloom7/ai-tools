---
name: vhs-demo
description: Create a short VHS demo tape for a project and embed the resulting GIF in its README. Use when the user asks for a "vhs demo", "vhs tape", a terminal demo GIF, or to add a demo GIF to the README. Requires the vhs CLI.
compatibility: Requires the vhs CLI (https://github.com/charmbracelet/vhs)
---

# VHS demo

Write a short [VHS](https://github.com/charmbracelet/vhs) tape that demos the project's CLI, render it to a GIF and embed the GIF in the README.

## Tape format (required)

- **Short:** 4-8 commands, enough to show the main use of the project.
- **One blank line between commands.** Each command is a group of lines (`Type`, `Enter`, `Sleep`); groups are separated by exactly one empty line.
- **A comment before every command** (`# ...`) saying what the command does, in plain words.

```tape
# Render the GIF next to the tape
Output docs/demo.gif

# Keep the recording small and readable
Set Shell "bash"
Set FontSize 16
Set Width 1000
Set Height 500

# Show the available commands
Type "mytool --help"
Enter
Sleep 2s

# Run the tool on the sample input
Type "mytool run example.txt"
Enter
Sleep 3s
```

## Steps

1. **Check for vhs.** Run `which vhs`. If missing, tell the user to install it (`brew install vhs`) and stop.
2. **Pick the commands.** Read the README and the CLI's `--help` to choose the commands that best show the project. Use only commands that run without secrets, network access or destructive effects. Ask the user if nothing safe is obvious.
3. **Write the tape** to `docs/demo.tape` (or `demo.tape` if the repo has no `docs/`), following the format above. Match the settings block's `Output` path to where the GIF should live.
4. **Validate and render.** Run `vhs validate <tape>`, then `vhs <tape>`. Open the GIF if possible and check the commands ran without errors; fix the tape and re-render if not.
5. **Embed in the README.** Add `![Demo](docs/demo.gif)` near the top, after the project description (use the repo's path to the GIF). Keep the existing README style.
6. **Report** the files added and how to re-render (`vhs docs/demo.tape`). Commit only following the project's own commit rules.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Comment after, or missing for, a command | Put a `#` comment line directly above every command group |
| No blank line between commands | Separate every command group with one empty line |
| Output cut off | `Sleep` long enough after `Enter`, or raise `Set Height` |
| GIF too large for the README | Fewer commands, smaller `Set Width`/`Set Height`, shorter `Sleep`s |
