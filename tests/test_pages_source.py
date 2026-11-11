from pathlib import Path

from kp_tz_check.blocks import build_blocks
from kp_tz_check.models import build_conclusion
from kp_tz_check.report import render_html
from kp_tz_check.serde import to_jsonable

ROOT = Path(__file__).resolve().parents[1]
SIDE_PAGES = (
    "6_Поставщики.py",
    "7_Расчёты.py",
    "8_ОКПД2.py",
    "9_Календарь.py",
    "10_Обеспечение.py",
)


def _block_row(document: str, block_id: str) -> str:
    marker = f'data-block="{block_id}"'
    start = document.index(marker)
    return document[start : document.index("</tr>", start)]


def test_side_pages_do_not_reread_the_package():
    for name in SIDE_PAGES:
        source = (ROOT / "pages" / name).read_text(encoding="utf-8")
        assert "load_incoming" not in source
        assert "has_results" in source
    calendar = (ROOT / "pages" / "9_Календарь.py").read_text(encoding="utf-8")
    assert "build_timeline" in calendar


def test_page_status_matches_html_conclusion():
    conclusion = to_jsonable(build_conclusion(build_blocks({})))
    document = render_html([], conclusion=conclusion)
    assert len(conclusion["blocks"]) == 8
    for block in conclusion["blocks"]:
        row = _block_row(document, str(block["block_id"]))
        assert block["status"] in row
        assert block["title"] in row
