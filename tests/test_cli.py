"""Tests for the textworkspace CLI entry point."""

from click.testing import CliRunner

from textworkspace.cli import main


def test_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "textworkspace" in result.output


def test_help_shows_all_subcommands():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    expected = ["init", "status", "doctor", "update", "switch", "sessions", "stats", "serve", "config", "which"]
    for cmd in expected:
        assert cmd in result.output, f"subcommand '{cmd}' missing from --help"
