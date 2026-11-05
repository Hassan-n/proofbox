"""Deterministic municipal water tariff engine for Bill Lens.

All money and consumption values use Decimal. Rounding follows the policy in the
tariff file: each charge line is rounded to cents, the subtotal is the sum of the
rounded lines, and VAT is rounded on that subtotal.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

TARIFF_PATH_ENV = "PROOFBOX_TARIFF_PATH"
SUPPORTED_ROUNDING_MODES = {"ROUND_HALF_UP": ROUND_HALF_UP}


@dataclass(frozen=True)
class WaterTier:
    from_kl: Decimal
    to_kl: Decimal | None
    rate_per_kl: Decimal


@dataclass(frozen=True)
class FixedCharge:
    code: str
    description: str
    amount: Decimal


@dataclass(frozen=True)
class Tariff:
    tariff_id: str
    version: int
    currency: str
    water_tiers: tuple[WaterTier, ...]
    fixed_charges: tuple[FixedCharge, ...]
    vat_rate: Decimal
    rounding_mode: str
    rounding_quantum: Decimal

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Tariff:
        try:
            tiers = tuple(
                WaterTier(
                    from_kl=_decimal(tier["from_kl"], "from_kl"),
                    to_kl=None if tier["to_kl"] is None else _decimal(tier["to_kl"], "to_kl"),
                    rate_per_kl=_decimal(tier["rate_per_kl"], "rate_per_kl"),
                )
                for tier in data["water_tiers"]
            )
            fixed = tuple(
                FixedCharge(
                    code=str(charge["code"]),
                    description=str(charge["description"]),
                    amount=_decimal(charge["amount"], "fixed charge amount"),
                )
                for charge in data["fixed_charges"]
            )
            tariff = cls(
                tariff_id=str(data["tariff_id"]),
                version=int(data["version"]),
                currency=str(data["currency"]),
                water_tiers=tiers,
                fixed_charges=fixed,
                vat_rate=_decimal(data["vat_rate"], "vat_rate"),
                rounding_mode=str(data["rounding"]["mode"]),
                rounding_quantum=_decimal(data["rounding"]["quantum"], "rounding quantum"),
            )
        except KeyError as exc:
            raise ValueError(f"Tariff is missing required field: {exc.args[0]}") from exc
        tariff.validate()
        return tariff

    def validate(self) -> None:
        if not self.water_tiers:
            raise ValueError("Tariff must define at least one water tier")
        expected_start = Decimal("0")
        for index, tier in enumerate(self.water_tiers):
            if tier.from_kl != expected_start:
                raise ValueError("Water tiers must start at 0 and be contiguous")
            if tier.rate_per_kl < 0:
                raise ValueError("Water tier rates cannot be negative")
            is_last = index == len(self.water_tiers) - 1
            if tier.to_kl is None:
                if not is_last:
                    raise ValueError("Only the last water tier may be open-ended")
            else:
                if tier.to_kl <= tier.from_kl:
                    raise ValueError("Each water tier must end after it starts")
                if is_last:
                    raise ValueError("The last water tier must be open-ended")
                expected_start = tier.to_kl
        for charge in self.fixed_charges:
            if charge.amount < 0:
                raise ValueError("Fixed charges cannot be negative")
        if self.vat_rate < 0:
            raise ValueError("VAT rate cannot be negative")
        if self.rounding_mode not in SUPPORTED_ROUNDING_MODES:
            raise ValueError(f"Unsupported rounding mode: {self.rounding_mode}")
        if self.rounding_quantum <= 0:
            raise ValueError("Rounding quantum must be positive")

    def money(self, value: Decimal) -> Decimal:
        return value.quantize(self.rounding_quantum, rounding=SUPPORTED_ROUNDING_MODES[self.rounding_mode])


@dataclass(frozen=True)
class ChargeLine:
    code: str
    description: str
    amount: Decimal
    quantity_kl: Decimal | None = None
    rate_per_kl: Decimal | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "description": self.description,
            "quantity_kl": _string_or_none(self.quantity_kl),
            "rate_per_kl": _string_or_none(self.rate_per_kl),
            "amount": str(self.amount),
        }


@dataclass(frozen=True)
class BillCalculation:
    tariff_id: str
    tariff_version: int
    currency: str
    consumption_kl: Decimal
    water_lines: tuple[ChargeLine, ...]
    fixed_lines: tuple[ChargeLine, ...]
    subtotal: Decimal
    vat_rate: Decimal
    vat: Decimal
    total: Decimal

    @property
    def water_total(self) -> Decimal:
        return sum((line.amount for line in self.water_lines), Decimal("0"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "tariff_id": self.tariff_id,
            "tariff_version": self.tariff_version,
            "currency": self.currency,
            "consumption_kl": str(self.consumption_kl),
            "water_lines": [line.to_dict() for line in self.water_lines],
            "fixed_lines": [line.to_dict() for line in self.fixed_lines],
            "water_total": str(self.water_total),
            "subtotal": str(self.subtotal),
            "vat_rate": str(self.vat_rate),
            "vat": str(self.vat),
            "total": str(self.total),
        }


def default_tariff_path() -> Path:
    configured = os.getenv(TARIFF_PATH_ENV)
    if configured:
        return Path(configured)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "tariffs" / "tariff_v1.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"tariff_v1.json not found; set {TARIFF_PATH_ENV}")


def load_tariff(path: str | Path | None = None) -> Tariff:
    with Path(path or default_tariff_path()).open(encoding="utf-8") as tariff_file:
        return Tariff.from_dict(json.load(tariff_file, parse_float=Decimal))


def calculate_bill(consumption_kl: Decimal | int | str, tariff: Tariff | None = None) -> BillCalculation:
    tariff = tariff or load_tariff()
    consumption = _decimal(consumption_kl, "consumption_kl")
    if consumption < 0:
        raise ValueError("consumption_kl cannot be negative")

    water_lines = []
    for index, tier in enumerate(tariff.water_tiers, start=1):
        upper = consumption if tier.to_kl is None else min(consumption, tier.to_kl)
        quantity = max(Decimal("0"), upper - tier.from_kl)
        if quantity:
            water_lines.append(
                ChargeLine(
                    code=f"water_tier_{index}",
                    description=_tier_description(tier),
                    quantity_kl=quantity,
                    rate_per_kl=tier.rate_per_kl,
                    amount=tariff.money(quantity * tier.rate_per_kl),
                )
            )

    fixed_lines = tuple(
        ChargeLine(code=charge.code, description=charge.description, amount=tariff.money(charge.amount))
        for charge in tariff.fixed_charges
    )
    subtotal = sum((line.amount for line in (*water_lines, *fixed_lines)), Decimal("0"))
    vat = tariff.money(subtotal * tariff.vat_rate)
    return BillCalculation(
        tariff_id=tariff.tariff_id,
        tariff_version=tariff.version,
        currency=tariff.currency,
        consumption_kl=consumption,
        water_lines=tuple(water_lines),
        fixed_lines=fixed_lines,
        subtotal=subtotal,
        vat_rate=tariff.vat_rate,
        vat=vat,
        total=subtotal + vat,
    )


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, (bool, float)):
        raise TypeError(f"{field} must be a Decimal, int or numeric string, not {type(value).__name__}")
    if not isinstance(value, (Decimal, int, str)):
        raise TypeError(f"{field} must be a Decimal, int or numeric string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def _tier_description(tier: WaterTier) -> str:
    if tier.to_kl is None:
        return f"Water above {tier.from_kl} kl"
    return f"Water {tier.from_kl}-{tier.to_kl} kl"


def _string_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
