"""Translate a rendered page before it is sent, so Chinese shows on the first paint.

The UI is written in English and the catalogue is keyed by that English text
(:mod:`web.i18n`). Translating in the browser after ``DOMContentLoaded`` leaves
one frame of English on every navigation, so the page is translated here, on the
server, after the template has rendered: text nodes and the user-facing
attributes are replaced with the catalogue's Chinese. The browser-side script
(``static/js/i18n.js``) stays as the second pass, for text the app writes later.

Everything inside ``script``/``style``/``pre``/``code``/``textarea`` is left
alone: it is markup, a log line or an example, not a label.
"""

from __future__ import annotations

import html as html_module
import json
import re
from functools import lru_cache
from pathlib import Path

from loguru import logger

#: The cookie the language toggle writes; a request without it gets the default.
LANG_COOKIE = "mpg_lang"
DEFAULT_LANG = "zh-CN"
SUPPORTED_LANGS = ("zh-CN", "en")

#: Elements whose content is code or an example, never a label.
_RAW_TAGS = frozenset({"script", "style", "pre", "code", "textarea", "kbd", "samp"})
_TAG_RE = re.compile(r"(<[^>]*>)")
#: ``value`` is deliberately absent: it is the value the app compares, submits and stores, never a label shown on
#: screen. Translating it broke two controls — the segmented control over a ``<select>`` (its buttons compared "关闭"
#: against the option's own "off"), and Clear jobs, whose checkboxes submitted "已完成" to an API that only accepts
#: "completed" ("unknown status(es): ['已完成', ...]"). A control's visible words live in its text, not in ``value``.
_ATTR_RE = re.compile(
    r"""\b(title|placeholder|aria-label|alt|data-bs-title|data-bs-original-title)\s*=\s*"([^"]*)\"""",
    re.IGNORECASE,
)
_TAG_NAME_RE = re.compile(r"<\s*/?\s*([A-Za-z][A-Za-z0-9-]*)")
_SLOT_RE = re.compile(r"\{(\d+)\}")

#: The catalogue the server translates pages with (generated from ``i18n/zh-CN.json``).
_CATALOGUE_PATH = Path(__file__).with_name("i18n") / "zh-CN.json"


@lru_cache(maxsize=4)
def catalogue(lang: str) -> tuple[dict[str, str], tuple[tuple[re.Pattern[str], str, int], ...]]:
    """The ``(strings, patterns)`` for ``lang``; empty when there is no catalogue."""
    if lang == "en":
        return {}, ()
    if lang != DEFAULT_LANG or not _CATALOGUE_PATH.exists():
        if not _CATALOGUE_PATH.exists():
            logger.debug("No UI catalogue at {}; pages stay in English", _CATALOGUE_PATH)
        return {}, ()
    try:
        raw = json.loads(_CATALOGUE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Could not read the UI catalogue: {}", exc)
        return {}, ()
    strings = {str(key): str(value) for key, value in (raw.get("strings") or {}).items()}
    compiled: list[tuple[re.Pattern[str], str, int]] = []
    for source, target in raw.get("patterns") or []:
        slots = 0
        pieces: list[str] = []
        cursor = 0
        for match in _SLOT_RE.finditer(source):
            pieces.append(re.escape(source[cursor : match.start()]))
            # ``.*?``, not ``.+?``: a slot can legitimately be empty (the "on nodes" part of the capacity line), and an
            # empty slot made the whole sentence fall through to English.
            pieces.append(r"(.*?)")
            slots = max(slots, int(match.group(1)) + 1)
            cursor = match.end()
        pieces.append(re.escape(source[cursor:]))
        try:
            compiled.append((re.compile("^" + "".join(pieces) + "$"), target, slots))  # slots kept for the doc
        except re.error:  # pragma: no cover - a hand-edited catalogue
            continue
    return strings, tuple(compiled)


def _normalize(text: str) -> str:
    return " ".join(text.split())


def translate(text: str, lang: str) -> str | None:
    """The Chinese for ``text``, or None when it isn't a known label.

    Args:
        text: A text node's or attribute's value, with its surrounding spaces.
        lang: The language to translate into.

    Returns:
        The translated string keeping the original leading and trailing spaces, or None.
    """
    strings, patterns = catalogue(lang)
    if not strings and not patterns:
        return None
    if not text or not re.search(r"[A-Za-z]", text):
        return None
    stripped = text.strip()
    if not stripped:
        return None
    key = _normalize(stripped)
    hit = strings.get(key)
    if hit is None:
        for regex, target, _slots in patterns:  # noqa: B007 - the slot count is not needed to substitute
            match = regex.match(key)
            if not match:
                continue
            hit = target
            for index, group in enumerate(match.groups()):
                value = group or ""
                hit = hit.replace("{" + str(index) + "}", strings.get(_normalize(value), value))
            break
    if hit is None or hit == stripped:
        return None
    lead = text[: len(text) - len(text.lstrip())]
    tail = text[len(text.rstrip()) :]
    return lead + hit + tail


def translate_html(document: str, lang: str) -> str:
    """Translate the text nodes and user-facing attributes of a rendered page.

    Args:
        document: The HTML as the template rendered it.
        lang: The language to translate into.

    Returns:
        The page, with the strings the catalogue knows replaced. Anything else is untouched.
    """
    strings, patterns = catalogue(lang)
    if (not strings and not patterns) or not document:
        return document

    out: list[str] = []
    # Raw-text elements are copied up to their closing tag without being read.
    raw_end: re.Pattern[str] | None = None
    for token in _TAG_RE.split(document):
        if not token:
            continue
        if not token.startswith("<"):
            if raw_end is not None:
                out.append(token)
                continue
            out.append(_translate_text(token, lang))
            continue
        name_match = _TAG_NAME_RE.match(token)
        name = (name_match.group(1) if name_match else "").lower()
        closing = token.startswith("</")
        if raw_end is not None:
            out.append(token)
            if closing and raw_end.match(name):
                raw_end = None
            continue
        if not closing and name in _RAW_TAGS and not token.rstrip().endswith("/>"):
            raw_end = re.compile(r"^" + re.escape(name) + "$")
        out.append(_translate_attributes(token, lang))
    return "".join(out)


def _translate_text(text: str, lang: str) -> str:
    """A text node, translated whole; a node holding only whitespace is returned as it is.

    Text nodes can contain HTML entities (``you&#39;re``, ``Intro &amp; Credits``). Unescape them before looking the
    label up, and escape the answer back so the document stays valid — otherwise any label with an apostrophe or an
    ampersand stayed English and the browser-side translator had to fix it after paint (a visible flash).
    """
    if not text.strip():
        return text
    lead = text[: len(text) - len(text.lstrip())]
    tail = text[len(text.rstrip()) :]
    plain = html_module.unescape(text.strip())
    translated = translate(plain, lang)
    if translated is None:
        return text
    return lead + html_module.escape(translated, quote=False) + tail


def _translate_attributes(tag: str, lang: str) -> str:
    """The ``title``/``placeholder``/``aria-label``/``alt`` of one tag, translated in place.

    ``value`` is not in the list: it is what the app compares, submits and stores, so it stays exactly as the
    template wrote it. A checkbox's visible words are its surrounding text, not its value.
    """

    def replace(match: re.Match[str]) -> str:
        name, value = match.group(1), match.group(2)
        translated = translate(html_module.unescape(value), lang)
        if translated is None:
            return match.group(0)
        return f'{name}="{html_module.escape(translated, quote=True)}"'

    return _ATTR_RE.sub(replace, tag)
