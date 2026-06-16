"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";

type Platform = "x" | "instagram" | "tiktok" | "linkedin";
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

// The structured brand-video spec the backend generates (BrandVideoProps). This
// service produces the spec, not a rendered MP4 — the card renders the spec itself.
interface VideoProps {
  brandName: string;
  tagline: string;
  primaryColor: string;
  secondaryColor: string;
  accentColor: string;
  sectionLabel: string;
  stats: VideoStat[];
  headline: string;
  subtext: string;
  ctaLabel: string;
  contact: string;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  variant?:
    | "status"
    | "draft"
    | "text-preview"
    | "html-preview"
    | "video-pending"
    | "video-preview";
  platform?: Platform;
  draft?: DraftContent;
  html?: string;
  videoJobId?: string;
  approval?: ApprovalStatus;
  timestamp: Date;
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
    timestamp: new Date(Date.now() - 6 * 60 * 1000),
  },
  {
    id: "2",
    role: "user",
    content:
      "We're EcoHome Solutions — we sell sustainable bamboo home products targeting eco-conscious millennials aged 25–40. Our brand tone is warm, aspirational, and educational. We want to promote our new Bamboo Kitchen Collection across Instagram and LinkedIn.",
    timestamp: new Date(Date.now() - 5 * 60 * 1000),
  },
  {
    id: "3",
    role: "assistant",
    content:
      "Brand profile captured. Generating a multi-platform content strategy for EcoHome Solutions — Bamboo Kitchen Collection...",
    variant: "status",
    timestamp: new Date(Date.now() - 4 * 60 * 1000),
  },
  {
    id: "4",
    role: "assistant",
    content: "Here's your Instagram draft. Review and approve or reject:",
    variant: "draft",
    platform: "instagram",
    draft: {
      text: "🌿 Meet your kitchen's new best friend — the Bamboo Kitchen Collection.\n\nCrafted from 100% organic bamboo, each piece is naturally antimicrobial, carbon-negative in production, and built to last a decade. Because sustainable living shouldn't mean settling for less. 🏡",
      hashtags: [
        "#EcoHome",
        "#BambooKitchen",
        "#SustainableLiving",
        "#ZeroWaste",
        "#GreenHome",
        "#BambooDesign",
        "#ConsciousLiving",
        "#EcoConscious",
      ],
      imageDesc:
        "Flat lay of bamboo cutting boards, utensils, and storage containers on white marble with fresh green herbs",
    },
    approval: "pending",
    timestamp: new Date(Date.now() - 3 * 60 * 1000),
  },
  {
    id: "5",
    role: "assistant",
    content: "And here's your LinkedIn draft:",
    variant: "draft",
    platform: "linkedin",
    draft: {
      text: "The sustainable homewares market is projected to reach $150B by 2030 — and EcoHome Solutions is proud to be part of that shift.\n\nToday we're launching the Bamboo Kitchen Collection: premium products that prove sustainable materials can exceed conventional standards.\n\nBamboo grows 3× faster than hardwood, sequesters carbon during growth, and outlasts plastic by decades. We invite designers, buyers, and conscious consumers to explore what responsible innovation looks like.\n\nThe kitchens we design today reflect the values we leave for tomorrow.",
    },
    approval: "pending",
    timestamp: new Date(Date.now() - 2 * 60 * 1000),
  },
];

const platformMap = Object.fromEntries(PLATFORMS.map((p) => [p.id, p]));

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

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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
    const platformLabel =
      platformMap[msg?.platform ?? ""]?.label ?? "platform";

    setMessages((prev) =>
      prev.map((m) => (m.id === messageId ? { ...m, approval } : m))
    );

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

  async function genText(prompt: string) {
    pushMessage({ role: "assistant", content: "Generating post copy…", variant: "status" });
    const platform = (selectedPlatforms[0] ?? "linkedin") as Platform;
    try {
      const res = await fetch("/api/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, platform }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        pushMessage({ role: "assistant", content: `Text generation failed: ${data.error ?? "unknown error"}` });
        return;
      }
      pushMessage({
        role: "assistant",
        content: "Here's your post copy. Review and approve or reject:",
        variant: "text-preview",
        platform: data.platform as Platform,
        draft: { text: data.text as string },
        approval: "pending",
      });
    } catch {
      pushMessage({ role: "assistant", content: "Could not reach the text backend." });
    }
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
        body: JSON.stringify({ prompt }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        pushMessage({ role: "assistant", content: `Brand animation failed: ${data.error ?? "unknown error"}` });
        return;
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

  async function genVideo(prompt: string) {
    pushMessage({ role: "assistant", content: "Generating your brand video spec…", variant: "status" });
    try {
      const res = await fetch("/api/video", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brief: prompt }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        pushMessage({ role: "assistant", content: `Video spec failed: ${data.error ?? "unknown error"}` });
        return;
      }
      pushMessage({
        role: "assistant",
        content: "Here's your brand video spec:",
        variant: "video-pending",
        videoJobId: data.jobId as string,
        approval: "pending",
      });
    } catch {
      pushMessage({ role: "assistant", content: "Could not reach the video backend." });
    }
  }

  async function handleSend() {
    const trimmed = input.trim();
    if (!trimmed || isLoading || contentTypes.length === 0) return;

    pushMessage({ role: "user", content: trimmed });
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }

    // Fan out to every selected content type at once.
    const jobs: Promise<void>[] = [];
    if (contentTypes.includes("text")) jobs.push(genText(trimmed));
    if (contentTypes.includes("brand")) jobs.push(genBrand(trimmed));
    if (contentTypes.includes("video")) jobs.push(genVideo(trimmed));

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

          {/* Brand Profile */}
          <div>
            <h3 className="text-xs font-semibold text-[#9E9893] uppercase tracking-wider mb-3">
              Brand Profile
            </h3>
            <div className="bg-[#F8F5EE] border border-[#E8E3DA] rounded-xl p-3.5 space-y-2.5 text-sm">
              {[
                { label: "Business", value: "EcoHome Solutions" },
                { label: "Tone", value: "Warm, aspirational, educational" },
                { label: "Topic", value: "Bamboo Kitchen Collection" },
                { label: "Audience", value: "Eco-conscious millennials, 25–40" },
                { label: "Notes", value: "Emphasise sustainability & durability" },
              ].map(({ label, value }) => (
                <div key={label}>
                  <span className="text-[#9E9893] text-xs">{label}</span>
                  <p className="text-[#1B1A17] mt-0.5">{value}</p>
                </div>
              ))}
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
                EcoHome Solutions — Bamboo Kitchen Collection
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
            if (
              (msg.variant === "video-pending" || msg.variant === "video-preview") &&
              msg.videoJobId
            ) {
              return (
                <BrandVideoCard
                  key={msg.id}
                  message={msg}
                  onApprove={() => handleApproval(msg.id, "approved")}
                  onReject={() => handleApproval(msg.id, "rejected")}
                  formatTime={formatTime}
                />
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

// ── Brand Video Card ──────────────────────────────────────────────────────────

interface BrandVideoCardProps {
  message: Message;
  onApprove: () => void;
  onReject: () => void;
  formatTime: (d: Date) => string;
}

/**
 * Renders a brand video card that polls /api/video/[jobId] until the spec is ready,
 * then shows the structured BrandVideoProps spec (palette + scenes + CTA). The
 * backend produces the spec — not a rendered MP4 — so the card visualises the spec
 * a downstream Remotion render would consume. Polling state is local to each card.
 */
function BrandVideoCard({
  message,
  onApprove,
  onReject,
  formatTime,
}: BrandVideoCardProps) {
  const [renderStatus, setRenderStatus] = useState<"pending" | "done" | "error">(
    message.variant === "video-preview" ? "done" : "pending"
  );
  const [elapsed, setElapsed] = useState(0);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [props, setProps] = useState<VideoProps | null>(null);
  const approval = message.approval;

  useEffect(() => {
    if (renderStatus !== "pending" || !message.videoJobId) return;

    // Poll job status every 1.5 s (spec generation is fast — a single LLM call)
    const poll = setInterval(async () => {
      try {
        const res = await fetch(`/api/video/${message.videoJobId}`);
        const data = await res.json();
        if (data.status === "done") {
          setProps(data.props ?? null);
          setRenderStatus("done");
        } else if (data.status === "error") {
          setRenderStatus("error");
          setRenderError(data.error ?? "Spec generation failed.");
        }
      } catch {
        // transient network error — keep polling
      }
    }, 1500);

    const tick = setInterval(() => setElapsed((s) => s + 1), 1000);

    return () => {
      clearInterval(poll);
      clearInterval(tick);
    };
  }, [renderStatus, message.videoJobId]);

  return (
    <div className="w-full max-w-sm">
      <p className="text-sm text-[#6B6561] mb-2">{message.content}</p>
      <div className="bg-white border border-[#E8E3DA] rounded-2xl overflow-hidden shadow-sm">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2.5 bg-[#1B1A17] text-white">
          <span className="text-sm font-semibold">✦ Brand Video Spec</span>
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

        {/* Body — pending spinner, error, or the structured spec */}
        <div className="bg-[#F8F5EE] p-3">
          {renderStatus === "pending" && (
            <div className="flex flex-col items-center justify-center gap-3 text-[#9E9893] py-12">
              <svg className="animate-spin" width={36} height={36} viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="#E8E3DA" strokeWidth="3" />
                <path d="M12 2a10 10 0 0 1 10 10" stroke="#FF4800" strokeWidth="3" strokeLinecap="round" />
              </svg>
              <p className="text-xs font-medium text-center">Generating video spec…</p>
              <p className="text-xs text-center">{elapsed}s elapsed</p>
            </div>
          )}

          {renderStatus === "error" && (
            <div className="flex flex-col items-center justify-center gap-2 text-center px-4 py-12">
              <p className="text-sm font-medium text-red-500">Spec generation failed</p>
              <p className="text-xs text-[#9E9893]">{renderError}</p>
            </div>
          )}

          {renderStatus === "done" && props && <VideoSpec props={props} />}
        </div>

        {/* Actions */}
        {renderStatus === "done" && approval === "pending" && (
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

/**
 * Visualises a BrandVideoProps spec: a poster-style hero in the brand palette,
 * the three Scene-2 stats, and the Scene-3 CTA — i.e. the data a Remotion render
 * turns into the 3-scene video.
 */
function VideoSpec({ props }: { props: VideoProps }) {
  return (
    <div className="flex flex-col gap-3">
      {/* Hero / Scene 1 — brand identity in the generated palette */}
      <div
        className="rounded-lg p-4 text-center"
        style={{ background: props.primaryColor, color: "#fff" }}
      >
        <div className="text-lg font-bold tracking-wide" style={{ color: props.secondaryColor }}>
          {props.brandName}
        </div>
        <div className="text-xs mt-1 opacity-90">{props.tagline}</div>
        <div className="flex justify-center gap-1.5 mt-3">
          {[props.primaryColor, props.secondaryColor, props.accentColor].map((c, i) => (
            <span
              key={i}
              className="w-5 h-5 rounded-full border border-white/30"
              style={{ background: c }}
              title={c}
            />
          ))}
        </div>
      </div>

      {/* Scene 2 — three stats */}
      <div>
        <div className="text-[11px] font-semibold text-[#9E9893] uppercase tracking-wider mb-1.5">
          {props.sectionLabel}
        </div>
        <div className="grid grid-cols-3 gap-2">
          {props.stats.map((s, i) => (
            <div
              key={i}
              className="bg-white border border-[#E8E3DA] rounded-lg p-2 text-center"
            >
              <div className="text-base" style={{ color: props.accentColor }}>{s.icon}</div>
              <div className="text-sm font-bold text-[#1B1A17]">{s.value}</div>
              <div className="text-[10px] text-[#6B6561] leading-tight">{s.label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Scene 3 — CTA */}
      <div className="bg-white border border-[#E8E3DA] rounded-lg p-3 text-center">
        <div className="text-sm font-semibold text-[#1B1A17]">{props.headline}</div>
        <div className="text-xs text-[#6B6561] mt-1">{props.subtext}</div>
        <div
          className="inline-block text-xs font-semibold text-white px-3 py-1.5 rounded-full mt-2"
          style={{ background: `linear-gradient(90deg, ${props.secondaryColor}, ${props.accentColor})` }}
        >
          {props.ctaLabel}
        </div>
        <div className="text-[10px] text-[#9E9893] mt-2">{props.contact}</div>
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
