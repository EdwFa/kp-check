from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from kp_tz_check.checks import audit
from kp_tz_check.parse import load_incoming
from kp_tz_check.report import render_text, write_html_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Сверка комплекта документов запрос → КП → ТЗ",
    )
    parser.add_argument(
        "--incoming",
        type=Path,
        default=ROOT / "incoming",
        help="Папка с requests/, kp/, tz/",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "reports" / "report.html",
        help="HTML-отчёт",
    )
    args = parser.parse_args(argv)

    requests, kps, tzs = load_incoming(args.incoming)
    results = audit(requests, kps, tzs)
    path = write_html_report(results, args.out)
    print(render_text(results))
    print(f"\nHTML-отчёт: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
