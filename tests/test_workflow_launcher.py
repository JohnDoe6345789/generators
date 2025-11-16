"""Tests for the Tk workflow launcher helper functions."""
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
