# The FinOps Governor demo - a VHS script (https://github.com/charmbracelet/vhs).
# The demo is code: regenerate the GIF any time with `vhs demo/demo.tape`
# from the REPO ROOT (fixture paths are root-relative). Deterministic: every
# command is gate-only - no API key, no network, identical output every run.

Output demo/demo.gif

Set Shell "bash"
Set FontSize 20
Set Width 1400
Set Height 720
Set Padding 20
Set Margin 20
Set MarginFill "#1a1b26"
Set BorderRadius 12
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set Framerate 24
Set CursorBlink false

Hide
Type "PS1='$ ' && clear"
Enter
Show


# --- Scene 1: the headline - waste priced AND removed -------------------
Type "# A $373 job that is ~100% redundant: flagged in dollars, trimmed to the same coverage"
Enter
Sleep 1.5s
Type "finops-governor fixtures/diversity/redundant/production_scale.json"
Enter
Sleep 11s

Type "clear"
Enter

# --- Scene 2: geometric validity - blocked before a cent is spent -------
Type "# Affordable and diverse - but the arm is authored through the floor: BLOCKED, $0 spent"
Enter
Sleep 1.5s
Type "finops-governor fixtures/geometry/floor_clip_scene.json --geometry"
Enter
Sleep 8s

Type "clear"
Enter

# --- Scene 3: the FinOps advisor - which GPU should this run on? --------
Type "# Same job, every GPU profile: the mid-tier card wins, not the cheapest-per-hour"
Enter
Sleep 1.5s
Type "finops-governor fixtures/plans/valid/multi_scene.json --advise"
Enter
Sleep 9s

Type "clear"
Enter

# --- Outro: the full pipeline (shown, not executed - needs ANTHROPIC_API_KEY)
Type "# English in, governed job out - the full pipeline with the audit trail as the receipt:"
Enter
Sleep 1s
Type `finops-governor "50,000 variations of a robotic arm, RGB and depth" --budget 1000 --audit audit.json`
Sleep 5s
