# ParcelPilot Frontend

Small static assessment UI for the ParcelPilot backend.

## Run

Start the backend first, then serve this directory on port `3000`:

```powershell
cd frontend
python -m http.server 3000
```

Open:

```text
http://localhost:3000
```

The backend CORS config already allows `http://localhost:3000`.

## What it shows

- Mock identity selector: Northstar, LumenWorks, admin
- Streaming chat via `POST /api/v1/chat/stream`
- Friendly tool activity labels
- Retrieved source cards
- Deterministic decision summaries
- Confidence labels based on observable evidence/tool state
- Human approval card for pending escalations
- Approval/rejection calls to `POST /api/v1/threads/{thread_id}/decisions`
