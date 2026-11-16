#!/usr/bin/env python3
"""Print a title card: big block letters with a color gradient, then a tagline, centered in the terminal.
Usage: banner.py NAME [TAGLINE] [--colors STOP,STOP,...]
By default the gradient uses the terminal's ANSI magentas, blues and cyans, so it follows the vhs theme.
Pure standard library, so a demo needs no figlet. Prints one row at a time so it can be revealed on screen,
then hides the cursor; restore it with `tput cnorm`."""
import shutil, sys, time
F = {
 'A':["  █  "," █ █ ","█████","█   █","█   █"], 'B':["████ ","█   █","████ ","█   █","████ "],
 'C':[" ████","█    ","█    ","█    "," ████"], 'D':["████ ","█   █","█   █","█   █","████ "],
 'E':["█████","█    ","████ ","█    ","█████"], 'F':["█████","█    ","████ ","█    ","█    "],
 'G':[" ████","█    ","█  ██","█   █"," ████"], 'H':["█   █","█   █","█████","█   █","█   █"],
 'I':["█████","  █  ","  █  ","  █  ","█████"], 'J':["█████","   █ ","   █ ","█  █ "," ██  "],
 'K':["█   █","█  █ ","███  ","█  █ ","█   █"], 'L':["█    ","█    ","█    ","█    ","█████"],
 'M':["█   █","██ ██","█ █ █","█   █","█   █"], 'N':["█   █","██  █","█ █ █","█  ██","█   █"],
 'O':[" ███ ","█   █","█   █","█   █"," ███ "], 'P':["████ ","█   █","████ ","█    ","█    "],
 'Q':[" ███ ","█   █","█ █ █","█  █ "," ██ █"], 'R':["████ ","█   █","████ ","█  █ ","█   █"],
 'S':[" ████","█    "," ███ ","    █","████ "], 'T':["█████","  █  ","  █  ","  █  ","  █  "],
 'U':["█   █","█   █","█   █","█   █"," ███ "], 'V':["█   █","█   █","█   █"," █ █ ","  █  "],
 'W':["█   █","█   █","█ █ █","██ ██","█   █"], 'X':["█   █"," █ █ ","  █  "," █ █ ","█   █"],
 'Y':["█   █"," █ █ ","  █  ","  █  ","  █  "], 'Z':["█████","   █ ","  █  "," █   ","█████"],
 '-':["     ","     ","█████","     ","     "], ' ':["   "]*5,
}
import argparse
ap = argparse.ArgumentParser(description="Print a gradient block-letter title card.")
ap.add_argument("name")
ap.add_argument("tagline", nargs="?", default="")
ap.add_argument("--colors", help="comma-separated gradient stops, left to right: #rrggbb or 0-255 (256-color index). "
                                 "Default: the terminal's own ANSI magentas, blues and cyans, so the card follows the theme.")
args = ap.parse_args()
name, tag = args.name.upper(), args.tagline
rows = ["  ".join(F[c][r] for c in name) for r in range(5)]
width = max(len(r) for r in rows)

def sgr(stop):
    stop = stop.strip()
    if stop.startswith("#"):
        r, g, b = (int(stop[i:i + 2], 16) for i in (1, 3, 5))
        return f"38;2;{r};{g};{b}"
    return f"38;5;{int(stop)}"

# ANSI codes 95, 35, 34, 94, 36, 96: bright magenta, magenta, blue, bright blue, cyan, bright cyan.
ramp = [sgr(c) for c in args.colors.split(",")] if args.colors else ["95", "35", "34", "94", "36", "96"]

def grad(x):
    return ramp[min(len(ramp) - 1, int(x / max(width, 1) * len(ramp)))]
cols, lines = shutil.get_terminal_size((100, 30))
left = " " * max(0, (cols - width) // 2)
print("\n" * max(0, (lines - len(rows) - (2 if tag else 0)) // 2 - 1))
for r in rows:
    print(left + "".join(f"\033[{grad(i)}m{ch}\033[0m" if ch != " " else " " for i, ch in enumerate(r)), flush=True)
    time.sleep(0.12)
if tag:
    print("\n" + " " * max(0, (cols - len(tag)) // 2) + tag, flush=True)
print("\033[?25l", end="", flush=True)  # hide the cursor while the card shows; the tape restores it with `tput cnorm`
