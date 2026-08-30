"""Loads and validates config/products.yaml and config/environments.yaml.

Architecture.md §3: "Config | config/products.yaml | Per-product: App Store
id, Play Store package, target Doc id/title, stakeholder distribution list".
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_MAX_COST_USD_PER_RUN = 2.00
_VALID_EMAIL_MODES = ("draft", "send")
_REQUIRED_PRODUCT_FIELDS = (
    "name",
    "app_store_id",
    "play_store_package",
    "doc_id",
    "doc_title",
    "stakeholders",
)
_REQUIRED_ENV_FIELDS = (
    "email_mode",
    "ingestion_window_weeks",
    "max_tokens_per_run",
)


class ConfigValidationError(ValueError):
    """Raised when products.yaml / environments.yaml fails validation."""


@dataclass(frozen=True)
class ProductConfig:
    name: str
    app_store_id: str
    play_store_package: str
    doc_id: str
    doc_title: str
    stakeholders: tuple[str, ...]


@dataclass(frozen=True)
class EnvironmentConfig:
    name: str
    email_mode: str  # "draft" | "send"
    ingestion_window_weeks: int
    max_tokens_per_run: int
    max_cost_usd_per_run: float


def _load_yaml(path: Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_products(path: Path) -> dict[str, ProductConfig]:
    data = _load_yaml(path) or {}
    raw_products = data.get("products")
    if not isinstance(raw_products, list) or not raw_products:
        raise ConfigValidationError(f"{path}: 'products' must be a non-empty list")

    products: dict[str, ProductConfig] = {}
    for i, raw in enumerate(raw_products):
        if not isinstance(raw, dict):
            raise ConfigValidationError(f"{path}: products[{i}] must be a mapping")

        missing = [
            field
            for field in _REQUIRED_PRODUCT_FIELDS
            if raw.get(field) in (None, "", [])
        ]
        if missing:
            label = raw.get("name", f"index {i}")
            raise ConfigValidationError(
                f"{path}: product '{label}' is missing required field(s): "
                f"{', '.join(missing)}"
            )

        name = str(raw["name"])
        if name in products:
            raise ConfigValidationError(f"{path}: duplicate product name '{name}'")

        stakeholders = raw["stakeholders"]
        if not isinstance(stakeholders, list) or not stakeholders:
            raise ConfigValidationError(
                f"{path}: product '{name}' must have at least one stakeholder"
            )

        products[name] = ProductConfig(
            name=name,
            app_store_id=str(raw["app_store_id"]),
            play_store_package=str(raw["play_store_package"]),
            doc_id=str(raw["doc_id"]),
            doc_title=str(raw["doc_title"]),
            stakeholders=tuple(str(s) for s in stakeholders),
        )
    return products


def load_environments(path: Path) -> dict[str, EnvironmentConfig]:
    data = _load_yaml(path) or {}
    raw_envs = data.get("environments")
    if not isinstance(raw_envs, dict) or not raw_envs:
        raise ConfigValidationError(f"{path}: 'environments' must be a non-empty mapping")

    environments: dict[str, EnvironmentConfig] = {}
    for name, raw in raw_envs.items():
        if not isinstance(raw, dict):
            raise ConfigValidationError(f"{path}: environment '{name}' must be a mapping")

        missing = [field for field in _REQUIRED_ENV_FIELDS if field not in raw]
        if missing:
            raise ConfigValidationError(
                f"{path}: environment '{name}' is missing required field(s): "
                f"{', '.join(missing)}"
            )

        email_mode = str(raw["email_mode"])
        if email_mode not in _VALID_EMAIL_MODES:
            raise ConfigValidationError(
                f"{path}: environment '{name}' has invalid email_mode "
                f"'{email_mode}' (must be one of {_VALID_EMAIL_MODES})"
            )

        environments[name] = EnvironmentConfig(
            name=name,
            email_mode=email_mode,
            ingestion_window_weeks=int(raw["ingestion_window_weeks"]),
            max_tokens_per_run=int(raw["max_tokens_per_run"]),
            max_cost_usd_per_run=float(
                raw.get("max_cost_usd_per_run", _DEFAULT_MAX_COST_USD_PER_RUN)
            ),
        )
    return environments


def get_product(products: dict[str, ProductConfig], name: str) -> ProductConfig:
    try:
        return products[name]
    except KeyError:
        available = ", ".join(sorted(products)) or "(none configured)"
        raise ConfigValidationError(
            f"Unknown product '{name}'. Configured products: {available}"
        ) from None


def get_environment(environments: dict[str, EnvironmentConfig], name: str) -> EnvironmentConfig:
    try:
        return environments[name]
    except KeyError:
        available = ", ".join(sorted(environments)) or "(none configured)"
        raise ConfigValidationError(
            f"Unknown environment '{name}'. Configured environments: {available}"
        ) from None
