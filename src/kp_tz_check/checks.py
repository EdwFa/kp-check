from __future__ import annotations

import re
from pathlib import Path

from kp_tz_check.match import (
    PairLink,
    choose_tz,
    match_items,
    pair_requests_and_kps_detailed,
    suppliers_conflict,
)
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
    *,
    pair_links: list[PairLink] | None = None,
    nomenclature: list[dict] | None = None,
) -> list[PairResult]:
    if pair_links is None:
        pair_links, unmatched_requests, unmatched_kps = pair_requests_and_kps_detailed(requests, kps)
    else:
        unmatched_requests, unmatched_kps = _unmatched_from_links(requests, kps, pair_links)
    results: list[PairResult] = []
    nomen_map = _nomenclature_map(nomenclature)

    for link in pair_links:
        tz = choose_tz(tzs, link.request)
        mismatches = _lookup_mismatches(nomen_map, link.request, link.kp)
        results.append(
            _check_pair(
                link.request,
                link.kp,
                tz,
                tzs_present=bool(tzs),
                mismatches=mismatches,
            )
        )
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
    mismatches: list[ItemMismatch] | None = None,
) -> PairResult:
    comments: list[str] = []
    date_mark, date_comments, date_hard, date_unknown = _check_dates(request, kp)
    comments.extend(date_comments)

    product_mark, product_comments, product_hard, product_unknown, mismatches = _check_products(
        request, kp, tz, tzs_present, mismatches=mismatches
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
    mismatches: list[ItemMismatch] | None = None,
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

    if mismatches is None:
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


def _request_key(item: RequestRecord) -> tuple:
    return (str(item.source_file), item.outgoing_no)


def _kp_key(item: KpRecord) -> tuple:
    return (str(item.source_file), item.outgoing_no)


def _unmatched_from_links(
    requests: list[RequestRecord],
    kps: list[KpRecord],
    links: list[PairLink],
) -> tuple[list[RequestRecord], list[KpRecord]]:
    used_requests = {_request_key(item.request) for item in links}
    used_kps = {_kp_key(item.kp) for item in links}
    unmatched_requests = [item for item in requests if _request_key(item) not in used_requests]
    unmatched_kps = [item for item in kps if _kp_key(item) not in used_kps]
    return unmatched_requests, unmatched_kps


def _nomenclature_map(nomenclature: list[dict] | None) -> dict[tuple, dict]:
    mapping: dict[tuple, dict] = {}
    for row in nomenclature or []:
        outgoing = row.get("request_outgoing_no")
        kp_file = row.get("kp_file_name") or row.get("kp_file")
        if kp_file:
            mapping[(outgoing, str(kp_file))] = row
            mapping[(outgoing, Path(str(kp_file)).name)] = row
    return mapping


def _lookup_mismatches(
    nomen_map: dict[tuple, dict],
    request: RequestRecord | None,
    kp: KpRecord | None,
) -> list[ItemMismatch] | None:
    if not nomen_map or kp is None:
        return None
    outgoing = request.outgoing_no if request else None
    row = nomen_map.get((outgoing, str(kp.source_file))) or nomen_map.get((outgoing, kp.source_file.name))
    if row is None:
        return None
    from kp_tz_check.serde import from_jsonable

    return [from_jsonable(ItemMismatch, item) if isinstance(item, dict) else item for item in row.get("mismatches") or []]


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
