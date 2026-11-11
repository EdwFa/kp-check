"""Сводка восьми блоков проверки из уже посчитанного ядра.

Модуль не читает документы и не повышает статус. Нереализованная проверка
не получает «замечаний нет».
"""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any

from kp_tz_check.application_math import check_applications
from kp_tz_check.competition import build_competition_report
from kp_tz_check.npa import UNCHECKED as NPA_UNCHECKED
from kp_tz_check.npa import build_npa_report
from kp_tz_check.base_reconcile import BaselineStatus, reconcile_pack
from kp_tz_check.calculations import calculate_offer_totals
from kp_tz_check.nmck import JUSTIFICATION_NOTE, build_nmck_report
from kp_tz_check.models import (
    BLOCK_TITLES,
    BlockFinding,
    BlockId,
    BlockResult,
    BlockStatus,
    FinalStatus,
    FindingSeverity,
)
from kp_tz_check.okpd2 import check_catalog_codes, check_okpd2
from kp_tz_check.okpd2_catalog import CatalogConfigError, load_okpd2_catalog
from kp_tz_check.security import (
    check_security_requirements,
    classify_security_amounts,
    evaluate_security,
    extract_security_requirements,
)
from kp_tz_check.serde import to_jsonable

MISSING_SOURCE = "источник отсутствует"
SUCCESS_COMMENTS = {
    "Хронология дат соблюдена",
    "Позиции ТЗ соответствуют КП",
}
NMCK_JUSTIFICATION = JUSTIFICATION_NOTE
KP_ARITHMETIC = "Арифметика посчитана по КП; заявка не загружена."
OKPD_CATALOG = "Справочник СМП не подключён."
SECURITY_THRESHOLDS = "Пороги обеспечения 5 000 000, 2%, 5% и 5–30% ещё не применяются."
SECURITY_ABSENT = "Требования к обеспечению не найдены."
BASELINE_NOT_LOADED = "Базовые документы не загружены."
BASELINE_APPLICATION_MISSING = "Заявка не предоставлена."
BASELINE_DIVERGED = "Есть расхождения базовых документов."
BASELINE_CRITICAL = "Есть критичные расхождения КП с базовыми документами."
BASELINE_SOURCE = "сверка базовых документов"


def build_blocks(state: dict[str, Any] | None = None) -> list[BlockResult]:
    """Разложить результаты ядра по восьми блокам п. 4.2.4."""
    payload = state or {}
    results = _dicts(payload.get("results") or [])
    requests = _dicts(payload.get("requests") or [])
    kps = _dicts(payload.get("kps") or [])
    tzs = _dicts(payload.get("tzs") or [])
    applications = _dicts(payload.get("applications") or [])
    catalog, catalog_error = _catalog(payload)
    regime = payload["national_regime"] if "national_regime" in payload else None
    regime_explicit = "national_regime" in payload
    nmck_total = payload["nmck_total"] if "nmck_total" in payload else _nmck_total(
        kps,
        tzs,
        payload.get("baseline"),
        _dicts(payload.get("nmck") or []),
        _dicts(payload.get("security_documents") or []),
    )
    smp = payload["smp"] if "smp" in payload else _smp_flag(applications, tzs, catalog)
    return [
        _block_package(results),
        _block_baseline(payload.get("baseline"), requests, applications, tzs, kps),
        _block_competition(kps, tzs, regime, load_catalog=not regime_explicit),
        _block_nmck(kps, tzs, payload.get("baseline"), _dicts(payload.get("nmck") or []), _dicts(payload.get("security_documents") or [])),
        _block_arithmetic(kps, applications),
        _block_okpd2(requests, tzs, applications, catalog, catalog_error),
        _block_npa(tzs, applications, payload.get("npa_catalog"), load_catalog="npa_catalog" not in payload),
        _block_security(requests, tzs, nmck_total=nmck_total, smp=smp),
    ]


def _dicts(values: list[Any]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, dict):
            converted.append(value)
        elif is_dataclass(value) and not isinstance(value, type):
            converted.append(to_jsonable(value))
        else:
            raise TypeError(f"Ожидался словарь или запись, получено {type(value).__name__}")
    return converted


def _unchecked(block_id: BlockId, reason: str) -> BlockResult:
    return _result(
        block_id,
        BlockStatus.NOT_CHECKED,
        [_finding(block_id.value, reason, MISSING_SOURCE, FindingSeverity.NOTE)],
        reason,
    )


def _result(
    block_id: BlockId,
    status: BlockStatus,
    findings: list[BlockFinding],
    reason: str | None,
) -> BlockResult:
    return BlockResult(
        block_id,
        BLOCK_TITLES[block_id],
        status,
        findings=findings,
        reason=reason,
    )


def _finding(code: str, text: str, source: str | None, severity: FindingSeverity) -> BlockFinding:
    return BlockFinding(code, text, _present_source(source), severity)


def _present_source(value: Any) -> str:
    if value is None:
        return MISSING_SOURCE
    text = str(value).strip()
    if not text or text == "—":
        return MISSING_SOURCE
    return text


def _pair_source(pair: dict[str, Any]) -> str:
    for key in ("kp", "request", "tz"):
        record = pair.get(key) or {}
        if isinstance(record, dict) and record.get("source_file"):
            return _present_source(record.get("source_file"))
    return MISSING_SOURCE


def _block_package(results: list[dict[str, Any]]) -> BlockResult:
    if not results:
        return _unchecked(BlockId.PACKAGE, "Комплект запроса и КП не загружен.")
    findings: list[BlockFinding] = []
    worst = BlockStatus.CLEAN
    for pair in results:
        status = FinalStatus(pair.get("status"))
        source = _pair_source(pair)
        pair_findings: list[BlockFinding] = []
        for comment in pair.get("comments") or []:
            text = str(comment).strip()
            if not text or text in SUCCESS_COMMENTS:
                continue
            severity = FindingSeverity.CRITICAL if status == FinalStatus.MISMATCH else FindingSeverity.REMARK
            pair_findings.append(_finding("pair", text, source, severity))
        if status == FinalStatus.MISMATCH and not pair_findings:
            pair_findings.append(_finding("pair", "Есть критичное расхождение пары.", source, FindingSeverity.CRITICAL))
        if status == FinalStatus.MISMATCH:
            worst = BlockStatus.CRITICAL
        elif status == FinalStatus.NEEDS_REVIEW and worst != BlockStatus.CRITICAL:
            worst = BlockStatus.REMARKS
        elif pair_findings and worst == BlockStatus.CLEAN:
            worst = BlockStatus.REMARKS
        findings.extend(pair_findings)
    if worst == BlockStatus.CRITICAL:
        reason = "Есть критичные расхождения комплекта."
    elif worst == BlockStatus.REMARKS:
        reason = "Есть замечания по комплектности или хронологии."
    else:
        reason = None
    return _result(BlockId.PACKAGE, worst, _unique(findings), reason)


def _block_baseline(
    baseline: dict[str, Any] | None,
    requests: list[dict[str, Any]],
    applications: list[dict[str, Any]],
    tzs: list[dict[str, Any]],
    kps: list[dict[str, Any]],
) -> BlockResult:
    if baseline is None:
        if not (requests or applications or tzs):
            return _unchecked(BlockId.BASELINE, BASELINE_NOT_LOADED)
        baseline = to_jsonable(reconcile_pack(tzs, applications, requests, kps))
    rows = baseline.get("rows") or []
    findings: list[BlockFinding] = []
    for row in rows:
        status = str(row.get("status") or "")
        if status == BaselineStatus.AGREED:
            continue
        findings.append(
            _finding("2", _baseline_row_text(row), BASELINE_SOURCE, FindingSeverity.REMARK)
        )
    for item in baseline.get("critical_findings") or []:
        if not isinstance(item, dict):
            continue
        findings.append(
            _finding(
                str(item.get("code") or "2"),
                str(item.get("text") or ""),
                item.get("source") or BASELINE_SOURCE,
                FindingSeverity.CRITICAL,
            )
        )
    if not rows and not findings:
        return _unchecked(BlockId.BASELINE, BASELINE_NOT_LOADED)
    if any(item.severity == FindingSeverity.CRITICAL for item in findings):
        return _result(BlockId.BASELINE, BlockStatus.CRITICAL, _unique(findings), BASELINE_CRITICAL)
    if findings:
        reason = BASELINE_DIVERGED
        if any(BASELINE_APPLICATION_MISSING.rstrip(".") in item.text for item in findings) and not any(
            str(row.get("status") or "") == BaselineStatus.DIVERGED for row in rows
        ):
            reason = BASELINE_APPLICATION_MISSING
        return _result(BlockId.BASELINE, BlockStatus.REMARKS, _unique(findings), reason)
    return _result(BlockId.BASELINE, BlockStatus.CLEAN, [], None)


def _baseline_row_text(row: dict[str, Any]) -> str:
    parts = [str(row.get("status") or "—")]
    note = str(row.get("note") or "").strip()
    if note:
        parts.append(note)
    texts = []
    for source in row.get("sources") or []:
        if not isinstance(source, dict):
            continue
        texts.append(
            f"{source.get('document') or '—'}: "
            f"{source.get('name') or ''} | {source.get('specs') or ''} | "
            f"{source.get('unit') or ''} | {source.get('qty') or ''}"
        )
    if texts:
        parts.append("; ".join(texts))
    return ". ".join(parts)


def _block_competition(
    kps: list[dict[str, Any]],
    tzs: list[dict[str, Any]],
    catalog: list[dict[str, str]] | None,
    *,
    load_catalog: bool,
) -> BlockResult:
    report = build_competition_report(kps, tzs, catalog, load_catalog=load_catalog)
    if report["status"] == "not_checked":
        return _unchecked(BlockId.COMPETITION, report["findings"][0]["text"])
    findings = [
        _finding(item["code"], item["text"], item.get("source"), _severity(item.get("severity")))
        for item in report["findings"]
    ]
    if report["status"] == "critical":
        status = BlockStatus.CRITICAL
        reason = next(item.text for item in findings if item.severity == FindingSeverity.CRITICAL)
    elif report["status"] == "clean":
        status = BlockStatus.CLEAN
        reason = None
    else:
        status = BlockStatus.REMARKS
        reason = next((item.text for item in findings if item.severity == FindingSeverity.REMARK), None)
    return _result(BlockId.COMPETITION, status, _unique(findings), reason)


def _block_npa(
    tzs: list[dict[str, Any]],
    applications: list[dict[str, Any]],
    catalog: list[dict[str, str]] | None,
    *,
    load_catalog: bool,
) -> BlockResult:
    report = build_npa_report(tzs, applications, catalog, load_catalog=load_catalog)
    if not report["rows"]:
        return _unchecked(BlockId.NPA, "Упоминания НПА и стандартов не найдены.")
    findings = [
        _finding(
            "npa",
            f"{row['citation']}: {row['status']}. {row['method']}",
            row["source"],
            FindingSeverity.NOTE if row["status"].casefold() == "действует" else FindingSeverity.REMARK,
        )
        for row in report["rows"]
    ]
    if any(item.severity == FindingSeverity.REMARK for item in findings):
        return _result(BlockId.NPA, BlockStatus.REMARKS, findings, NPA_UNCHECKED)
    return _result(BlockId.NPA, BlockStatus.REMARKS, findings, "локальный перечень, не правовая база")


def _severity(value: str | None) -> FindingSeverity:
    if value == "критичная":
        return FindingSeverity.CRITICAL
    if value == "справка":
        return FindingSeverity.NOTE
    return FindingSeverity.REMARK


def _block_nmck(
    kps: list[dict[str, Any]],
    tzs: list[dict[str, Any]],
    baseline: dict[str, Any] | None,
    nmck_records: list[dict[str, Any]],
    security_documents: list[dict[str, Any]],
) -> BlockResult:
    tz_items = [item for tz in tzs for item in (tz.get("items") or [])]
    report = build_nmck_report(
        kps,
        tz_items=tz_items,
        nmck_records=nmck_records,
        baseline=baseline if isinstance(baseline, dict) else None,
        security_documents=security_documents,
    )
    findings = [
        _finding(item["code"], item["text"], item.get("source"), _severity(item.get("severity")))
        for item in report["findings"]
    ]
    if not kps and not nmck_records and not findings:
        return _unchecked(BlockId.NMCK, NMCK_JUSTIFICATION)
    if any(item.severity == FindingSeverity.CRITICAL for item in findings):
        status = BlockStatus.CRITICAL
    elif any(item.severity == FindingSeverity.REMARK for item in findings):
        status = BlockStatus.REMARKS
    else:
        status = BlockStatus.CLEAN
    if not report["justification_checked"]:
        reason = NMCK_JUSTIFICATION
    elif status == BlockStatus.CLEAN:
        reason = None
    else:
        reason = next((item.text for item in findings if item.severity == FindingSeverity.REMARK), None)
    return _result(BlockId.NMCK, status, _unique(findings), reason)


def _block_arithmetic(kps: list[dict[str, Any]], applications: list[dict[str, Any]]) -> BlockResult:
    findings: list[BlockFinding] = []
    if applications:
        checked = check_applications(applications)
        for item in checked["findings"]:
            findings.append(
                _finding(item["code"], item["text"], item.get("source"), _severity(item.get("severity")))
            )
        if any(item.severity == FindingSeverity.CRITICAL for item in findings):
            reason = "Содержательная ошибка арифметики заявки."
            worst = BlockStatus.CRITICAL
        elif findings:
            reason = "Арифметика заявки проверена, есть замечания."
            worst = BlockStatus.REMARKS
        else:
            reason = "Арифметика заявки проверена."
            worst = BlockStatus.CLEAN
    else:
        findings.append(_finding("application-missing", KP_ARITHMETIC, _first_source(kps), FindingSeverity.REMARK))
        reason = KP_ARITHMETIC
        worst = BlockStatus.REMARKS
    for report in calculate_offer_totals(kps):
        source = _present_source(report.get("source_file"))
        if report.get("arithmetic_status") == "fail":
            worst = BlockStatus.CRITICAL
            findings.append(
                _finding(
                    "kp-total",
                    report.get("arithmetic_reason") or "Итоговая сумма КП не совпадает с суммой строк.",
                    source,
                    FindingSeverity.CRITICAL,
                )
            )
        elif report.get("arithmetic_status") != "pass" and report.get("arithmetic_reason"):
            findings.append(_finding("kp-total", str(report["arithmetic_reason"]), source, FindingSeverity.REMARK))
        for line in report.get("lines") or []:
            if line.get("status") == "ok":
                continue
            findings.append(
                _finding(
                    "kp-line",
                    f"{line.get('position') or '—'}: {line.get('reason') or 'строка КП не посчитана'}.",
                    source,
                    FindingSeverity.REMARK,
                )
            )
    if applications and any(item.code.startswith("kp-") for item in findings):
        reason = f"{reason} Арифметика КП — отдельная секция."
    return _result(BlockId.ARITHMETIC, worst, _unique(findings), reason)


def _block_okpd2(
    requests: list[dict[str, Any]],
    tzs: list[dict[str, Any]],
    applications: list[dict[str, Any]],
    catalog: list[dict[str, str]] | None,
    catalog_error: str | None = None,
) -> BlockResult:
    if catalog_error:
        return _result(
            BlockId.OKPD2,
            BlockStatus.REMARKS,
            [_finding("okpd2-catalog", catalog_error, MISSING_SOURCE, FindingSeverity.REMARK)],
            catalog_error,
        )
    if catalog is None:
        if not requests and not tzs and not applications:
            return _unchecked(BlockId.OKPD2, f"{OKPD_CATALOG} Документы для сверки кодов не загружены.")
        findings = [_finding("okpd2-catalog", OKPD_CATALOG, MISSING_SOURCE, FindingSeverity.NOTE)]
        if requests:
            for item in check_okpd2(requests, tzs):
                findings.append(
                    _finding("okpd2", item["reason"], _present_source(item.get("request_file")), FindingSeverity.NOTE)
                )
        return _result(BlockId.OKPD2, BlockStatus.NOT_CHECKED, _unique(findings), OKPD_CATALOG)
    positions = _okpd_positions(applications, tzs)
    checked = check_catalog_codes(positions, catalog)
    findings = [
        _finding("okpd2", item["text"], item.get("source"), FindingSeverity.REMARK)
        for item in checked["findings"]
    ]
    findings.append(_finding("okpd2-summary", checked["summary"], MISSING_SOURCE, FindingSeverity.NOTE))
    if findings and any(item.severity == FindingSeverity.REMARK for item in findings):
        return _result(BlockId.OKPD2, BlockStatus.REMARKS, _unique(findings), checked["findings"][0]["text"] if checked["findings"] else checked["summary"])
    return _result(BlockId.OKPD2, BlockStatus.CLEAN, _unique(findings), None)


def _okpd_positions(applications: list[dict[str, Any]], tzs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    for record in applications + tzs:
        source = record.get("source_file")
        for item in record.get("items") or []:
            if (item.get("extra") or {}).get("okpd2"):
                positions.append({**item, "source": source})
    return positions


def _block_security(
    requests: list[dict[str, Any]],
    tzs: list[dict[str, Any]],
    *,
    nmck_total: float | None,
    smp: bool | None,
) -> BlockResult:
    checks = check_security_requirements(requests, tzs) if requests else []
    found = [item for item in checks if item.get("percentages") or item.get("amounts")]
    tz_text = "\n".join(str(item.get("body") or "") for item in tzs)
    request_text = "\n".join(str(item.get("body") or "") for item in requests)
    extracted = extract_security_requirements(f"{request_text}\n{tz_text}")
    if not found and not (extracted["percentages"] or extracted["amounts"]):
        return _unchecked(BlockId.SECURITY, SECURITY_ABSENT)
    classified = classify_security_amounts(f"{request_text}\n{tz_text}")
    rows = evaluate_security(nmck_total=nmck_total, smp=smp, **classified)
    findings = [
        _finding(
            "security",
            row["text"],
            _first_source(requests) if requests else _first_source(tzs),
            FindingSeverity.CRITICAL if row["status"] == "ОШИБКА" else FindingSeverity.REMARK,
        )
        for row in rows
        if row["status"] != "ОК"
    ]
    for row in rows:
        if row["status"] == "ОК":
            findings.append(
                _finding("security", row["text"], _first_source(requests) or _first_source(tzs), FindingSeverity.NOTE)
            )
    if any(item.severity == FindingSeverity.CRITICAL for item in findings):
        status = BlockStatus.CRITICAL
    elif any(item.severity == FindingSeverity.REMARK for item in findings):
        status = BlockStatus.REMARKS
    else:
        status = BlockStatus.CLEAN
    reason = next((row["text"] for row in rows if row["kind"] == "заявка"), rows[0]["text"])
    return _result(BlockId.SECURITY, status, _unique(findings), reason)


def _catalog(payload: dict[str, Any]) -> tuple[list[dict[str, str]] | None, str | None]:
    if "okpd2_catalog" in payload:
        return payload.get("okpd2_catalog"), None
    try:
        return load_okpd2_catalog(), None
    except CatalogConfigError as exc:
        return None, str(exc)


def _smp_flag(
    applications: list[dict[str, Any]],
    tzs: list[dict[str, Any]],
    catalog: list[dict[str, str]] | None,
) -> bool | None:
    if not catalog:
        return None
    return check_catalog_codes(_okpd_positions(applications, tzs), catalog)["smp"]


def _nmck_total(
    kps: list[dict[str, Any]],
    tzs: list[dict[str, Any]],
    baseline: dict[str, Any] | None,
    nmck_records: list[dict[str, Any]],
    security_documents: list[dict[str, Any]],
) -> float | None:
    tz_items = [item for tz in tzs for item in (tz.get("items") or [])]
    report = build_nmck_report(
        kps,
        tz_items=tz_items,
        nmck_records=nmck_records,
        baseline=baseline if isinstance(baseline, dict) else None,
        security_documents=security_documents,
    )
    totals = [row.get("total_nmck") for row in report.get("rows") or []]
    if not totals or any(value is None for value in totals):
        return None
    return float(sum(totals))


def _first_source(records: list[dict[str, Any]]) -> str:
    for record in records:
        if record.get("source_file"):
            return _present_source(record.get("source_file"))
    return MISSING_SOURCE


def _unique(findings: list[BlockFinding]) -> list[BlockFinding]:
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[BlockFinding] = []
    for finding in findings:
        key = (finding.code, finding.text, finding.source or "", finding.severity.value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique
