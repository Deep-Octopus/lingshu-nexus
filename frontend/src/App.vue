<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

type ViewMode = "admin" | "chat";

type SkillOption = {
  id: string;
  name: string;
  description: string;
  version: string;
  status: string;
  scope: string;
  minimum_role?: string;
};

type SkillValidationReport = {
  skill_id: string;
  version: string;
  valid: boolean;
  computed_checksum: string;
  issues: string[];
};

type DocumentSummary = {
  id: string;
  title: string;
  filename: string;
  media_type: string;
  status: string;
  failure_reason?: string | null;
  chunk_count: number;
  parse_attempts: number;
  updated_at: string;
};

type DocumentChunk = {
  id: string;
  locator: {
    reference: string;
    heading?: string | null;
    page?: number | null;
    paragraph?: number | null;
  };
  text: string;
  parser_version: string;
};

type DocumentDetail = DocumentSummary & {
  chunks: DocumentChunk[];
  status_history: string[];
  parsed_uri?: string | null;
  source_uri?: string | null;
};

type ReviewAssertion = {
  id: string;
  subject: EvidenceTerm;
  predicate: string;
  object: EvidenceTerm;
  source_chunk_ids: string[];
  review_status: string;
  population?: string | null;
  outcome?: string | null;
  direction: string;
  extraction_confidence: number;
  metadata: Record<string, unknown>;
};

type EvidenceTerm = {
  type: string;
  text: string;
  concept_id?: string | null;
  original_text?: string | null;
};

type ReleaseRecord = {
  id: string;
  version: string;
  active: boolean;
  assertion_count: number;
  included_assertion_ids: string[];
  created_at: string;
};

type ReleasePreview = {
  included_assertion_ids: string[];
  excluded_assertions: { assertion_id: string; reason: string }[];
  additions: string[];
  removals: string[];
  unchanged: string[];
  conflict_assertion_ids: string[];
  active_release_id?: string | null;
};

type AdminOverview = {
  documents_total: number;
  document_status_counts: Record<string, number>;
  pending_review_count: number;
  review_status_counts: Record<string, number>;
  active_release?: { id: string; version: string; assertion_count: number } | null;
  failed_jobs_count: number;
  skill_execution_summary: { total: number; failed: number };
  model_usage_summary: {
    records_available: boolean;
    total_tokens?: number | null;
    estimated_cost?: number | null;
    note: string;
  };
};

type JobRun = {
  id: string;
  job_type: string;
  status: string;
  input_ref?: string | null;
  output_ref?: string | null;
  error?: string | null;
};

type AuditEvent = {
  id: string;
  actor_id: string;
  action: string;
  target_type: string;
  target_id: string;
  created_at: string;
  metadata: Record<string, unknown>;
};

type Citation = {
  document_id: string;
  document_title?: string | null;
  source_uri?: string | null;
  chunk_id: string;
  locator: string;
  parser_version?: string | null;
  snippet?: string | null;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  skill?: { id: string; version: string };
  release?: { id: string | null; version: string | null };
};

type StreamEvent = {
  event: string;
  data: Record<string, unknown>;
};

const apiBase = import.meta.env.VITE_API_BASE_URL || "/api/v1";
const domainId = "acupuncture";
const researcherActorId = "researcher-ui";
const reviewerActorId = "reviewer-ui";
const adminActorId = "admin-ui";
const actorRole = "researcher";

const activeView = ref<ViewMode>("admin");
const adminStatus = ref("Loading");
const adminError = ref("");
const adminNotice = ref("");
const overview = ref<AdminOverview | null>(null);
const documents = ref<DocumentSummary[]>([]);
const selectedDocument = ref<DocumentDetail | null>(null);
const reviewAssertions = ref<ReviewAssertion[]>([]);
const selectedAssertionId = ref("");
const reviewReason = ref("Source locator verified.");
const editSubjectText = ref("");
const editObjectText = ref("");
const editPopulation = ref("");
const editOutcome = ref("");
const selectedReleaseAssertionIds = ref<string[]>([]);
const releasePreview = ref<ReleasePreview | null>(null);
const releases = ref<ReleaseRecord[]>([]);
const activeReleaseId = ref<string | null>(null);
const releaseVersion = ref(`v-ui-${new Date().toISOString().slice(0, 10)}`);
const jobs = ref<JobRun[]>([]);
const sourceConnectorStatus = ref("");
const auditEvents = ref<AuditEvent[]>([]);
const skills = ref<SkillOption[]>([]);
const skillReports = ref<Record<string, SkillValidationReport>>({});
const skillRunQuery = ref("Cymba Conchae frequency 25 Hz PSQI parameter");
const skillRunResult = ref("");
const skillUploadId = ref("uploaded-readonly-skill");
const skillUploadMd = ref(
  [
    "---",
    "name: uploaded-readonly-skill",
    "description: Uploaded read-only Skill package.",
    "---",
    "",
    "# Uploaded Read-only Skill",
    "",
    "Use only platform read-only retrieval tools and cite published source chunks.",
    "",
  ].join("\n"),
);
const skillUploadRegistry = ref(
  [
    "skill_id: uploaded-readonly-skill",
    'version: "0.1.0"',
    "status: disabled",
    "scope: read_only",
    "minimum_role: researcher",
    "domain_ids:",
    "  - acupuncture",
    "server_allowed_tools:",
    "  - published_graph_search",
    "supported_query_types:",
    "  - evidence_lookup",
    "checksum: auto",
    "",
  ].join("\n"),
);
const skillUploadTests = ref("cases:\n  - query: evidence lookup\n");

const selectedSkillId = ref("");
const sessionId = ref<string | null>(null);
const messages = ref<ChatMessage[]>([]);
const citations = ref<Citation[]>([]);
const query = ref("Cymba Conchae frequency 25 Hz PSQI parameter");
const statusText = ref("Ready");
const errorText = ref("");
const feedbackNote = ref("");
const feedbackStatus = ref("");
const isStreaming = ref(false);

const chatSkills = computed(() =>
  skills.value.filter((skill) => skill.status === "active" && skill.scope === "read_only"),
);
const assistantMessages = computed(() => messages.value.filter((message) => message.role === "assistant"));
const lastAssistantMessage = computed(() => assistantMessages.value.at(-1));
const selectedAssertion = computed(
  () => reviewAssertions.value.find((assertion) => assertion.id === selectedAssertionId.value) || null,
);
const publishableAssertions = computed(() =>
  reviewAssertions.value.filter((assertion) =>
    ["approved", "conflict"].includes(assertion.review_status),
  ),
);
const failedJobs = computed(() => jobs.value.filter((job) => job.status === "failed"));

onMounted(async () => {
  await refreshAdmin();
  await loadSkills();
});

async function refreshAdmin() {
  adminError.value = "";
  adminStatus.value = "Loading";
  try {
    await Promise.all([
      loadOverview(),
      loadDocuments(),
      loadReviewAssertions(),
      loadReleases(),
      loadJobs(),
      loadAuditEvents(),
    ]);
    syncReleaseSelection();
    adminStatus.value = "Ready";
  } catch (error) {
    adminError.value = error instanceof Error ? error.message : "Unable to load admin data";
    adminStatus.value = "Blocked";
  }
}

async function loadOverview() {
  const response = await fetch(`${apiBase}/admin/overview?domain_id=${domainId}`);
  overview.value = await readJson<AdminOverview>(response, "Admin overview");
}

async function loadDocuments() {
  const response = await fetch(`${apiBase}/documents?domain_id=${domainId}`);
  const payload = await readJson<{ documents: DocumentSummary[] }>(response, "Document list");
  documents.value = payload.documents;
  if (!selectedDocument.value && payload.documents.length > 0) {
    await selectDocument(payload.documents[0].id);
  }
}

async function selectDocument(documentId: string) {
  const response = await fetch(`${apiBase}/documents/${documentId}?domain_id=${domainId}`);
  selectedDocument.value = await readJson<DocumentDetail>(response, "Document detail");
}

async function uploadDocuments(event: Event) {
  const input = event.target as HTMLInputElement;
  if (!input.files || input.files.length === 0) {
    return;
  }
  const formData = new FormData();
  for (const file of Array.from(input.files)) {
    formData.append("files", file);
  }
  adminStatus.value = "Uploading";
  const response = await fetch(`${apiBase}/domains/${domainId}/documents:batch-upload`, {
    method: "POST",
    body: formData,
  });
  await readJson(response, "Document upload");
  input.value = "";
  adminNotice.value = "Upload processed.";
  await refreshAdmin();
}

async function reprocessDocument(documentId: string) {
  if (!window.confirm("Reprocess this document and create a new parse attempt?")) {
    return;
  }
  const response = await fetch(`${apiBase}/documents/${documentId}:reprocess?domain_id=${domainId}`, {
    method: "POST",
  });
  await readJson(response, "Document reprocess");
  adminNotice.value = "Reprocess attempt recorded.";
  await refreshAdmin();
}

async function loadReviewAssertions() {
  const response = await fetch(`${apiBase}/review-assertions?domain_id=${domainId}`);
  const payload = await readJson<{ assertions: ReviewAssertion[] }>(response, "Review assertions");
  reviewAssertions.value = payload.assertions;
  if (!selectedAssertionId.value && payload.assertions.length > 0) {
    selectAssertion(payload.assertions[0]);
  }
}

function selectAssertion(assertion: ReviewAssertion) {
  selectedAssertionId.value = assertion.id;
  editSubjectText.value = assertion.subject.text;
  editObjectText.value = assertion.object.text;
  editPopulation.value = assertion.population || "";
  editOutcome.value = assertion.outcome || "";
}

async function reviewAssertion(action: "approve" | "reject" | "modify" | "mark-conflict") {
  const assertion = selectedAssertion.value;
  if (!assertion) {
    return;
  }
  const reason = reviewReason.value.trim();
  if (!reason) {
    adminError.value = "Review reason is required.";
    return;
  }
  const payload: Record<string, unknown> = {
    reviewer: reviewerActorId,
    reason,
  };
  if (action === "modify") {
    payload.subject_text = editSubjectText.value || undefined;
    payload.object_text = editObjectText.value || undefined;
    payload.population = editPopulation.value || undefined;
    payload.outcome = editOutcome.value || undefined;
  }
  if (action === "mark-conflict") {
    const rawIds = window.prompt("Conflict assertion ids, comma separated");
    const ids = (rawIds || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (ids.length === 0) {
      return;
    }
    payload.conflict_with_assertion_ids = ids;
  }
  const response = await fetch(
    `${apiBase}/review-assertions/${assertion.id}:${action}?domain_id=${domainId}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  const updated = await readJson<ReviewAssertion>(response, `Assertion ${action}`);
  selectAssertion(updated);
  adminNotice.value = `Assertion ${action} recorded.`;
  await loadReviewAssertions();
  await loadOverview();
  await loadAuditEvents();
  syncReleaseSelection();
}

function syncReleaseSelection() {
  if (selectedReleaseAssertionIds.value.length > 0) {
    return;
  }
  selectedReleaseAssertionIds.value = publishableAssertions.value.map((assertion) => assertion.id);
}

async function previewRelease() {
  if (selectedReleaseAssertionIds.value.length === 0) {
    adminError.value = "Select at least one approved or conflict assertion.";
    return;
  }
  const response = await fetch(`${apiBase}/domains/${domainId}/releases:preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ assertion_ids: selectedReleaseAssertionIds.value }),
  });
  releasePreview.value = await readJson<ReleasePreview>(response, "Release preview");
}

async function createRelease() {
  if (selectedReleaseAssertionIds.value.length === 0) {
    adminError.value = "Select at least one approved or conflict assertion.";
    return;
  }
  if (!window.confirm("Create an immutable graph release snapshot?")) {
    return;
  }
  const response = await fetch(`${apiBase}/domains/${domainId}/releases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      version: releaseVersion.value,
      assertion_ids: selectedReleaseAssertionIds.value,
      released_by: reviewerActorId,
    }),
  });
  await readJson<ReleaseRecord>(response, "Release create");
  adminNotice.value = "Release snapshot created.";
  await Promise.all([loadReleases(), loadOverview(), loadAuditEvents()]);
}

async function activateRelease(releaseId: string) {
  if (!window.confirm("Activate this release for user-facing retrieval and chat?")) {
    return;
  }
  const response = await fetch(`${apiBase}/domains/${domainId}/releases/${releaseId}:activate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor_id: adminActorId }),
  });
  await readJson(response, "Release activate");
  adminNotice.value = "Release activated.";
  await Promise.all([loadReleases(), loadOverview(), loadAuditEvents()]);
}

async function rollbackRelease(releaseId: string) {
  const reason = window.prompt("Rollback reason");
  if (!reason || !window.confirm("Rollback active release pointer to this release?")) {
    return;
  }
  const response = await fetch(`${apiBase}/domains/${domainId}/releases/${releaseId}:rollback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor_id: adminActorId, reason }),
  });
  await readJson(response, "Release rollback");
  adminNotice.value = "Release rollback recorded.";
  await Promise.all([loadReleases(), loadOverview(), loadAuditEvents()]);
}

async function loadReleases() {
  const response = await fetch(`${apiBase}/domains/${domainId}/releases`);
  const payload = await readJson<{ active_release_id: string | null; releases: ReleaseRecord[] }>(
    response,
    "Release list",
  );
  releases.value = payload.releases;
  activeReleaseId.value = payload.active_release_id;
}

async function loadJobs() {
  const response = await fetch(`${apiBase}/admin/jobs?domain_id=${domainId}`);
  const payload = await readJson<{
    jobs: JobRun[];
    source_connector: { status: string; message: string };
  }>(response, "Admin jobs");
  jobs.value = payload.jobs;
  sourceConnectorStatus.value = `${payload.source_connector.status}: ${payload.source_connector.message}`;
}

async function loadAuditEvents() {
  const response = await fetch(`${apiBase}/admin/audit-events?domain_id=${domainId}`);
  const payload = await readJson<{ audit_events: AuditEvent[] }>(response, "Audit events");
  auditEvents.value = payload.audit_events.slice().reverse();
}

async function loadSkills() {
  try {
    const response = await fetch(`${apiBase}/skills?domain_id=${domainId}`);
    const payload = await readJson<{ skills: SkillOption[] }>(response, "Skill list");
    skills.value = payload.skills;
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "Unable to load Skills";
  }
}

async function validateSkill(skillId: string) {
  const response = await fetch(`${apiBase}/skills/${skillId}:validate?domain_id=${domainId}`, {
    method: "POST",
  });
  const report = await readJson<SkillValidationReport>(response, "Skill validation");
  skillReports.value = { ...skillReports.value, [skillId]: report };
}

async function setSkillStatus(skill: SkillOption, status: "enable" | "disable") {
  const action = status === "enable" ? "enable" : "disable";
  if (!window.confirm(`${action} ${skill.id}?`)) {
    return;
  }
  const response = await fetch(`${apiBase}/admin/skills/${skill.id}:${action}?domain_id=${domainId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor_id: adminActorId, actor_role: "admin" }),
  });
  await readJson<SkillOption>(response, `Skill ${action}`);
  adminNotice.value = `Skill ${action} recorded.`;
  await Promise.all([loadSkills(), loadAuditEvents(), loadOverview()]);
}

async function uploadSkillPackage() {
  if (!window.confirm("Upload and validate this Skill package?")) {
    return;
  }
  const response = await fetch(`${apiBase}/admin/skills:upload`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      actor_id: adminActorId,
      actor_role: "admin",
      skill_id: skillUploadId.value,
      skill_md: skillUploadMd.value,
      registry_yaml: skillUploadRegistry.value,
      test_cases_yaml: skillUploadTests.value,
    }),
  });
  const skill = await readJson<SkillOption>(response, "Skill upload");
  adminNotice.value = `Skill ${skill.id} uploaded.`;
  await Promise.all([loadSkills(), loadAuditEvents(), loadOverview()]);
}

async function executeSkill(skillId: string) {
  const response = await fetch(`${apiBase}/domains/${domainId}/skills:execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query: skillRunQuery.value,
      actor_id: researcherActorId,
      actor_role: actorRole,
      skill_id: skillId,
    }),
  });
  const payload = await readJson<{ answer: string }>(response, "Skill execution");
  skillRunResult.value = payload.answer;
  await Promise.all([loadOverview(), loadJobs()]);
}

async function readJson<T>(response: Response, label: string): Promise<T> {
  if (!response.ok) {
    throw new Error(`${label} failed: ${response.status}${await responsePreview(response)}`);
  }
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error(
      `${label} expected JSON but received ${describeContentType(contentType)}. Check API server/proxy config.`,
    );
  }
  return (await response.json()) as T;
}

async function readSseStream(response: Response): Promise<ReadableStream<Uint8Array>> {
  if (!response.ok || !response.body) {
    throw new Error(`Stream failed: ${response.status}${await responsePreview(response)}`);
  }
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("text/event-stream")) {
    throw new Error(
      `Stream expected text/event-stream but received ${describeContentType(contentType)}. Check API server/proxy config.${await responsePreview(response)}`,
    );
  }
  return response.body;
}

async function responsePreview(response: Response): Promise<string> {
  const text = await response.text();
  const preview = text.trim().replace(/\s+/g, " ").slice(0, 120);
  return preview ? `: ${preview}` : "";
}

function describeContentType(contentType: string) {
  return contentType || "no content type";
}

async function ensureSession(): Promise<string> {
  if (sessionId.value) {
    return sessionId.value;
  }
  const response = await fetch(`${apiBase}/chat/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      domain_id: domainId,
      actor_id: researcherActorId,
      title: "Evidence chat",
    }),
  });
  const payload = await readJson<{ id: string }>(response, "Session creation");
  sessionId.value = payload.id;
  return payload.id;
}

async function submitQuestion() {
  const question = query.value.trim();
  if (!question || isStreaming.value) {
    return;
  }
  errorText.value = "";
  feedbackStatus.value = "";
  citations.value = [];
  isStreaming.value = true;
  statusText.value = "Starting retrieval";

  messages.value.push({
    id: `local-user-${Date.now()}`,
    role: "user",
    content: question,
  });
  const assistantMessage: ChatMessage = {
    id: `local-assistant-${Date.now()}`,
    role: "assistant",
    content: "",
  };
  messages.value.push(assistantMessage);

  try {
    const activeSessionId = await ensureSession();
    const response = await fetch(
      `${apiBase}/chat/sessions/${activeSessionId}/messages:stream?domain_id=${domainId}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: question,
          actor_id: researcherActorId,
          actor_role: actorRole,
          skill_id: selectedSkillId.value || undefined,
          limit: 5,
        }),
      },
    );
    const stream = await readSseStream(response);
    await readSse(stream, (streamEvent) => handleStreamEvent(streamEvent, assistantMessage));
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown chat error";
    errorText.value = message;
    assistantMessage.content = message;
  } finally {
    isStreaming.value = false;
    if (!errorText.value) {
      statusText.value = "Complete";
    }
  }
}

async function readSse(stream: ReadableStream<Uint8Array>, onEvent: (event: StreamEvent) => void) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      const parsed = parseSseBlock(block);
      if (parsed) {
        onEvent(parsed);
      }
    }
  }
  if (buffer.trim()) {
    const parsed = parseSseBlock(buffer);
    if (parsed) {
      onEvent(parsed);
    }
  }
}

function parseSseBlock(block: string): StreamEvent | null {
  const lines = block.split("\n");
  const eventLine = lines.find((line) => line.startsWith("event: "));
  const dataLine = lines.find((line) => line.startsWith("data: "));
  if (!eventLine || !dataLine) {
    return null;
  }
  return {
    event: eventLine.slice("event: ".length),
    data: JSON.parse(dataLine.slice("data: ".length)) as Record<string, unknown>,
  };
}

function handleStreamEvent(streamEvent: StreamEvent, assistantMessage: ChatMessage) {
  if (streamEvent.event === "retrieval") {
    const stage = streamEvent.data.stage;
    statusText.value = typeof stage === "string" ? stage : "Retrieving";
    return;
  }
  if (streamEvent.event === "text") {
    const delta = streamEvent.data.delta;
    if (typeof delta === "string") {
      assistantMessage.content += delta;
    }
    return;
  }
  if (streamEvent.event === "citation") {
    citations.value.push(streamEvent.data as Citation);
    return;
  }
  if (streamEvent.event === "done") {
    const messageId = streamEvent.data.message_id;
    const skill = streamEvent.data.skill;
    const release = streamEvent.data.graph_release;
    if (typeof messageId === "string") {
      assistantMessage.id = messageId;
    }
    if (isSkillPayload(skill)) {
      assistantMessage.skill = skill;
    }
    if (isReleasePayload(release)) {
      assistantMessage.release = release;
    }
    statusText.value = "Complete";
    return;
  }
  if (streamEvent.event === "error") {
    const message = streamEvent.data.message;
    errorText.value = typeof message === "string" ? message : "Chat stream error";
    assistantMessage.content = errorText.value;
    statusText.value = "Blocked";
  }
}

async function submitFeedback(rating: "helpful" | "not_helpful" | "correction") {
  const message = lastAssistantMessage.value;
  if (!sessionId.value || !message || message.id.startsWith("local-")) {
    feedbackStatus.value = "No completed assistant message to review.";
    return;
  }
  const response = await fetch(
    `${apiBase}/chat/sessions/${sessionId.value}/messages/${message.id}:feedback?domain_id=${domainId}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        actor_id: researcherActorId,
        rating,
        note: feedbackNote.value || undefined,
      }),
    },
  );
  feedbackStatus.value = response.ok ? "Feedback recorded." : `Feedback failed: ${response.status}`;
  if (response.ok) {
    feedbackNote.value = "";
  }
}

function citationHref(citation: Citation) {
  return `${apiBase}/documents/${citation.document_id}?domain_id=${domainId}#${citation.chunk_id}`;
}

function statusClass(status: string) {
  return status.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

function isSkillPayload(value: unknown): value is { id: string; version: string } {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    "version" in value &&
    typeof (value as { id: unknown }).id === "string" &&
    typeof (value as { version: unknown }).version === "string"
  );
}

function isReleasePayload(value: unknown): value is { id: string | null; version: string | null } {
  return typeof value === "object" && value !== null && "id" in value && "version" in value;
}
</script>

<template>
  <main class="app-shell" aria-labelledby="app-title">
    <aside class="rail">
      <p class="eyebrow">LingShu Nexus</p>
      <h1 id="app-title">Research Console</h1>
      <nav class="nav-tabs" aria-label="Workspace">
        <button type="button" :class="{ active: activeView === 'admin' }" @click="activeView = 'admin'">
          Manage
        </button>
        <button type="button" :class="{ active: activeView === 'chat' }" @click="activeView = 'chat'">
          Chat
        </button>
      </nav>
      <div class="rail-status" :class="{ blocked: Boolean(adminError || errorText) }">
        {{ activeView === "admin" ? adminStatus : statusText }}
      </div>
      <button type="button" class="secondary" @click="refreshAdmin">Refresh</button>
    </aside>

    <section v-if="activeView === 'admin'" class="admin-workspace" aria-label="Management panel">
      <header class="page-header">
        <div>
          <h2>Management</h2>
          <p class="notice">内部科研证据辅助，不作为诊疗建议。</p>
        </div>
        <label class="upload-button">
          Upload
          <input type="file" multiple accept=".md,.markdown,.pdf" @change="uploadDocuments" />
        </label>
      </header>

      <p class="error" v-if="adminError">{{ adminError }}</p>
      <p class="success" v-if="adminNotice">{{ adminNotice }}</p>

      <section class="metric-grid" v-if="overview">
        <article>
          <span>Documents</span>
          <strong>{{ overview.documents_total }}</strong>
          <small>{{ overview.document_status_counts.PARSED || 0 }} parsed</small>
        </article>
        <article>
          <span>Pending Review</span>
          <strong>{{ overview.pending_review_count }}</strong>
          <small>{{ overview.review_status_counts.approved || 0 }} approved</small>
        </article>
        <article>
          <span>Active Release</span>
          <strong>{{ overview.active_release?.version || "none" }}</strong>
          <small>{{ overview.active_release?.assertion_count || 0 }} assertions</small>
        </article>
        <article>
          <span>Failed Jobs</span>
          <strong>{{ overview.failed_jobs_count }}</strong>
          <small>{{ overview.model_usage_summary.note }}</small>
        </article>
      </section>

      <section class="split-layout">
        <div class="work-section">
          <div class="section-heading">
            <h3>Documents</h3>
            <span>{{ documents.length }}</span>
          </div>
          <div class="table-list">
            <button
              v-for="document in documents"
              :key="document.id"
              type="button"
              class="row-button"
              :class="{ selected: selectedDocument?.id === document.id }"
              @click="selectDocument(document.id)"
            >
              <span>
                <strong>{{ document.title }}</strong>
                <small>{{ document.filename }} · {{ document.chunk_count }} chunks</small>
              </span>
              <b :class="['pill', statusClass(document.status)]">{{ document.status }}</b>
            </button>
          </div>
        </div>

        <div class="work-section detail-pane">
          <div class="section-heading">
            <h3>Document Detail</h3>
            <button
              v-if="selectedDocument"
              type="button"
              class="secondary compact"
              @click="reprocessDocument(selectedDocument.id)"
            >
              Reprocess
            </button>
          </div>
          <template v-if="selectedDocument">
            <p class="muted">
              {{ selectedDocument.status }} · attempts {{ selectedDocument.parse_attempts }}
            </p>
            <p class="error inline" v-if="selectedDocument.failure_reason">
              {{ selectedDocument.failure_reason }}
            </p>
            <article v-for="chunk in selectedDocument.chunks" :key="chunk.id" class="chunk">
              <strong>{{ chunk.locator.reference }}</strong>
              <p>{{ chunk.text }}</p>
            </article>
          </template>
          <p v-else class="muted">No document selected.</p>
        </div>
      </section>

      <section class="split-layout">
        <div class="work-section">
          <div class="section-heading">
            <h3>Review Workbench</h3>
            <span>{{ reviewAssertions.length }}</span>
          </div>
          <div class="assertion-list">
            <button
              v-for="assertion in reviewAssertions"
              :key="assertion.id"
              type="button"
              class="assertion-row"
              :class="{ selected: selectedAssertionId === assertion.id }"
              @click="selectAssertion(assertion)"
            >
              <span>
                <strong>{{ assertion.subject.text }} → {{ assertion.object.text }}</strong>
                <small>{{ assertion.predicate }} · {{ assertion.direction }} · {{ assertion.id }}</small>
              </span>
              <b :class="['pill', statusClass(assertion.review_status)]">
                {{ assertion.review_status }}
              </b>
            </button>
          </div>
        </div>

        <div class="work-section detail-pane">
          <div class="section-heading">
            <h3>Decision</h3>
            <span v-if="selectedAssertion">{{ selectedAssertion.id }}</span>
          </div>
          <template v-if="selectedAssertion">
            <label>
              <span>Subject</span>
              <input v-model="editSubjectText" />
            </label>
            <label>
              <span>Object</span>
              <input v-model="editObjectText" />
            </label>
            <label>
              <span>Population</span>
              <input v-model="editPopulation" />
            </label>
            <label>
              <span>Outcome</span>
              <input v-model="editOutcome" />
            </label>
            <label>
              <span>Reason</span>
              <textarea v-model="reviewReason" rows="3" />
            </label>
            <div class="action-grid">
              <button type="button" @click="reviewAssertion('approve')">Approve</button>
              <button type="button" class="secondary" @click="reviewAssertion('modify')">Modify</button>
              <button type="button" class="warning" @click="reviewAssertion('mark-conflict')">
                Conflict
              </button>
              <button type="button" class="danger" @click="reviewAssertion('reject')">Reject</button>
            </div>
          </template>
          <p v-else class="muted">No assertion selected.</p>
        </div>
      </section>

      <section class="split-layout">
        <div class="work-section">
          <div class="section-heading">
            <h3>Graph Releases</h3>
            <button type="button" class="secondary compact" @click="previewRelease">Preview</button>
          </div>
          <div class="release-builder">
            <label>
              <span>Version</span>
              <input v-model="releaseVersion" />
            </label>
            <div class="checkbox-list">
              <label v-for="assertion in publishableAssertions" :key="assertion.id">
                <input
                  v-model="selectedReleaseAssertionIds"
                  type="checkbox"
                  :value="assertion.id"
                />
                <span>{{ assertion.subject.text }} → {{ assertion.object.text }}</span>
              </label>
            </div>
            <button type="button" @click="createRelease">Create Release</button>
          </div>
          <div v-if="releasePreview" class="preview-block">
            <strong>{{ releasePreview.included_assertion_ids.length }} included</strong>
            <span>{{ releasePreview.additions.length }} additions</span>
            <span>{{ releasePreview.removals.length }} removals</span>
            <span>{{ releasePreview.excluded_assertions.length }} excluded</span>
          </div>
        </div>

        <div class="work-section">
          <div class="section-heading">
            <h3>Release History</h3>
            <span>{{ releases.length }}</span>
          </div>
          <article v-for="release in releases" :key="release.id" class="release-row">
            <span>
              <strong>{{ release.version }}</strong>
              <small>{{ release.assertion_count }} assertions · {{ release.id }}</small>
            </span>
            <b v-if="release.id === activeReleaseId" class="pill active-release">active</b>
            <div class="row-actions">
              <button
                type="button"
                class="secondary compact"
                :disabled="release.id === activeReleaseId"
                @click="activateRelease(release.id)"
              >
                Activate
              </button>
              <button type="button" class="warning compact" @click="rollbackRelease(release.id)">
                Rollback
              </button>
            </div>
          </article>
        </div>
      </section>

      <section class="split-layout">
        <div class="work-section">
          <div class="section-heading">
            <h3>Skills</h3>
            <span>{{ skills.length }}</span>
          </div>
          <details class="upload-package">
            <summary>Upload Skill Package</summary>
            <label>
              <span>Skill ID</span>
              <input v-model="skillUploadId" />
            </label>
            <label>
              <span>SKILL.md</span>
              <textarea v-model="skillUploadMd" rows="7" />
            </label>
            <label>
              <span>registry.yaml</span>
              <textarea v-model="skillUploadRegistry" rows="9" />
            </label>
            <label>
              <span>tests/cases.yaml</span>
              <textarea v-model="skillUploadTests" rows="4" />
            </label>
            <button type="button" @click="uploadSkillPackage">Upload Package</button>
          </details>
          <article v-for="skill in skills" :key="skill.id" class="skill-row">
            <span>
              <strong>{{ skill.name }} {{ skill.version }}</strong>
              <small>{{ skill.scope }} · {{ skill.minimum_role }} · {{ skill.description }}</small>
            </span>
            <b :class="['pill', statusClass(skill.status)]">{{ skill.status }}</b>
            <div class="row-actions">
              <button type="button" class="secondary compact" @click="validateSkill(skill.id)">
                Validate
              </button>
              <button
                type="button"
                class="secondary compact"
                v-if="skill.status !== 'active'"
                @click="setSkillStatus(skill, 'enable')"
              >
                Enable
              </button>
              <button
                type="button"
                class="warning compact"
                v-if="skill.status === 'active'"
                @click="setSkillStatus(skill, 'disable')"
              >
                Disable
              </button>
              <button type="button" class="secondary compact" @click="executeSkill(skill.id)">
                Run
              </button>
            </div>
            <p v-if="skillReports[skill.id]" class="muted">
              validation {{ skillReports[skill.id].valid ? "passed" : "failed" }}
            </p>
          </article>
          <label>
            <span>Skill Test Query</span>
            <textarea v-model="skillRunQuery" rows="3" />
          </label>
          <pre v-if="skillRunResult" class="result-output">{{ skillRunResult }}</pre>
        </div>

        <div class="work-section">
          <div class="section-heading">
            <h3>Jobs & Audit</h3>
            <span>{{ failedJobs.length }} failed</span>
          </div>
          <p class="muted">{{ sourceConnectorStatus }}</p>
          <article v-for="job in jobs" :key="job.id" class="job-row">
            <b :class="['pill', statusClass(job.status)]">{{ job.status }}</b>
            <span>{{ job.job_type }} · {{ job.input_ref }}</span>
            <small v-if="job.error">{{ job.error }}</small>
          </article>
          <div class="audit-list">
            <article v-for="event in auditEvents" :key="event.id" class="audit-row">
              <strong>{{ event.action }}</strong>
              <span>{{ event.actor_id }} · {{ event.target_type }}/{{ event.target_id }}</span>
              <small>{{ event.created_at }}</small>
            </article>
          </div>
        </div>
      </section>
    </section>

    <section v-else class="chat-workspace" aria-label="Evidence chat">
      <section class="chat-surface">
        <header class="topbar">
          <div>
            <p class="eyebrow">LingShu Nexus</p>
            <h2>Evidence Chat</h2>
          </div>
          <div class="rail-status" :class="{ blocked: Boolean(errorText) }">{{ statusText }}</div>
        </header>

        <div class="message-list" aria-live="polite">
          <article v-if="messages.length === 0" class="empty-state">
            <h3>内部科研证据辅助</h3>
            <p>回答仅检索 active release 中已审核发布的证据，并随流式事件返回引用。</p>
          </article>
          <article
            v-for="message in messages"
            :key="message.id"
            class="message"
            :class="message.role"
          >
            <div class="message-meta">
              <span>{{ message.role === "user" ? "Researcher" : "LingShu" }}</span>
              <span v-if="message.skill">{{ message.skill.id }} {{ message.skill.version }}</span>
              <span v-if="message.release">release {{ message.release.version || "unknown" }}</span>
            </div>
            <p>{{ message.content || "Streaming..." }}</p>
          </article>
        </div>

        <form class="composer" @submit.prevent="submitQuestion">
          <label>
            <span>Skill</span>
            <select v-model="selectedSkillId" :disabled="isStreaming">
              <option value="">Auto route</option>
              <option v-for="skill in chatSkills" :key="skill.id" :value="skill.id">
                {{ skill.name }} {{ skill.version }}
              </option>
            </select>
          </label>
          <label class="query-field">
            <span>Question</span>
            <textarea v-model="query" rows="3" :disabled="isStreaming" />
          </label>
          <button type="submit" :disabled="isStreaming || !query.trim()">
            {{ isStreaming ? "Streaming" : "Send" }}
          </button>
        </form>

        <p class="error" v-if="errorText">{{ errorText }}</p>
      </section>

      <aside class="citation-panel" aria-label="Citations and feedback">
        <section class="panel-section">
          <h3>Citations</h3>
          <p v-if="citations.length === 0" class="muted">No citations returned yet.</p>
          <a
            v-for="citation in citations"
            :key="`${citation.document_id}-${citation.chunk_id}`"
            class="citation"
            :href="citationHref(citation)"
            target="_blank"
            rel="noreferrer"
          >
            <strong>{{ citation.document_title || citation.document_id }}</strong>
            <span>{{ citation.locator }}</span>
            <small>{{ citation.snippet }}</small>
          </a>
        </section>

        <section class="panel-section">
          <h3>Feedback</h3>
          <div class="feedback-actions">
            <button type="button" @click="submitFeedback('helpful')">Useful</button>
            <button type="button" class="secondary" @click="submitFeedback('not_helpful')">
              Not useful
            </button>
          </div>
          <textarea v-model="feedbackNote" rows="4" placeholder="Correction note" />
          <button type="button" @click="submitFeedback('correction')">Submit correction</button>
          <p class="muted">{{ feedbackStatus }}</p>
        </section>
      </aside>
    </section>
  </main>
</template>
