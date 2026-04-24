"""Config loader."""

from __future__ import annotations

import json

import pytest

from agentboot.config import Config, load_config, save_config


def test_load_config_no_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTBOOT_CONFIG", raising=False)
    missing = tmp_path / "not-there.json"
    cfg = load_config(missing)
    assert isinstance(cfg, Config)
    assert cfg.model_path is None
    assert cfg.log_level == "INFO"


def test_load_config_reads_known_fields(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({
        "model_path": "/opt/models/q.gguf",
        "session_dir": "/var/agentboot",
        "anthropic_api_key": "sk-abc",
        "preferred_llm": "anthropic",
        "log_level": "DEBUG",
    }), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.model_path == "/opt/models/q.gguf"
    assert cfg.session_dir == "/var/agentboot"
    assert cfg.anthropic_api_key == "sk-abc"
    assert cfg.preferred_llm == "anthropic"
    assert cfg.log_level == "DEBUG"


def test_load_config_unknown_fields_become_extras(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({
        "model_path": "/foo",
        "future_v2_field": {"nested": True},
    }), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.model_path == "/foo"
    assert cfg.extras == {"future_v2_field": {"nested": True}}


def test_load_config_rejects_bad_json(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text("{not valid", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_config(path)


def test_load_config_rejects_non_object_top_level(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_config(path)


def test_env_override(tmp_path, monkeypatch):
    path = tmp_path / "envcfg.json"
    path.write_text(json.dumps({"log_level": "ERROR"}), encoding="utf-8")
    monkeypatch.setenv("AGENTBOOT_CONFIG", str(path))
    cfg = load_config()
    assert cfg.log_level == "ERROR"


def test_save_and_reload_roundtrip(tmp_path):
    cfg = Config(model_path="/foo", preferred_llm="local", log_level="DEBUG")
    out = tmp_path / "written.json"
    save_config(cfg, out)
    assert out.is_file()

    back = load_config(out)
    assert back.model_path == cfg.model_path
    assert back.preferred_llm == cfg.preferred_llm
    assert back.log_level == "DEBUG"


def test_merged_anthropic_key_prefers_config_over_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    cfg = Config(anthropic_api_key="from-config")
    assert cfg.merged_anthropic_key() == "from-config"


def test_merged_anthropic_key_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    cfg = Config()
    assert cfg.merged_anthropic_key() == "from-env"


def test_merged_google_key_none_when_absent(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    cfg = Config()
    assert cfg.merged_google_key() is None
