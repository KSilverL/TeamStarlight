"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";

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

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  variant?: "status" | "draft" | "text-preview" | "html-preview";
  platform?: Platform;
  draft?: DraftContent;
  html?: string;
  approval?: ApprovalStatus;
  timestamp: Date;
  // Workflow-specific fields — set when the message originates from the MAF pipeline.
  workflowTaskId?: string;
  needsHumanIntervention?: boolean;
  videoStoryboard?: VideoStoryboard;
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
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Conversation history persisted for the lifetime of this page mount so each
  // request continues the same thread rather than starting a new LLM session.
  const historyRef = useRef<{ role: "user" | "assistant"; content: string }[]>([]);
  // Registered once on the first send; null until then.
  const sessionIdRef = useRef<string | null>(null);
  // Active EventSource for the MAF workflow SSE stream; replaced on each new workflow run.
  const workflowEsRef = useRef<EventSource | null>(null);

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

  function pushMessage(msg: Omit<Message, "id" | "timestamp">) {
    setMessages((prev) => [...prev, { ...msg, id: newId(), timestamp: new Date() }]);
  }

  // ── Per-content-type generators (each appends its own status + result) ──────

  async function genWorkflow(prompt: string) {
    pushMessage({ role: "assistant", content: "Starting the virtual newsroom…", variant: "status" });

    // Close any previous SSE stream before opening a new one.
    if (workflowEsRef.current) {
      workflowEsRef.current.close();
      workflowEsRef.current = null;
    }

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

        <p className="text-xs text-[#9E9893] px-4 pb-3">
          {formatTime(message.timestamp)}
        </p>
      </div>
    </div>
  );
}
