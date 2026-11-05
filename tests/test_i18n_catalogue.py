"""The generated Chinese catalogue stays consistent with the engine that reads it."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

CATALOGUE = Path(__file__).resolve().parents[1] / "media_preview_generator" / "web" / "static" / "i18n" / "zh-CN.js"
_SLOTS = re.compile(r"\{(\d+)\}")


def _load() -> tuple[dict[str, str], list[list[str]]]:
    text = CATALOGUE.read_text(encoding="utf-8")
    labels = re.search(r'window\.__MPG_I18N__\["zh-CN"\] = (\{.*?\});\n', text, re.DOTALL)
    patterns = re.search(r'window\.__MPG_I18N_PATTERNS__\["zh-CN"\] = (\[.*?\]);\n', text, re.DOTALL)
    assert labels and patterns, "catalogue script is missing one of its assignments"
    return json.loads(labels.group(1)), json.loads(patterns.group(1))


def test_catalogue_is_generated_and_substantial():
    labels, patterns = _load()

    assert len(labels) > 800
    assert len(patterns) > 50
    assert all(source and target for source, target in labels.items())
    assert all(isinstance(item, list) and len(item) == 2 for item in patterns)


def test_core_labels_are_chinese():
    labels, _patterns = _load()

    assert labels["Save"] == "保存"
    assert labels["Cancel"] == "取消"
    assert labels["Settings"] == "设置"
    assert labels["Media Preview Generator"] == "媒体预览生成器"


def test_every_pattern_keeps_its_placeholders():
    _labels, patterns = _load()

    for source, target in patterns:
        assert sorted(_SLOTS.findall(source)) == sorted(_SLOTS.findall(target)), f"{source} -> {target}"


def test_longer_patterns_come_first():
    _labels, patterns = _load()
    lengths = [len(source) for source, _target in patterns]

    assert lengths == sorted(lengths, reverse=True), "a shorter template would swallow a longer sentence"


@pytest.mark.parametrize("template", ["base.html", "login.html"])
def test_pages_load_the_translator(template: str):
    path = Path(__file__).resolve().parents[1] / "media_preview_generator" / "web" / "templates" / template
    text = path.read_text(encoding="utf-8")

    assert "i18n/zh-CN.js" in text
    assert "js/i18n.js" in text
