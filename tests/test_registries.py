import pytest

from kp_tz_check.price_fairness import DUMPING, HIGH, JUSTIFIED, assess_prices
from kp_tz_check.registries import RegistryConfigError, build_registry
from kp_tz_check.supplier_checks import check_suppliers


def test_default_flags_do_not_call_the_network(monkeypatch):
    for name in ("KP_REGISTRY_EGRUL", "KP_REGISTRY_RNP", "KP_REGISTRY_ECG", "KP_REGISTRY_MARKET"):
        monkeypatch.delenv(name, raising=False)
    calls = []

    class Client:
        def get(self, kind, key):
            calls.append((kind, key))
            return {}

    registry = build_registry(Client())
    found = registry.lookup("egrul", "7701234567")
    assert calls == []
    assert found["status"] == "not_checked"
    assert found["source_url"] is None


def test_other_registry_without_client_is_a_config_error(monkeypatch):
    monkeypatch.delenv("KP_REGISTRY_EGRUL", raising=False)
    monkeypatch.setenv("KP_REGISTRY_RNP", "1")
    with pytest.raises(RegistryConfigError):
        build_registry()


def test_complete_requisites_are_not_called_legitimate():
    result = check_suppliers(
        [
            {
                "request": {"supplier": "ООО Поставщик"},
                "kp": {"supplier": "ООО Поставщик", "source_file": "offer.pdf"},
            }
        ],
        kps=[{"source_file": "offer.pdf", "body": "ИНН 7701234567 КПП 770101001 ОГРН 1027700132195"}],
    )[0]
    assert result["status"] == "PASS"
    assert result["card"] == "Проверка реестров не выполнялась"
    assert result["card"] != "Все поставщики легитимны"
    assert len(result["criteria"]) == 11
    assert all(row["source"] == "" for row in result["criteria"])
    assert all("ФНС" not in row["source"] for row in result["criteria"])


def test_name_conflict_is_a_risk_without_registries():
    result = check_suppliers(
        [
            {
                "request": {"supplier": "ООО Заказчик"},
                "kp": {"supplier": "ООО Другой поставщик", "source_file": "offer.pdf"},
            }
        ],
        kps=[{"source_file": "offer.pdf", "body": "ИНН 7701234567 КПП 770101001 ОГРН 1027700132195"}],
    )[0]
    assert result["card"] == "Выявлены риски"


def test_russian_money_text_is_a_price():
    report = assess_prices(
        [{"supplier": "А", "position": "Набор", "price": "223 300,00", "nmck": "300 000,00"}],
        cv_passed=True,
        market_price=None,
    )
    assert report["rows"][0]["price"] == 223300.0
    assert report["rows"][0]["nmck"] == 300000.0


def test_price_boundaries_and_missing_market():
    dumping = assess_prices([{"supplier": "А", "position": "Набор", "price": 75, "nmck": 100}], cv_passed=True, market_price=None)
    high = assess_prices([{"supplier": "А", "position": "Набор", "price": 120, "nmck": 100}], cv_passed=True, market_price=None)
    inside = assess_prices([{"supplier": "А", "position": "Набор", "price": 90, "nmck": 100}], cv_passed=True, market_price=None)
    assert DUMPING in dumping["rows"][0]["notes"]
    assert HIGH in high["rows"][0]["notes"]
    assert inside["rows"][0]["notes"] == []
    assert inside["rows"][0]["market_status"] == "не проверена"
    assert inside["verdict"] != JUSTIFIED


def test_outlier_beyond_two_sigma_is_an_anomaly():
    rows = [{"supplier": "А", "position": "Набор", "price": price, "nmck": 10} for price in (10, 10, 10, 10, 10, 100)]
    report = assess_prices(rows, cv_passed=False, market_price=None)
    assert "Аномалия" in report["rows"][-1]["notes"]
    assert report["verdict"] != JUSTIFIED


def test_justified_requires_market_price_and_passed_cv():
    report = assess_prices(
        [{"supplier": "А", "position": "Набор", "price": 100, "nmck": 100}],
        cv_passed=True,
        market_price=100,
    )
    assert report["verdict"] == JUSTIFIED
