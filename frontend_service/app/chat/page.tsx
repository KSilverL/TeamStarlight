"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { useRealtimeVoice, type VoiceBriefPartial } from "./useRealtimeVoice";

type Platform = "x" | "instagram" | "tiktok" | "linkedin";

interface SessionSummary {
  id: string;
  createdAt: string;
  status: string;
  targetPlatforms: string[] | null;
}

interface DBMessage {
  messageId: number;
  role: "user" | "assistant";
  variant?: string;
  content: string;
  timestamp: string;
}
// The three content kinds the backend can actually generate. Multi-select: one
// "send" can fan out to several of these at once.
type ContentType = "text" | "video" | "brand";
type ApprovalStatus = "pending" | "approved" | "rejected";

interface DraftContent {
  text: string;
  hashtags?: string[];
  imageDesc?: string;
}

interface VideoStat {
  value: string;
  label: string;
  icon: string;
}

// The dynamic storyboard the backend composes (core.video_schema.StoryboardSpec):
// an ordered list of typed slides — nine fixed templates plus "generated", a
// bespoke Remotion scene the codegen agent authors from scratch when none of the
// fixed types fit (workflow/video/codegen.py). The agent decides which slides,
// order, and length fit the brief, never a hardcoded template count.
interface HookSlide {
  type: "hook";
  headline: string;
  subtext?: string | null;
  imageQuery?: string | null;
  shape: "circle" | "blob" | "hex";
  durationFrames?: number | null;
}
interface CounterStatSlide {
  type: "counter_stat";
  sectionLabel?: string | null;
  stats: VideoStat[];
  durationFrames?: number | null;
}
interface CollageSlide {
  type: "collage";
  headline?: string | null;
  imageQueries: string[];
  layout: "grid" | "scatter" | "stack";
  durationFrames?: number | null;
}
interface OutroSlide {
  type: "outro";
  brandName: string;
  ctaLabel: string;
  contact?: string | null;
  durationFrames?: number | null;
}
interface PieSlice {
  label: string;
  value: number;
}
interface PieChartSlide {
  type: "pie_chart";
  headline?: string | null;
  slices: PieSlice[];
  calloutText?: string | null;
  durationFrames?: number | null;
}
interface ChartSeries {
  label: string;
  values: number[];
}
interface LineChartSlide {
  type: "line_chart";
  headline?: string | null;
  xLabels: string[];
  series: ChartSeries[];
  durationFrames?: number | null;
}
interface BarItem {
  label: string;
  value: number;
}
interface BarChartSlide {
  type: "bar_chart";
  headline?: string | null;
  bars: BarItem[];
  durationFrames?: number | null;
}
interface NodeDiagramSlide {
  type: "node_diagram";
  headline?: string | null;
  nodes: string[];
  durationFrames?: number | null;
}
interface ComparisonRow {
  label: string;
  values: string[];
}
interface ComparisonTableSlide {
  type: "comparison_table";
  headline?: string | null;
  columns: string[];
  rows: ComparisonRow[];
  durationFrames?: number | null;
}
interface GeneratedSlide {
  type: "generated";
  description: string;
  data: Record<string, unknown>;
  durationFrames?: number | null;
}
type VideoSlide =
  | HookSlide
  | CounterStatSlide
  | CollageSlide
  | OutroSlide
  | PieChartSlide
  | LineChartSlide
  | BarChartSlide
  | NodeDiagramSlide
  | ComparisonTableSlide
  | GeneratedSlide;

interface VideoStoryboard {
  brandName: string;
  primaryColor: string;
  secondaryColor: string;
  accentColor: string;
  platform: string;
  slides: VideoSlide[];
}

// One turn in a roundtable discussion (agent_utterance event).
interface RoundtableTurn {
  speaker: string;
  role: string;
  text: string;
  roundIndex: number;
}

// Step-mode's per-round prompt (round_control "waiting" event) — null once resolved/auto.
interface RoundControlPrompt {
  roundIndex: number;
  timeout: number | null;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  variant?: "status" | "draft" | "text-preview" | "html-preview" | "roundtable";
  platform?: Platform;
  draft?: DraftContent;
  html?: string;
  approval?: ApprovalStatus;
  timestamp: Date;
  // Workflow-specific fields — set when the message originates from the MAF pipeline.
  workflowTaskId?: string;
  needsHumanIntervention?: boolean;
  videoStoryboard?: VideoStoryboard;
  // Roundtable-specific fields (variant === "roundtable") — one card grows in place as
  // agent_utterance / discussion_consensus / round_control events land for its table.
  roundtableTableId?: string;
  roundtableTurns?: RoundtableTurn[];
  roundtableConverged?: boolean;
  roundtableStrategy?: string;
  roundControlWaiting?: RoundControlPrompt | null;
  // Set on voice turns (native speech-to-speech) once the clip is fully assembled —
  // an object URL for a WAV blob built client-side from the raw PCM16 the session
  // streamed, so the turn's audio can be replayed/downloaded from its bubble.
  audioUrl?: string;
}

const PLATFORMS: {
  id: Platform;
  label: string;
  abbr: string;
  badgeClass: string;
  headerClass: string;
}[] = [
  {
    id: "x",
    label: "X (Twitter)",
    abbr: "X",
    badgeClass: "bg-[#1B1A17] text-white",
    headerClass: "bg-[#1B1A17] text-white",
  },
  {
    id: "instagram",
    label: "Instagram",
    abbr: "IG",
    badgeClass: "bg-pink-600 text-white",
    headerClass: "bg-gradient-to-r from-purple-600 to-pink-600 text-white",
  },
  {
    id: "tiktok",
    label: "TikTok",
    abbr: "TK",
    badgeClass: "bg-[#1B1A17] text-white",
    headerClass: "bg-[#1B1A17] text-white",
  },
  {
    id: "linkedin",
    label: "LinkedIn",
    abbr: "in",
    badgeClass: "bg-blue-600 text-white",
    headerClass: "bg-blue-700 text-white",
  },
];

const CONTENT_TYPES: { id: ContentType; label: string }[] = [
  { id: "text", label: "Text" },
  { id: "video", label: "Video" },
  { id: "brand", label: "Brand Animation" },
];

const INITIAL_MESSAGES: Message[] = [
  {
    id: "1",
    role: "assistant",
    content:
      "Welcome to Starlight! I'm your AI social media content assistant. Tell me about your business, brand tone, target audience, and what you'd like to promote — I'll generate platform-specific content and walk you through the approval process.",
    timestamp: new Date(),
  },
];

const platformMap = Object.fromEntries(PLATFORMS.map((p) => [p.id, p]));

// Human-readable labels for each MAF executor shown as live status messages.
const NODE_LABELS: Record<string, string> = {
  dispatcher: "Validating brief…",
  scout: "Scouting content strategy…",
  creator: "Writing platform copy…",
  reviewer: "Running safety & brand review…",
  archivist: "Learning from your edits…",
  media_producer: "Generating brand assets…",
};

// Display name + badge colour for each roundtable persona (workflow/roundtable/personas.py).
const SPEAKER_LABELS: Record<string, { label: string; badge: string }> = {
  platform_editor: { label: "Platform Editor", badge: "bg-sky-600" },
  brand_voice: { label: "Brand Voice", badge: "bg-purple-600" },
  user_advocate: { label: "User Advocate", badge: "bg-emerald-600" },
  audience_advocate: { label: "Audience Advocate", badge: "bg-amber-600" },
  trend_scout: { label: "Trend Scout", badge: "bg-rose-600" },
  user: { label: "You", badge: "bg-[#FF4800]" },
};

function speakerInfo(speaker: string) {
  return SPEAKER_LABELS[speaker] ?? { label: speaker, badge: "bg-[#6B6561]" };
}

// Monotonic message ids — several generators append concurrently when multiple
// content types are selected, so Date.now() alone would collide.
let _msgSeq = 0;
function newId() {
  _msgSeq += 1;
  return `m${Date.now().toString(36)}-${_msgSeq}`;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>(INITIAL_MESSAGES);
  const [input, setInput] = useState("");
  const [selectedPlatforms, setSelectedPlatforms] = useState<Platform[]>([
    "instagram",
    "linkedin",
  ]);
  const [contentTypes, setContentTypes] = useState<ContentType[]>(["text"]);
  // "manual" pauses each roundtable table at round boundaries for a 4-way user prompt
  // (round_control); "auto" (default) never prompts — the backend's own default.
  const [roundtableMode, setRoundtableMode] = useState<"auto" | "manual">("auto");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Conversation history persisted for the lifetime of this page mount so each
  // request continues the same thread rather than starting a new LLM session.
  const historyRef = useRef<{ role: "user" | "assistant"; content: string }[]>([]);
  // Registered once on the first send; null until then.
  const sessionIdRef = useRef<string | null>(null);
  // The currently-growing assistant voice bubble (id + text-so-far), so streamed
  // transcript deltas update ONE message in place instead of spawning a new bubble per
  // fragment; cleared once the turn ends (persisted exactly once at that point).
  const streamingAssistantRef = useRef<{ id: string; text: string } | null>(null);
  // Active EventSource for the MAF workflow SSE stream; replaced on each new workflow run.
  const workflowEsRef = useRef<EventSource | null>(null);
  // table_id -> the id of that table's RoundtableCard message, so later agent_utterance /
  // round_control events for the same table update the SAME card instead of spawning new ones.
  const roundtableMsgIdRef = useRef<Map<string, string>>(new Map());

  /** Fire-and-forget: persist a message to the backend. Non-fatal if it fails. */
  async function persistMessage(sessionId: string, role: "user" | "assistant", content: string) {
    const token = localStorage.getItem("starlight_token");
    try {
      await fetch(`/api/sessions/${sessionId}/messages`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ role, content }),
      });
    } catch {
      // Non-fatal — message is already visible in the UI
      console.log("Persistance failure. Request not saved to session.")
    }
  }
  const [pastSessions, setPastSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [loadingSessionId, setLoadingSessionId] = useState<string | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Load the user's past sessions on mount if they're logged in.
  useEffect(() => {
    const token = localStorage.getItem("starlight_token");
    if (!token) return;
    fetch("/api/sessions", {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json())
      .then((data: SessionSummary[]) => {
        if (Array.isArray(data)) {
          setPastSessions(data.sort((a, b) => b.createdAt.localeCompare(a.createdAt)));
        }
      })
      .catch(() => {});
  }, []);

  async function loadSession(session: SessionSummary) {
    if (loadingSessionId) return;
    setLoadingSessionId(session.id);
    try {
      const token = localStorage.getItem("starlight_token");
      const res = await fetch(`/api/sessions/${session.id}/messages`, {
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      const dbMessages: DBMessage[] = await res.json();

      // Map DB messages to the chat UI format.
      const loaded: Message[] = Array.isArray(dbMessages)
        ? dbMessages.map((m) => ({
            id: String(m.messageId),
            role: m.role,
            content: m.content,
            timestamp: new Date(m.timestamp),
          }))
        : [];

      // Prepend a marker so the user knows they're viewing a past session.
      const marker: Message = {
        id: `resume-${session.id}`,
        role: "assistant",
        content: `Session resumed from ${formatDate(session.createdAt)}.`,
        timestamp: new Date(),
      };

      setMessages(loaded.length > 0 ? loaded : [marker]);
      historyRef.current = loaded
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));
      sessionIdRef.current = session.id;
      setActiveSessionId(session.id);
    } catch (err) {
      console.error("Failed to load session:", err);
    } finally {
      setLoadingSessionId(null);
    }
  }

  function formatDate(isoString: string) {
    try {
      return new Date(isoString).toLocaleDateString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return isoString;
    }
  }

  function togglePlatform(platform: Platform) {
    setSelectedPlatforms((prev) =>
      prev.includes(platform)
        ? prev.filter((p) => p !== platform)
        : [...prev, platform]
    );
  }

  function toggleContentType(type: ContentType) {
    setContentTypes((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type]
    );
  }

  function handleApproval(messageId: string, approval: ApprovalStatus) {
    const msg = messages.find((m) => m.id === messageId);
    const platformLabel = platformMap[msg?.platform ?? ""]?.label ?? "platform";

    setMessages((prev) =>
      prev.map((m) => (m.id === messageId ? { ...m, approval } : m))
    );

    // For workflow drafts, submit the verdict to the human gate so the MAF
    // pipeline can continue (media_producer runs after approval, creator re-drafts after reject).
    if (msg?.workflowTaskId && msg.platform) {
      const decision = approval === "approved" ? "approve" : "reject";
      fetch(`/api/tasks/${msg.workflowTaskId}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verdicts: { [msg.platform]: { decision } } }),
      }).catch(() => {
        // Non-fatal: the SSE stream will surface an error event if the review fails.
      });
    }

    setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now().toString(),
          role: "assistant",
          content:
            approval === "approved"
              ? `✓ ${platformLabel} content approved and queued for publishing.`
              : `Noted. Regenerating ${platformLabel} content with your feedback in mind...`,
          variant: approval === "rejected" ? "status" : undefined,
          timestamp: new Date(),
        },
      ]);
    }, 350);
  }

  function pushMessage(msg: Omit<Message, "id" | "timestamp">, insertBeforeId?: string): string {
    const id = newId();
    const full: Message = { ...msg, id, timestamp: new Date() };
    setMessages((prev) => {
      const idx = insertBeforeId ? prev.findIndex((m) => m.id === insertBeforeId) : -1;
      if (idx === -1) return [...prev, full];
      return [...prev.slice(0, idx), full, ...prev.slice(idx)];
    });
    return id;
  }

  // ── Roundtable card helpers — one growing card per table_id ──────────────────

  /** Appends one turn to a table's card, creating the card on the first turn. */
  function upsertRoundtableTurn(taskId: string, tableId: string, turn: RoundtableTurn) {
    setMessages((prev) => {
      const existingId = roundtableMsgIdRef.current.get(tableId);
      if (existingId) {
        return prev.map((m) =>
          m.id === existingId
            ? { ...m, roundtableTurns: [...(m.roundtableTurns ?? []), turn] }
            : m
        );
      }
      const id = newId();
      roundtableMsgIdRef.current.set(tableId, id);
      const msg: Message = {
        id,
        role: "assistant",
        content: `Roundtable discussion — ${tableId}:`,
        variant: "roundtable",
        platform: tableId as Platform,
        workflowTaskId: taskId,
        roundtableTableId: tableId,
        roundtableTurns: [turn],
        roundtableConverged: false,
        timestamp: new Date(),
      };
      return [...prev, msg];
    });
  }

  function finalizeRoundtable(tableId: string, strategy: Record<string, unknown> | undefined) {
    const existingId = roundtableMsgIdRef.current.get(tableId);
    if (!existingId) return;
    const summary = strategy
      ? Object.entries(strategy)
          .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
          .join(" · ")
      : undefined;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === existingId
          ? { ...m, roundtableConverged: true, roundtableStrategy: summary, roundControlWaiting: null }
          : m
      )
    );
  }

  function setRoundControlPrompt(tableId: string, prompt: RoundControlPrompt | null) {
    const existingId = roundtableMsgIdRef.current.get(tableId);
    if (!existingId) return;
    setMessages((prev) =>
      prev.map((m) => (m.id === existingId ? { ...m, roundControlWaiting: prompt } : m))
    );
  }

  // ── Per-content-type generators (each appends its own status + result) ──────

  async function genWorkflow(prompt: string) {
    pushMessage({ role: "assistant", content: "Starting the virtual newsroom…", variant: "status" });

    // Close any previous SSE stream before opening a new one.
    if (workflowEsRef.current) {
      workflowEsRef.current.close();
      workflowEsRef.current = null;
    }
    // Each call is a fresh task with its own tables — table_ids (== platform names) are
    // reused across runs, so a stale map entry would otherwise append onto a dead card.
    roundtableMsgIdRef.current.clear();

    // 1. Start the MAF workflow task.
    let taskId: string;
    try {
      const res = await fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: prompt,
          target_platforms: selectedPlatforms,
          user_intent: prompt,
          content_types: contentTypes,
          roundtable_mode: roundtableMode,
        }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        pushMessage({ role: "assistant", content: `Workflow failed to start: ${data.error ?? "unknown error"}` });
        return;
      }
      taskId = data.task_id as string;
    } catch {
      pushMessage({ role: "assistant", content: "Could not reach the workflow backend." });
      return;
    }

    // 2. Open the SSE stream and handle events as they arrive.
    // genWorkflow() returns here so handleSend() isn't blocked — events fire asynchronously.
    const es = new EventSource(`/api/tasks/${taskId}/events`);
    workflowEsRef.current = es;
    const seenNodes = new Set<string>();
    // GET /tasks/{id}/events replays its full buffer on every (re)connect, including after
    // the browser's automatic EventSource reconnect on a dropped connection. Each event
    // carries a stable per-task `seq`; skip anything at or below the last one we've already
    // acted on so a replay can't re-fire side effects (e.g. double-submitting /review).
    let lastSeq = -1;

    es.onmessage = (e) => {
      let event: Record<string, unknown>;
      try { event = JSON.parse(e.data as string); } catch { return; }

      const seq = event.seq as number | undefined;
      if (typeof seq === "number") {
        if (seq <= lastSeq) return;
        lastSeq = seq;
      }

      const type = event.type as string;
      const node = event.node as string;
      const status = event.status as string;
      const platform = event.platform as string | undefined;

      if (type === "progress") {
        // Show each executor once per platform to avoid duplicate status lines.
        if (status === "running") {
          const key = `${node}-${platform ?? ""}`;
          if (!seenNodes.has(key)) {
            seenNodes.add(key);
            const label = NODE_LABELS[node];
            if (label) {
              pushMessage({
                role: "assistant",
                content: platform ? `[${platform}] ${label}` : label,
                variant: "status",
              });
            }
          }
        }
        if (node === "workflow" && status === "done") {
          es.close();
          workflowEsRef.current = null;
        }
      }

      // agent_utterance: one roundtable persona (or the user) spoke — grow that table's card.
      if (type === "agent_utterance") {
        const tableId = event.table_id as string;
        upsertRoundtableTurn(taskId, tableId, {
          speaker: event.speaker as string,
          role: event.role as string,
          text: event.text as string,
          roundIndex: event.round_index as number,
        });
      }

      // discussion_consensus: the table converged on a strategy before drafting starts.
      if (type === "result" && status === "discussion_consensus") {
        finalizeRoundtable(event.table_id as string, event.strategy as Record<string, unknown> | undefined);
      }

      // round_control: step mode (roundtable_mode: "manual") pausing at a round boundary.
      if (type === "round_control") {
        const tableId = event.table_id as string;
        if ((event.status as string) === "waiting") {
          setRoundControlPrompt(tableId, {
            roundIndex: event.round_index as number,
            timeout: (event.timeout as number | null) ?? null,
          });
        } else {
          setRoundControlPrompt(tableId, null);
        }
      }

      // draft_ready: the human gate has paused.
      // If the user wants a text draft, show the DraftCard for manual approval.
      // If they only want brand/video assets, auto-approve so media_producer runs
      // immediately — they never asked to review the underlying text copy.
      if (type === "result" && status === "draft_ready") {
        if (contentTypes.includes("text")) {
          pushMessage({
            role: "assistant",
            content: `Here's your ${platform} draft — approve or request changes:`,
            variant: "text-preview",
            platform: platform as Platform,
            draft: { text: event.draft as string },
            workflowTaskId: taskId,
            needsHumanIntervention: (event.needs_human_intervention as boolean) ?? false,
            approval: "pending",
          });
          if (sessionIdRef.current) {
            persistMessage(sessionIdRef.current, "assistant", event.draft as string);
          }
        } else {
          // Auto-approve: submit verdict immediately so media_producer can run.
          fetch(`/api/tasks/${taskId}/review`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ verdicts: { [platform as string]: { decision: "approve" } } }),
          }).catch(() => {});
        }
      }

      // final: approved draft + media assets from media_producer.
      if (type === "result" && status === "final") {
        historyRef.current = [
          ...historyRef.current,
          { role: "assistant", content: event.draft as string },
        ];
        if (sessionIdRef.current) {
          persistMessage(sessionIdRef.current, "assistant", event.draft as string);
        }
        // Only render the brand animation card when the user selected "Brand Animation".
        if (event.html_preview && contentTypes.includes("brand")) {
          pushMessage({
            role: "assistant",
            content: `Brand animation — ${platform}:`,
            variant: "html-preview",
            html: event.html_preview as string,
            approval: "approved",
          });
        }
        // Only render the storyboard card when the user selected "Video". The
        // storyboard is data only at this point — rendering the MP4 is a separate,
        // explicitly-triggered job (see VideoStoryboardCard's "Render Video" button).
        if (event.video_storyboard && contentTypes.includes("video")) {
          pushMessage({
            role: "assistant",
            content: `Brand video storyboard — ${platform}:`,
            videoStoryboard: event.video_storyboard as VideoStoryboard,
            platform: platform as Platform,
            workflowTaskId: taskId,
            approval: "approved",
          });
        }
      }
    };

    es.onerror = () => {
      if (workflowEsRef.current === es) {
        es.close();
        workflowEsRef.current = null;
      }
    };
  }

  async function genBrand(prompt: string) {
    pushMessage({
      role: "assistant",
      content: "Generating brand animation — this can take up to a minute…",
      variant: "status",
    });
    try {
      const res = await fetch("/api/brand", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, history: historyRef.current }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        pushMessage({ role: "assistant", content: `Brand animation failed: ${data.error ?? "unknown error"}` });
        return;
      }
      historyRef.current = [
        ...historyRef.current,
        { role: "assistant", content: "[brand animation generated]" },
      ];
      if (sessionIdRef.current) {
        persistMessage(sessionIdRef.current, "assistant", "[brand animation generated]");
      }
      pushMessage({
        role: "assistant",
        content: "Here's your brand animation. Review and approve or reject:",
        variant: "html-preview",
        html: data.html as string,
        approval: "pending",
      });
    } catch {
      pushMessage({ role: "assistant", content: "Could not reach the brand backend." });
    }
  }

  // ── Voice (native speech-to-speech, direct WS to LLM_service) ────────────────
  // MVP: bypasses the Java backend (no WS infra there yet). Registers/reuses the same
  // session_id the typed-chat path uses, then hands the finished brief to genWorkflow —
  // the exact same downstream pipeline a typed message drives.
  const voice = useRealtimeVoice({
    targetPlatforms: selectedPlatforms,
    onTranscript: (role, fullText, isNewTurn, audioUrl) => {
      if (role === "user") {
        // The user's turn arrives as one complete transcript (Whisper delivers the
        // whole segment at once, not deltas) — one bubble, persisted immediately.
        // The model can start replying before this catches up (transcription is a
        // side channel, never a gate on it), so if the assistant's bubble for this
        // exchange is already open, insert the user's bubble BEFORE it — otherwise
        // the conversation reads out of order despite arriving in this order.
        pushMessage({ role: "user", content: fullText, audioUrl }, streamingAssistantRef.current?.id);
        if (sessionIdRef.current) persistMessage(sessionIdRef.current, "user", fullText);
        return;
      }
      // The assistant streams many small deltas per turn — grow ONE bubble in place
      // instead of spawning a new one per fragment. Persisted once in onTurnEnd below.
      if (isNewTurn || !streamingAssistantRef.current) {
        const id = pushMessage({ role: "assistant", content: fullText });
        streamingAssistantRef.current = { id, text: fullText };
      } else {
        const { id } = streamingAssistantRef.current;
        streamingAssistantRef.current.text = fullText;
        setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, content: fullText } : m)));
      }
    },
    onTurnEnd: (audioUrl) => {
      const streaming = streamingAssistantRef.current;
      if (streaming) {
        if (sessionIdRef.current) persistMessage(sessionIdRef.current, "assistant", streaming.text);
        if (audioUrl) {
          setMessages((prev) => prev.map((m) => (m.id === streaming.id ? { ...m, audioUrl } : m)));
        }
      }
      streamingAssistantRef.current = null;
    },
    onComplete: (briefPartial: VoiceBriefPartial) => {
      if (briefPartial.topic) {
        void genWorkflow(briefPartial.topic);
      }
    },
    onError: (message) => {
      pushMessage({ role: "assistant", content: `Voice error: ${message}` });
    },
  });

  async function handleMicToggle() {
    if (voice.status === "recording" || voice.status === "connecting") {
      voice.stop();
      return;
    }
    let sessionId = sessionIdRef.current;
    if (!sessionId) {
      const newId = `sess-${crypto.randomUUID()}`;
      sessionId = newId;
      sessionIdRef.current = newId;
      setActiveSessionId(newId);
      setPastSessions((prev) => [
        { id: newId, createdAt: new Date().toISOString(), status: "running", targetPlatforms: selectedPlatforms },
        ...prev,
      ]);
    }
    await voice.start(sessionId);
  }

  async function handleSend() {
    const trimmed = input.trim();
    if (!trimmed || isLoading || contentTypes.length === 0) return;

    pushMessage({ role: "user", content: trimmed });
    historyRef.current = [...historyRef.current, { role: "user", content: trimmed }];
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }

    // Register a new session in the backend on the first message of each chat.
    if (sessionIdRef.current === null) {
      try {
        const token = localStorage.getItem("starlight_token");
        const res = await fetch("/api/sessions", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ opening_input: trimmed }),
        });
        const data = await res.json();
        if (res.ok && data.session_id) {
          sessionIdRef.current = data.session_id;
          setActiveSessionId(data.session_id);
          setPastSessions((prev) => [
            { id: data.session_id, createdAt: new Date().toISOString(), status: "running", targetPlatforms: selectedPlatforms },
            ...prev,
          ]);
        }
      } catch (err) {
        console.error("Session registration failed:", err);
      }
    }

    // Persist the user message now that we have a session ID.
    if (sessionIdRef.current) {
      persistMessage(sessionIdRef.current, "user", trimmed);
    }

    // Single workflow call — the MAF pipeline generates text drafts, brand
    // animations, and video specs in one pass. genWorkflow() gates which output
    // cards are shown based on the current contentTypes selection.
    const jobs: Promise<void>[] = [];
    jobs.push(genWorkflow(trimmed));

    setIsLoading(true);
    try {
      await Promise.allSettled(jobs);
    } finally {
      setIsLoading(false);
    }
  }

  function handleTextareaChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = `${Math.min(e.target.scrollHeight, 128)}px`;
  }

  function formatTime(date: Date) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  return (
    <div className="flex h-screen bg-[#F8F5EE] text-[#1B1A17] overflow-hidden">
      {/* Sidebar */}
      <aside
        className={`${
          sidebarOpen ? "w-72" : "w-0"
        } transition-all duration-200 overflow-hidden flex-shrink-0 border-r border-[#E8E3DA] flex flex-col bg-white`}
      >
        <div className="p-5 border-b border-[#E8E3DA] flex-shrink-0">
          <Link
            href="/"
            className="flex items-center gap-2 font-bold text-lg text-[#1B1A17] hover:text-[#FF4800] transition-colors"
          >
            ✦ Starlight
          </Link>
          <p className="text-xs text-[#9E9893] mt-0.5">AI Content Assistant</p>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-7">
          {/* Past Sessions */}
          {pastSessions.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-[#9E9893] uppercase tracking-wider mb-3">
                Past Sessions
              </h3>
              <div className="space-y-1.5">
                {pastSessions.map((s) => {
                  const isActive = s.id === activeSessionId;
                  const isLoading = s.id === loadingSessionId;
                  return (
                    <button
                      key={s.id}
                      onClick={() => loadSession(s)}
                      disabled={isLoading}
                      className={`w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors ${
                        isActive
                          ? "bg-[#FFF0EB] border border-[#FFCBB8] text-[#FF4800]"
                          : "text-[#6B6561] hover:text-[#1B1A17] hover:bg-[#F2EDE4]"
                      } disabled:opacity-50`}
                    >
                      <p className="font-medium text-xs truncate">
                        {isLoading ? "Loading…" : formatDate(s.createdAt)}
                      </p>
                      {s.targetPlatforms && s.targetPlatforms.length > 0 && (
                        <p className="text-[10px] text-[#9E9893] mt-0.5 truncate">
                          {s.targetPlatforms.join(", ")}
                        </p>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Platforms */}
          <div>
            <h3 className="text-xs font-semibold text-[#9E9893] uppercase tracking-wider mb-3">
              Platforms
            </h3>
            <div className="space-y-1.5">
              {PLATFORMS.map((p) => {
                const active = selectedPlatforms.includes(p.id);
                return (
                  <button
                    key={p.id}
                    onClick={() => togglePlatform(p.id)}
                    className={`flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm transition-colors ${
                      active
                        ? "bg-[#FFF0EB] text-[#FF4800] border border-[#FFCBB8]"
                        : "text-[#6B6561] hover:text-[#1B1A17] hover:bg-[#F2EDE4]"
                    }`}
                  >
                    <span
                      className={`w-6 h-6 rounded flex items-center justify-center text-xs font-bold flex-shrink-0 ${p.badgeClass}`}
                    >
                      {p.abbr}
                    </span>
                    <span>{p.label}</span>
                    {active && (
                      <span className="ml-auto w-1.5 h-1.5 rounded-full bg-[#FF4800] flex-shrink-0" />
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Content Type (multi-select) */}
          <div>
            <h3 className="text-xs font-semibold text-[#9E9893] uppercase tracking-wider mb-3">
              Content Type
              <span className="ml-1 normal-case font-normal text-[#BDB6AE]">
                · choose one or more
              </span>
            </h3>
            <div className="grid grid-cols-2 gap-2">
              {CONTENT_TYPES.map((ct) => {
                const active = contentTypes.includes(ct.id);
                return (
                  <button
                    key={ct.id}
                    onClick={() => toggleContentType(ct.id)}
                    aria-pressed={active}
                    className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                      ct.id === "brand" ? "col-span-2" : ""
                    } ${
                      active
                        ? "bg-[#FF4800] text-white"
                        : "bg-[#F8F5EE] text-[#6B6561] border border-[#E8E3DA] hover:bg-[#E8E3DA] hover:text-[#1B1A17]"
                    }`}
                  >
                    {ct.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Roundtable discussion mode */}
          <div>
            <h3 className="text-xs font-semibold text-[#9E9893] uppercase tracking-wider mb-3">
              Roundtable
            </h3>
            <button
              onClick={() => setRoundtableMode((m) => (m === "auto" ? "manual" : "auto"))}
              aria-pressed={roundtableMode === "manual"}
              className={`flex items-center justify-between w-full px-3 py-2 rounded-lg text-sm transition-colors border ${
                roundtableMode === "manual"
                  ? "bg-[#FFF0EB] text-[#FF4800] border-[#FFCBB8]"
                  : "text-[#6B6561] border-[#E8E3DA] hover:bg-[#F2EDE4]"
              }`}
            >
              <span>Join the discussion</span>
              <span
                className={`w-9 h-5 rounded-full relative transition-colors flex-shrink-0 ${
                  roundtableMode === "manual" ? "bg-[#FF4800]" : "bg-[#E8E3DA]"
                }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                    roundtableMode === "manual" ? "translate-x-4" : "translate-x-0"
                  }`}
                />
              </span>
            </button>
            <p className="text-[10px] text-[#BDB6AE] mt-1.5 leading-relaxed">
              When on, each table pauses for your call between rounds (next / speak / enough /
              auto). Off runs the discussion hands-off.
            </p>
          </div>

        </div>
      </aside>

      {/* Chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="flex items-center justify-between px-5 py-4 border-b border-[#E8E3DA] bg-white flex-shrink-0">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="text-[#9E9893] hover:text-[#1B1A17] transition-colors p-1 rounded"
              aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
            >
              <svg width="18" height="14" viewBox="0 0 18 14" fill="none" aria-hidden="true">
                <rect width="18" height="2" rx="1" fill="currentColor" />
                <rect y="6" width="18" height="2" rx="1" fill="currentColor" />
                <rect y="12" width="18" height="2" rx="1" fill="currentColor" />
              </svg>
            </button>
            <div>
              <h1 className="font-semibold text-sm text-[#1B1A17]">
                {activeSessionId ? `Session ${activeSessionId}` : "New Session"}
              </h1>
              <p className="text-xs text-[#9E9893] mt-0.5">
                {selectedPlatforms.length} platform
                {selectedPlatforms.length !== 1 ? "s" : ""} ·{" "}
                {contentTypes.length ? contentTypes.join(", ") : "no"} content
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            {selectedPlatforms.map((pid) => {
              const p = platformMap[pid];
              return (
                <span
                  key={pid}
                  className={`text-xs font-bold px-2.5 py-1 rounded-full ${p.badgeClass}`}
                >
                  {p.abbr}
                </span>
              );
            })}
          </div>
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-5">
          {messages.map((msg) => {
            // Workflow final event: storyboard delivered directly (no job polling
            // needed for this part) — actually rendering the MP4 is a separate,
            // explicitly-triggered job the card kicks off on demand.
            if (msg.videoStoryboard) {
              return (
                <VideoStoryboardCard key={msg.id} message={msg} formatTime={formatTime} />
              );
            }

            if (msg.variant === "roundtable") {
              return <RoundtableCard key={msg.id} message={msg} formatTime={formatTime} />;
            }

            if (msg.variant === "html-preview" && msg.html) {
              return (
                <BrandAnimationCard
                  key={msg.id}
                  message={msg}
                  onApprove={() => handleApproval(msg.id, "approved")}
                  onReject={() => handleApproval(msg.id, "rejected")}
                  formatTime={formatTime}
                />
              );
            }

            if (
              (msg.variant === "draft" || msg.variant === "text-preview") &&
              msg.draft &&
              msg.platform
            ) {
              return (
                <DraftCard
                  key={msg.id}
                  message={msg}
                  onApprove={() => handleApproval(msg.id, "approved")}
                  onReject={() => handleApproval(msg.id, "rejected")}
                  formatTime={formatTime}
                />
              );
            }

            if (msg.variant === "status") {
              return (
                <div
                  key={msg.id}
                  className="flex items-center gap-2 text-sm text-[#9E9893] italic"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-[#FF4800] animate-pulse flex-shrink-0" />
                  {msg.content}
                </div>
              );
            }

            return (
              <div
                key={msg.id}
                className={`flex ${
                  msg.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                <div
                  className={`max-w-[68%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                    msg.role === "user"
                      ? "bg-[#FF4800] text-white rounded-br-sm shadow-sm"
                      : "bg-white text-[#1B1A17] border border-[#E8E3DA] rounded-bl-sm shadow-sm"
                  }`}
                >
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                  {msg.audioUrl && (
                    <div className="mt-2 flex items-center gap-2">
                      <audio controls src={msg.audioUrl} className="h-8 max-w-[220px]" />
                      <a
                        href={msg.audioUrl}
                        download={`voice-${msg.role}-${msg.id}.wav`}
                        className={`text-xs underline flex-shrink-0 ${
                          msg.role === "user" ? "text-[#FFCBB8] hover:text-white" : "text-[#9E9893] hover:text-[#1B1A17]"
                        }`}
                        aria-label="Download audio"
                        title="Download audio"
                      >
                        Save
                      </a>
                    </div>
                  )}
                  <p
                    className={`text-xs mt-2 ${
                      msg.role === "user" ? "text-[#FFCBB8]" : "text-[#9E9893]"
                    }`}
                  >
                    {formatTime(msg.timestamp)}
                  </p>
                </div>
              </div>
            );
          })}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="px-6 py-4 border-t border-[#E8E3DA] bg-white flex-shrink-0">
          <div className="flex gap-3 items-end">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={handleTextareaChange}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="Type a message or revision request… (Enter to send, Shift+Enter for new line)"
              className="flex-1 bg-[#F8F5EE] border border-[#E8E3DA] rounded-xl px-4 py-3 text-sm text-[#1B1A17] placeholder:text-[#9E9893] resize-none focus:outline-none focus:border-[#FF4800] transition-colors"
              rows={1}
            />
            <button
              onClick={handleMicToggle}
              disabled={isLoading || voice.status === "connecting"}
              className={`p-3 rounded-xl transition-colors flex-shrink-0 disabled:opacity-40 disabled:cursor-not-allowed ${
                voice.status === "recording"
                  ? "bg-[#FF4800] text-white hover:bg-[#E03E00]"
                  : "bg-[#F8F5EE] text-[#6B6561] border border-[#E8E3DA] hover:text-[#1B1A17] hover:bg-[#F2EDE4]"
              }`}
              aria-label={voice.status === "recording" ? "Stop recording" : "Record voice message"}
              title={voice.status === "recording" ? "Stop recording" : "Record voice message"}
            >
              {voice.status === "recording" ? (
                <span className="relative flex items-center justify-center w-4 h-4">
                  <span className="absolute inline-flex h-full w-full rounded-full bg-white opacity-40 animate-ping" />
                  <span className="relative inline-flex rounded-sm h-2.5 w-2.5 bg-white" />
                </span>
              ) : (
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <rect x="5.5" y="1" width="5" height="8" rx="2.5" fill="currentColor" />
                  <path
                    d="M3 7.5a5 5 0 0 0 10 0M8 12.5v2.5"
                    stroke="currentColor"
                    strokeWidth="1.3"
                    strokeLinecap="round"
                    fill="none"
                  />
                </svg>
              )}
            </button>
            <button
              onClick={handleSend}
              disabled={!input.trim() || isLoading}
              className="bg-[#FF4800] hover:bg-[#E03E00] disabled:opacity-40 disabled:cursor-not-allowed text-white p-3 rounded-xl transition-colors flex-shrink-0"
              aria-label="Send message"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path d="M14 8L2 2l2.5 6L2 14l12-6z" fill="currentColor" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

interface DraftCardProps {
  message: Message;
  onApprove: () => void;
  onReject: () => void;
  formatTime: (d: Date) => string;
}

// ── Brand Video Storyboard Card ───────────────────────────────────────────────

interface VideoStoryboardCardProps {
  message: Message;
  formatTime: (d: Date) => string;
}

const SLIDE_ICON: Record<VideoSlide["type"], string> = {
  hook: "🎬",
  counter_stat: "🔢",
  collage: "🖼️",
  outro: "🏁",
  pie_chart: "🥧",
  line_chart: "📈",
  bar_chart: "📊",
  node_diagram: "🔗",
  comparison_table: "📋",
  generated: "✨",
};

function slideSummary(slide: VideoSlide): string {
  switch (slide.type) {
    case "hook":
      return slide.headline;
    case "counter_stat":
      return `${slide.stats.length} stat${slide.stats.length === 1 ? "" : "s"}`;
    case "collage":
      return `${slide.imageQueries.length} image${slide.imageQueries.length === 1 ? "" : "s"}`;
    case "outro":
      return slide.ctaLabel;
    case "pie_chart":
      return `${slide.slices.length} slice${slide.slices.length === 1 ? "" : "s"}`;
    case "line_chart":
      return `${slide.series.length} series over ${slide.xLabels.length} points`;
    case "bar_chart":
      return `${slide.bars.length} bar${slide.bars.length === 1 ? "" : "s"}`;
    case "node_diagram":
      return slide.nodes.join(" → ");
    case "comparison_table":
      return `${slide.rows.length} row${slide.rows.length === 1 ? "" : "s"} × ${slide.columns.length} col${slide.columns.length === 1 ? "" : "s"}`;
    case "generated":
      return `custom scene — ${slide.description}`;
  }
}

/**
 * Shows the dynamically-composed storyboard the agent picked (palette + ordered
 * slide list) immediately — no polling needed, it's already in hand from the
 * result/final SSE event. Rendering the actual MP4 is a separate, explicitly
 * triggered job: clicking "Render Video" posts {taskId, platform} to /api/video,
 * polls /api/video/[jobId] until done, then swaps the preview for a real
 * <video> player sourced from the finished download.
 */
function VideoStoryboardCard({ message, formatTime }: VideoStoryboardCardProps) {
  const storyboard = message.videoStoryboard!;
  const [renderState, setRenderState] = useState<"idle" | "pending" | "done" | "error">("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);

  async function startRender() {
    if (!message.workflowTaskId || !message.platform) return;
    setRenderState("pending");
    setError(null);
    setElapsed(0);
    try {
      const res = await fetch("/api/video", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ taskId: message.workflowTaskId, platform: message.platform }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        setRenderState("error");
        setError(data.error ?? "Could not start the render.");
        return;
      }
      setJobId(data.jobId as string);
    } catch {
      setRenderState("error");
      setError("Could not reach the video backend.");
    }
  }

  useEffect(() => {
    if (renderState !== "pending" || !jobId) return;

    // Render is a local Remotion CLI subprocess (asset fetch + headless Chromium) —
    // tens of seconds, so poll every 3s rather than the storyboard's near-instant cadence.
    const poll = setInterval(async () => {
      try {
        const res = await fetch(`/api/video/${jobId}`);
        const data = await res.json();
        if (data.status === "done") {
          setDownloadUrl(data.downloadUrl as string);
          setRenderState("done");
        } else if (data.status === "error") {
          setRenderState("error");
          setError(data.error ?? "Render failed.");
        }
      } catch {
        // transient network error — keep polling
      }
    }, 3000);

    const tick = setInterval(() => setElapsed((s) => s + 1), 1000);

    return () => {
      clearInterval(poll);
      clearInterval(tick);
    };
  }, [renderState, jobId]);

  return (
    <div className="w-full max-w-sm">
      <p className="text-sm text-[#6B6561] mb-2">{message.content}</p>
      <div className="bg-white border border-[#E8E3DA] rounded-2xl overflow-hidden shadow-sm">
        <div className="flex items-center px-4 py-2.5 bg-[#1B1A17] text-white">
          <span className="text-sm font-semibold">✦ Brand Video Storyboard</span>
        </div>

        <div className="bg-[#F8F5EE] p-3">
          {renderState === "done" && downloadUrl ? (
            <video src={downloadUrl} controls autoPlay className="w-full rounded-lg bg-black" />
          ) : (
            <StoryboardPreview storyboard={storyboard} />
          )}

          {renderState === "pending" && (
            <div className="flex flex-col items-center justify-center gap-2 text-[#9E9893] py-4">
              <svg className="animate-spin" width={28} height={28} viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="#E8E3DA" strokeWidth="3" />
                <path d="M12 2a10 10 0 0 1 10 10" stroke="#FF4800" strokeWidth="3" strokeLinecap="round" />
              </svg>
              <p className="text-xs font-medium text-center">Rendering video… {elapsed}s elapsed</p>
            </div>
          )}

          {renderState === "error" && (
            <p className="text-xs text-red-500 text-center mt-3">{error}</p>
          )}
        </div>

        {(renderState === "idle" || renderState === "error") && (
          <div className="px-4 pt-1 pb-4">
            <button
              onClick={startRender}
              className="w-full bg-[#FF4800] hover:bg-[#E03E00] text-white text-sm font-medium py-2 rounded-lg transition-colors"
            >
              {renderState === "error" ? "Retry Render" : "Render Video"}
            </button>
          </div>
        )}

        <p className="text-xs text-[#9E9893] px-4 pb-3">
          {formatTime(message.timestamp)}
        </p>
      </div>
    </div>
  );
}

// ── Roundtable Card ───────────────────────────────────────────────────────────

interface RoundtableCardProps {
  message: Message;
  formatTime: (d: Date) => string;
}

/**
 * One growing card per discussion table: renders every agent_utterance turn so far,
 * in order, and — while roundtable_mode is "manual" — the step-mode 4-way prompt
 * (next / speak / enough / auto) whenever the table pauses at a round boundary. A
 * "raise hand" control is always available regardless of mode, letting the user
 * inject a message into an otherwise hands-off ("auto") discussion.
 */
function RoundtableCard({ message, formatTime }: RoundtableCardProps) {
  const [handRaised, setHandRaised] = useState(false);
  const [sayText, setSayText] = useState("");
  const [speakText, setSpeakText] = useState("");
  const [busy, setBusy] = useState(false);

  const taskId = message.workflowTaskId;
  const tableId = message.roundtableTableId;
  const turns = message.roundtableTurns ?? [];
  const waiting = message.roundControlWaiting;

  async function postJson(url: string, body: unknown) {
    try {
      await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch {
      // Non-fatal — the SSE stream stays the source of truth; the user can retry.
    }
  }

  async function handleRaiseHand() {
    if (!taskId || !tableId) return;
    setHandRaised(true);
    await postJson(`/api/tasks/${taskId}/raise-hand`, { table_id: tableId });
  }

  async function handleSay() {
    if (!taskId || !tableId || !sayText.trim()) return;
    setBusy(true);
    await postJson(`/api/tasks/${taskId}/say`, { table_id: tableId, text: sayText.trim() });
    setSayText("");
    setHandRaised(false);
    setBusy(false);
  }

  async function handleRoundControl(action: "next" | "speak" | "enough" | "auto") {
    if (!taskId || !tableId) return;
    setBusy(true);
    const text = action === "speak" && speakText.trim() ? speakText.trim() : undefined;
    await postJson(`/api/tasks/${taskId}/round-control`, {
      table_id: tableId,
      action,
      ...(text ? { text } : {}),
    });
    setSpeakText("");
    setBusy(false);
  }

  return (
    <div className="w-full max-w-lg">
      <p className="text-sm text-[#6B6561] mb-2">{message.content}</p>
      <div className="bg-white border border-[#E8E3DA] rounded-2xl overflow-hidden shadow-sm">
        <div className="flex items-center justify-between px-4 py-2.5 bg-[#1B1A17] text-white">
          <span className="text-sm font-semibold">🗣️ Roundtable — {tableId}</span>
          {message.roundtableConverged && (
            <span className="text-xs bg-green-500 text-white px-2 py-0.5 rounded-full font-medium">
              Converged
            </span>
          )}
        </div>

        <div className="max-h-72 overflow-y-auto p-4 space-y-3 bg-[#F8F5EE]">
          {turns.length === 0 && (
            <p className="text-xs text-[#9E9893] italic">Waiting for the first speaker…</p>
          )}
          {turns.map((turn, i) => {
            const info = speakerInfo(turn.speaker);
            return (
              <div key={i} className="bg-white border border-[#E8E3DA] rounded-xl px-3 py-2">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`text-[10px] font-bold text-white px-1.5 py-0.5 rounded ${info.badge}`}
                  >
                    {info.label}
                  </span>
                  <span className="text-[10px] text-[#9E9893]">round {turn.roundIndex}</span>
                </div>
                <p className="text-sm text-[#1B1A17] whitespace-pre-wrap leading-relaxed">
                  {turn.text}
                </p>
              </div>
            );
          })}
        </div>

        {waiting && !message.roundtableConverged && (
          <div className="px-4 pt-2 pb-3 border-t border-[#E8E3DA] space-y-2">
            <p className="text-xs text-[#9E9893]">
              The table is waiting for your call — round {waiting.roundIndex}
              {waiting.timeout ? ` (goes hands-off in ~${Math.round(waiting.timeout)}s)` : ""}.
            </p>
            <div className="flex gap-2">
              <button
                disabled={busy}
                onClick={() => handleRoundControl("next")}
                className="flex-1 bg-[#F2EDE4] hover:bg-[#E8E3DA] text-[#1B1A17] text-xs font-medium py-1.5 rounded-lg transition-colors disabled:opacity-40"
              >
                Next
              </button>
              <button
                disabled={busy}
                onClick={() => handleRoundControl("enough")}
                className="flex-1 bg-[#F2EDE4] hover:bg-[#E8E3DA] text-[#1B1A17] text-xs font-medium py-1.5 rounded-lg transition-colors disabled:opacity-40"
              >
                Enough
              </button>
              <button
                disabled={busy}
                onClick={() => handleRoundControl("auto")}
                className="flex-1 bg-[#F2EDE4] hover:bg-[#E8E3DA] text-[#1B1A17] text-xs font-medium py-1.5 rounded-lg transition-colors disabled:opacity-40"
              >
                Auto
              </button>
            </div>
            <div className="flex gap-2">
              <input
                value={speakText}
                onChange={(e) => setSpeakText(e.target.value)}
                placeholder="Say something to the table…"
                className="flex-1 bg-white border border-[#E8E3DA] rounded-lg px-3 py-1.5 text-xs text-[#1B1A17] placeholder:text-[#9E9893] focus:outline-none focus:border-[#FF4800]"
              />
              <button
                disabled={busy || !speakText.trim()}
                onClick={() => handleRoundControl("speak")}
                className="bg-[#FF4800] hover:bg-[#E03E00] disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
              >
                Speak
              </button>
            </div>
          </div>
        )}

        {!message.roundtableConverged && !waiting && (
          <div className="px-4 pt-2 pb-3 border-t border-[#E8E3DA]">
            {!handRaised ? (
              <button
                onClick={handleRaiseHand}
                className="text-xs font-medium text-[#FF4800] hover:underline"
              >
                ✋ Raise hand to join
              </button>
            ) : (
              <div className="flex gap-2">
                <input
                  value={sayText}
                  onChange={(e) => setSayText(e.target.value)}
                  placeholder="Your turn — say something…"
                  autoFocus
                  className="flex-1 bg-white border border-[#E8E3DA] rounded-lg px-3 py-1.5 text-xs text-[#1B1A17] placeholder:text-[#9E9893] focus:outline-none focus:border-[#FF4800]"
                />
                <button
                  disabled={busy || !sayText.trim()}
                  onClick={handleSay}
                  className="bg-[#FF4800] hover:bg-[#E03E00] disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
                >
                  Send
                </button>
              </div>
            )}
          </div>
        )}

        {message.roundtableConverged && message.roundtableStrategy && (
          <div className="px-4 pb-3 pt-1 text-xs text-[#6B6561] border-t border-[#E8E3DA]">
            <span className="text-[#9E9893]">Strategy: </span>
            {message.roundtableStrategy}
          </div>
        )}

        <p className="text-xs text-[#9E9893] px-4 pb-3">{formatTime(message.timestamp)}</p>
      </div>
    </div>
  );
}

/**
 * Visualises a StoryboardSpec: a poster-style hero in the brand palette, then the
 * ordered list of slides the agent chose — i.e. the data a Remotion render turns
 * into the actual video, before any image queries are resolved.
 */
function StoryboardPreview({ storyboard }: { storyboard: VideoStoryboard }) {
  return (
    <div className="flex flex-col gap-3">
      <div
        className="rounded-lg p-4 text-center"
        style={{ background: storyboard.primaryColor, color: "#fff" }}
      >
        <div className="text-lg font-bold tracking-wide" style={{ color: storyboard.secondaryColor }}>
          {storyboard.brandName}
        </div>
        <div className="flex justify-center gap-1.5 mt-3">
          {[storyboard.primaryColor, storyboard.secondaryColor, storyboard.accentColor].map((c, i) => (
            <span
              key={i}
              className="w-5 h-5 rounded-full border border-white/30"
              style={{ background: c }}
              title={c}
            />
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        {storyboard.slides.map((slide, i) => (
          <div
            key={i}
            className="flex items-center gap-2 bg-white border border-[#E8E3DA] rounded-lg px-3 py-2"
          >
            <span className="text-base">{SLIDE_ICON[slide.type]}</span>
            <div className="flex-1 min-w-0">
              <div className="text-[10px] font-semibold text-[#9E9893] uppercase tracking-wider">
                {slide.type.replace("_", " ")}
              </div>
              <div className="text-xs text-[#1B1A17] truncate">{slideSummary(slide)}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Brand Animation Card ──────────────────────────────────────────────────────

interface BrandAnimationCardProps {
  message: Message;
  onApprove: () => void;
  onReject: () => void;
  formatTime: (d: Date) => string;
}

/**
 * Renders the self-contained HTML returned by the brand agent inside a
 * sandboxed iframe. The iframe is CSS-scaled from the agent's native 360×640
 * viewport down to 240×427 so it fits comfortably in the chat column.
 */
function BrandAnimationCard({
  message,
  onApprove,
  onReject,
  formatTime,
}: BrandAnimationCardProps) {
  const approval = message.approval;

  return (
    <div className="w-full max-w-sm">
      <p className="text-sm text-[#6B6561] mb-2">{message.content}</p>
      <div className="bg-white border border-[#E8E3DA] rounded-2xl overflow-hidden shadow-sm">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2.5 bg-[#1B1A17] text-white">
          <span className="text-sm font-semibold">✦ Brand Animation</span>
          {approval === "approved" && (
            <span className="text-xs bg-green-500 text-white px-2 py-0.5 rounded-full font-medium">
              Approved
            </span>
          )}
          {approval === "rejected" && (
            <span className="text-xs bg-red-500 text-white px-2 py-0.5 rounded-full font-medium">
              Rejected
            </span>
          )}
        </div>

        {/* Scaled iframe preview — agent outputs 360×640, displayed at 240×427 */}
        <div className="flex justify-center bg-[#F8F5EE] p-3">
          <div
            className="overflow-hidden rounded-lg border border-[#E8E3DA]"
            style={{ width: 240, height: 427 }}
          >
            <iframe
              srcDoc={message.html}
              sandbox="allow-scripts"
              title="Brand animation preview"
              style={{
                width: 360,
                height: 640,
                border: "none",
                transform: "scale(0.667)",
                transformOrigin: "top left",
              }}
            />
          </div>
        </div>

        {/* Actions */}
        {approval === "pending" && (
          <div className="flex gap-2 px-4 pt-1 pb-4">
            <button
              onClick={onApprove}
              className="flex-1 bg-green-600 hover:bg-green-500 text-white text-sm font-medium py-2 rounded-lg transition-colors"
            >
              Approve
            </button>
            <button
              onClick={onReject}
              className="flex-1 bg-[#F2EDE4] hover:bg-[#E8E3DA] text-[#1B1A17] text-sm font-medium py-2 rounded-lg transition-colors border border-[#E8E3DA]"
            >
              Reject
            </button>
          </div>
        )}

        <p className="text-xs text-[#9E9893] px-4 pb-3">
          {formatTime(message.timestamp)}
        </p>
      </div>
    </div>
  );
}

// ── Draft Card ────────────────────────────────────────────────────────────────

function DraftCard({ message, onApprove, onReject, formatTime }: DraftCardProps) {
  const platform = platformMap[message.platform!];
  const draft = message.draft!;
  const approval = message.approval;
  const [postStatus, setPostStatus] = useState<"idle" | "posting" | "posted" | "error">("idle");
  const [postError, setPostError] = useState<string | null>(null);

  async function handlePostToLinkedIn() {
    const token = localStorage.getItem("starlight_token");
    if (!token) {
      setPostStatus("error");
      setPostError("Log in, then connect LinkedIn from your Brand Profile before posting.");
      return;
    }
    setPostStatus("posting");
    setPostError(null);
    const text =
      draft.hashtags && draft.hashtags.length > 0
        ? `${draft.text}\n\n${draft.hashtags.join(" ")}`
        : draft.text;
    try {
      const res = await fetch("/api/linkedin/post", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        setPostStatus("error");
        setPostError(data.error ?? "Failed to post to LinkedIn.");
        return;
      }
      setPostStatus("posted");
    } catch {
      setPostStatus("error");
      setPostError("Could not reach the backend.");
    }
  }

  return (
    <div className="w-full max-w-lg">
      <p className="text-sm text-[#6B6561] mb-2">{message.content}</p>
      <div className="bg-white border border-[#E8E3DA] rounded-2xl overflow-hidden shadow-sm">
        {/* Platform header */}
        <div
          className={`flex items-center justify-between px-4 py-2.5 ${platform.headerClass}`}
        >
          <span className="text-sm font-semibold">{platform.label}</span>
          {approval === "approved" && (
            <span className="text-xs bg-green-500 text-white px-2 py-0.5 rounded-full font-medium">
              Approved
            </span>
          )}
          {approval === "rejected" && (
            <span className="text-xs bg-red-500 text-white px-2 py-0.5 rounded-full font-medium">
              Rejected
            </span>
          )}
        </div>

        {/* Content */}
        <div className="p-4 space-y-3">
          {message.needsHumanIntervention && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-700">
              The AI reviewer flagged this draft after multiple attempts — your direct input is needed.
            </div>
          )}
          {draft.imageDesc && (
            <div className="bg-[#F8F5EE] border border-[#E8E3DA] rounded-lg px-3 py-2 text-xs text-[#6B6561]">
              <span className="text-[#9E9893]">Image prompt: </span>
              {draft.imageDesc}
            </div>
          )}
          <p className="text-sm text-[#1B1A17] whitespace-pre-wrap leading-relaxed">
            {draft.text}
          </p>
          {draft.hashtags && (
            <div className="flex flex-wrap gap-1.5">
              {draft.hashtags.map((tag) => (
                <span
                  key={tag}
                  className="text-xs text-[#FF4800] bg-[#FFF0EB] border border-[#FFCBB8] px-2 py-0.5 rounded-full"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Actions */}
        {approval === "pending" && (
          <div className="flex gap-2 px-4 pb-4">
            <button
              onClick={onApprove}
              className="flex-1 bg-green-600 hover:bg-green-500 text-white text-sm font-medium py-2 rounded-lg transition-colors"
            >
              Approve
            </button>
            <button
              onClick={onReject}
              className="flex-1 bg-[#F2EDE4] hover:bg-[#E8E3DA] text-[#1B1A17] text-sm font-medium py-2 rounded-lg transition-colors border border-[#E8E3DA]"
            >
              Reject &amp; Regenerate
            </button>
          </div>
        )}

        {approval === "approved" && message.platform === "linkedin" && (
          <div className="px-4 pb-4">
            {postStatus === "posted" ? (
              <div className="text-center py-2 rounded-xl text-sm font-medium bg-green-50 text-green-700 border border-green-200">
                ✓ Posted to LinkedIn
              </div>
            ) : (
              <button
                onClick={handlePostToLinkedIn}
                disabled={postStatus === "posting"}
                className="w-full bg-[#0A66C2] hover:bg-[#0952A0] disabled:opacity-50 text-white text-sm font-medium py-2 rounded-lg transition-colors"
              >
                {postStatus === "posting" ? "Posting…" : "Post to LinkedIn"}
              </button>
            )}
            {postStatus === "error" && postError && (
              <p className="text-xs text-red-600 mt-2 text-center">{postError}</p>
            )}
          </div>
        )}

        <p className="text-xs text-[#9E9893] px-4 pb-3">
          {formatTime(message.timestamp)}
        </p>
      </div>
    </div>
  );
}
