from click.testing import CliRunner

from jarvis.cli import main


EXPECTED_COMMANDS = {
    "canvas", "ask", "schedule", "brief", "ate", "gym", "cardio",
    "macros", "week", "markets", "jobs", "apply", "status", "pipeline", "next",
}


def test_help_lists_all_commands():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    for cmd in EXPECTED_COMMANDS:
        assert cmd in result.output, f"missing {cmd} in --help"


def test_stubs_exit_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()
    for cmd in ("brief", "macros", "week", "markets", "pipeline", "next"):
        result = runner.invoke(main, [cmd])
        assert result.exit_code == 0, f"{cmd} failed: {result.output}"
        assert "not yet implemented" in result.output.lower()
