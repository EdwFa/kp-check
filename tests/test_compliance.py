from kp_tz_check.calculations import (
    calculate_market_statistics,
    calculate_nmck,
    calculate_offer_totals,
    check_spec_constraint,
    collect_market_prices,
    extract_declared_total,
)
from kp_tz_check.knowledge import get_concepts, load_bundle


def test_okf_bundle_contains_non_obvious_rules():
    concepts = load_bundle()
    assert "playbooks/qualifiers" in concepts
    assert "quotes/market-homogeneity" in concepts
    assert "quotes/market-variation" in concepts
    assert concepts["playbooks/qualifiers"].type == "Playbook"


def test_okf_lookup_is_explicit_not_semantic_search():
    concepts = get_concepts(tags=["instruction"])
    assert {item.concept_id for item in concepts} == {
        "quotes/instruction-concrete",
        "playbooks/qualifiers",
    }


def test_market_statistics_uses_population_cv_and_threshold():
    result = calculate_market_statistics([90, 100, 110])
    assert result["status"] == "homogeneous"
    assert result["mean"] == 100
    assert result["coefficient_of_variation"] == 8.16496580927726
    assert calculate_market_statistics([67, 100, 133])["status"] == "homogeneous"
    assert calculate_market_statistics([50, 100, 150])["status"] == "heterogeneous"


def test_market_statistics_rejects_invalid_data():
    result = calculate_market_statistics([])
    assert result["status"] == "insufficient_data"


def test_market_prices_require_explicit_price_fields_and_supplier_data():
    result = collect_market_prices(
        [
            {
                "source_file": "a.pdf",
                "supplier": "ООО А",
                "items": [
                    {
                        "name": "Товар",
                        "unit": "шт.",
                        "extra": {"price": "100,00", "price_kind": "price_unit", "vat": "10"},
                    }
                ],
            },
            {
                "source_file": "b.pdf",
                "supplier": "ООО Б",
                "items": [
                    {
                        "name": "Товар",
                        "unit": "шт.",
                        "extra": {"price": "120,00", "price_kind": "price_unit", "vat": "10"},
                    }
                ],
            },
            {
                "source_file": "c.pdf",
                "supplier": "ООО В",
                "items": [
                    {
                        "name": "Товар",
                        "unit": "шт.",
                        "extra": {"price": "80,00", "price_kind": "price_unit", "vat": "10"},
                    }
                ],
            },
        ]
    )
    assert result["status"] == "homogeneous"
    assert result["groups"]["Товар"]["values"] == [100.0, 120.0, 80.0]


def test_spec_constraint_checks_concrete_kp_value():
    assert check_spec_constraint("не менее 300 циклов", "300 циклов")["status"] == "pass"
    assert check_spec_constraint("не менее 300 циклов", "250 циклов")["status"] == "fail"
    assert check_spec_constraint("не более 16 часов", "18 часов")["status"] == "fail"


def test_offer_totals_include_line_formula_and_total():
    result = calculate_offer_totals(
        [
            {
                "supplier": "ООО А",
                "source_file": "a.pdf",
                "items": [
                    {
                        "name": "Товар",
                        "qty": "2",
                        "unit": "шт.",
                        "extra": {
                            "price": "100,00",
                            "price_kind": "price_unit",
                            "vat": "20%",
                        },
                    }
                ],
            }
        ]
    )
    assert result[0]["status"] == "ok"
    assert result[0]["total"] == 200
    assert result[0]["lines"][0]["formula"] == "2 × 100.00 = 200.00"


def test_offer_totals_validate_declared_total():
    assert extract_declared_total("Итого: 200,00 руб.")["value"] == 200
    result = calculate_offer_totals(
        [
            {
                "body": "Итого: 250,00 руб.",
                "items": [
                    {
                        "name": "Товар",
                        "qty": "2",
                        "unit": "шт.",
                        "extra": {"price": "100,00", "price_kind": "price_unit"},
                    }
                ],
            }
        ]
    )
    assert result[0]["arithmetic_status"] == "fail"
    assert result[0]["difference"] == -50


def test_nmck_uses_average_price_and_tz_quantity():
    result = calculate_nmck(
        [
            {
                "supplier": "ООО А",
                "source_file": "a.pdf",
                "items": [
                    {
                        "name": "Товар",
                        "unit": "шт.",
                        "extra": {
                            "price": "100",
                            "price_kind": "price_unit",
                            "vat": "20",
                        },
                    }
                ],
            },
            {
                "supplier": "ООО Б",
                "source_file": "b.pdf",
                "items": [
                    {
                        "name": "Товар",
                        "unit": "шт.",
                        "extra": {
                            "price": "120",
                            "price_kind": "price_unit",
                            "vat": "20",
                        },
                    }
                ],
            },
            {
                "supplier": "ООО В",
                "source_file": "c.pdf",
                "items": [
                    {
                        "name": "Товар",
                        "unit": "шт.",
                        "extra": {
                            "price": "80",
                            "price_kind": "price_unit",
                            "vat": "20",
                        },
                    }
                ],
            },
        ],
        [{"name": "Товар", "qty": "2"}],
    )
    assert result["rows"][0]["unit_nmck"] == 100
    assert result["rows"][0]["total_nmck"] == 200
