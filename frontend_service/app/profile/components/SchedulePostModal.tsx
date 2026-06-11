"use client";

import { useState, useRef, useEffect } from "react";
import { PLATFORM_CONFIG } from "../data";
import type { Platform, ScheduledPost, ChatMessage } from "../types";

/**
 * Converts an ISO date string ("YYYY-MM-DD") to a human-readable label.
 *
 * Date parts are parsed manually rather than passing the raw string to `new Date()`
 * because the Date constructor treats "YYYY-MM-DD" as UTC midnight, which shifts
 * the displayed day by one in negative UTC-offset timezones.
 *
 * @param dateStr ISO date string, e.g. "2026-06-15"
 * @returns e.g. "Monday, June 15, 2026"
 */
function formatDisplayDate(dateStr: string): string {
  const [year, month, day] = dateStr.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

/**
 * Mock content generator — stand-in for the real LLM call that will be routed
 * through the Python/LangGraph service once the backend is integrated.
 *
 * Each platform returns copy that matches its tone conventions:
 * - Instagram: visual, emoji-heavy, link-in-bio CTA
 * - LinkedIn: formal, thought-leadership framing, no hashtags
 * - TikTok: Hook / Body / CTA / Sound script structure
 * - X: concise, direct, 1–2 hashtags only
 *
 * @param prompt   Raw text the user typed into the chat input.
 * @param platform The platform currently selected in the left panel.
 * @returns Structured draft with body text and hashtag array.
 */
function generateContent(
  prompt: string,
  platform: Platform,
): { text: string; hashtags: string[] } {
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  const templates: Record<Platform, { text: string; hashtags: string[] }> = {
    instagram: {
      text: `✨ ${cap(prompt)}.\n\nAt EcoHome Solutions, we believe sustainable living should be beautiful. Our Bamboo Collection brings nature into your everyday routine — crafted to last, designed to inspire. 🌿\n\nShop the full collection — link in bio.`,
      hashtags: [
        "#EcoHome",
        "#BambooKitchen",
        "#SustainableLiving",
        "#HomeInspo",
        "#ZeroWaste",
      ],
    },
    linkedin: {
      text: `${cap(prompt)}.\n\nAt EcoHome Solutions, we're committed to proving that sustainable manufacturing can meet — and exceed — conventional quality standards. Our Bamboo Kitchen Collection is the latest example of that commitment.\n\nWe'd love to hear your thoughts on sustainable homewares.`,
      hashtags: [], // LinkedIn performs better without hashtag clutter
    },
    tiktok: {
      text: `Hook: ${cap(prompt)} 🎋\nBody: Here's what most people don't know about sustainable kitchenware — bamboo is 3× stronger than steel by weight and grows back in months.\nCTA: Check out our Bamboo Collection — link in bio!\nSound: Upbeat indie acoustic`,
      hashtags: [
        "#EcoTok",
        "#BambooLife",
        "#SustainableKitchen",
        "#KitchenTok",
      ],
    },
    x: {
      text: `${cap(prompt)}. 🌿\n\nEcoHome Bamboo Collection — sustainable, durable, beautiful. Shop now →`,
      hashtags: ["#EcoHome", "#SustainableLiving"],
    },
  };
  return templates[platform];
}

/** Props for the SchedulePostModal component. */
interface SchedulePostModalProps {
  /** ISO date string of the day that was clicked in the calendar. */
  day: string;
  /** Posts already scheduled on this day — shown in the left panel for context. */
  existingPosts: ScheduledPost[];
  /** Called when the user dismisses the modal without scheduling. */
  onClose: () => void;
  /** Called with the assembled ScheduledPost when the user confirms scheduling. */
  onSchedule: (post: ScheduledPost) => void;
}

export default function SchedulePostModal({
  day,
  existingPosts,
  onClose,
  onSchedule,
}: SchedulePostModalProps) {
  const [time, setTime] = useState("09:00");
  const [platform, setPlatform] = useState<Platform>("instagram");

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

  /**
   * Appends the user's message, triggers the mock AI delay, then appends the
   * generated draft as an assistant message with attached `draftData`.
   *
   * The 1.3 s delay simulates LLM latency and shows the typing indicator.
   * Replace `generateContent` with a real fetch call when the LLM service is ready.
   */
  async function sendMessage() {
    if (!input.trim() || isThinking) return;

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      content: input.trim(),
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsThinking(true);

    // Simulated LLM response delay.
    await new Promise((r) => setTimeout(r, 1300));

    const draft = generateContent(input.trim(), platform);
    const aiMsg: ChatMessage = {
      id: `a-${Date.now()}`,
      role: "assistant",
      content: draft.text,
      timestamp: new Date(),
      draftData: draft, // attaching draftData enables the "Use this content" button
    };
    setMessages((prev) => [...prev, aiMsg]);
    setIsThinking(false);
  }

  /**
   * Assembles a ScheduledPost from the current form state and selected draft,
   * then hands it to the parent ContentCalendar via `onSchedule`.
   * Guard on `scheduledContent` ensures the button is only clickable when a
   * draft has been explicitly selected by the user.
   */
  function handleSchedule() {
    if (!scheduledContent) return;
    onSchedule({
      id: `sc-${Date.now()}`,
      date: day,
      time,
      platform,
      text: scheduledContent.text,
      hashtags: scheduledContent.hashtags,
      status: "scheduled",
    });
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

              {/* Platform selector — 2×2 grid of toggle buttons */}
              <div>
                <label className="block text-xs font-semibold text-[#1B1A17] mb-2">
                  Platform
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {(["instagram", "linkedin", "tiktok", "x"] as Platform[]).map(
                    (p) => (
                      <button
                        key={p}
                        onClick={() => setPlatform(p)}
                        className={`flex items-center gap-2 px-2.5 py-2 rounded-xl text-xs font-medium border transition-colors ${
                          platform === p
                            ? "border-[#FF4800] bg-[#FFF0EB] text-[#FF4800]" // active state
                            : "border-[#E8E3DA] text-[#6B6561] hover:border-[#FF4800]/40 hover:bg-[#FFFAF8]"
                        }`}
                      >
                        {/* Coloured platform badge badge (e.g. Instagram gradient) */}
                        <span
                          className={`w-5 h-5 rounded flex items-center justify-center text-[10px] font-bold text-white flex-shrink-0 ${PLATFORM_CONFIG[p].badge}`}
                        >
                          {PLATFORM_CONFIG[p].abbr}
                        </span>
                        {/* Strip "(Twitter)" from "X (Twitter)" to keep labels short */}
                        {PLATFORM_CONFIG[p].label.split(" ")[0]}
                      </button>
                    ),
                  )}
                </div>
              </div>

              {/* Existing posts on this day — contextual read-only list */}
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
                      <div
                        key={post.id}
                        className="bg-[#F8F5EE] rounded-xl p-3 border border-[#E8E3DA]"
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
                        </div>
                        {/* Show only the first line of text to keep the card compact */}
                        <p className="text-xs text-[#9E9893] line-clamp-2 leading-relaxed">
                          {post.text.split("\n")[0]}
                        </p>
                      </div>
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

            {/* Schedule button — disabled until a draft has been selected */}
            <div className="p-5 border-t border-[#E8E3DA] flex-shrink-0">
              <button
                onClick={handleSchedule}
                disabled={!scheduledContent}
                className={`w-full py-2.5 rounded-xl text-sm font-semibold transition-colors ${
                  scheduledContent
                    ? "bg-[#FF4800] hover:bg-[#E03E00] text-white"
                    : "bg-[#F2EDE4] text-[#C8C2BA] cursor-not-allowed"
                }`}
              >
                Schedule Post
              </button>
              {!scheduledContent && (
                <p className="text-xs text-[#C8C2BA] text-center mt-2">
                  Generate content to continue
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
