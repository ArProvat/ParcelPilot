"""Deterministic business-rule schemas."""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ServiceCreditRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    delay_threshold_minutes: int
    require_carrier_fault: bool
    require_no_customer_fault: bool
    calculation_type: Literal["fixed", "percentage_capped"]
    fixed_amount: Decimal | None = None
    percentage: Decimal | None = None
    maximum_amount: Decimal | None = None
    source_name: str
    source_section: str


class CancellationDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    fee_inr: Decimal | None
    reason_code: str
    explanation: str
    applied_sources: list[str]
    requires_human: bool = False


class ServiceCreditDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    eligible: bool
    amount_inr: Decimal | None
    delay_minutes: int | None
    rule_source: str
    explanation: str
    requires_verification: bool = False
    requires_manager_approval: bool = False


class SLAEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    severity: Literal["P1", "P2", "P3"]
    response_target_minutes: int | None
    breached: bool
    breach_minutes: int | None
    requires_immediate_escalation: bool
    source: str
