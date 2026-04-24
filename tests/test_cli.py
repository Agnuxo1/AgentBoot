"""CLI argument parsing tests (no model required)."""

from __future__ import annotations

from pathlib import Path

from agentboot import cli


def test_main_returns_error_code_when_model_missing(tmp_path, capsys):
    missing = tmp_path / "not-here.gguf"
    rc = cli.main(["--model", str(missing)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "model file not found" in err


def test_default_model_path_points_under_models_dir():
    assert cli.DEFAULT_MODEL.name.endswith(".gguf")
    assert cli.DEFAULT_MODEL.parent.name == "models"


def test_system_prompt_defined():
    assert isinstance(cli.SYSTEM_PROMPT, str)
    assert len(cli.SYSTEM_PROMPT) > 0
