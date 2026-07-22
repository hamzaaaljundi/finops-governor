"""Frozen-kit integrity guard (ADR 0011, decision 3).

Session 4a discovered that the committed session_kit/ - treated as frozen session-3
state - had been silently regenerated post-session by a since-regressed adapter,
invalidating every "byte-identical proven script" assumption built on it. This test
makes that failure loud: each frozen kit carries a MANIFEST.sha256 generated at
freeze time, and any change to a manifested file (including regeneration that
happens to produce different bytes) fails CI with the exact file named.

Deliberately NOT covered: the pre-manifest session_kit/ (its drift already happened
and is documented history - manifesting it now would checksum the drifted state and
imply a freshness it doesn't have) and any frame outputs (uncommitted by design).

To legitimately update a frozen kit: change the files, regenerate the manifest
(the one-liner in the module docstring of the generator below), and let the diff
show BOTH the file change and the manifest change in the same commit - visible,
reviewable, never silent.

Manifest regeneration one-liner (from the repo root):
    python3 -c "import hashlib; from pathlib import Path; root = Path('session_kit_s4'); lines = [f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root)}' for p in sorted(root.rglob('*')) if p.is_file() and p.suffix in {'.py', '.json', '.md'} and p.name != 'MANIFEST.sha256']; (root / 'MANIFEST.sha256').write_text(chr(10).join(lines) + chr(10))"
"""

import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FROZEN_KITS = [ROOT / "session_kit_s4"]


@pytest.mark.parametrize("kit", FROZEN_KITS, ids=lambda p: p.name)
def test_frozen_kit_matches_its_manifest(kit: Path):
    manifest = kit / "MANIFEST.sha256"
    assert manifest.exists(), (
        f"{kit.name} has no MANIFEST.sha256 - a frozen kit without a manifest is "
        f"unguarded against silent regeneration (ADR 0011)."
    )

    expected: dict[str, str] = {}
    for line in manifest.read_text().splitlines():
        digest, _, rel = line.partition("  ")
        expected[rel] = digest

    actual: dict[str, str] = {}
    for p in sorted(kit.rglob("*")):
        if p.is_file() and p.suffix in {".py", ".json", ".md"} and p.name != "MANIFEST.sha256":
            actual[str(p.relative_to(kit))] = hashlib.sha256(p.read_bytes()).hexdigest()

    missing = sorted(set(expected) - set(actual))
    added = sorted(set(actual) - set(expected))
    changed = sorted(rel for rel in set(expected) & set(actual) if expected[rel] != actual[rel])

    assert not (missing or added or changed), (
        f"{kit.name} drifted from its manifest - "
        f"missing: {missing or 'none'}; unmanifested new files: {added or 'none'}; "
        f"changed: {changed or 'none'}. If this change is intentional, regenerate "
        f"MANIFEST.sha256 in the same commit (see module docstring) so the change "
        f"is visible, not silent (ADR 0011, decision 3)."
    )
