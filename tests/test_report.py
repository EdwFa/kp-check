from kp_tz_check.blocks import build_blocks
from kp_tz_check.models import build_conclusion
from kp_tz_check.report import render_html
from kp_tz_check.serde import to_jsonable


def _block_row(document: str, block_id: str) -> str:
    marker = f'data-block="{block_id}"'
    start = document.index(marker)
    return document[start : document.index("</tr>", start)]


def test_missing_conclusion_does_not_look_clean():
    document = render_html([])
    assert "Сводка не построена." in document
    assert "Проверен, замечаний нет" not in document
    assert "data-block=" not in document


def test_conclusion_lists_eight_blocks_and_keeps_block_seven_unchecked():
    conclusion = to_jsonable(build_conclusion(build_blocks({})))
    document = render_html([], conclusion=conclusion)
    assert document.index("Сводное заключение") < document.index("Запрос (дата отправки)")
    for block_id in "12345678":
        assert f'data-block="{block_id}"' in document
    block_seven = _block_row(document, "7")
    assert "Не проверен — документы не предоставлены" in block_seven
    assert "замечаний нет" not in block_seven
    assert "Заключение не подтверждено оператором." in document
    assert "Доказательства compliance" not in document
