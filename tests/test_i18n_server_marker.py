"""Server-side translation of HTML entities, and the "already translated" marker."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from media_preview_generator.web.server_i18n import translate_html

if not hasattr(os, "getuid"):
    os.getuid = lambda: 1000
    os.getgid = lambda: 1000
if not hasattr(os, "statvfs"):
    os.statvfs = lambda p: SimpleNamespace(
        f_bavail=100 * 1024**2, f_frsize=4096, f_blocks=1000 * 1024**2 // 4096, f_bfree=900 * 1024**2 // 4096
    )


@pytest.mark.parametrize(
    "markup,expected",
    [
        ("<span>Intro &amp; Credits</span>", "片头与片尾"),
        ("<p>Only change this if you know what you&#39;re doing.</p>", "仅在"),
        ("<label>Keep Plex's</label>", "保留 Plex 的"),
        ("<label>Keep Emby's</label>", "保留 Emby 的"),
    ],
)
def test_entities_do_not_hide_a_label(markup, expected):
    """An apostrophe/ampersand entity used to stop the whole text node from matching a catalogue key."""
    assert expected in translate_html(markup, "zh-CN")


def test_translation_stays_valid_html():
    """The answer is escaped back, so a translated label can't break the document."""
    out = translate_html("<p>Tom &amp; Jerry</p>", "zh-CN")

    assert out.startswith("<p>") and out.endswith("</p>")


def test_the_server_marker_is_set_on_a_translated_page(tmp_path, monkeypatch):
    """A page the server translated carries data-i18n="server" so the browser skips its second full-DOM pass."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    auth = config_dir / "auth.json"
    auth.write_text(json.dumps({"token": "test-token-12345678"}), encoding="utf-8")
    (config_dir / "settings.json").write_text(json.dumps({"setup_complete": True}), encoding="utf-8")
    monkeypatch.setenv("CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("WEB_AUTH_TOKEN", "test-token-12345678")
    monkeypatch.setattr("media_preview_generator.web.auth.AUTH_FILE", str(auth))
    monkeypatch.setattr("media_preview_generator.web.auth.CONFIG_DIR", str(config_dir))
    monkeypatch.setattr("media_preview_generator.web.auth.get_config_dir", lambda: str(config_dir))

    from media_preview_generator.web.app import create_app

    app = create_app(config_dir=str(config_dir))
    client = app.test_client()
    client.set_cookie("mpg_lang", "zh-CN")
    # /login is a public page with translatable labels.
    response = client.get("/login")

    assert response.status_code == 200
    assert 'data-i18n="server"' in response.get_data(as_text=True)
