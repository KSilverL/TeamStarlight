"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";

type Platform = "x" | "instagram" | "tiktok" | "linkedin";
type ContentType = "text" | "image" | "video" | "mix";
type ApprovalStatus = "pending" | "approved" | "rejected";

interface DraftContent {
  text: string;
  hashtags?: string[];
  imageDesc?: string;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  variant?: "status" | "draft";
  platform?: Platform;
  draft?: DraftContent;
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
    badgeClass: "bg-zinc-800 text-white",
    headerClass: "bg-zinc-900 text-white",
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
    badgeClass: "bg-black text-white border border-white/20",
    headerClass: "bg-black text-white",
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
  { id: "image", label: "Image" },
  { id: "video", label: "Video" },
  { id: "mix", label: "Mix" },
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

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>(INITIAL_MESSAGES);
  const [input, setInput] = useState("");
  const [selectedPlatforms, setSelectedPlatforms] = useState<Platform[]>([
    "instagram",
    "linkedin",
  ]);
  const [contentType, setContentType] = useState<ContentType>("mix");
  const [sidebarOpen, setSidebarOpen] = useState(true);
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

  function handleSend() {
    const trimmed = input.trim();
    if (!trimmed) return;

    setMessages((prev) => [
      ...prev,
      {
        id: Date.now().toString(),
        role: "user",
        content: trimmed,
        timestamp: new Date(),
      },
    ]);
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }

    setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          role: "assistant",
          content:
            "Got it — I've noted your feedback and am updating the content strategy. Revised drafts will appear shortly...",
          variant: "status",
          timestamp: new Date(),
        },
      ]);
    }, 700);
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
    <div className="flex h-screen bg-zinc-950 text-white overflow-hidden">
      {/* Sidebar */}
      <aside
        className={`${
          sidebarOpen ? "w-72" : "w-0"
        } transition-all duration-200 overflow-hidden flex-shrink-0 border-r border-white/10 flex flex-col bg-zinc-900`}
      >
        <div className="p-5 border-b border-white/10 flex-shrink-0">
          <Link
            href="/"
            className="flex items-center gap-2 font-bold text-lg hover:text-indigo-300 transition-colors"
          >
            ✦ Starlight
          </Link>
          <p className="text-xs text-zinc-500 mt-0.5">AI Content Assistant</p>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-7">
          {/* Platforms */}
          <div>
            <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">
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
                        ? "bg-indigo-500/15 text-indigo-300 border border-indigo-500/25"
                        : "text-zinc-400 hover:text-zinc-200 hover:bg-white/5"
                    }`}
                  >
                    <span
                      className={`w-6 h-6 rounded flex items-center justify-center text-xs font-bold flex-shrink-0 ${p.badgeClass}`}
                    >
                      {p.abbr}
                    </span>
                    <span>{p.label}</span>
                    {active && (
                      <span className="ml-auto w-1.5 h-1.5 rounded-full bg-indigo-400 flex-shrink-0" />
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Content Type */}
          <div>
            <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">
              Content Type
            </h3>
            <div className="grid grid-cols-2 gap-2">
              {CONTENT_TYPES.map((ct) => (
                <button
                  key={ct.id}
                  onClick={() => setContentType(ct.id)}
                  className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                    contentType === ct.id
                      ? "bg-indigo-600 text-white"
                      : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-white"
                  }`}
                >
                  {ct.label}
                </button>
              ))}
            </div>
          </div>

          {/* Brand Profile */}
          <div>
            <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">
              Brand Profile
            </h3>
            <div className="bg-zinc-800 rounded-xl p-3.5 space-y-2.5 text-sm">
              {[
                { label: "Business", value: "EcoHome Solutions" },
                { label: "Tone", value: "Warm, aspirational, educational" },
                { label: "Topic", value: "Bamboo Kitchen Collection" },
                { label: "Audience", value: "Eco-conscious millennials, 25–40" },
                { label: "Notes", value: "Emphasise sustainability & durability" },
              ].map(({ label, value }) => (
                <div key={label}>
                  <span className="text-zinc-500 text-xs">{label}</span>
                  <p className="text-zinc-200 mt-0.5">{value}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </aside>

      {/* Chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="flex items-center justify-between px-5 py-4 border-b border-white/10 bg-zinc-900/60 backdrop-blur flex-shrink-0">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="text-zinc-400 hover:text-white transition-colors p-1 rounded"
              aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
            >
              <svg width="18" height="14" viewBox="0 0 18 14" fill="none" aria-hidden="true">
                <rect width="18" height="2" rx="1" fill="currentColor" />
                <rect y="6" width="18" height="2" rx="1" fill="currentColor" />
                <rect y="12" width="18" height="2" rx="1" fill="currentColor" />
              </svg>
            </button>
            <div>
              <h1 className="font-semibold text-sm text-white">
                EcoHome Solutions — Bamboo Kitchen Collection
              </h1>
              <p className="text-xs text-zinc-500 mt-0.5">
                {selectedPlatforms.length} platform
                {selectedPlatforms.length !== 1 ? "s" : ""} · {contentType}{" "}
                content
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
            if (msg.variant === "draft" && msg.draft && msg.platform) {
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
                  className="flex items-center gap-2 text-sm text-zinc-500 italic"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse flex-shrink-0" />
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
                      ? "bg-indigo-600 text-white rounded-br-sm"
                      : "bg-zinc-800 text-zinc-200 rounded-bl-sm"
                  }`}
                >
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                  <p
                    className={`text-xs mt-2 ${
                      msg.role === "user" ? "text-indigo-300" : "text-zinc-500"
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
        <div className="px-6 py-4 border-t border-white/10 bg-zinc-900/60 flex-shrink-0">
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
              className="flex-1 bg-zinc-800 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder:text-zinc-500 resize-none focus:outline-none focus:border-indigo-500 transition-colors"
              rows={1}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white p-3 rounded-xl transition-colors flex-shrink-0"
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

function DraftCard({ message, onApprove, onReject, formatTime }: DraftCardProps) {
  const platform = platformMap[message.platform!];
  const draft = message.draft!;
  const approval = message.approval;

  return (
    <div className="w-full max-w-lg">
      <p className="text-sm text-zinc-400 mb-2">{message.content}</p>
      <div className="bg-zinc-800 border border-white/10 rounded-2xl overflow-hidden">
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
            <div className="bg-zinc-700/50 border border-white/5 rounded-lg px-3 py-2 text-xs text-zinc-300">
              <span className="text-zinc-500">Image prompt: </span>
              {draft.imageDesc}
            </div>
          )}
          <p className="text-sm text-zinc-200 whitespace-pre-wrap leading-relaxed">
            {draft.text}
          </p>
          {draft.hashtags && (
            <div className="flex flex-wrap gap-1.5">
              {draft.hashtags.map((tag) => (
                <span
                  key={tag}
                  className="text-xs text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded-full"
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
              className="flex-1 bg-zinc-700 hover:bg-zinc-600 text-zinc-200 text-sm font-medium py-2 rounded-lg transition-colors"
            >
              Reject &amp; Regenerate
            </button>
          </div>
        )}

        <p className="text-xs text-zinc-600 px-4 pb-3">
          {formatTime(message.timestamp)}
        </p>
      </div>
    </div>
  );
}
