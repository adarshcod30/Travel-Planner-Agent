"""Guards on what may enter the repository.

These are not tests of the product. They are tests of the repository itself,
and they exist because every one of the things they check has already gone
wrong once: a tooling directory reached a commit, a credential-bearing file was
one careless `git add` away from doing the same, and Next 16 quietly wrote an
assistant file into the tree on every `npm run dev`.

A convention in a README does not survive a hurried commit. A failing test does.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Directories belonging to editors and coding assistants. They are local
#: workspace configuration, not part of the project, and have no business in a
#: repository that is read as someone's own work.
TOOLING_DIRS = (".tooling", ".cursor", ".aider", ".continue", ".windsurf", ".vscode", ".idea")

#: Files coding assistants and their frameworks generate into a project. Next
#: 16 writes both of these on every dev start unless `agentRules` is off.
TOOLING_FILES = ("AGENTS.md", "TOOLING.md", ".cursorrules", ".windsurfrules")


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


def test_no_assistant_files_are_tracked():
    """Next 16 generates AGENTS.md and TOOLING.md on every `npm run dev`, in
    whatever directory it is run from. `agentRules: false` stops it; this
    catches the day someone drops that setting."""
    offenders = [f for f in _tracked() if Path(f).name in TOOLING_FILES]
    assert not offenders, f"assistant-generated files are tracked: {offenders}"


def test_next_does_not_generate_assistant_files():
    config = (ROOT / "frontend" / "next.config.ts").read_text()
    assert "agentRules: false" in config, "Next will write AGENTS.md and TOOLING.md without this"


def test_assistant_files_are_ignored():
    ignore = (ROOT / ".gitignore").read_text().splitlines()
    for name in ("AGENTS.md", "TOOLING.md"):
        assert name in ignore, f"{name} is not in .gitignore"


def test_the_systemd_units_point_at_scripts_that_exist():
    """A unit naming a script that was renamed fails at `systemctl start`, on
    someone else's server, with a message about an exit code."""
    import re

    units = sorted((ROOT / "deploy" / "systemd").glob("*.service"))
    assert units, "the deployment units are part of the deliverable"
    for unit in units:
        for path in re.findall(r"/opt/travel-planner/(\S+\.sh)", unit.read_text()):
            assert (ROOT / path).is_file(), f"{unit.name} runs {path}, which does not exist"


def test_every_script_is_executable():
    for script in sorted((ROOT / "scripts").glob("*.sh")):
        assert script.stat().st_mode & 0o111, f"{script.name} is not executable"
