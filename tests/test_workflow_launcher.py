"""Tests for the Tk workflow launcher helper functions."""
from pathlib import Path

from gui import workflow_launcher


def test_discover_helper_scripts_lists_repo_scripts() -> None:
    """The helper script discovery should list the known shell scripts."""

    scripts = workflow_launcher.discover_helper_scripts()
    names = [path.name for path in scripts]
    assert "bootstrapmacsetup.sh" in names
    assert "set_default_python.sh" in names


def test_base_commands_include_setup_and_tests() -> None:
    """Setup and test commands should be available on POSIX hosts."""

    labels = [spec.label for spec in workflow_launcher.base_commands()]
    assert "Setup Environment" in labels
    assert "Run Tests" in labels


def test_parse_usage_parameters_returns_optional_and_required() -> None:
    """Usage lines should turn into ScriptParameter objects."""

    usage = "Usage: script.sh <INPUT> [OUTPUT] [-h]"
    params = workflow_launcher.parse_usage_parameters(usage)
    assert [param.label for param in params] == ["Input", "Output"]
    assert params[0].required is True
    assert params[1].required is False


def test_script_parameters_detects_real_script() -> None:
    """Scripts that implement --help should expose their parameters."""

    script = Path("scripts/set_default_python.sh")
    params = workflow_launcher.script_parameters(script)
    assert params
    assert params[0].label == "Config File"
    assert params[0].required is False
