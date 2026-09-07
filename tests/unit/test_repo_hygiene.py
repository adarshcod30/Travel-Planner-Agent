"""Guards on what may enter the repository.

These are not tests of the product. They are tests of the repository itself,
and they exist because both of the things they check have already gone wrong
once: a tooling directory reached a commit, and a credential-bearing file was
one careless `git add` away from doing the same.

A convention in a README does not survive a hurried commit. A failing test does.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Directories belonging to editors and coding assistants. They are local
#: workspace configuration, not part of the project, and have no business in a
#: repository that is read as someone's own work.
TOOLING_DIRS = (".tooling", ".cursor", ".aider", ".continue", ".windsurf", ".vscode", ".idea")


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def test_no_tooling_directories_are_tracked():
    offenders = [
        f for f in _tracked() if any(f == d or f.startswith(f"{d}/") for d in TOOLING_DIRS)
    ]
    assert not offenders, f"tooling files are tracked: {offenders}"


def test_tooling_directories_are_ignored():
    """Ignored, not merely absent — otherwise the next run of the tool re-adds them."""
    ignore = (ROOT / ".gitignore").read_text()
    for d in (".tooling", ".cursor"):
        assert f"{d}/" in ignore, f"{d}/ is not in .gitignore"


def test_no_env_file_is_tracked():
    tracked = _tracked()
    assert ".env" not in tracked
    assert not [f for f in tracked if f.endswith("/.env")]


def test_env_example_carries_no_real_secrets():
    """Placeholders only. The example file is committed; the real one is not."""
    text = (ROOT / ".env.example").read_text()
    for marker in ("AKIA", "tvly-dev-", "sk-", "gsk_"):
        assert marker not in text, f"{marker!r} appears in .env.example"
