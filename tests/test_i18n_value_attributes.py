"""A control's ``value`` is never translated; its label still is.

Translating ``value`` broke two controls: the segmented control over a ``<select>`` (buttons compared "关闭"
against the option's own "off") and Clear jobs (checkboxes submitted "已完成", which the API rejects:
"unknown status(es): ['已完成']").
"""

from __future__ import annotations

import pytest

from media_preview_generator.web.server_i18n import translate_html


@pytest.mark.parametrize(
    "markup,kept",
    [
        ('<input type="checkbox" class="clear-status-cb" value="completed">', 'value="completed"'),
        ('<input type="checkbox" value="failed">', 'value="failed"'),
        ('<option value="off" selected>Off</option>', 'value="off"'),
        ('<option value="on">On</option>', 'value="on"'),
        ('<select id="jobAuditMode" data-seg-default="off"><option value="off">Off</option></select>', 'value="off"'),
    ],
)
def test_value_attributes_survive(markup, kept):
    assert kept in translate_html(markup, "zh-CN")


@pytest.mark.parametrize(
    "markup,translated",
    [
        ('<option value="off">Off</option>', "关闭"),
        ('<option value="on">On</option>', "开启"),
        ('<span title="Retry now">Retry now</span>', "立即重试"),
        ('<input placeholder="Add server">', "添加服务器"),
    ],
)
def test_labels_still_translate(markup, translated):
    assert translated in translate_html(markup, "zh-CN")


def test_the_data_seg_default_marker_survives():
    """The segmented control reads this attribute to decide which chip shows the 默认 badge."""
    out = translate_html('<select data-seg-default="off"><option value="off">Off</option></select>', "zh-CN")

    assert 'data-seg-default="off"' in out
