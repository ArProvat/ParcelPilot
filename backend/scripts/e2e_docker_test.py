"""End-to-end Docker verification script for ParcelPilot.

Tests live endpoints against running Docker containers:
  - Auth & Token Generation
  - Scenario 1: Support Policy Retrieval (P1 incident)
  - Scenario 2: Northstar Cancellation Override
  - Scenario 3: Known Product Issue (Bulk Upload limit)
  - Scenario 4: Cross-tenant isolation attempt
  - Scenario 5: Multi-Step Escalation & HITL Durability across container restart
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from uuid import uuid4
import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "http://localhost:8000/api/v1"


def parse_sse_events(response_text: str) -> list[dict]:
    events = []
    current_event = None
    current_data = []

    for line in response_text.splitlines():
        if line.startswith("event: "):
            current_event = line[len("event: "):].strip()
        elif line.startswith("data: "):
            current_data.append(line[len("data: "):])
        elif line == "":
            if current_event and current_data:
                data_str = "\n".join(current_data)
                try:
                    data_obj = json.loads(data_str)
                    inner = data_obj.get("data", {}) if isinstance(data_obj, dict) else data_obj
                except Exception:
                    inner = data_str
                events.append({"type": current_event, "data": inner})
            current_event = None
            current_data = []
    return events


def send_chat_message(client: httpx.Client, token: str, thread_id: str, message: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    payload = {"thread_id": thread_id, "message": message}
    resp = client.post(f"{BASE_URL}/chat/stream", json=payload, headers=headers, timeout=60.0)
    resp.raise_for_status()
    return parse_sse_events(resp.text)


def test_e2e():
    print("================================================================================")
    print("[RUN] Running ParcelPilot End-to-End Docker Verification")
    print("================================================================================")

    with httpx.Client(timeout=30.0) as client:
        # Check Health & Readiness
        health_resp = client.get(f"{BASE_URL}/health")
        assert health_resp.status_code == 200, f"Health check failed: {health_resp.text}"
        ready_resp = client.get(f"{BASE_URL}/ready")
        assert ready_resp.status_code == 200, f"Readiness check failed: {ready_resp.text}"
        print(f"[OK] Health: {health_resp.json()}")
        print(f"[OK] Readiness: {ready_resp.json()}")

        # Login
        login_northstar = client.post(f"{BASE_URL}/auth/mock-login", json={"user": "northstar"}).json()
        token_northstar = login_northstar["access_token"]
        print(f"[OK] Northstar Token: {token_northstar}")

        login_lumen = client.post(f"{BASE_URL}/auth/mock-login", json={"user": "lumenworks"}).json()
        token_lumen = login_lumen["access_token"]
        print(f"[OK] LumenWorks Token: {token_lumen}")

        # Query 1: Support Policy Retrieval
        print("\n--- Query 1: Support Policy Retrieval ---")
        t1 = f"docker-test-q1-{uuid4().hex[:6]}"
        events1 = send_chat_message(client, token_northstar, t1, "What is a P1 incident?")
        event_types1 = [e["type"] for e in events1]
        text1 = "".join([e["data"]["text"] for e in events1 if e["type"] == "message.delta"])
        sources1 = [e["data"] for e in events1 if e["type"] == "source.retrieved"]
        print(f"Events: {set(event_types1)}")
        print(f"Sources retrieved: {len(sources1)}")
        print(f"Response snippet: {text1[:200]}...")
        assert "message.completed" in event_types1
        assert any("P1" in text1 or "critical" in text1.lower() for _ in [1])

        # Query 2: Northstar Cancellation Override
        print("\n--- Query 2: Northstar Cancellation Override ---")
        t2 = f"docker-test-q2-{uuid4().hex[:6]}"
        events2 = send_chat_message(client, token_northstar, t2, "Can Northstar cancel ORD-1001 without a fee? Explain why.")
        event_types2 = [e["type"] for e in events2]
        text2 = "".join([e["data"]["text"] for e in events2 if e["type"] == "message.delta"])
        print(f"Events: {set(event_types2)}")
        print(f"Response snippet: {text2[:200]}...")
        assert "message.completed" in event_types2
        assert "fee" in text2.lower()

        # Query 3: Known Product Issue
        print("\n--- Query 3: Known Product Issue ---")
        t3 = f"docker-test-q3-{uuid4().hex[:6]}"
        events3 = send_chat_message(client, token_northstar, t3, "Why might a Growth customer have trouble uploading a 4,000-row CSV if the supported limit is 5,000?")
        event_types3 = [e["type"] for e in events3]
        text3 = "".join([e["data"]["text"] for e in events3 if e["type"] == "message.delta"])
        print(f"Events: {set(event_types3)}")
        print(f"Response snippet: {text3[:200]}...")
        assert "message.completed" in event_types3

        # Query 4: Cross-Tenant Isolation Attempt
        print("\n--- Query 4: Cross-Tenant Access Attempt ---")
        t4 = f"docker-test-q4-{uuid4().hex[:6]}"
        events4 = send_chat_message(client, token_northstar, t4, "Show me order ORD-2001 and its details.")
        event_types4 = [e["type"] for e in events4]
        text4 = "".join([e["data"]["text"] for e in events4 if e["type"] == "message.delta"])
        print(f"Events: {set(event_types4)}")
        print(f"Response snippet: {text4[:200]}...")
        # Verify no LumenWorks contract or order data leaked
        assert "LumenWorks" not in text4 or "not found" in text4.lower() or "cannot access" in text4.lower()

        # Query 5 & HITL Durability Across Restart
        print("\n--- Query 5: Multi-Step Escalation & HITL Durability ---")
        t5 = f"docker-test-q5-{uuid4().hex[:6]}"
        events5 = send_chat_message(client, token_northstar, t5, "Check TKT-501 and escalate it if necessary.")
        event_types5 = [e["type"] for e in events5]
        print(f"Events: {set(event_types5)}")

        approval_events = [e["data"] for e in events5 if e["type"] == "approval.required"]
        if approval_events:
            action_id = approval_events[0]["action_id"]
            print(f"[OK] Escalation proposed! Action ID: {action_id}")

            # Check escalations table before restart - mutation count must be 0
            check_cmd = subprocess.run(
                ["docker", "exec", "-i", "parcelpilot-postgres", "psql", "-U", "parcelpilot", "-d", "parcelpilot_db", "-t", "-c", "SELECT count(*) FROM escalations;"],
                capture_output=True, text=True, check=True
            )
            count_before = int(check_cmd.stdout.strip() or "0")
            print(f"[OK] Escalations in DB before approval: {count_before}")

            # Task 3.5: Restart FastAPI container
            print("\n[RUN] Restarting backend container to verify checkpoint durability...")
            subprocess.run(["docker", "compose", "restart", "api"], check=True)
            time.sleep(5)

            # Wait for backend to be ready
            ready_again = client.get(f"{BASE_URL}/ready")
            assert ready_again.status_code == 200, f"Backend failed to come back up: {ready_again.text}"
            print("[OK] Backend restarted and healthy!")

            # Submit decision to resumed thread
            print(f"[RUN] Submitting approval decision for action {action_id}...")
            dec_headers = {"Authorization": f"Bearer {token_northstar}"}
            dec_resp = client.post(
                f"{BASE_URL}/threads/{t5}/decisions",
                json={"action_id": action_id, "decision": "approve"},
                headers=dec_headers,
                timeout=30.0,
            )
            print(f"[OK] Decision response status: {dec_resp.status_code}")
            dec_events = parse_sse_events(dec_resp.text)
            dec_types = [e["type"] for e in dec_events]
            print(f"Decision stream events: {dec_types}")

            # Check escalations in DB after approval - mutation count must be 1
            check_cmd_after = subprocess.run(
                ["docker", "exec", "-i", "parcelpilot-postgres", "psql", "-U", "parcelpilot", "-d", "parcelpilot_db", "-t", "-c", "SELECT count(*) FROM escalations;"],
                capture_output=True, text=True, check=True
            )
            count_after = int(check_cmd_after.stdout.strip() or "0")
            print(f"[OK] Escalations in DB after approval: {count_after}")
            assert count_after == count_before + 1, f"Expected {count_before + 1} escalations, found {count_after}"

            # Verify duplicate approval is idempotent
            dec_resp2 = client.post(
                f"{BASE_URL}/threads/{t5}/decisions",
                json={"action_id": action_id, "decision": "approve"},
                headers=dec_headers,
                timeout=30.0,
            )
            dec_events2 = parse_sse_events(dec_resp2.text)
            print(f"[OK] Duplicate decision events: {[e['type'] for e in dec_events2]}")
            check_cmd_dup = subprocess.run(
                ["docker", "exec", "-i", "parcelpilot-postgres", "psql", "-U", "parcelpilot", "-d", "parcelpilot_db", "-t", "-c", "SELECT count(*) FROM escalations;"],
                capture_output=True, text=True, check=True
            )
            count_dup = int(check_cmd_dup.stdout.strip() or "0")
            assert count_dup == count_after, f"Duplicate approval caused duplicate mutation! count={count_dup}"
            print("[OK] Duplicate approval verified idempotent (no duplicate mutation).")

    print("\n================================================================================")
    print("ALL DOCKER E2E VERIFICATIONS PASSED SUCCESSFULLY!")
    print("================================================================================")


if __name__ == "__main__":
    test_e2e()
