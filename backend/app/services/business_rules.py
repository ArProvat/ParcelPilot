"""Deterministic business-rule evaluators."""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, Order, Ticket
from app.repositories import AccountRepository, DatasetConfigRepository, OrderRepository, TicketRepository
from app.schemas.auth import UserContext
from app.schemas.decisions import CancellationDecision, SLAEvaluation, ServiceCreditDecision, ServiceCreditRule
from app.security.authorization import require_permission
from app.services.operational_data import pickup_delay_minutes


CANCELLATION_SOP_SOURCE = "Cancellation & Service Credit SOP v4"
NORTHSTAR_AGREEMENT_SOURCE = "Northstar Logistics Enterprise Agreement"
LUMENWORKS_AGREEMENT_SOURCE = "LumenWorks Service Agreement"
SUPPORT_POLICY_V3_SOURCE = "ParcelPilot Support Policy v3"

DEFAULT_SERVICE_CREDIT_RULE = ServiceCreditRule(
    delay_threshold_minutes=120,
    require_carrier_fault=True,
    require_no_customer_fault=True,
    calculation_type="percentage_capped",
    percentage=Decimal("0.10"),
    maximum_amount=Decimal("500"),
    source_name=CANCELLATION_SOP_SOURCE,
    source_section="Failed-pickup service credits",
)

LUMENWORKS_SERVICE_CREDIT_RULE = ServiceCreditRule(
    delay_threshold_minutes=240,
    require_carrier_fault=True,
    require_no_customer_fault=True,
    calculation_type="fixed",
    fixed_amount=Decimal("300"),
    source_name=LUMENWORKS_AGREEMENT_SOURCE,
    source_section="Failed-pickup credits",
)


class BusinessRuleService:
    def __init__(self, session: AsyncSession) -> None:
        self.accounts = AccountRepository(session)
        self.dataset_config = DatasetConfigRepository(session)
        self.orders = OrderRepository(session)
        self.tickets = TicketRepository(session)

    async def evaluate_cancellation(self, order_id: str, user: UserContext) -> CancellationDecision:
        require_permission(user, "orders:read")
        order = await self.orders.get_accessible(order_id, user)
        if order is None:
            return CancellationDecision(
                allowed=False,
                fee_inr=None,
                reason_code="NOT_FOUND",
                explanation="No accessible order was found.",
                applied_sources=[],
                requires_human=False,
            )

        account = await self._account_for_order(order)
        return evaluate_cancellation_rule(order, account)

    async def evaluate_service_credit(self, order_id: str, user: UserContext) -> ServiceCreditDecision:
        require_permission(user, "orders:read")
        order = await self.orders.get_accessible(order_id, user)
        if order is None:
            return ServiceCreditDecision(
                eligible=False,
                amount_inr=None,
                delay_minutes=None,
                rule_source="none",
                explanation="No accessible order was found.",
                requires_verification=False,
            )

        account = await self._account_for_order(order)
        snapshot_at = await self.dataset_config.snapshot_time()
        rule = service_credit_rule_for_account(account)
        return evaluate_service_credit_rule(order, snapshot_at, rule)

    async def evaluate_ticket_sla(self, ticket_id: str, user: UserContext) -> SLAEvaluation:
        require_permission(user, "tickets:read")
        ticket = await self.tickets.get_accessible(ticket_id, user)
        if ticket is None:
            return SLAEvaluation(
                severity="P3",
                response_target_minutes=None,
                breached=False,
                breach_minutes=None,
                requires_immediate_escalation=False,
                source="none",
            )

        account = await self.accounts.get(ticket.account_id)
        if account is None:
            return SLAEvaluation(
                severity="P3",
                response_target_minutes=None,
                breached=False,
                breach_minutes=None,
                requires_immediate_escalation=False,
                source="none",
            )

        snapshot_at = await self.dataset_config.snapshot_time()
        return evaluate_ticket_sla_rule(ticket, account, snapshot_at)

    async def _account_for_order(self, order: Order) -> Account:
        account = await self.accounts.get(order.account_id)
        if account is None:
            raise LookupError(f"Order {order.id} references missing account {order.account_id}.")
        return account


def evaluate_cancellation_rule(order: Order, account: Account) -> CancellationDecision:
    if order.status == "DRAFT":
        return CancellationDecision(
            allowed=True,
            fee_inr=Decimal("0.00"),
            reason_code="DRAFT_NO_FEE",
            explanation="DRAFT shipments may be cancelled with no fee.",
            applied_sources=[CANCELLATION_SOP_SOURCE],
        )

    if order.status == "PICKED_UP":
        return CancellationDecision(
            allowed=False,
            fee_inr=None,
            reason_code="USE_RETURN_TO_ORIGIN",
            explanation="PICKED_UP shipments should use the return-to-origin workflow instead of cancellation.",
            applied_sources=[CANCELLATION_SOP_SOURCE],
        )

    if order.status == "DELIVERED":
        return CancellationDecision(
            allowed=False,
            fee_inr=None,
            reason_code="DELIVERED_CANNOT_CANCEL",
            explanation="DELIVERED shipments cannot be cancelled.",
            applied_sources=[CANCELLATION_SOP_SOURCE],
        )

    if order.status != "BOOKED":
        return CancellationDecision(
            allowed=False,
            fee_inr=None,
            reason_code="UNKNOWN_STATUS",
            explanation="The order status is not covered by the cancellation rules.",
            applied_sources=[CANCELLATION_SOP_SOURCE],
            requires_human=True,
        )

    if account.id == "ACCT-001":
        return CancellationDecision(
            allowed=True,
            fee_inr=Decimal("0.00"),
            reason_code="CONTRACT_WAIVER",
            explanation="Northstar's signed agreement waives cancellation fees for BOOKED shipments before pickup.",
            applied_sources=[NORTHSTAR_AGREEMENT_SOURCE, CANCELLATION_SOP_SOURCE],
        )

    if order.cancellation_requested_at is None:
        return CancellationDecision(
            allowed=True,
            fee_inr=None,
            reason_code="CANCELLATION_TIME_UNKNOWN",
            explanation="BOOKED shipments may be cancelled, but the cancellation request time is unknown.",
            applied_sources=[CANCELLATION_SOP_SOURCE],
            requires_human=True,
        )

    booking_age = order.cancellation_requested_at - order.booked_at
    if booking_age <= timedelta(minutes=30):
        return CancellationDecision(
            allowed=True,
            fee_inr=Decimal("0.00"),
            reason_code="BOOKED_WITHIN_30_MINUTES",
            explanation="BOOKED shipments cancelled within 30 minutes of booking have no cancellation fee.",
            applied_sources=[CANCELLATION_SOP_SOURCE],
        )

    return CancellationDecision(
        allowed=True,
        fee_inr=Decimal("250.00"),
        reason_code="BOOKED_STANDARD_FEE",
        explanation="BOOKED shipments cancelled after 30 minutes incur the default INR 250 fee unless a customer agreement waives it.",
        applied_sources=[CANCELLATION_SOP_SOURCE],
    )


def service_credit_rule_for_account(account: Account) -> ServiceCreditRule:
    if account.id == "ACCT-002":
        return LUMENWORKS_SERVICE_CREDIT_RULE
    return DEFAULT_SERVICE_CREDIT_RULE


def evaluate_service_credit_rule(
    order: Order,
    snapshot_at: datetime,
    rule: ServiceCreditRule,
) -> ServiceCreditDecision:
    delay_minutes = pickup_delay_minutes(snapshot_at, order.pickup_window_end)

    if order.carrier_fault is None:
        return _credit_needs_verification(delay_minutes, rule, "Carrier fault has not been verified.")

    if order.customer_fault is None:
        return _credit_needs_verification(delay_minutes, rule, "Customer fault has not been verified.")

    if rule.require_carrier_fault and not order.carrier_fault:
        return ServiceCreditDecision(
            eligible=False,
            amount_inr=None,
            delay_minutes=delay_minutes,
            rule_source=rule.source_name,
            explanation="The order is not eligible because carrier fault is not indicated.",
        )

    if rule.require_no_customer_fault and order.customer_fault:
        return ServiceCreditDecision(
            eligible=False,
            amount_inr=None,
            delay_minutes=delay_minutes,
            rule_source=rule.source_name,
            explanation="The order is not eligible because a customer-caused issue is indicated.",
        )

    if delay_minutes <= rule.delay_threshold_minutes:
        return ServiceCreditDecision(
            eligible=False,
            amount_inr=None,
            delay_minutes=delay_minutes,
            rule_source=rule.source_name,
            explanation=f"The pickup delay is {delay_minutes} minutes, which does not exceed the {rule.delay_threshold_minutes}-minute threshold.",
        )

    amount = _calculate_credit_amount(order, rule)
    return ServiceCreditDecision(
        eligible=True,
        amount_inr=amount,
        delay_minutes=delay_minutes,
        rule_source=rule.source_name,
        explanation=f"The pickup delay is {delay_minutes} minutes and the applicable rule grants a service credit.",
        requires_manager_approval=amount > Decimal("1000"),
    )


def evaluate_ticket_sla_rule(ticket: Ticket, account: Account, snapshot_at: datetime) -> SLAEvaluation:
    severity = classify_ticket_severity(ticket)
    target_minutes, source = response_target_minutes(account, severity)
    age_minutes = max(int((snapshot_at - ticket.created_at).total_seconds() / 60), 0)
    breached = age_minutes > target_minutes
    breach_minutes = age_minutes - target_minutes if breached else 0

    return SLAEvaluation(
        severity=severity,
        response_target_minutes=target_minutes,
        breached=breached,
        breach_minutes=breach_minutes,
        requires_immediate_escalation=severity == "P1" and breached,
        source=source,
    )


def classify_ticket_severity(ticket: Ticket) -> str:
    text = f"{ticket.subject} {ticket.description}".lower()
    if "all shipment creation" in text or "http 500" in text or "api key exposure" in text or "production api key" in text:
        return "P1"
    if "bulk upload" in text or "major" in text or "failing" in text:
        return "P2"
    return "P3"


def response_target_minutes(account: Account, severity: str) -> tuple[int, str]:
    if account.id == "ACCT-001":
        return {"P1": 15, "P2": 60, "P3": 480}[severity], NORTHSTAR_AGREEMENT_SOURCE
    if account.id == "ACCT-002":
        return {"P1": 120, "P2": 240, "P3": 960}[severity], LUMENWORKS_AGREEMENT_SOURCE

    if account.plan == "Enterprise":
        return {"P1": 30, "P2": 120, "P3": 480}[severity], SUPPORT_POLICY_V3_SOURCE
    if account.plan == "Growth":
        return {"P1": 240, "P2": 480, "P3": 1440}[severity], SUPPORT_POLICY_V3_SOURCE
    return {"P1": 480, "P2": 960, "P3": 1440}[severity], SUPPORT_POLICY_V3_SOURCE


def _calculate_credit_amount(order: Order, rule: ServiceCreditRule) -> Decimal:
    if rule.calculation_type == "fixed":
        if rule.fixed_amount is None:
            raise ValueError("Fixed service-credit rule is missing fixed_amount.")
        return _money(rule.fixed_amount)

    if rule.percentage is None or rule.maximum_amount is None:
        raise ValueError("Percentage-capped service-credit rule is incomplete.")

    percentage_amount = order.shipment_fee_inr * rule.percentage
    return _money(min(percentage_amount, rule.maximum_amount))


def _credit_needs_verification(delay_minutes: int, rule: ServiceCreditRule, explanation: str) -> ServiceCreditDecision:
    return ServiceCreditDecision(
        eligible=False,
        amount_inr=None,
        delay_minutes=delay_minutes,
        rule_source=rule.source_name,
        explanation=explanation,
        requires_verification=True,
    )


def _money(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
