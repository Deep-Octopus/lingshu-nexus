<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

type SkillOption = {
  id: string;
  name: string;
  description: string;
  version: string;
  status: string;
  scope: string;
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
const actorId = "researcher-ui";
const actorRole = "researcher";

const skills = ref<SkillOption[]>([]);
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

const assistantMessages = computed(() => messages.value.filter((message) => message.role === "assistant"));
const lastAssistantMessage = computed(() => assistantMessages.value.at(-1));

onMounted(async () => {
  await loadSkills();
});

async function loadSkills() {
  try {
    const response = await fetch(`${apiBase}/skills?domain_id=${domainId}`);
    if (!response.ok) {
      throw new Error(`Skill list failed: ${response.status}`);
    }
    const payload = (await response.json()) as { skills: SkillOption[] };
    skills.value = payload.skills.filter((skill) => skill.status === "active" && skill.scope === "read_only");
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "Unable to load Skills";
  }
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
      actor_id: actorId,
      title: "Evidence chat",
    }),
  });
  if (!response.ok) {
    throw new Error(`Session creation failed: ${response.status}`);
  }
  const payload = (await response.json()) as { id: string };
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
          actor_id: actorId,
          actor_role: actorRole,
          skill_id: selectedSkillId.value || undefined,
          limit: 5,
        }),
      },
    );
    if (!response.ok || !response.body) {
      throw new Error(`Stream failed: ${response.status}`);
    }
    await readSse(response.body, (streamEvent) => handleStreamEvent(streamEvent, assistantMessage));
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
        actor_id: actorId,
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
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    "version" in value
  );
}
</script>

<template>
  <main class="workspace" aria-labelledby="app-title">
    <section class="chat-surface" aria-label="Evidence chat">
      <header class="topbar">
        <div>
          <p class="eyebrow">LingShu Nexus</p>
          <h1 id="app-title">Evidence Chat</h1>
        </div>
        <div class="status" :class="{ blocked: Boolean(errorText) }">{{ statusText }}</div>
      </header>

      <div class="message-list" aria-live="polite">
        <article v-if="messages.length === 0" class="empty-state">
          <h2>内部科研证据辅助</h2>
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
            <option v-for="skill in skills" :key="skill.id" :value="skill.id">
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
        <h2>Citations</h2>
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
        <h2>Feedback</h2>
        <div class="feedback-actions">
          <button type="button" @click="submitFeedback('helpful')">Useful</button>
          <button type="button" @click="submitFeedback('not_helpful')">Not useful</button>
        </div>
        <textarea v-model="feedbackNote" rows="4" placeholder="Correction note" />
        <button type="button" @click="submitFeedback('correction')">Submit correction</button>
        <p class="muted">{{ feedbackStatus }}</p>
      </section>
    </aside>
  </main>
</template>
