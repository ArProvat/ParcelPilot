# ParcelPilot

ParcelPilot is an AI-powered logistics, customer support, and decision intelligence agent platform. It leverages Retrieval-Augmented Generation (RAG), structured tool calling with LangGraph, authoritative source precedence resolution, and human-in-the-loop (HITL) workflows.

## Features

- **Agentic Decision Engine**: LangGraph-powered conversational agent with tool execution.
- **Authoritative Retrieval**: Multi-source knowledge retriever resolving conflicting policies with explicit authority precedence.
- **Workflow & Ingestion Pipeline**: Ingestion of unstructured PDF documentation and structured assessment workbooks.
- **Security & Authorization**: Role-based access control (RBAC), JWT authentication, and policy enforcement.
- **Human-in-the-Loop (HITL)**: Service credit approvals, escalation handling, and cancellation workflows.

## Project Structure

```text
parcelpilot/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── agent/
│   │   ├── tools/
│   │   ├── retrieval/
│   │   ├── db/
│   │   ├── ingestion/
│   │   └── security/
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
│
├── frontend/
│
├── data/
│   ├── documents/
│   ├── ParcelPilot_Assessment_Data.xlsx
│   └── source_manifest.yaml
│
├── docker-compose.yml
├── README.md
├── ARCHITECTURE.md
└── PRODUCT.md
```

## Quick Start

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Docker

```powershell
cp .env.example .env
docker compose up --build
```

If another local Postgres service already uses port `5432`, run the stack with a different host port:

```powershell
$env:POSTGRES_PORT='5433'
docker compose up -d
```

If another local service already uses frontend port `3000`, set:

```powershell
$env:FRONTEND_PORT='3001'
docker compose up -d
```

Docker starts:

- Frontend: `http://localhost:3000`
- FastAPI: `http://localhost:8000`
- Swagger: `http://localhost:8000/api/v1/docs`
- Health: `http://localhost:8000/api/v1/health`
- Readiness: `http://localhost:8000/api/v1/ready`

On startup the API runs Alembic migrations and idempotently imports the workbook and PDF corpus from `data/`.

### Frontend

For local frontend-only development, serve the static UI on port `3000`:

```powershell
cd frontend
python -m http.server 3000
```

Then open:

```text
http://localhost:3000
```
