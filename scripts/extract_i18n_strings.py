#!/usr/bin/env python3
"""Collect the user-facing English strings of the web UI, for the Chinese catalogue.

The UI is Jinja templates plus static JavaScript, with no gettext markers, so the
catalogue is keyed by the English text itself: ``i18n.js`` swaps a text node or
an attribute whose whole value is a key. This script walks the templates and the
JavaScript, drops the strings that are code, selectors, paths or brand names,
and writes the candidates as JSON (with where each came from).

Usage::

    python scripts/extract_i18n_strings.py            # write build/i18n/source.json
    python scripts/extract_i18n_strings.py --print    # also print the list
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "media_preview_generator" / "web" / "templates"
SCRIPTS = ROOT / "media_preview_generator" / "web" / "static" / "js"
PACKAGE = ROOT / "media_preview_generator"
OUT = ROOT / "build" / "i18n" / "source.json"

# Whole blocks whose text is code, not prose.
_BLOCK_RE = re.compile(r"<(script|style|pre)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
# Inline code splits a sentence into separate text nodes in the browser; a sentinel keeps the halves apart here too.
_INLINE_RE = re.compile(r"<(code|kbd|samp|textarea)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)
_TEXT_RE = re.compile(r">([^<>]+)<", re.DOTALL)
_JINJA_EXPR_RE = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_ATTR_RE = re.compile(
    r"""\b(placeholder|title|aria-label|alt|data-bs-title|value)\s*=\s*(?:"([^"]*)"|'([^']*)')""",
    re.IGNORECASE,
)
_JINJA_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
_JS_STRING_RE = re.compile(r"""(['"`])((?:\\.|(?!\1).){2,240}?)\1""", re.DOTALL)
_JS_TEMPLATE_RE = re.compile(r"`((?:\\.|[^`\\]){2,300})`", re.DOTALL)
# Python messages the web layer shows: a JSON error/message value, a flash, or a named text field.
_PY_MESSAGE_RE = re.compile(
    r"""(?:message|error|detail|reason|hint|label)\s*[=:]\s*(["\'])((?:\\.|(?!\1).){3,200}?)\1"""
    r"""|(?:flash|jsonify|abort|_error_response|_json_error)\(\s*(["\'])((?:\\.|(?!\3).){3,200}?)\3""",
    re.DOTALL,
)
_INTERPOLATION_RE = re.compile(r"\$\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}")
_CAMEL_RE = re.compile(r"[a-z][A-Z]")

# Names and technical tokens that stay as they are inside Chinese text.
KEEP = re.compile(
    r"^(Media Preview Generator|Plex|Emby|Jellyfin|Sonarr|Radarr|Sportarr|Tdarr|FileFlows|Docker|DockerHub|"
    r"GitHub|Unraid|Windows|Linux|macOS|iOS|Android|TrueNAS|Synology|GPU|CPU|HDR|HDR10|HLG|SDR|Dolby Vision|"
    r"Dolby|BIF|JPG|JPEG|PNG|WebP|FFmpeg|ffmpeg|ffprobe|MediaInfo|Vulkan|OpenCL|NVIDIA|Intel|AMD|Apple|VAAPI|"
    r"QSV|NVDEC|CUDA|API|URL|JSON|HTTP|HTTPS|Webhook|STRM|STRM 文件|TMDB|TVDB|IMDb|Plex Pass|Emby Premiere|"
    r"OK|No|Yes|English|中文)$"
)

_SKIP_RE = (
    re.compile(r"^[\W\d_]+$"),  # punctuation, numbers only
    re.compile(r"^(https?|ftp|rtsp|rtmp)://", re.IGNORECASE),
    re.compile(r"^(/|\./|\.\./|[A-Za-z]:[\\/])"),  # a path
    re.compile(r"^[\w.-]+@[\w.-]+$"),
    re.compile(
        r"\.(mkv|mp4|m4v|avi|mov|ts|srt|ass|vtt|bif|jpg|jpeg|png|webp|json|ya?ml|html|py|sh|js|css|txt|xml)$",
        re.IGNORECASE,
    ),
    re.compile(r"^[a-z0-9]+(_[a-z0-9]+)+$"),  # snake_case identifier
    re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)+$"),  # kebab-case identifier
    re.compile(r"^[#.\[]"),  # CSS/JS selector
    re.compile(r"[{}]"),  # template/code braces
    re.compile(r"(^|\s)(class|style|href|src|id|data-[a-z-]+)=", re.IGNORECASE),
    re.compile(r"(&&|\|\||=>|\?\.|\.includes\(|function\b|return\b)"),  # code, not prose
    re.compile(r"^\s*[+:=]|\+\s*$"),  # concatenation fragments
)


def _normal(text: str) -> str:
    return " ".join(html.unescape(text).split())


def _acceptable(text: str) -> bool:
    if not text or len(text) > 200:
        return False
    if not re.search(r"[A-Za-z]", text):
        return False
    if KEEP.match(text):
        return False
    for pattern in _SKIP_RE:
        if pattern.search(text):
            return False
    if " " not in text and _CAMEL_RE.search(text):
        return False
    # Mostly-uppercase constants ("API KEY", "S01E01") aren't prose; a normal sentence or label has lowercase.
    if text.isupper():
        return False
    if not re.search(r"[a-z]{2}", text):
        return False
    # HTML/JS fragments (a quote of markup, a template expression).
    if any(ch in text for ch in "<>=`\\") or "${" in text:
        return False
    # A literal cut out of a concatenation or a selector list, not a whole label.
    if text[0] in ",;:?)]}+-#.'\"" or text[-1] in "'\"+([{,$":
        return False
    # A fragment of a sentence (the rest of it lives in another JS string).
    if text.startswith(("and ", "or ", "with ", "to ", "the ", "a ", "an ")) and len(text.split()) <= 3:
        return False
    # CSS utility classes (`btn btn-sm`, `alert alert-danger`), but not lowercase prose.
    if not text.endswith((".", ":", "?", "!")):
        tokens = text.split()
        if all(re.fullmatch(r"[a-z0-9-]+", token) for token in tokens):
            if any("-" in token for token in tokens):
                return False
        if len(tokens) == 1 and re.fullmatch(r"[a-z][a-z0-9]+", text):
            return False
    return True


def from_templates() -> dict[str, set[str]]:
    found: dict[str, set[str]] = defaultdict(set)
    for path in sorted(TEMPLATES.glob("*.html")):
        raw = path.read_text(encoding="utf-8")
        raw = _COMMENT_RE.sub(" ", raw)
        raw = _BLOCK_RE.sub(" ", raw)
        raw = _INLINE_RE.sub(" \x00 ", raw)
        for match in _TEXT_RE.finditer(raw):
            chunk = match.group(1)
            if _JINJA_RE.search(chunk):
                continue
            for part in chunk.split("\x00"):
                text = _normal(part)
                if _acceptable(text):
                    found[text].add(path.name)
        for match in _ATTR_RE.finditer(raw):
            name = match.group(1).lower()
            text = _normal(match.group(2) if match.group(2) is not None else match.group(3))
            if name == "value" and not re.search(r"[A-Za-z]{2}", text):
                continue
            if _acceptable(text):
                found[text].add(f"{path.name}[{name}]")
    return found


def from_template_expressions() -> dict[str, set[str]]:
    """Prose passed to a Jinja macro or helper inside ``{{ ... }}`` (the nav menu's one-line purposes)."""
    found: dict[str, set[str]] = defaultdict(set)
    quoted = re.compile(r"""(['"])((?:\\.|(?!\1).){3,200}?)\1""")
    for path in sorted(TEMPLATES.glob("*.html")):
        raw = path.read_text(encoding="utf-8")
        for expression in _JINJA_EXPR_RE.finditer(raw):
            for match in quoted.finditer(expression.group(1)):
                text = _normal(match.group(2))
                if _acceptable(text):
                    found[text].add(f"{path.name}[expr]")
    return found


def from_scripts() -> dict[str, set[str]]:
    found: dict[str, set[str]] = defaultdict(set)
    for path in sorted(SCRIPTS.glob("*.js")):
        raw = path.read_text(encoding="utf-8")
        for match in _JS_STRING_RE.finditer(raw):
            literal = match.group(2)
            if "\\n" in literal or "\\t" in literal:
                continue
            text = _normal(literal)
            if _acceptable(text):
                found[text].add(path.name)
    return found


def from_scripts_html() -> dict[str, set[str]]:
    """Text between tags inside a JavaScript HTML string (``'<div>Nothing queued</div>'``)."""
    found: dict[str, set[str]] = defaultdict(set)
    between_tags = re.compile(r">([^<>]+)<")
    for path in sorted(SCRIPTS.glob("*.js")):
        raw = path.read_text(encoding="utf-8")
        for match in _JS_TEMPLATE_RE.finditer(raw):
            literal = match.group(1)
            if "<" not in literal:
                continue
            cleaned = _INTERPOLATION_RE.sub(" ", literal)
            for text_match in between_tags.finditer(cleaned):
                text = _normal(text_match.group(1))
                if _acceptable(text):
                    found[text].add(path.name)
        for match in _JS_STRING_RE.finditer(raw):
            literal = match.group(2)
            if "<" not in literal or ">" not in literal:
                continue
            for text_match in between_tags.finditer(literal):
                text = _normal(text_match.group(1))
                if _acceptable(text):
                    found[text].add(path.name)
    return found


def from_script_templates() -> dict[str, set[str]]:
    """Sentences built from a template literal, with each ``${...}`` turned into a ``{n}`` slot."""
    found: dict[str, set[str]] = defaultdict(set)
    for path in sorted(SCRIPTS.glob("*.js")):
        raw = path.read_text(encoding="utf-8")
        for match in _JS_TEMPLATE_RE.finditer(raw):
            literal = match.group(1)
            if "${" not in literal:
                continue
            counter = iter(range(100))
            with_slots = _INTERPOLATION_RE.sub(lambda _m, counter=counter: "{" + str(next(counter)) + "}", literal)
            text = _normal(with_slots)
            if "<" in text or ">" in text or "\\n" in text:
                continue
            if not re.search(r"[A-Za-z]{3}", text):
                continue
            if not re.search(r"\{[0-9]+\}", text):
                continue
            if len(text) > 200 or KEEP.match(text):
                continue
            if any(ch in text for ch in "=;`$"):
                continue
            # Selectors, URLs and utility-class fragments aren't sentences.
            if re.search(r"^(#|\.|/)", text) or "/api/" in text or "bi bi-" in text or "btn" in text:
                continue
            if "gpuEnable" in text or text.startswith(("mt-", "ms-")):
                continue
            # Every slot must still be a slot (a nested ${...} would have left braces or a ``?``).
            if len(re.findall(r"\{[0-9]+\}", text)) != text.count("{"):
                continue
            # Two prose words, not one class name around a slot.
            if len(re.findall(r"[A-Za-z]{3,}", text)) < 2:
                continue
            found[text].add(path.name)
    return found


def from_python() -> dict[str, set[str]]:
    """Messages the API puts in front of the user (not log lines), from their JSON/flash call sites."""
    found: dict[str, set[str]] = defaultdict(set)
    for path in sorted(PACKAGE.rglob("*.py")):
        if "node_modules" in path.parts:
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in _PY_MESSAGE_RE.finditer(raw):
            literal = match.group(2) if match.group(2) is not None else match.group(4)
            if not literal or "{" in literal or "}" in literal:
                continue
            text = _normal(literal)
            if _acceptable(text):
                found[text].add(path.name)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", help="print every candidate")
    args = parser.parse_args()

    found = from_templates()
    for text, where in from_scripts().items():
        found[text].update(where)
    for text, where in from_python().items():
        found[text].update(where)
    for text, where in from_template_expressions().items():
        found[text].update(where)
    for text, where in from_scripts_html().items():
        found[text].update(where)
    patterns = from_script_templates()
    for text in patterns:
        found.pop(text, None)

    rows = [
        {"key": text, "sources": sorted(where)}
        for text, where in sorted(found.items(), key=lambda item: item[0].lower())
    ] + [
        {"key": text, "sources": sorted(where), "pattern": True}
        for text, where in sorted(patterns.items(), key=lambda item: item[0].lower())
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(rows)} strings -> {OUT.relative_to(ROOT)}")
    if args.print:
        import sys

        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        for row in rows:
            print(row["key"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
