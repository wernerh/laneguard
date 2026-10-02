# Laneguard hero demo (VHS tape). https://github.com/charmbracelet/vhs
#
# Record in a scratch git repo, inside a Claude Code session that already has the Laneguard plugin
# installed. Every command below is real; nothing is simulated and the tape contains no output text.
# Slash commands run inside Claude Code, so the tape starts `claude` first.
#
#   vhs examples/demo/demo.tape
#
# Replace the pauses with the time your actual run takes; the lane run can take minutes, so cut or
# speed up the recording honestly (for example 2x) rather than faking completion.

Output examples/demo/demo.gif

Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 700
Set Padding 20

Type "cd ~/laneguard-demo-sandbox"
Enter
Sleep 1s

Type "claude"
Enter
Sleep 6s

Type "/laneguard:init"
Enter
Sleep 30s

Type "/laneguard:doctor"
Enter
Sleep 20s

Type "/laneguard:run dev --dry-run"
Enter
Sleep 45s

# Exit Claude Code, then run the guard doctor directly from the shell.
Ctrl+D
Sleep 2s

Type "python3 .laneguard/guard/doctor.py"
Enter
Sleep 8s
