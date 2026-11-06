"""The Chinese catalogue, and the server that renders pages with it."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE_JSON = ROOT / "i18n" / "zh-CN.json"
SERVER_JSON = ROOT / "media_preview_generator" / "web" / "i18n" / "zh-CN.json"
BROWSER_JS = ROOT / "media_preview_generator" / "web" / "static" / "i18n" / "zh-CN.js"
_SLOTS = re.compile(r"\{(\d+)\}")


def _source() -> dict:
    return json.loads(CATALOGUE_JSON.read_text(encoding="utf-8"))


def _generated() -> dict:
    return json.loads(SERVER_JSON.read_text(encoding="utf-8"))


def test_catalogue_is_substantial():
    rows = _source()

    assert len(rows["strings"]) > 2500
    assert len(rows["patterns"]) > 100


def test_core_labels_are_chinese():
    strings = _source()["strings"]

    assert strings["Save"] == "保存"
    assert strings["Cancel"] == "取消"
    assert strings["Settings"] == "设置"
    assert strings["Media Preview Generator"] == "媒体预览生成器"
    assert strings["Nothing queued"] == "队列为空"


def test_every_pattern_keeps_its_placeholders():
    for source, target in _source()["patterns"]:
        assert sorted(_SLOTS.findall(source)) == sorted(_SLOTS.findall(target)), f"{source} -> {target}"


def test_longer_patterns_come_first():
    lengths = [len(source) for source, _target in _source()["patterns"]]

    assert lengths == sorted(lengths, reverse=True), "a shorter template would swallow a longer sentence"


def test_generated_outputs_match_the_source():
    """The two files the app reads hold every label the source does (the builder merges i18n/overrides.json)."""
    rows = _source()
    generated = _generated()

    missing = [key for key in rows["strings"] if key not in generated["strings"]]
    assert not missing, missing[:5]
    assert all(generated["strings"][key] == value for key, value in rows["strings"].items())
    assert BROWSER_JS.exists()
    assert '"zh-CN"' in BROWSER_JS.read_text(encoding="utf-8")


class TestServerTranslation:
    def test_a_label_becomes_chinese(self):
        from media_preview_generator.web.server_i18n import translate

        assert translate("Save", "zh-CN") == "保存"

    def test_a_pattern_fills_its_slots(self):
        from media_preview_generator.web.server_i18n import translate

        assert translate("Attempt 2/5 running", "zh-CN") == "第 2/5 次尝试运行中"

    def test_surrounding_spaces_are_kept(self):
        from media_preview_generator.web.server_i18n import translate

        assert translate("  Save  ", "zh-CN") == "  保存  "

    def test_unknown_text_is_left_alone(self):
        from media_preview_generator.web.server_i18n import translate

        assert translate("A sentence no catalogue has", "zh-CN") is None

    def test_english_asks_for_no_translation(self):
        from media_preview_generator.web.server_i18n import translate

        assert translate("Save", "en") is None

    def test_code_and_scripts_are_never_translated(self):
        from media_preview_generator.web.server_i18n import translate_html

        page = '<p>Save</p><code>Save</code><script>var a = "Save";</script><pre>Save</pre>'
        out = translate_html(page, "zh-CN")

        assert "<p>保存</p>" in out
        assert "<code>Save</code>" in out
        assert '<script>var a = "Save";</script>' in out
        assert "<pre>Save</pre>" in out

    def test_attributes_are_translated(self):
        from media_preview_generator.web.server_i18n import translate_html

        out = translate_html('<button title="Retry now">Retry now</button>', "zh-CN")

        assert 'title="立即重试"' in out
        assert ">立即重试<" in out

    def test_chinese_text_is_untouched(self):
        from media_preview_generator.web.server_i18n import translate_html

        assert translate_html("<span>后台</span>", "zh-CN") == "<span>后台</span>"


def test_pages_load_the_browser_translator():
    for name in ("base.html", "login.html"):
        text = (ROOT / "media_preview_generator" / "web" / "templates" / name).read_text(encoding="utf-8")
        assert "i18n/zh-CN.js" in text
        assert "js/i18n.js" in text
