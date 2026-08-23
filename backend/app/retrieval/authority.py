"""Authority classes and contextual precedence for evidence ranking."""
from enum import StrEnum


class AuthorityClass(StrEnum):
    CUSTOMER_AGREEMENT = "signed_customer_agreement"
    CURRENT_DOMAIN_POLICY = "current_domain_policy"
    CURRENT_POLICY = "current_policy"
    CURRENT_PRODUCT_DOCS = "current_product_docs"
    HISTORICAL_CONTEXT = "historical_context"
    DEPRECATED = "deprecated"


class EvidenceDomain(StrEnum):
    CANCELLATION = "cancellation"
    SERVICE_CREDIT = "service_credit"
    SUPPORT_SLA = "support_sla"
    SEVERITY = "severity"
    PLAN_ENTITLEMENT = "plan_entitlement"
    KNOWN_ISSUE = "known_issue"
    SHIPMENT_STATUS = "shipment_status"
    GENERAL = "general"


def authority_rank(authority_class: str, domain: str) -> int:
    """Return contextual authority precedence for a domain."""
    authority = AuthorityClass(authority_class)

    if authority is AuthorityClass.DEPRECATED:
        return 0
    if authority is AuthorityClass.HISTORICAL_CONTEXT:
        return 10

    if domain in {EvidenceDomain.CANCELLATION, EvidenceDomain.SERVICE_CREDIT}:
        return {
            AuthorityClass.CUSTOMER_AGREEMENT: 100,
            AuthorityClass.CURRENT_DOMAIN_POLICY: 90,
            AuthorityClass.CURRENT_POLICY: 70,
            AuthorityClass.CURRENT_PRODUCT_DOCS: 50,
        }.get(authority, 0)

    if domain in {EvidenceDomain.SUPPORT_SLA, EvidenceDomain.SEVERITY}:
        return {
            AuthorityClass.CUSTOMER_AGREEMENT: 100,
            AuthorityClass.CURRENT_POLICY: 90,
            AuthorityClass.CURRENT_DOMAIN_POLICY: 70,
            AuthorityClass.CURRENT_PRODUCT_DOCS: 50,
        }.get(authority, 0)

    if domain in {EvidenceDomain.KNOWN_ISSUE, EvidenceDomain.PLAN_ENTITLEMENT, EvidenceDomain.SHIPMENT_STATUS}:
        return {
            AuthorityClass.CURRENT_PRODUCT_DOCS: 100,
            AuthorityClass.CUSTOMER_AGREEMENT: 80,
            AuthorityClass.CURRENT_POLICY: 70,
            AuthorityClass.CURRENT_DOMAIN_POLICY: 60,
        }.get(authority, 0)

    return {
        AuthorityClass.CUSTOMER_AGREEMENT: 100,
        AuthorityClass.CURRENT_POLICY: 80,
        AuthorityClass.CURRENT_DOMAIN_POLICY: 75,
        AuthorityClass.CURRENT_PRODUCT_DOCS: 70,
    }.get(authority, 0)
