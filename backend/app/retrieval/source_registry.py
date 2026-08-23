"""Manual registry for document-level authority metadata."""
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class SourceDefinition:
    source_key: str
    filename: str
    source_name: str
    source_type: str
    status: str
    scope: str
    authority_class: str
    effective_at: date | None = None
    account_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


DOCUMENT_SOURCES: tuple[SourceDefinition, ...] = (
    SourceDefinition(
        source_key="support_policy_v3",
        filename="01_Support_Policy_v3_CURRENT.pdf",
        source_name="ParcelPilot Support Policy v3",
        source_type="support_policy",
        status="current",
        scope="global",
        authority_class="current_policy",
        effective_at=date(2026, 5, 1),
    ),
    SourceDefinition(
        source_key="support_policy_v2",
        filename="02_Support_Policy_v2_DEPRECATED.pdf",
        source_name="ParcelPilot Support Policy v2",
        source_type="support_policy",
        status="deprecated",
        scope="global",
        authority_class="deprecated",
        effective_at=date(2025, 1, 1),
        metadata={"superseded_by": "support_policy_v3"},
    ),
    SourceDefinition(
        source_key="cancellation_service_credit_sop_v4",
        filename="03_Cancellation_and_Service_Credit_SOP_v4.pdf",
        source_name="ParcelPilot Cancellation & Service Credit SOP v4",
        source_type="sop",
        status="current",
        scope="global",
        authority_class="current_sop",
        effective_at=date(2026, 6, 15),
    ),
    SourceDefinition(
        source_key="product_operations_guide",
        filename="04_Product_Operations_Guide_and_Known_Issues.pdf",
        source_name="ParcelPilot Product Operations Guide",
        source_type="product_documentation",
        status="current",
        scope="global",
        authority_class="current_product_documentation",
    ),
    SourceDefinition(
        source_key="northstar_agreement",
        filename="05_Northstar_Logistics_Enterprise_Agreement.pdf",
        source_name="Northstar Logistics Enterprise Agreement",
        source_type="customer_agreement",
        status="current",
        scope="customer",
        account_id="ACCT-001",
        authority_class="signed_customer_agreement",
        effective_at=date(2026, 1, 1),
    ),
    SourceDefinition(
        source_key="lumenworks_agreement",
        filename="06_LumenWorks_Service_Agreement.pdf",
        source_name="LumenWorks Service Agreement",
        source_type="customer_agreement",
        status="current",
        scope="customer",
        account_id="ACCT-002",
        authority_class="signed_customer_agreement",
        effective_at=date(2026, 3, 1),
    ),
)


SOURCE_BY_KEY = {source.source_key: source for source in DOCUMENT_SOURCES}
