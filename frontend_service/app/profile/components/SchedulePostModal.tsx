"use client";

import { useState, useRef, useEffect } from "react";
import { PLATFORM_CONFIG } from "../data";
import { formatDisplayDate } from "../format";
import { isSchedulable } from "../types";
import type { Platform, ScheduledPost, ChatMessage } from "../types";

/** Order the platform picker is drawn in. Only the schedulable ones can be queued; the rest
 * still generate copy so the modal is useful for drafting before an integration exists. */
const PLATFORMS: Platform[] = ["linkedin", "facebook", "instagram", "tiktok", "x"];

/**
 * Splits trailing hashtags off generated copy.
 *
 * The LLM service returns one blob of text with hashtags baked into it, but the calendar
 * stores and styles them separately (and LinkedIn copy is meant to carry none). Only a
 * trailing run of hashtag-only lines is taken, so a `#1` inside a sentence stays in the body.
 */
function splitHashtags(text: string): { text: string; hashtags: string[] } {
  const lines = text.trimEnd().split("\n");
  const hashtags: string[] = [];

  while (lines.length > 0) {
    const line = lines[lines.length - 1].trim();
    if (line === "") {
      lines.pop();
      continue;
    }
    const tokens = line.split(/\s+/);
    if (tokens.every((t) => t.startsWith("#") && t.length > 1)) {
      hashtags.unshift(...tokens);
      lines.pop();
      continue;
    }
    break;
  }

  return { text: lines.join("\n").trimEnd(), hashtags };
}

/** The Facebook Page ids picked in the Brand Profile — the same selection the chat page
 * publishes to, so a post scheduled here lands on the Pages the user already chose. */
function getSelectedPageIds(): number[] {
  try {
    const ids = JSON.parse(localStorage.getItem("starlight_meta_page_ids") || "[]");
    return Array.isArray(ids) ? ids.map(Number).filter((n) => Number.isFinite(n)) : [];
  } catch {
    return [];
  }
}

/** Props for the SchedulePostModal component. */
interface SchedulePostModalProps {
  /** ISO date string of the day that was clicked in the calendar. */
  day: string;
  /** Posts already scheduled on this day — shown in the left panel for context. */
  existingPosts: ScheduledPost[];
  /** Called when the user dismisses the modal without scheduling. */
  onClose: () => void;
  /** Called after the backend has accepted a new scheduled post. */
  onScheduled: () => void;
  /** Opens one of this day's existing posts in the detail view (which owns cancelling). */
  onOpenPost: (post: ScheduledPost) => void;
}

export default function SchedulePostModal({
  day,
  existingPosts,
  onClose,
  onScheduled,
  onOpenPost,
}: SchedulePostModalProps) {
  const [time, setTime] = useState("09:00");
  const [platform, setPlatform] = useState<Platform>("linkedin");
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Chat message history; seeded with a contextual greeting on mount.
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "init",
      role: "assistant",
      content: `Hi! I'll help you create content for ${formatDisplayDate(day)}. Describe what you'd like to post about and I'll generate platform-optimised copy for you.`,
      timestamp: new Date(),
    },
  ]);

  const [input, setInput] = useState("");
  const [isThinking, setIsThinking] = useState(false);

  // The draft the user has chosen to schedule; null until "Use this content" is clicked.
  const [scheduledContent, setScheduledContent] = useState<{
    text: string;
    hashtags: string[];
  } | null>(null);

  // Tracks which message bubble is highlighted as "selected" so its button shows "✓ Selected".
  const [selectedMsgId, setSelectedMsgId] = useState<string | null>(null);

  // Ref attached to a sentinel div at the bottom of the message list for auto-scroll.
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Scroll to the latest message whenever the list grows or the typing indicator appears.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isThinking]);

  const pageIds = platform === "facebook" ? getSelectedPageIds() : [];
  const needsFacebookPage = platform === "facebook" && pageIds.length === 0;
  const canSchedule =
    !!scheduledContent && isSchedulable(platform) && !needsFacebookPage && !isSaving;

  /**
   * Appends the user's message, calls the LLM service for a draft, then appends it as an
   * assistant message with attached `draftData`.
   *
   * Prior turns go along as `history` so a follow-up ("shorter", "make it punchier") continues
   * the thread rather than regenerating from scratch.
   */
  async function sendMessage() {
    if (!input.trim() || isThinking) return;

    const prompt = input.trim();
    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      content: prompt,
      timestamp: new Date(),
    };

    // Built before the state update so it holds the turns *preceding* this one; the greeting
    // is dropped because it's UI chrome, not part of the conversation the model should see.
    const history = messages
      .filter((m) => m.id !== "init")
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsThinking(true);

    try {
      const res = await fetch("/api/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, platform, history }),
      });
      const data = await res.json();

      if (!res.ok || data.error) {
        setMessages((prev) => [
          ...prev,
          {
            id: `a-${Date.now()}`,
            role: "assistant",
            content:
              data.error ??
              "The content service could not generate copy just now. Try again in a moment.",
            timestamp: new Date(),
          },
        ]);
        return;
      }

      const draft = splitHashtags(String(data.text ?? ""));
      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          content: draft.text,
          timestamp: new Date(),
          draftData: draft, // attaching draftData enables the "Use this content" button
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          content: "Could not reach the content service.",
          timestamp: new Date(),
        },
      ]);
    } finally {
      setIsThinking(false);
    }
  }

  /**
   * Sends the selected draft to the scheduling API.
   *
   * The browser's timezone rides along so the backend resolves "09:00 on this day" to the same
   * moment the user meant, rather than to 09:00 in whatever zone the server happens to run in.
   */
  async function handleSchedule() {
    if (!scheduledContent || !isSchedulable(platform)) return;

    const token = localStorage.getItem("starlight_token");
    if (!token) {
      setSaveError("Log in before scheduling a post.");
      return;
    }

    setIsSaving(true);
    setSaveError(null);

    try {
      const res = await fetch("/api/schedule/posts", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          platform,
          date: day,
          time,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          message: scheduledContent.text,
          hashtags: scheduledContent.hashtags,
          page_ids: pageIds,
        }),
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok || data.error) {
        setSaveError(data.error ?? "Could not schedule the post.");
        return;
      }
      onScheduled();
    } catch {
      setSaveError("Could not reach the backend.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    // Full-screen backdrop with blur; z-50 sits above the sidebar and header.
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 p-6">
      <div
        className="bg-[#F8F5EE] rounded-2xl shadow-2xl w-full max-w-4xl flex flex-col overflow-hidden"
        style={{ height: "620px" }}
      >
        {/* ── Modal header ─────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#E8E3DA] bg-white rounded-t-2xl flex-shrink-0">
          <div>
            <h2 className="text-base font-semibold text-[#1B1A17]">
              Schedule Post
            </h2>
            <p className="text-xs text-[#9E9893] mt-0.5">
              {formatDisplayDate(day)}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="w-8 h-8 flex items-center justify-center rounded-lg text-[#9E9893] hover:text-[#1B1A17] hover:bg-[#F2EDE4] transition-colors"
          >
            {/* × icon */}
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path
                d="M2 2l10 10M12 2L2 12"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>

        {/* ── Two-panel body ────────────────────────────────────────────────── */}
        {/*
          Left panel  (w-72): scheduling controls — time, platform, existing posts, confirm button.
          Right panel (flex-1): inline chat for curating post content.
        */}
        <div className="flex-1 flex overflow-hidden">
          {/* ── Left panel ───────────────────────────────────────────────── */}
          <div className="w-72 flex-shrink-0 border-r border-[#E8E3DA] bg-white flex flex-col">
            <div className="flex-1 overflow-y-auto p-5 space-y-5">
              {/* Time picker */}
              <div>
                <label className="block text-xs font-semibold text-[#1B1A17] mb-2">
                  Post Time
                </label>
                <input
                  type="time"
                  value={time}
                  onChange={(e) => setTime(e.target.value)}
                  className="w-full border border-[#E8E3DA] rounded-xl px-3 py-2.5 text-sm text-[#1B1A17] focus:outline-none focus:border-[#FF4800] bg-white transition-colors"
                />
              </div>

              {/* Platform selector — 2-column grid of toggle buttons */}
              <div>
                <label className="block text-xs font-semibold text-[#1B1A17] mb-2">
                  Platform
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {PLATFORMS.map((p) => (
                    <button
                      key={p}
                      onClick={() => setPlatform(p)}
                      className={`flex items-center gap-2 px-2.5 py-2 rounded-xl text-xs font-medium border transition-colors ${
                        platform === p
                          ? "border-[#FF4800] bg-[#FFF0EB] text-[#FF4800]" // active state
                          : "border-[#E8E3DA] text-[#6B6561] hover:border-[#FF4800]/40 hover:bg-[#FFFAF8]"
                      }`}
                    >
                      {/* Coloured platform badge (e.g. Instagram gradient) */}
                      <span
                        className={`w-5 h-5 rounded flex items-center justify-center text-[10px] font-bold text-white flex-shrink-0 ${PLATFORM_CONFIG[p].badge}`}
                      >
                        {PLATFORM_CONFIG[p].abbr}
                      </span>
                      {/* Strip "(Twitter)" from "X (Twitter)" to keep labels short */}
                      {PLATFORM_CONFIG[p].label.split(" ")[0]}
                    </button>
                  ))}
                </div>
              </div>

              {/* Everything already queued for this day. Each row opens the post's own detail
                  view, which is where the full copy and the cancel action live — this list is
                  a compact index, not a second place to act on a post. */}
              {existingPosts.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-[#1B1A17] mb-2">
                    Already Scheduled{" "}
                    <span className="text-[#9E9893] font-normal">
                      ({existingPosts.length})
                    </span>
                  </p>
                  <div className="space-y-2">
                    {existingPosts.map((post) => (
                      <button
                        key={post.id}
                        onClick={() => onOpenPost(post)}
                        className="w-full text-left bg-[#F8F5EE] rounded-xl p-3 border border-[#E8E3DA] hover:border-[#FF4800]/40 hover:bg-[#FFFAF8] transition-colors"
                      >
                        <div className="flex items-center gap-2 mb-1.5">
                          <span
                            className={`w-5 h-5 rounded flex items-center justify-center text-[10px] font-bold text-white flex-shrink-0 ${PLATFORM_CONFIG[post.platform].badge}`}
                          >
                            {PLATFORM_CONFIG[post.platform].abbr}
                          </span>
                          <span className="text-xs text-[#6B6561] font-medium">
                            {post.time}
                          </span>
                          <span className="text-xs text-[#C8C2BA] ml-auto">View →</span>
                        </div>
                        {/* Show only the first line of text to keep the card compact */}
                        <p className="text-xs text-[#9E9893] line-clamp-2 leading-relaxed">
                          {post.text.split("\n")[0]}
                        </p>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Content confirmation banner — appears after "Use this content" is clicked */}
              {scheduledContent && (
                <div className="p-3 bg-green-50 rounded-xl border border-green-200">
                  <p className="text-xs font-semibold text-green-700 mb-1">
                    Content ready ✓
                  </p>
                  <p className="text-xs text-green-600 line-clamp-2 leading-relaxed">
                    {scheduledContent.text.split("\n")[0]}
                  </p>
                </div>
              )}
            </div>

            {/* Schedule button — disabled until there's a draft on a platform we can publish to */}
            <div className="p-5 border-t border-[#E8E3DA] flex-shrink-0">
              <button
                onClick={handleSchedule}
                disabled={!canSchedule}
                className={`w-full py-2.5 rounded-xl text-sm font-semibold transition-colors ${
                  canSchedule
                    ? "bg-[#FF4800] hover:bg-[#E03E00] text-white"
                    : "bg-[#F2EDE4] text-[#C8C2BA] cursor-not-allowed"
                }`}
              >
                {isSaving ? "Scheduling…" : "Schedule Post"}
              </button>

              {/* One reason at a time, most specific first, so the hint always names the next
                  thing to do rather than the first unmet condition alphabetically. */}
              {!isSchedulable(platform) ? (
                <p className="text-xs text-[#C8C2BA] text-center mt-2 leading-relaxed">
                  {PLATFORM_CONFIG[platform].label.split(" ")[0]} isn&apos;t connected for
                  publishing yet — you can still draft copy here.
                </p>
              ) : needsFacebookPage ? (
                <p className="text-xs text-[#C8C2BA] text-center mt-2 leading-relaxed">
                  Pick a Facebook Page in your Brand Profile first.
                </p>
              ) : !scheduledContent ? (
                <p className="text-xs text-[#C8C2BA] text-center mt-2">
                  Generate content to continue
                </p>
              ) : null}

              {saveError && (
                <p className="text-xs text-red-600 text-center mt-2 leading-relaxed">
                  {saveError}
                </p>
              )}
            </div>
          </div>

          {/* ── Right panel: inline chat ──────────────────────────────────── */}
          <div className="flex-1 flex flex-col overflow-hidden bg-[#F8F5EE]">
            {/* Scrollable message list */}
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  // User messages align right; assistant messages align left.
                  className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  {/* Avatar shown only for assistant messages */}
                  {msg.role === "assistant" && (
                    <div className="w-7 h-7 rounded-full bg-[#1B1A17] flex items-center justify-center flex-shrink-0 mr-2.5 mt-0.5">
                      <span className="text-white text-xs font-bold">✦</span>
                    </div>
                  )}

                  {/* Bubble: orange for user, white card for assistant */}
                  <div
                    className={`max-w-xs lg:max-w-sm px-4 py-3 rounded-2xl text-sm leading-relaxed ${
                      msg.role === "user"
                        ? "bg-[#FF4800] text-white rounded-br-sm"
                        : "bg-white border border-[#E8E3DA] text-[#1B1A17] rounded-bl-sm shadow-sm"
                    }`}
                  >
                    <p className="whitespace-pre-wrap">{msg.content}</p>

                    {/* Draft actions — only rendered on assistant messages that carry draftData */}
                    {msg.draftData && (
                      <>
                        {msg.draftData.hashtags.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-2">
                            {msg.draftData.hashtags.map((tag) => (
                              <span
                                key={tag}
                                className="text-xs text-[#FF4800] bg-[#FFF0EB] px-1.5 py-0.5 rounded-full"
                              >
                                {tag}
                              </span>
                            ))}
                          </div>
                        )}
                        {/*
                          "Use this content" stores the draft in scheduledContent and marks
                          this message as selected. Clicking on a different message's button
                          replaces the selection — only one draft can be scheduled at a time.
                        */}
                        <button
                          onClick={() => {
                            setScheduledContent(msg.draftData!); // safe: inside draftData guard
                            setSelectedMsgId(msg.id);
                          }}
                          className={`mt-3 text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors border ${
                            selectedMsgId === msg.id
                              ? "text-green-700 border-green-200 bg-green-50" // selected state
                              : "text-[#FF4800] border-[#FFCBB8] bg-[#FFF0EB] hover:bg-[#FFE4D9]"
                          }`}
                        >
                          {selectedMsgId === msg.id
                            ? "✓ Selected"
                            : "Use this content"}
                        </button>
                      </>
                    )}
                  </div>
                </div>
              ))}

              {/* Animated typing indicator — three staggered bouncing dots */}
              {isThinking && (
                <div className="flex justify-start">
                  <div className="w-7 h-7 rounded-full bg-[#1B1A17] flex items-center justify-center flex-shrink-0 mr-2.5">
                    <span className="text-white text-xs font-bold">✦</span>
                  </div>
                  <div className="bg-white border border-[#E8E3DA] px-4 py-3 rounded-2xl rounded-bl-sm shadow-sm">
                    <div className="flex gap-1 items-center h-4">
                      <span
                        className="w-1.5 h-1.5 bg-[#9E9893] rounded-full animate-bounce"
                        style={{ animationDelay: "0ms" }}
                      />
                      <span
                        className="w-1.5 h-1.5 bg-[#9E9893] rounded-full animate-bounce"
                        style={{ animationDelay: "150ms" }}
                      />
                      <span
                        className="w-1.5 h-1.5 bg-[#9E9893] rounded-full animate-bounce"
                        style={{ animationDelay: "300ms" }}
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Sentinel — scrollIntoView target to keep the latest message in view */}
              <div ref={messagesEndRef} />
            </div>

            {/* ── Chat input bar ──────────────────────────────────────────── */}
            <div className="flex-shrink-0 p-4 border-t border-[#E8E3DA] bg-white">
              <div className="flex gap-2 items-end">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    // Submit on Enter; Shift+Enter inserts a newline instead.
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      sendMessage();
                    }
                  }}
                  placeholder={`Describe your ${PLATFORM_CONFIG[platform].label} post...`}
                  rows={2}
                  className="flex-1 bg-[#F8F5EE] border border-[#E8E3DA] rounded-xl px-3 py-2.5 text-sm text-[#1B1A17] placeholder:text-[#C8C2BA] resize-none focus:outline-none focus:border-[#FF4800] transition-colors"
                />
                {/* Send button — disabled while AI is thinking or input is empty */}
                <button
                  onClick={sendMessage}
                  disabled={!input.trim() || isThinking}
                  className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 transition-colors ${
                    input.trim() && !isThinking
                      ? "bg-[#FF4800] hover:bg-[#E03E00] text-white"
                      : "bg-[#F2EDE4] text-[#C8C2BA]"
                  }`}
                >
                  {/* Paper-plane send icon */}
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                    <path
                      d="M1.5 12.5L12.5 7 1.5 1.5V5.5l8 1.5-8 1.5v4z"
                      fill="currentColor"
                    />
                  </svg>
                </button>
              </div>
              <p className="text-xs text-[#C8C2BA] mt-1.5">
                Enter to send · Shift+Enter for new line
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
