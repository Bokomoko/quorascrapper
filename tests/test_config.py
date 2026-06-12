import os
from pathlib import Path
from unittest.mock import patch

from quorascrapper.config import Settings, load_project_env


def test_load_project_env_global_then_cwd_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    global_env = tmp_path / "global.env"
    global_env.write_text("KAFKA_BOOTSTRAP=global:9092\nSENDER=stdout\n", encoding="utf-8")
    (tmp_path / ".env").write_text("KAFKA_BOOTSTRAP=local:9092\n", encoding="utf-8")

    with patch("quorascrapper.ops.config_cmd.config_paths", return_value=[global_env]):
        load_project_env()

    assert os.environ["KAFKA_BOOTSTRAP"] == "local:9092"
    assert os.environ["SENDER"] == "stdout"


def test_settings_from_env_after_load(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "KAFKA_BOOTSTRAP=bokomint.local:19092\nMONGODB_URI=mongodb+srv://x\n",
        encoding="utf-8",
    )
    load_project_env()
    s = Settings.from_env()
    assert s.kafka_bootstrap == "bokomint.local:19092"
    assert s.mongodb_uri == "mongodb+srv://x"
