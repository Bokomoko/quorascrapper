from pathlib import Path
from unittest.mock import patch

from quorascrapper.ops import install as install_mod


def test_install_extension_copies_tree(tmp_path):
    src = tmp_path / "src_ext"
    src.mkdir()
    (src / "manifest.json").write_text("{}", encoding="utf-8")
    (src / "lib").mkdir()
    (src / "lib" / "filter.js").write_text("//", encoding="utf-8")

    dest = tmp_path / "dest"
    with patch.object(install_mod, "extension_source_dir", return_value=src):
        out = install_mod.install_extension(dest)

    assert out == dest
    assert (dest / "manifest.json").is_file()
    assert (dest / "lib" / "filter.js").is_file()


def test_install_extension_replaces_existing(tmp_path):
    src = tmp_path / "src_ext"
    src.mkdir()
    (src / "manifest.json").write_text('{"v":2}', encoding="utf-8")

    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "manifest.json").write_text('{"v":1}', encoding="utf-8")

    with patch.object(install_mod, "extension_source_dir", return_value=src):
        install_mod.install_extension(dest)

    assert (dest / "manifest.json").read_text(encoding="utf-8") == '{"v":2}'


def test_launch_chrome_with_extension_requires_quit(tmp_path):
    ext = tmp_path / "ext"
    ext.mkdir()
    chrome = tmp_path / "Google Chrome"
    chrome.write_text("", encoding="utf-8")

    with (
        patch.object(install_mod, "_chrome_binary", return_value=chrome),
        patch.object(install_mod, "_chrome_running", return_value=True),
    ):
        ok, msg = install_mod.launch_chrome_with_extension(ext)

    assert ok is False
    assert "already running" in msg


def test_launch_chrome_with_extension_spawns(tmp_path):
    ext = tmp_path / "ext"
    ext.mkdir()
    chrome = tmp_path / "Google Chrome"
    chrome.write_text("", encoding="utf-8")

    with (
        patch.object(install_mod, "_chrome_binary", return_value=chrome),
        patch.object(install_mod, "_chrome_running", return_value=False),
        patch.object(install_mod.subprocess, "Popen") as popen,
    ):
        ok, msg = install_mod.launch_chrome_with_extension(ext)

    assert ok is True
    popen.assert_called_once()
    args = popen.call_args[0][0]
    assert args[0] == str(chrome)
    assert args[1].startswith("--load-extension=")


def test_qsbk_install_subcommand():
    from quorascrapper.cli import main

    with patch("quorascrapper.ops.install.main", return_value=0) as mock_install:
        assert main(["install", "--dir", "/tmp/x"]) == 0
        mock_install.assert_called_once_with(["--dir", "/tmp/x"])
