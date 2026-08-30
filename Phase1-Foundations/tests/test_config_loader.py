import pytest

from pulse.config.loader import (
    ConfigValidationError,
    get_environment,
    get_product,
    load_environments,
    load_products,
)

VALID_PRODUCTS_YAML = """
products:
  - name: Groww
    app_store_id: "123"
    play_store_package: "com.nextbillion.groww"
    doc_id: "doc-groww"
    doc_title: "Weekly Review Pulse — Groww"
    stakeholders:
      - product@example.com
  - name: Kuvera
    app_store_id: "456"
    play_store_package: "com.kuvera.app"
    doc_id: "doc-kuvera"
    doc_title: "Weekly Review Pulse — Kuvera"
    stakeholders:
      - product@example.com
"""

VALID_ENV_YAML = """
environments:
  dev:
    email_mode: draft
    ingestion_window_weeks: 8
    max_tokens_per_run: 200000
  production:
    email_mode: send
    ingestion_window_weeks: 12
    max_tokens_per_run: 300000
    max_cost_usd_per_run: 5.0
"""


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_load_valid_products(tmp_path):
    path = _write(tmp_path, "products.yaml", VALID_PRODUCTS_YAML)
    products = load_products(path)
    assert set(products) == {"Groww", "Kuvera"}
    assert products["Groww"].play_store_package == "com.nextbillion.groww"
    assert products["Groww"].stakeholders == ("product@example.com",)


def test_missing_required_field_rejected(tmp_path):
    bad = VALID_PRODUCTS_YAML.replace('    doc_id: "doc-groww"\n', "")
    path = _write(tmp_path, "products.yaml", bad)
    with pytest.raises(ConfigValidationError, match="doc_id"):
        load_products(path)


def test_duplicate_product_name_rejected(tmp_path):
    dup = (
        VALID_PRODUCTS_YAML
        + """  - name: Groww
    app_store_id: "999"
    play_store_package: "com.dup"
    doc_id: "doc-dup"
    doc_title: "dup"
    stakeholders:
      - a@example.com
"""
    )
    path = _write(tmp_path, "products.yaml", dup)
    with pytest.raises(ConfigValidationError, match="duplicate"):
        load_products(path)


def test_empty_stakeholders_rejected(tmp_path):
    bad_yaml = """
products:
  - name: Groww
    app_store_id: "123"
    play_store_package: "com.nextbillion.groww"
    doc_id: "doc-groww"
    doc_title: "Weekly Review Pulse — Groww"
    stakeholders: []
"""
    path = _write(tmp_path, "products.yaml", bad_yaml)
    with pytest.raises(ConfigValidationError, match="stakeholder"):
        load_products(path)


def test_get_product_unknown_lists_available(tmp_path):
    path = _write(tmp_path, "products.yaml", VALID_PRODUCTS_YAML)
    products = load_products(path)
    with pytest.raises(ConfigValidationError, match="Groww"):
        get_product(products, "NotAProduct")


def test_load_valid_environments_applies_default_cost_ceiling(tmp_path):
    path = _write(tmp_path, "environments.yaml", VALID_ENV_YAML)
    envs = load_environments(path)
    assert envs["dev"].max_cost_usd_per_run == pytest.approx(2.0)  # documented default
    assert envs["production"].max_cost_usd_per_run == pytest.approx(5.0)


def test_invalid_email_mode_rejected(tmp_path):
    bad = VALID_ENV_YAML.replace("email_mode: send", "email_mode: bogus")
    path = _write(tmp_path, "environments.yaml", bad)
    with pytest.raises(ConfigValidationError, match="email_mode"):
        load_environments(path)


def test_get_environment_unknown(tmp_path):
    path = _write(tmp_path, "environments.yaml", VALID_ENV_YAML)
    envs = load_environments(path)
    with pytest.raises(ConfigValidationError, match="dev"):
        get_environment(envs, "nonexistent")


def test_real_products_yaml_loads(tmp_path):
    """The shipped pulse/config/products.yaml (placeholders included) must
    itself be valid — this is what Phase 1's exit criteria checks."""
    from pathlib import Path

    real_path = Path(__file__).resolve().parents[1] / "pulse" / "config" / "products.yaml"
    products = load_products(real_path)
    assert set(products) == {
        "INDMoney",
        "Groww",
        "PowerUp Money",
        "Wealth Monitor",
        "Kuvera",
    }
