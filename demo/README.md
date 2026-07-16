# Demo assets

`demo.gif` is generated - never hand-recorded - from `demo.tape` using
[VHS](https://github.com/charmbracelet/vhs), so the demo is reproducible like
everything else in this repo.

## Regenerate

```bash
brew install vhs          # one-time (installs ttyd + ffmpeg with it)
pip install -e .          # the `finops-governor` command must be on PATH
vhs demo/demo.tape        # run from the REPO ROOT; writes demo/demo.gif
```

Every command in the tape is deterministic (gate-only, no API key, no network),
so the GIF is identical on every render. The natural-language pipeline command
appears as the outro but is not executed - it needs `ANTHROPIC_API_KEY`; a real
session is shown in the main README instead.
