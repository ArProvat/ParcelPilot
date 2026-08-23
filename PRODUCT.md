# ParcelPilot Product Note

## Broader problem addressed: trust and reliability

The main product problem addressed is not “make a chatbot answer logistics questions.” It is making support automation trustworthy when the available information can be customer-specific, outdated, conflicting, or unsafe to act on automatically.

ParcelPilot support workflows contain several reliability risks:

- customer agreements can override default policy;
- deprecated policy may still look semantically relevant;
- historical ticket resolutions can be wrong or stale;
- financial calculations must be exact;
- customer data must not cross account boundaries;
- state-changing actions must not happen without confirmation.

The product therefore focuses on authority-aware assistance rather than generic retrieval-augmented chat.

## What was built

ParcelPilot Copilot addresses the trust problem with these product behaviors:

- Account-scoped operational lookup for orders, tickets, and accounts.
- Authority-aware document retrieval across current policies, SOPs, product documentation, and customer agreements.
- Deprecated-source exclusion for current operational answers.
- Historical-ticket demotion to context-only status.
- Deterministic cancellation, service-credit, and SLA calculations.
- Source citations showing which agreement, SOP, or policy supported the answer.
- Tool activity in the UI so reviewers can see which systems were consulted.
- Human approval before escalation creation.
- Audit events for proposed, approved/rejected, and executed mutations.

The result is a support assistant that can answer questions such as “Can Northstar cancel ORD-1001 without a fee?” using both operational facts and authoritative contract/policy evidence, while preventing a Northstar user from seeing LumenWorks data.

## Why trust and reliability is the right focus

The assessment data is intentionally designed to break naive RAG systems.

A simple “split PDFs, embed chunks, return top similarity” approach could:

- return Support Policy v2 even though it is deprecated;
- prefer a historical ticket over a current signed agreement;
- expose another customer’s agreement because it is semantically similar;
- calculate a credit using the default SOP when a customer agreement overrides it;
- create an escalation immediately even though human approval is required.

ParcelPilot handles those cases with explicit source metadata, account filters before ranking, deterministic rule services, and write-action approval.

## Examples

### Northstar cancellation

Default SOP:

- BOOKED shipments after 30 minutes normally incur an INR 250 cancellation fee unless a customer agreement waives it.

Northstar agreement:

- BOOKED shipments before pickup can be cancelled with no cancellation fee.

Product behavior:

- answer: cancellation allowed;
- fee: INR 0;
- reason: customer agreement overrides default SOP;
- cited sources: Northstar agreement and current Cancellation SOP.

### LumenWorks failed-pickup credit

Default SOP:

- threshold is more than 2 hours;
- credit is lower of INR 500 or 10% of shipment fee.

LumenWorks agreement:

- threshold is more than 4 hours;
- credit is fixed at INR 300.

Product behavior:

- use the LumenWorks override for LumenWorks users/orders;
- return INR 300 only when required operational facts are verified;
- require verification if carrier fault, customer fault, or pickup timing is unknown.

### Known upload issue

Product guide:

- Growth and Enterprise support 5,000-row CSV uploads;
- a current known issue can cause intermittent failures above approximately 3,000 rows;
- workaround is to split files below that size.

Product behavior:

- do not incorrectly say the product limit is 3,000 rows;
- distinguish entitlement from a temporary known issue.

## Future work

### P0: production identity and defense-in-depth authorization

- Add OIDC/SSO.
- Replace demo identities with real user provisioning.
- Add real internal roles and account assignment.
- Add PostgreSQL Row Level Security for defense in depth.

Reason: customer isolation is a hard requirement in a real support product.

### P1: proactive issue detection

- Detect complaint spikes.
- Cluster related tickets.
- Identify multi-customer incidents.
- Surface SLA-risk dashboards.
- Alert operations when a known issue starts affecting many customers.

Reason: the same data used for support answers can also reduce incident response time.

### P1: validated contract-rule ingestion

- Extract candidate rule overrides from agreements.
- Route extracted rules to human review.
- Store approved rules in a versioned registry.
- Link every deterministic rule back to agreement clauses.

Reason: manual configuration is appropriate for this small assessment data pack, but production needs a controlled workflow for many customer contracts.

### P2: evaluation and monitoring

- Track citation accuracy.
- Track tool success and failure rates.
- Track human correction rate.
- Track unsupported-claim rate.
- Track escalation approval/rejection rates.

Reason: agent quality should be measured continuously, not only by local test cases.

## Intentionally omitted

The following were intentionally left out because they do not materially improve the core assessment workflow:

- Kubernetes;
- Kafka or a distributed event bus;
- advanced multi-agent architecture;
- full SSO implementation;
- real carrier APIs;
- production billing;
- large workflow orchestration platform;
- Redis-based rate limiting.

The current implementation keeps the architecture focused on the required support-agent behaviors: safe retrieval, structured lookup, deterministic calculations, authorization, human approval, and auditability.

## One useful metric

Primary metric:

```text
Verified autonomous resolution rate
```

Definition:

```text
Percentage of support requests resolved without human intervention
where the final answer passes policy/source validation
and requires no correction within 24 hours.
```

Why this metric matters:

- It measures correct resolution, not chatbot engagement.
- It rewards answers grounded in current authoritative sources.
- It penalizes unsupported claims and wrong policy application.
- It reflects actual support value.

Guardrail metric:

```text
Authorization violation rate = 0
```

Any cross-account data exposure should be treated as a hard product failure, not as a normal quality miss.
