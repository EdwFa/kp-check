from pathlib import Path

import pytest

from kp_tz_check.okpd2_catalog import CatalogConfigError, load_okpd2_catalog, row_is_smp


def test_catalog_rejects_missing_column(tmp_path: Path):
    path = tmp_path / "bad.csv"
    path.write_text("code,name\n1,Тест\n", encoding="utf-8")
    with pytest.raises(CatalogConfigError):
        load_okpd2_catalog(path)


def test_smp_is_true_only_for_yes(tmp_path: Path):
    path = tmp_path / "okpd.csv"
    path.write_text(
        "code,official_name,smp\n32.50.13.190,Набор,yes\n21.20.10.110,Реагент,no\n",
        encoding="utf-8",
    )
    rows = load_okpd2_catalog(path)
    assert rows is not None
    assert row_is_smp(rows[0]) is True
    assert row_is_smp(rows[1]) is False


def test_missing_env_does_not_load_catalog(monkeypatch):
    monkeypatch.delenv("KP_OKPD2_CATALOG", raising=False)
    assert load_okpd2_catalog() is None
