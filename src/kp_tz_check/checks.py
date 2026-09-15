from __future__ import annotations

import re

from kp_tz_check.match import choose_tz, match_items, pair_requests_and_kps, suppliers_conflict
from kp_tz_check.models import (
    DateCheckMark,
    FinalStatus,
    ItemMismatch,
    KpRecord,
    PairResult,
    ProductCheckMark,
    RequestRecord,
    TzRecord,
)

MIN_MARKET_KPS = 3
VALIDITY_RE = re.compile(r"срок действия[^\n]{0,80}?(\d+)\s*(день|дня|дней|месяц|месяца|месяцев)", re.I)


def audit(
    requests: list[RequestRecord],
    kps: list[KpRecord],
    tzs: list[TzRecord],
) -> list[PairResult]:
    pairs, unmatched_requests, unmatched_kps = pair_requests_and_kps(requests, kps)
    results: list[PairResult] = []

    for request, kp in pairs:
        results.append(_check_pair(request, kp, choose_tz(tzs, request), tzs_present=bool(tzs)))
    for request in unmatched_requests:
        results.append(_check_pair(request, None, choose_tz(tzs, request), tzs_present=bool(tzs)))
    for kp in unmatched_kps:
        results.append(_check_pair(None, kp, choose_tz(tzs, None), tzs_present=bool(tzs)))

    _apply_market_package_rule(results, kps)
    return results


def _apply_market_package_rule(results: list[PairResult], kps: list[KpRecord]) -> None:
    if len(kps) >= MIN_MARKET_KPS:
        return
    extra = (
        f"Положение о закупке (Приложение № 3 п. 8): для метода анализа рынка нужно "
        f"не менее {MIN_MARKET_KPS} цен разных поставщиков. Сейчас КП: {len(kps)}."
    )
    for item in results:
        item.comments.append(extra)
        if item.status == FinalStatus.MATCH:
            item.status = FinalStatus.NEEDS_REVIEW


def _check_pair(
    request: RequestRecord | None,
    kp: KpRecord | None,
    tz: TzRecord | None,
    tzs_present: bool,
) -> PairResult:
    comments: list[str] = []
    date_mark, date_comments, date_hard, date_unknown = _check_dates(request, kp)
    comments.extend(date_comments)

    product_mark, product_comments, product_hard, product_unknown, mismatches = _check_products(
        request, kp, tz, tzs_present
    )
    comments.extend(product_comments)

    if request and kp is None:
        comments.append("На отправленный запрос нет соответствующего КП")
        completeness_hard = True
    elif request is None and kp:
        comments.append("КП без исходного запроса")
        completeness_hard = True
    else:
        completeness_hard = False

    if request and kp and suppliers_conflict(request.supplier, kp.supplier):
        comments.append(
            f"Поставщик КП ({kp.supplier}) не совпадает с адресатом запроса ({request.supplier})"
        )
        completeness_hard = True

    comments.extend(_validity_comments(request, kp))

    if request:
        comments.extend(request.notes)
    if kp:
        comments.extend(kp.notes)
    if tz:
        comments.extend(tz.notes)

    comments = _unique(comments)

    if date_hard or product_hard or completeness_hard:
        status = FinalStatus.MISMATCH
    elif date_unknown or product_unknown or any("требует ручной проверки" in item.lower() for item in comments):
        status = FinalStatus.NEEDS_REVIEW
    else:
        status = FinalStatus.MATCH

    return PairResult(
        request=request,
        kp=kp,
        tz=tz,
        date_mark=date_mark,
        product_mark=product_mark,
        status=status,
        comments=comments,
        item_mismatches=mismatches,
    )


def _validity_comments(request: RequestRecord | None, kp: KpRecord | None) -> list[str]:
    if request is None or kp is None:
        return []
    found = VALIDITY_RE.findall(kp.body or "")
    if not found:
        return []
    days = []
    for number, unit in found:
        value = int(number)
        days.append(value * 30 if unit.lower().startswith("месяц") else value)
    unique_days = sorted(set(days))
    comments = []
    if len(unique_days) > 1:
        comments.append(
            f"В КП указаны разные сроки действия ({', '.join(str(item) for item in unique_days)} дн.), "
            "требует ручной проверки"
        )
    if unique_days and max(unique_days) < 90 and "3 месяц" in (request.body or "").lower():
        comments.append(
            f"Срок действия КП {max(unique_days)} дн. меньше требования запроса (не менее 3 месяцев)"
        )
    return comments


def _check_dates(
    request: RequestRecord | None, kp: KpRecord | None
) -> tuple[DateCheckMark, list[str], bool, bool]:
    comments: list[str] = []
    if request is None or kp is None:
        return DateCheckMark.UNKNOWN, ["Проверка дат невозможна без пары запрос—КП"], False, True

    sent, prep, reg = request.sent_on, kp.prepared_on, kp.registered_on
    unknown = False
    hard = False

    if sent is None:
        comments.append("Дата отправки запроса не прочитана, требует ручной проверки")
        unknown = True
    if prep is None:
        comments.append("Дата подготовки КП не указана или не прочитана, требует ручной проверки")
        unknown = True
    if reg is None:
        comments.append("Дата регистрации КП в названии файла не прочитана, требует ручной проверки")
        unknown = True

    if sent and prep and prep < sent:
        comments.append("КП подготовлено раньше отправки запроса — нарушение")
        hard = True
    if prep and reg and reg < prep:
        comments.append("Регистрация КП раньше даты подготовки — нарушение")
        hard = True
    if sent and reg and reg < sent:
        comments.append("Дата регистрации КП раньше даты отправки запроса — нарушение")
        hard = True

    if hard:
        return DateCheckMark.FAIL, comments, True, unknown
    if unknown:
        return DateCheckMark.UNKNOWN, comments, False, True
    comments.append("Хронология дат соблюдена")
    return DateCheckMark.OK, comments, False, False


def _check_products(
    request: RequestRecord | None,
    kp: KpRecord | None,
    tz: TzRecord | None,
    tzs_present: bool,
) -> tuple[ProductCheckMark, list[str], bool, bool, list[ItemMismatch]]:
    comments: list[str] = []
    if not tzs_present or tz is None:
        comments.append("Нет ТЗ, требует ручной проверки")
        return ProductCheckMark.UNKNOWN, comments, False, True, []
    if not tz.items:
        comments.append("В ТЗ не прочитаны позиции, требует ручной проверки")
        return ProductCheckMark.UNKNOWN, comments, False, True, []
    if kp is None:
        comments.append("Нет КП для сверки с ТЗ")
        return ProductCheckMark.FAIL, comments, True, False, []
    if not kp.items:
        comments.append("В КП не прочитаны товарные позиции, требует ручной проверки")
        return ProductCheckMark.UNKNOWN, comments, False, True, []

    mismatches = match_items(tz.items, kp.items)
    missing = [item for item in mismatches if item.kind == "missing"]
    extra = [item for item in mismatches if item.kind == "extra"]
    field_issues = [item for item in mismatches if item.kind not in {"missing", "extra"}]

    comments.extend(item.detail for item in mismatches)

    if missing or extra:
        return ProductCheckMark.FAIL, comments, True, False, mismatches
    if field_issues:
        return ProductCheckMark.PARTIAL, comments, False, True, mismatches
    comments.append("Позиции ТЗ соответствуют КП")
    return ProductCheckMark.OK, comments, False, False, mismatches


def summarize(results: list[PairResult]) -> dict[str, list[str] | int]:
    matched = sum(1 for item in results if item.status == FinalStatus.MATCH)
    diffs = []
    orphans_request = []
    orphans_kp = []
    for item in results:
        if item.request and item.kp is None:
            orphans_request.append(item.request_label)
        if item.kp and item.request is None:
            orphans_kp.append(item.kp.source_file.name)
        if item.status != FinalStatus.MATCH:
            diffs.extend(item.comments)
    return {
        "matched_pairs": matched,
        "total_rows": len(results),
        "differences": _unique(diffs),
        "requests_without_kp": orphans_request,
        "kps_without_request": orphans_kp,
    }


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result
