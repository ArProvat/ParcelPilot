const API_BASE =
  window.PARCELPILOT_API_BASE ||
  `${window.location.protocol}//${window.location.hostname}:8000/api/v1`;

const state = {
  token: localStorage.getItem("parcelpilot_token") || "",
  identity: localStorage.getItem("parcelpilot_identity") || "northstar",
  user: null,
  threadId: localStorage.getItem("parcelpilot_thread") || makeThreadId(),
  messages: [],
  activeAssistantId: null,
  busy: false,
};

const toolLabels = {
  search_documents: "Searching policies and agreements",
  get_order: "Looking up shipment",
  get_ticket: "Looking up support ticket",
  get_account: "Looking up account",
  get_my_account: "Looking up account",
  list_account_tickets: "Listing support tickets",
  evaluate_cancellation: "Checking cancellation eligibility",
  evaluate_service_credit: "Calculating service-credit eligibility",
  evaluate_ticket_sla: "Checking support SLA",
  create_escalation: "Creating escalation",
};

const elements = {
  identity: document.querySelector("#identity"),
  me: document.querySelector("#me"),
  threadId: document.querySelector("#thread-id"),
  backendStatus: document.querySelector("#backend-status"),
  toolCount: document.querySelector("#tool-count"),
  sourceCount: document.querySelector("#source-count"),
  messages: document.querySelector("#messages"),
  form: document.querySelector("#chat-form"),
  input: document.querySelector("#message-input"),
  send: document.querySelector("#send-button"),
  newThread: document.querySelector("#new-thread"),
};

init();

async function init() {
  elements.identity.value = state.identity;
  persistThread();
  bindEvents();
  render();
  await checkBackend();
  await login(state.identity);
}

function bindEvents() {
  elements.identity.addEventListener("change", async (event) => {
    state.identity = event.target.value;
    localStorage.setItem("parcelpilot_identity", state.identity);
    await login(state.identity);
  });

  elements.newThread.addEventListener("click", () => {
    state.threadId = makeThreadId();
    state.messages = [];
    state.activeAssistantId = null;
    persistThread();
    render();
  });

  document.querySelectorAll(".prompt").forEach((button) => {
    button.addEventListener("click", () => {
      elements.input.value = button.dataset.prompt;
      elements.input.focus();
    });
  });

  elements.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = elements.input.value.trim();
    if (!text || state.busy) return;
    elements.input.value = "";
    await sendMessage(text);
  });
}

async function checkBackend() {
  try {
    const response = await fetch(`${API_BASE}/health`);
    elements.backendStatus.textContent = response.ok ? "Healthy" : `HTTP ${response.status}`;
  } catch {
    elements.backendStatus.textContent = "Unavailable";
  }
}

async function login(identity) {
  elements.me.textContent = "Signing in…";
  try {
    const response = await fetch(`${API_BASE}/auth/mock-login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user: identity }),
    });
    if (!response.ok) throw new Error(`Login failed: ${response.status}`);
    const token = await response.json();
    state.token = token.access_token;
    localStorage.setItem("parcelpilot_token", state.token);
    const meResponse = await apiFetch(`${API_BASE}/auth/me`);
    state.user = await meResponse.json();
    renderIdentity();
  } catch (error) {
    state.user = null;
    elements.me.textContent = error.message || "Login failed";
  }
}

async function sendMessage(content) {
  state.busy = true;
  const assistant = {
    id: crypto.randomUUID(),
    role: "assistant",
    content: "",
    status: "streaming",
    toolCalls: [],
    sources: [],
    approvals: [],
    decisions: [],
    errors: [],
    startedAt: Date.now(),
  };

  state.messages.push({
    id: crypto.randomUUID(),
    role: "user",
    content,
    status: "completed",
    toolCalls: [],
    sources: [],
    approvals: [],
    decisions: [],
    errors: [],
  });
  state.messages.push(assistant);
  state.activeAssistantId = assistant.id;
  render();

  try {
    const response = await apiFetch(`${API_BASE}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: state.threadId, message: content }),
    });

    if (!response.ok || !response.body) {
      throw new Error(`Chat request failed: HTTP ${response.status}`);
    }

    await readSseStream(response.body, (event) => {
      applyStreamEvent(assistant, event);
      render();
    });

    assistant.status = assistant.errors.length ? "failed" : "completed";
  } catch (error) {
    assistant.status = "failed";
    assistant.errors.push({
      code: "FRONTEND_REQUEST_FAILED",
      message: error.message || "The request could not be completed.",
    });
  } finally {
    state.busy = false;
    render();
  }
}

async function readSseStream(stream, onEvent) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const raw = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);
      if (raw) onEvent(parseSseEvent(raw));
      boundary = buffer.indexOf("\n\n");
    }
  }
}

function parseSseEvent(raw) {
  const lines = raw.split(/\r?\n/);
  const eventLine = lines.find((line) => line.startsWith("event:"));
  const dataLines = lines.filter((line) => line.startsWith("data:"));
  const type = eventLine ? eventLine.slice(6).trim() : "message";
  const dataText = dataLines.map((line) => line.slice(5).trim()).join("\n");
  const envelope = dataText ? JSON.parse(dataText) : {};
  return { type, envelope, data: envelope.data || {} };
}

function applyStreamEvent(message, event) {
  const data = event.data;

  if (event.type === "tool.started") {
    message.toolCalls.push({
      id: data.tool_call_id || crypto.randomUUID(),
      tool: data.tool || "unknown_tool",
      label: data.label || labelForTool(data.tool),
      status: "running",
    });
    return;
  }

  if (event.type === "tool.completed") {
    const tool = [...message.toolCalls].reverse().find((item) => item.tool === data.tool);
    if (tool) tool.status = data.status === "success" ? "completed" : "failed";
    return;
  }

  if (event.type === "source.retrieved") {
    message.sources.push({
      id: crypto.randomUUID(),
      source: data.source,
      section: data.section,
      page: data.page,
      authority: inferAuthority(data.source),
    });
    return;
  }

  if (event.type === "decision.completed") {
    message.decisions.push(data);
    return;
  }

  if (event.type === "approval.required") {
    message.approvals.push({
      actionId: data.action_id,
      action: data.action,
      ticketId: data.ticket_id,
      priority: data.priority,
      reason: data.reason,
      status: "pending",
    });
    return;
  }

  if (event.type === "message.delta") {
    message.content += data.text || "";
    return;
  }

  if (event.type === "error") {
    message.errors.push(data);
    message.status = "failed";
  }
}

async function decide(messageId, actionId, decision) {
  const message = state.messages.find((item) => item.id === messageId);
  if (!message) return;
  const approval = message.approvals.find((item) => item.actionId === actionId);
  if (!approval || approval.status !== "pending") return;

  approval.status = "submitting";
  render();

  try {
    const response = await apiFetch(`${API_BASE}/threads/${encodeURIComponent(state.threadId)}/decisions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action_id: actionId, decision }),
    });

    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `Decision failed: HTTP ${response.status}`);

    approval.status = decision === "approve" ? "approved" : "rejected";
    approval.result = result;

    if (result.type === "action.completed") {
      message.content += "\n\nEscalation created.";
    } else {
      message.content += "\n\nEscalation cancelled. No changes were made.";
    }
  } catch (error) {
    approval.status = "pending";
    message.errors.push({
      code: "DECISION_FAILED",
      message: error.message || "The approval decision could not be submitted.",
    });
  } finally {
    render();
  }
}

function render() {
  elements.threadId.textContent = state.threadId;
  elements.send.disabled = state.busy;
  elements.input.disabled = state.busy;

  const totals = state.messages
    .filter((message) => message.role === "assistant")
    .reduce(
      (acc, message) => {
        acc.tools += message.toolCalls.length;
        acc.sources += message.sources.length;
        return acc;
      },
      { tools: 0, sources: 0 },
    );
  elements.toolCount.textContent = String(totals.tools);
  elements.sourceCount.textContent = String(totals.sources);

  if (!state.messages.length) {
    elements.messages.innerHTML = `
      <div class="empty-state">
        <div>
          <strong>Ask ParcelPilot a support question.</strong>
          <span>Use a demo prompt to show tools, citations, RBAC, or approval.</span>
        </div>
      </div>
    `;
    return;
  }

  elements.messages.innerHTML = state.messages.map(renderMessage).join("");
  elements.messages.querySelectorAll("[data-approval-button]").forEach((button) => {
    button.addEventListener("click", () => {
      decide(button.dataset.messageId, button.dataset.actionId, button.dataset.decision);
    });
  });
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

function renderIdentity() {
  if (!state.user) {
    elements.me.textContent = "Not signed in";
    return;
  }

  const account = state.user.account_id || "all authorized accounts";
  elements.me.innerHTML = `
    <strong>${escapeHtml(state.user.user_id)}</strong><br />
    ${escapeHtml(state.user.role)} · ${escapeHtml(account)}<br />
    ${escapeHtml((state.user.permissions || []).join(", "))}
  `;
}

function renderMessage(message) {
  const confidence = message.role === "assistant" ? confidenceFor(message) : null;
  return `
    <article class="message ${message.role}">
      <div class="message-head">
        <span>${message.role === "user" ? "User" : "ParcelPilot"}</span>
        ${
          confidence
            ? `<span class="confidence ${confidence.level.toLowerCase()}">${confidence.label}</span>`
            : `<span class="status-pill">${message.status}</span>`
        }
      </div>

      ${message.toolCalls.length ? renderTools(message.toolCalls) : ""}
      ${message.decisions.length ? renderDecisionSummary(message.decisions.at(-1)) : ""}
      ${message.sources.length ? renderSources(message.sources) : ""}
      ${message.sources.length > 1 ? renderResolution(message.sources) : ""}
      ${message.approvals.length ? message.approvals.map((approval) => renderApproval(message.id, approval)).join("") : ""}
      ${message.errors.length ? renderErrors(message.errors) : ""}

      <div class="message-content">${escapeHtml(message.content || (message.status === "streaming" ? "Working…" : ""))}</div>
    </article>
  `;
}

function renderTools(tools) {
  return `
    <section class="activity">
      <div class="activity-title">Tool activity</div>
      <div class="tool-list">
        ${tools
          .map(
            (tool) => `
              <div class="tool-row">
                <span class="dot ${tool.status}"></span>
                <span>${escapeHtml(tool.label || labelForTool(tool.tool))}</span>
                <span class="tool-name">${escapeHtml(tool.tool)}</span>
              </div>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function renderSources(sources) {
  return `
    <section class="sources">
      <div class="sources-title">Sources</div>
      <div class="source-list">
        ${sources
          .map(
            (source) => `
              <div class="source-card">
                <strong>${escapeHtml(source.source || "Unknown source")}</strong>
                <div class="source-meta">
                  ${escapeHtml(source.section || "Section not specified")}
                  ${source.page ? ` · Page ${escapeHtml(String(source.page))}` : ""}
                </div>
                <span class="authority">${escapeHtml(source.authority)}</span>
              </div>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function renderResolution(sources) {
  const winner = sources.find((source) => source.authority.includes("agreement")) || sources[0];
  return `
    <section class="resolution">
      <div class="resolution-title">Why this answer?</div>
      <div>
        ${escapeHtml(winner.source)} is treated as the most specific applicable source in the retrieved evidence.
        Customer-specific agreements override general default policies when they directly apply.
      </div>
    </section>
  `;
}

function renderDecisionSummary(decision) {
  const entries = Object.entries(decision)
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([key, value]) => `<div><dt>${escapeHtml(formatKey(key))}</dt><dd>${escapeHtml(String(value))}</dd></div>`)
    .join("");

  return `
    <section class="activity">
      <div class="activity-title">Deterministic decision</div>
      <dl class="facts">${entries}</dl>
    </section>
  `;
}

function renderApproval(messageId, approval) {
  const isPending = approval.status === "pending";
  const statusText = {
    pending: "This action has not been executed yet.",
    submitting: "Submitting decision…",
    approved: "Escalation approved and executed.",
    rejected: "Escalation rejected. No changes were made.",
  }[approval.status];

  return `
    <section class="approval">
      <div class="approval-title">Action requires confirmation</div>
      <dl class="approval-grid">
        <dt>Action</dt><dd>${escapeHtml(labelForTool(approval.action))}</dd>
        <dt>Ticket</dt><dd>${escapeHtml(approval.ticketId || "—")}</dd>
        <dt>Priority</dt><dd>${escapeHtml(approval.priority || "—")}</dd>
        <dt>Reason</dt><dd>${escapeHtml(approval.reason || "—")}</dd>
      </dl>
      <p class="approval-warning">${escapeHtml(statusText)}</p>
      <div class="approval-actions">
        <button
          class="reject"
          type="button"
          data-approval-button
          data-message-id="${escapeHtml(messageId)}"
          data-action-id="${escapeHtml(approval.actionId)}"
          data-decision="reject"
          ${isPending ? "" : "disabled"}
        >
          Reject
        </button>
        <button
          class="confirm"
          type="button"
          data-approval-button
          data-message-id="${escapeHtml(messageId)}"
          data-action-id="${escapeHtml(approval.actionId)}"
          data-decision="approve"
          ${isPending ? "" : "disabled"}
        >
          Confirm
        </button>
      </div>
    </section>
  `;
}

function renderErrors(errors) {
  return `
    <section class="approval">
      <div class="approval-title">Error</div>
      ${errors
        .map((error) => `<p>${escapeHtml(error.message || error.code || "The request could not be completed.")}</p>`)
        .join("")}
    </section>
  `;
}

function confidenceFor(message) {
  if (message.errors.length) return { level: "LOW", label: "Needs verification" };
  if (message.status === "streaming") return { level: "MEDIUM", label: "Working" };
  if (message.sources.length && message.decisions.length) return { level: "HIGH", label: "Confidence: High" };
  if (message.toolCalls.some((tool) => tool.status === "failed")) return { level: "LOW", label: "Needs verification" };
  if (message.toolCalls.length || message.sources.length) return { level: "MEDIUM", label: "Confidence: Medium" };
  return { level: "LOW", label: "Needs verification" };
}

function labelForTool(tool) {
  return toolLabels[tool] || tool || "Running tool";
}

function inferAuthority(sourceName = "") {
  const source = sourceName.toLowerCase();
  if (source.includes("agreement")) return "Customer-specific agreement";
  if (source.includes("sop")) return "Current SOP";
  if (source.includes("policy")) return "Current policy";
  if (source.includes("operations") || source.includes("guide")) return "Product documentation";
  return "Retrieved evidence";
}

function formatKey(key) {
  return key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function makeThreadId() {
  return `thr_${crypto.randomUUID().slice(0, 8)}`;
}

function persistThread() {
  localStorage.setItem("parcelpilot_thread", state.threadId);
}

function apiFetch(url, options = {}) {
  return fetch(url, {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Bearer ${state.token}`,
    },
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
