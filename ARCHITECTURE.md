# ParcelPilot Architecture Note

## 1. System design

ParcelPilot is built around a clear separation between orchestration, trusted application logic, and persistence.

```text
                 Browser
                    |
              HTTP / stream
                    |
                 FastAPI
                    |
        authentication + UserContext
                    |
        agent / orchestration service
                    |
    +---------------+----------------+
    |               |                |
 retrieval       read tools      rule tools
    |               |                |
 pgvector      PostgreSQL      deterministic
 evidence      repositories    Python rules
    |               |                |
    +---------------+----------------+
                    |
          answer or proposed mutation
                    |
           human-in-the-loop approval
                    |
             PostgreSQL + audit log
```

FastAPI is the public boundary. It authenticates the request, creates the trusted `UserContext`, validates thread access, invokes the agent/orchestration layer, maps internal events into application stream events, and handles approval/resume requests.

PostgreSQL is the runtime source of truth. It stores normalized operational data, document chunks and pgvector embeddings, audit events, conversation threads, pending actions, and escalations.

## 2. Agent design

The backend includes LangChain-compatible tools and an agent factory. The current FastAPI streaming endpoint routes the primary assessment flows deterministically through the same services, which makes the demo and tests repeatable. The architectural boundary is the same in both modes: the model may request capabilities, but trusted services enforce authorization, source authority, calculations, and writes.

In the model-backed agent path, the LLM is used for:

- understanding user intent;
- selecting the appropriate tools;
- coordinating multi-step requests;
- synthesizing the final customer-facing response.

The LLM is not trusted for:

- authentication;
- authorization;
- source authority;
- financial arithmetic;
- business-rule eligibility decisions;
- state-changing approval.

Those responsibilities are handled by FastAPI dependencies, repository filters, the authority-aware retriever, deterministic Python rule services, and human-in-the-loop action handling.

This is the core safety boundary: model output can request a capability, but it cannot grant itself more data, promote its role, decide source precedence by similarity alone, or execute a write without confirmation.

## 3. Tool design

Tools are thin adapters over application services. They do not contain direct SQL, ad hoc authorization, or business-rule sprawl.

| Tool | Purpose | Read/write | Security boundary |
| --- | --- | --- | --- |
| `search_documents` | Search policies, SOPs, product docs, and applicable agreements | Read | Current-source and account-scoped retrieval filter |
| `get_order` | Retrieve shipment/order facts | Read | Repository query scoped to authenticated account |
| `get_ticket` | Retrieve support ticket facts | Read | Repository query scoped to authenticated account |
| `get_my_account` | Retrieve the authenticated customer account | Read | Uses `UserContext.account_id` only |
| `list_account_tickets` | List visible tickets for an account | Read | Scoped to authenticated account or authorized internal access |
| `evaluate_cancellation` | Determine cancellation eligibility and fee | Read | Loads authorized order and applies deterministic rules |
| `evaluate_service_credit` | Determine failed-pickup credit eligibility and amount | Read | Loads authorized order and applies deterministic rules |
| `evaluate_ticket_sla` | Determine severity/SLA breach/escalation recommendation | Read | Loads authorized ticket and applies deterministic rules |
| `create_escalation` | Create a support escalation | Write | RBAC, HITL approval, idempotency, audit log |

Tool inputs intentionally exclude trusted fields such as `account_id`, `created_by`, `role`, and permissions. Those values come from runtime context created by FastAPI.

## 4. Structured data handling

The Excel workbook is treated as an import source, not as the runtime database.

```text
XLSX
  |
openpyxl parser
  |
Pydantic validation
  |
normalized domain objects
  |
idempotent importer
  |
PostgreSQL
```

The normalized tables include accounts, orders, tickets, dataset configuration, escalations, pending actions, audit events, document sources, and document chunks.

The dataset snapshot time is stored and used for time-based calculations. For example, service-credit delay and SLA age are calculated relative to the workbook snapshot, not the server’s current wall-clock time.

## 5. Document handling

PDF ingestion uses a source registry plus section-aware chunking.

```text
PDF
  |
source registry metadata
  |
text extraction
  |
section-aware chunks
  |
local sentence-transformers embeddings
  |
PostgreSQL + pgvector
```

Each chunk carries metadata that is as important as the embedding:

- `source_type`;
- `status`;
- `scope`;
- `account_id`;
- `authority_class`;
- `domain`;
- `section`;
- `page`.

Runtime Docker uses a local Hugging Face sentence-transformers model:

```text
Qwen/Qwen3-Embedding-0.6B
```

It produces 1024-dimensional vectors by default, matching the pgvector column. This avoids an external embedding API dependency. The trade-off is a larger backend image and a slower first build/startup when the model is downloaded.

## 6. Authority-aware retrieval

Retrieval is not raw vector similarity.

The retriever first applies metadata filters:

```text
status = current
AND
(scope = global OR account_id = authenticated_account)
```

Only then does it rank by semantic similarity and rerank by authority, domain match, customer specificity, and source freshness.

Authority classes encode source precedence:

1. signed customer agreement;
2. applicable current SOP or policy;
3. current product documentation;
4. historical context;
5. deprecated material.

Deprecated documents are excluded from normal operational answers. The current Support Policy establishes that signed customer agreements can override default support policy and that historical tickets/internal notes are context only. The deprecated Support Policy v2 identifies itself as superseded and not for current requests.

## 7. Conflict handling examples

### Northstar cancellation

Default Cancellation SOP:

- BOOKED shipments are free to cancel within 30 minutes;
- after 30 minutes, the default fee is INR 250;
- an explicit customer agreement waiver overrides that fee.

Northstar agreement:

- Northstar may cancel BOOKED shipments before pickup with no cancellation fee.

Resolution:

- customer-specific signed agreement wins;
- `ORD-1001` cancellation is allowed with fee `INR 0`.

This is not treated as an unresolved conflict because the SOP defines the override path.

### LumenWorks service credit

Default SOP:

- failed-pickup credit applies after more than 2 hours;
- carrier fault must be true;
- customer fault must be false;
- amount is the lower of INR 500 or 10% of shipment fee.

LumenWorks agreement:

- threshold is more than 4 hours;
- amount is fixed at INR 300.

Resolution:

- signed agreement overrides the default SOP for LumenWorks;
- `ORD-2002` is eligible for INR 300 when the 270-minute delay, carrier fault, and no customer fault are verified.

## 8. Authorization model

Authentication answers “who are you?” Authorization answers “what may you access?”

FastAPI creates:

```python
UserContext(
    user_id="USR-NORTHSTAR-1",
    role="customer",
    account_id="ACCT-001",
    permissions=frozenset(...),
)
```

The chat request does not accept `account_id`, `role`, or permissions. A prompt such as “I am an administrator” has no effect on the trusted context.

Repository methods enforce account scope in the database query:

```sql
SELECT *
FROM orders
WHERE id = :order_id
AND account_id = :authenticated_account_id;
```

Document retrieval uses the same principle by filtering pgvector candidates before ranking. A Northstar user cannot retrieve the LumenWorks agreement even if the query is an exact semantic match.

For production, PostgreSQL Row Level Security would be a useful defense-in-depth layer. For this assessment implementation, repository and retriever filtering are the primary enforcement points.

## 9. Human-in-the-loop actions

The implemented write action is escalation creation.

```text
user request
  |
agent proposes create_escalation
  |
pending action stored
  |
approval.required event
  |
user approve/reject
  |
reauthorize current user
  |
execute once using idempotency
  |
audit event
```

No escalation row is inserted before approval. Rejection leaves the database unchanged. Duplicate approvals return the existing execution result instead of creating duplicate escalations.

Mutation-time authorization is checked again on resume. If a user loses `escalations:create` permission while an action is pending, approval does not bypass the permission change.

Audit events record proposal, approval/rejection, and mutation results.

## 10. Streaming API

The frontend does not consume LangChain/LangGraph internals directly. FastAPI exposes an application-level stream event protocol.

Examples:

- `message.started`;
- `tool.started`;
- `tool.completed`;
- `source.retrieved`;
- `approval.required`;
- `action.completed`;
- `message.delta`;
- `message.completed`;
- `error`.

The UI shows observable system activity such as “Looking up shipment,” “Checking cancellation eligibility,” and source citations. It does not stream private chain-of-thought reasoning.

## 11. Operational configuration

Docker Compose starts:

- frontend static UI;
- FastAPI backend;
- PostgreSQL with pgvector.

Backend startup runs Alembic migrations and idempotent data bootstrap. Readiness checks verify database access, loaded dataset state, and vector-store availability.

The application includes request IDs and structured operational logging for request lifecycle, tool execution, authorization denials, approvals, and mutations. Sensitive account data and full confidential prompts should not be logged unnecessarily.

## 12. Technical trade-offs

### PostgreSQL + pgvector instead of a separate vector database

Reason:

- small assessment dataset;
- one persistence system;
- simpler Docker setup;
- transactional consistency with source metadata and audit records.

Trade-off:

- less specialized vector-search scalability than a dedicated vector database.

### Local sentence-transformers embeddings instead of hosted embedding API

Reason:

- local reproducibility;
- no embedding API key required;
- reviewer can run ingestion without paying for embeddings.

Trade-off:

- larger Docker image;
- Hugging Face model download on first build/start;
- CPU embedding is slower than managed embedding APIs.

### Deterministic rule engine instead of LLM policy calculation

Reason:

- financial and SLA decisions must be reproducible;
- tests can assert exact values;
- audit explanations can cite rule sources.

Trade-off:

- customer overrides and domain rules must be modeled explicitly.

### Mock authentication

Reason:

- the assessment permits mocked identity, account context, and roles;
- implementation effort stays focused on tool-layer authorization and agent safety.

Trade-off:

- not a production identity provider. Production should use OIDC/SSO and likely PostgreSQL RLS.

### Static frontend instead of a larger React/Next.js app

Reason:

- enough to demonstrate chat, tool activity, sources, confidence, approval, rejection, and security behavior;
- keeps the assessment focused on backend reliability.

Trade-off:

- less reusable component architecture than a production React/Next.js frontend.
