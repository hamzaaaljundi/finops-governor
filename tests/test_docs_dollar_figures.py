"""Docs-vs-code drift guard.

Session-3 recalibration (ADR 0009) silently went stale in five separate files -
README.md, ROADMAP.md, docs/diversity-model.md, docs/orchestration-model.md, and
docs/cost-model.md all kept quoting pre-recalibration dollar figures for months after
the constants changed, because nothing checked that hand-copied numbers in prose
matched what the code actually computes. This test is that check: it runs the CLI on
the same pinned fixtures the docs describe, and asserts every dollar figure the CLI
prints today also appears, verbatim, somewhere in the docs that quote that example.

This does not parse every dollar sign in every doc (deliberately - Consequences
sections and RUN_LOG.md quote historical, superseded figures on purpose, e.g. ADR 0007
and docs/calibration/RUN_LOG.md; rewriting those would falsify history, see ADR 0008/
ADR 0009's own amendment pattern). It only asserts that the CURRENT, correct number is
present somewhere - it cannot tell you an old wrong number was removed, only that the
right one is there. Catching drift here means the docs never go silently wrong again;
it doesn't replace the human judgment call about which docs are living vs historical.
"""

import re
from pathlib import Path

from finops_governor.cli import main

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"

# Living design docs that should always reflect current, correct figures for the
# examples they quote. Deliberately excludes ADRs (historical decision records) and
# docs/calibration/RUN_LOG.md (a dated historical narrative) - see module docstring.
LIVING_DOCS = [
    ROOT / "README.md",
    ROOT / "ROADMAP.md",
    ROOT / "docs" / "diversity-model.md",
    ROOT / "docs" / "orchestration-model.md",
]


def _run(capsys, *argv):
    code = main(list(argv))
    return code, capsys.readouterr().out


def _dollar_figures(text: str) -> set[str]:
    """Every complete $-prefixed figure the CLI printed, e.g. {'$930.27', '$0.0093'}.

    Requires the full run of decimal digits (so '$0.0093' isn't truncated to '$0.00')
    and excludes anything immediately followed by another digit or a '/' (so a rate
    like '$1.006/h' is never mistaken for a $1.00 total)."""
    return set(re.findall(r"\$[0-9][0-9,]*\.[0-9]{2,4}(?![0-9/])", text))


def _claimed_figures(cli_output: str) -> set[str]:
    """Dollar figures the CLI actually claims/computes - excludes the 'budget:' line,
    which only echoes the CLI's own input argument back, not a derived result docs
    would ever need to quote."""
    lines = [ln for ln in cli_output.splitlines() if not ln.startswith("budget:")]
    return _dollar_figures("\n".join(lines))


def _living_docs_text() -> str:
    return "\n".join(p.read_text() for p in LIVING_DOCS)


def test_production_redundancy_figures_match_docs(capsys):
    """Every dollar figure the CLI prints for the production_scale.json redundancy
    example must appear somewhere in the living docs that quote this example
    (README's opening blockquote, ROADMAP's M6.5 bullet, diversity-model.md's worked
    example, orchestration-model.md's convergence-invariant note)."""
    _, out = _run(capsys, str(FIXTURES / "diversity" / "redundant" / "production_scale.json"))
    live_figures = _claimed_figures(out)
    assert live_figures, "CLI printed no dollar figures - check the fixture/CLI itself first"

    docs_text = _living_docs_text()
    missing = sorted(fig for fig in live_figures if fig not in docs_text)
    assert not missing, (
        f"CLI computes {sorted(live_figures)} for production_scale.json, but "
        f"{missing} do not appear in any living doc. Either the docs are stale "
        f"(update them) or the cost/diversity model changed (that's expected - "
        f"update the docs to match, the same fix applied for ADR 0009)."
    )


def test_readme_try_it_commands_match_their_comments(capsys):
    """README's '## Try it' block shows bare commands with a one-line comment claiming
    the outcome (exit code / verdict) - it never quotes the advisor's actual output.
    This runs each command for real and checks the claimed outcome still holds, so a
    future constants or logic change that flips a verdict is caught here rather than
    silently leaving a comment that's simply wrong."""
    readme = (ROOT / "README.md").read_text()
    match = re.search(r"## Try it\n\n```bash\n(.*?)```", readme, re.S)
    assert match, "README's '## Try it' bash block not found - section renamed or moved?"

    pairs: list[tuple[str, str]] = []
    pending_comment = ""
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            pending_comment = stripped.lstrip("#").strip()
        elif stripped.startswith("finops-governor "):
            pairs.append((pending_comment, stripped[len("finops-governor ") :]))
            pending_comment = ""

    assert len(pairs) == 3, f"expected 3 Try-It commands, found {len(pairs)}: {pairs}"

    for comment, command in pairs:
        argv = [a for a in command.split(" ") if a]
        code, out = _run(capsys, *argv)
        if "exit 1" in comment:
            assert code == 1, f"'{comment}' claims exit 1, got {code}\n{out}"
        elif "BLOCKED" in comment:
            assert code == 2 and "verdict:   BLOCK" in out, (
                f"'{comment}' claims BLOCK, got exit {code}\n{out}"
            )
        elif "mid-tier" in comment:
            assert code == 0, f"'{comment}' claims a clean APPROVE, got exit {code}\n{out}"
            # the punchline this comment makes: the cheapest $/h card is not recommended
            lines = out.splitlines()
            recommended = next(ln for ln in lines if "<- recommended" in ln)
            cheapest_per_hour = min(
                (ln for ln in lines if "GPU-hours @" in ln),
                key=lambda ln: float(re.search(r"@ \$([0-9.]+)/h", ln).group(1)),
            )
            assert recommended != cheapest_per_hour, (
                f"'{comment}' claims the mid-tier card wins over the cheapest-per-hour "
                f"one, but the recommended card IS the cheapest per hour:\n{out}"
            )
