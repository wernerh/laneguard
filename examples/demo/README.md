# Hero demo GIF

**The GIF has not been recorded.** It has to be recorded by the repository owner, on their machine, against a real sandbox repository. No GIF, screenshot or output transcript is committed here, and `demo.tape` deliberately contains only commands, never output text.

## What the tape does

`demo.tape` is a [VHS](https://github.com/charmbracelet/vhs) script that types these real commands in order:

1. `/laneguard:init` (inside Claude Code) scaffolds Laneguard in the sandbox repo
2. `/laneguard:doctor` checks the setup
3. `/laneguard:run dev --dry-run` shows what a dev lane would do, without acting
4. `python3 .laneguard/guard/doctor.py` runs the guard's doctor from a plain shell

## Recording it

1. Install VHS (`brew install vhs`, or see its README) and make sure Claude Code is installed and logged in.
2. Create a throwaway repo, `~/laneguard-demo-sandbox`, with a git remote, and install the Laneguard plugin in Claude Code.
3. Run `vhs examples/demo/demo.tape` from the Laneguard repo root. Adjust the `Sleep` values to match the real durations. If a step is slow, speed the whole GIF up uniformly instead of trimming steps out.
4. Review the GIF for anything private (account names, paths, tokens) before publishing.

## Note on the spec

`docs/design-spec.md` describes a roughly 20 second hero that also shows a gate stopping an edit to a protected path. That scene needs a real blocked attempt in a real run and is not in this tape; add it only after you have recorded one for real.
