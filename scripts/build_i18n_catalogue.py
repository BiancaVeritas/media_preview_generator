#!/usr/bin/env python3
"""Build the Chinese UI catalogue that ``web/static/js/i18n.js`` reads.

Input is ``build/i18n/source.json`` (from ``scripts/extract_i18n_strings.py``) and
the translated chunks in ``build/i18n/parts/*.out.json``, each a JSON array of
``{"source": ..., "target": ...}``. The output is a plain script so the browser
loads it synchronously, before the first paint of the app's own scripts:

    window.__MPG_I18N__["zh-CN"] = {...}          # exact text -> Chinese
    window.__MPG_I18N_PATTERNS__["zh-CN"] = [...]  # "{0} files" -> "…"

Usage::

    python scripts/build_i18n_catalogue.py
    python scripts/build_i18n_catalogue.py --strict   # fail on an untranslated key
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "build" / "i18n" / "source.json"
PARTS = ROOT / "build" / "i18n" / "parts"
OUT = ROOT / "media_preview_generator" / "web" / "static" / "i18n" / "zh-CN.js"

_SLOT_RE = re.compile(r"\{(\d+)\}")

# Strings the extractor leaves out because they are the product name, plus the page titles built around it.
_MANUAL = {
    "Media Preview Generator": "媒体预览生成器",
    "Switch interface language": "切换界面语言",
    "? Enter server details manually": "？请手动输入服务器信息",
    "Showing Workers": "显示工作进程",
    "Showing Nodes": "显示节点",
    "0 = Auto": "0 = 自动",
    "(lower = sharper)": "（数值越小越清晰）",
    "seconds": "秒",
    "min": "分钟",
    "files": "个文件",
    "days": "天",
    "Webhook URL": "Webhook 地址",
    "with value": "值",
    "different": "不同",
    "On File Import": "文件导入时",
    "On File Upgrade": "文件升级时",
    "On Upgrade": "升级时",
    "off": "关闭",
    "Nothing queued": "队列为空",
    "Start a job, or choose All jobs and history (the All tab) to review past work.": "新建任务，或选择“所有任务和历史记录”（“全部”标签页）查看以往的工作。",
    "No jobs match these filters.": "没有任务符合这些筛选条件。",
    "Change a filter or use Clear filters to see other jobs.": "调整筛选条件，或点击“清除筛选”查看其他任务。",
    "Pause": "暂停",
    "Add one.": "添加一个。",
    "CPU workers": "CPU 工作进程",
    "TASK": "任务",
}
_MANUAL_PATTERNS = [
    ("{0} - Media Preview Generator", "{0} - 媒体预览生成器"),
    ("{0} · Media Preview Generator", "{0} · 媒体预览生成器"),
    ("Retry {0}/{1}", "重试 {0}/{1}"),
    ("{0} selected", "已选择 {0} 个"),
    ("{0} files", "{0} 个文件"),
    ("{0} jobs", "{0} 个任务"),
    ("{0} days", "{0} 天"),
    ("{0} hours", "{0} 小时"),
    ("{0} minutes", "{0} 分钟"),
    ("{0} seconds", "{0} 秒"),
    ("{0} servers", "{0} 台服务器"),
    ("{0} libraries", "{0} 个媒体库"),
    ("{0} items", "{0} 个项目"),
    ("{0} worker idle #{1}", "{0} 个工作进程空闲 #{1}"),
    ("{0} worker idle", "{0} 个工作进程空闲"),
    ("{0} / {1} busy", "{0} / {1} 忙碌"),
]

# Left in English on purpose: selectors, identifiers, examples and names.
_TECHNICAL_RE = re.compile(
    r"(^[#./\[]|__|_blank|_infer|\*\*|min-width|^[a-z]+(\[[^\]]*\])?$|^[a-z]+,\s*[a-z]+$|^[\d./:]+$)"
)


def _load_parts() -> dict[str, str]:
    translations: dict[str, str] = {}
    for path in sorted(PARTS.glob("*.out.json")):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"! {path.name}: {exc}", file=sys.stderr)
            continue
        if not isinstance(rows, list):
            print(f"! {path.name}: not a JSON array", file=sys.stderr)
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            source, target = row.get("source"), row.get("target")
            if isinstance(source, str) and isinstance(target, str) and target.strip():
                translations[source] = target.strip()
    return translations


def _slots(text: str) -> list[str]:
    return sorted(_SLOT_RE.findall(text))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="exit non-zero when a key has no translation")
    args = parser.parse_args()

    rows = json.loads(SOURCE.read_text(encoding="utf-8"))
    translations = _load_parts()
    catalogue: dict[str, str] = {}
    patterns: list[tuple[str, str]] = []
    missing: list[str] = []
    untranslated: list[str] = []
    bad_slots: list[str] = []

    for row in rows:
        key = row["key"]
        target = translations.get(key)
        if target is None:
            missing.append(key)
            continue
        if row.get("pattern"):
            if _slots(key) != _slots(target):
                bad_slots.append(f"{key} -> {target}")
                continue
            patterns.append((key, target))
            continue
        if target == key:
            untranslated.append(key)
            continue
        catalogue[key] = target

    for key, target in _MANUAL.items():
        catalogue.setdefault(key, target)
    for key, target in _MANUAL_PATTERNS:
        if all(existing != key for existing, _target in patterns):
            patterns.append((key, target))

    # Longest templates first: "Add {0} server" must win over "Add {0}".
    patterns.sort(key=lambda item: len(item[0]), reverse=True)

    lines = [
        "/* Generated by scripts/build_i18n_catalogue.py -- do not edit by hand.",
        " * Chinese UI strings for Media Preview Generator, keyed by the English text",
        " * they replace. Loaded by web/static/js/i18n.js. */",
        "window.__MPG_I18N__ = window.__MPG_I18N__ || {};",
        'window.__MPG_I18N__["zh-CN"] = ' + json.dumps(catalogue, ensure_ascii=False, indent=1, sort_keys=True) + ";",
        "window.__MPG_I18N_PATTERNS__ = window.__MPG_I18N_PATTERNS__ || {};",
        'window.__MPG_I18N_PATTERNS__["zh-CN"] = ' + json.dumps(patterns, ensure_ascii=False, indent=1) + ";",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")

    print(f"{len(catalogue)} labels + {len(patterns)} sentence patterns -> {OUT.relative_to(ROOT)}")
    if bad_slots:
        print(f"{len(bad_slots)} pattern(s) changed their placeholders:", file=sys.stderr)
        for item in bad_slots[:20]:
            print(f"  {item}", file=sys.stderr)
    if missing:
        print(f"{len(missing)} key(s) have no translation", file=sys.stderr)
        for key in missing[:20]:
            print(f"  {key}", file=sys.stderr)
    technical = [key for key in untranslated if _TECHNICAL_RE.search(key)]
    if untranslated:
        print(f"{len(untranslated)} key(s) kept English ({len(technical)} technical)", file=sys.stderr)
        for key in untranslated[:10]:
            print(f"  {key}", file=sys.stderr)
    if args.strict and (missing or bad_slots):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
