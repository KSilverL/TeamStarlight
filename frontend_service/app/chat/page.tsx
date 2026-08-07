"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { useRealtimeVoice, type VoiceBriefPartial } from "./useRealtimeVoice";

type Platform = "x" | "facebook" | "tiktok" | "linkedin";

interface SessionSummary {
  id: string;
  createdAt: string;
  status: string;
  targetPlatforms: string[] | null;
  title?: string | null;
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
  /** The storyboard's creative theme (StoryboardSpec.theme) — used as the byline in the
   *  LinkedIn preview. Optional here because only that card reads it. */
  theme?: string;
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
  // Set once the (asynchronous, background-synthesized) agent_utterance_audio event
  // for this same turn arrives — a data: URL, playable directly in an <audio> tag.
  audioUrl?: string;
}

// The discussion feed interleaves completed turns with the moderator's mic handoffs
// (speaker_scheduled events) so the transcript reads like meeting minutes.
type RoundtableFeedItem =
  | { kind: "turn"; turn: RoundtableTurn }
  | { kind: "announcement"; speaker: string; roundIndex: number };

// Who holds the mic right now (speaker_scheduled arrived, their utterance hasn't yet).
interface RoundtableFloor {
  speaker: string;
  roundIndex: number;
}

// Step-mode's per-round prompt (round_control "waiting" event) — null once resolved/auto.
interface RoundControlPrompt {
  roundIndex: number;
  timeout: number | null;
}

/**
 * Today's date in the *browser's* timezone, as YYYY-MM-DD.
 *
 * Built from local components rather than `toISOString().slice(0, 10)`, which yields the UTC
 * date — for a user west of Greenwich that is tomorrow's date all evening, and "next month"
 * asked on the 31st would resolve a whole month wrong.
 */
function localToday(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/**
 * A sidebar title for a campaign, out of its goal.
 *
 * A single post is named by the LLM service — `POST /tasks` returns a title and refines it over
 * SSE. A campaign never touches that pipeline; it goes to `/plans` instead, which is why
 * planning sessions showed a bare timestamp for ever. The goal is the right raw material: the
 * classifier already extracts it as a short phrase in the user's own terms, so it needs
 * tidying rather than generating.
 *
 * Same contract as `_clean_title` in LLM_service/api.py — strip wrapping quotes, collapse
 * whitespace, clamp to 48 chars, empty in / empty out — plus a leading capital, because a goal
 * reads as a fragment ("launch the subscription") and a title should not.
 */
function titleFromGoal(goal: string): string {
  const cleaned = (goal ?? "")
    .trim()
    .replace(/^["'“”‘’]+|["'“”‘’]+$/g, "")
    .split(/\s+/)
    .join(" ")
    .trim();
  if (!cleaned) return "";

  const clamped =
    cleaned.length > 48
      ? cleaned.slice(0, 48).replace(/[ ,.;:—-]+$/, "") + "…"
      : cleaned;
  return clamped.charAt(0).toUpperCase() + clamped.slice(1);
}

// ── Posting plans in chat ─────────────────────────────────────────────────────

/** One dated slot on a campaign schedule. Strategy, never copy — the posts themselves are
 * written when the plan is confirmed. */
interface PlanItem {
  item_id: string;
  planned_date: string;
  time_of_day?: string | null;
  platforms: string[];
  topic: string;
  angle?: string | null;
  rationale?: string | null;
  status: string;
}

interface Plan {
  plan_id: string;
  goal: string;
  target_platforms: string[];
  start_date: string;
  end_date: string;
  status: "draft" | "active" | string;
  strategy_summary?: string;
  recommended_cadence?: string;
  items: PlanItem[];
}

/** How much deliberation each of a campaign's posts gets when it is written: the full agent
 * roundtable, or straight to the writing. Chosen at confirm, because that is when the work
 * is commissioned — see LLM_service/core/plan_schema.py. */
type DraftMode = "roundtable" | "fast";

/**
 * Where a campaign request has got to, across turns.
 *
 * `POST /intake/classify` is stateless — it holds no session — so the accumulated `known` IS
 * the conversation, and passing it back is what tells the service the campaign conversation is
 * still open. A ref rather than state for the same reason `sessionIdRef` is: `handleSend`
 * reads and writes it within one turn, and a re-render in between would race it.
 */
type CampaignPhase =
  | "gathering"    // still filling in the goal / date window
  | "clarifying";  // asked the planner's follow-up questions, waiting on the reply

interface CampaignState {
  phase: CampaignPhase;
  known: Record<string, string>;
  followupsAsked: number;
  questions: string[];
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
    | "roundtable"
    | "plan-preview"
    | "social-post";
  platform?: Platform;
  draft?: DraftContent;
  html?: string;
  approval?: ApprovalStatus;
  timestamp: Date;
  // Workflow-specific fields — set when the message originates from the MAF pipeline.
  workflowTaskId?: string;
  needsHumanIntervention?: boolean;
  // Set on a text draft (variant "text-preview") when the same task also asked for a video:
  // the real publish is the native video post (video + this copy as caption), so the draft
  // card hides its own text/image post buttons and points the user to the video card below.
  videoAlsoRequested?: boolean;
  // "YYYY-MM-DDTHH:MM" when the request that produced this draft named a time to publish at
  // ("post this on Friday at 10"). The draft card opens on Schedule with it filled in instead
  // of on Post Now. Absent whenever the user named no time, which is the common case.
  publishAt?: string;
  videoStoryboard?: VideoStoryboard;
  // The storyboard's own gate (variant === "social-post"). Separate from `approval`, which
  // gates the copy: on a text+video post the user signs off the two in sequence inside one card,
  // and the storyboard can be sent back for changes after the copy is already approved.
  storyboardApproval?: ApprovalStatus;
  // User-attached reference images (base64 data URLs) for image-to-video generation
  // (Higgsfield backend). Threaded from the compose box onto the storyboard message so
  // the render trigger can forward them; the free Remotion backend ignores them.
  referenceImages?: string[];
  // Roundtable-specific fields (variant === "roundtable") — one stage grows in place as
  // speaker_scheduled / agent_utterance / discussion_consensus / round_control events land
  // for its table.
  roundtableTableId?: string;
  roundtableFeed?: RoundtableFeedItem[];
  roundtableFloor?: RoundtableFloor | null;
  roundtableConverged?: boolean;
  roundtableStrategy?: string;
  roundControlWaiting?: RoundControlPrompt | null;
  // The draft campaign schedule (variant === "plan-preview"). Grows in place: refining
  // replaces it, confirming flips its status, so the card is always the plan's current truth.
  plan?: Plan;
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
    id: "facebook",
    label: "Facebook",
    abbr: "f",
    badgeClass: "bg-[#1877F2] text-white",
    headerClass: "bg-[#1877F2] text-white",
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

/** How many past sessions the sidebar shows before it needs asking. Enough to cover the last
 *  day or two of work, few enough that the controls below stay on screen. */
const SESSIONS_COLLAPSED_COUNT = 6;

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

// Sessions stored before the Facebook pivot still carry "instagram" in target_platforms.
// Those drafts always published to a Facebook Page, so read them back under the name the
// platform goes by now rather than showing a platform the app no longer offers.
const LEGACY_PLATFORM_IDS: Record<string, Platform> = { instagram: "facebook" };

/** Display label for a stored platform id; unknown ids fall through as-is. */
function platformLabel(id: string): string {
  return platformMap[LEGACY_PLATFORM_IDS[id] ?? id]?.label ?? id;
}

/** Platforms whose posts are reviewed as an in-feed mockup (SocialPostCard) rather than the
 *  generic draft card — the ones we can actually publish to. */
type MockupPlatform = "linkedin" | "facebook";

const MOCKUP_PLATFORMS: readonly MockupPlatform[] = ["linkedin", "facebook"];

function isMockupPlatform(id: string): id is MockupPlatform {
  return (MOCKUP_PLATFORMS as readonly string[]).includes(id);
}

/**
 * Per-platform chrome and posting rules for the post mockup.
 *
 * Class names are written out in full rather than composed from a hex value, because Tailwind
 * scans this file as text — a `bg-[${color}]` built at runtime is a class that never gets
 * generated.
 */
const POST_MOCKUP: Record<
  MockupPlatform,
  {
    label: string;
    /** The wordmark glyph in the preview strip and on the avatar. */
    mark: string;
    markClass: string;
    buttonClass: string;
    toggleActiveClass: string;
    focusClass: string;
    accentTextClass: string;
    /** The line under the author name — each network shows something different there. */
    byline: string;
    /** The feed action row. Facebook has three; LinkedIn four. */
    actions: string[];
    /** Facebook publishes to Pages, so a Page must be picked before anything can go out. */
    needsPages: boolean;
    /** Graph captions a Page video from its own title/description fields. */
    videoTitle: boolean;
  }
> = {
  linkedin: {
    label: "LinkedIn",
    mark: "in",
    markClass: "bg-[#0A66C2]",
    buttonClass: "bg-[#0A66C2] hover:bg-[#0952A0]",
    toggleActiveClass: "bg-[#0A66C2] text-white",
    focusClass: "focus:border-[#0A66C2]",
    accentTextClass: "text-[#0A66C2]",
    byline: "Brand page",
    actions: ["Like", "Comment", "Repost", "Send"],
    needsPages: false,
    videoTitle: false,
  },
  facebook: {
    label: "Facebook",
    mark: "f",
    markClass: "bg-[#1877F2]",
    buttonClass: "bg-[#1877F2] hover:bg-[#166FE0]",
    toggleActiveClass: "bg-[#1877F2] text-white",
    focusClass: "focus:border-[#1877F2]",
    accentTextClass: "text-[#1877F2]",
    byline: "Page",
    actions: ["Like", "Comment", "Share"],
    needsPages: true,
    videoTitle: true,
  },
};

// The Facebook Page id(s) the user picked in their Brand Profile. Facebook drafts
// publish to these Pages via /api/meta/post; an empty list means Facebook isn't set up yet.
function getSelectedPageIds(): number[] {
  try {
    const ids = JSON.parse(localStorage.getItem("starlight_meta_page_ids") || "[]");
    return Array.isArray(ids) ? ids.map(Number).filter((n) => Number.isFinite(n)) : [];
  } catch {
    return [];
  }
}

/**
 * Splits the classifier's "YYYY-MM-DDTHH:MM" into the [date, time] pair the two inputs take.
 *
 * Anything else — an absent value, or a shape the LLM service should never produce but might —
 * comes back as ["", ""], which leaves the draft card on Post Now. That is the right fallback:
 * a half-parsed moment on a scheduling control is worse than no moment at all.
 */
function splitPublishAt(publishAt?: string): [string, string] {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(publishAt ?? "");
  return match ? [match[1], match[2]] : ["", ""];
}

// Human-readable labels for each MAF executor shown as live status messages.
const NODE_LABELS: Record<string, string> = {
  dispatcher: "Validating brief…",
  scout: "Scouting content strategy…",
  creator: "Writing platform copy…",
  reviewer: "Running safety & brand review…",
  archivist: "Learning from your edits…",
  media_producer: "Generating brand assets…",
};

// ── Roundtable persona metadata ───────────────────────────────────────────────
// One entry per seat (workflow/roundtable/personas.py). `color` tints the avatar +
// transcript accents; `glyph` is the seat's distinguishing SVG icon (24×24 viewBox,
// stroked in currentColor).

const MODERATOR = "moderator";

interface PersonaMeta {
  label: string;
  color: string;
  glyph: React.ReactNode;
}

const PERSONA_META: Record<string, PersonaMeta> = {
  [MODERATOR]: {
    label: "Moderator",
    color: "#E8E3DA",
    // Gavel — the chair of the meeting.
    glyph: (
      <>
        <path d="M8.5 5.5l5 5" strokeLinecap="round" />
        <path d="M11 3l6.5 6.5" strokeLinecap="round" />
        <path d="M12.5 7l-2 2L4 15.5 6.5 18l6.5-6.5 2-2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M13 20h8" strokeLinecap="round" />
      </>
    ),
  },
  platform_editor: {
    label: "Platform Editor",
    color: "#38BDF8",
    // Browser window with a cursor line — platform mechanics.
    glyph: (
      <>
        <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
        <path d="M3.5 9h17" />
        <path d="M7 13.5h6M7 16.5h4" strokeLinecap="round" />
      </>
    ),
  },
  brand_voice: {
    label: "Brand Voice",
    color: "#C084FC",
    // Shield — guardian of the brand rules.
    glyph: (
      <>
        <path d="M12 3.5l7 2.8v5.2c0 4.4-2.9 7.3-7 8.9-4.1-1.6-7-4.5-7-8.9V6.3z" strokeLinejoin="round" />
        <path d="M9.2 12l2 2 3.6-4" strokeLinecap="round" strokeLinejoin="round" />
      </>
    ),
  },
  user_advocate: {
    label: "User Advocate",
    color: "#34D399",
    // Fountain-pen nib — the author's personal editor.
    glyph: (
      <>
        <path d="M14 5.5l4.5 4.5L9 19.5 4 20l.5-5z" strokeLinejoin="round" />
        <path d="M12.5 7l4.5 4.5" />
        <circle cx="9.5" cy="14.5" r="1" />
      </>
    ),
  },
  audience_advocate: {
    label: "Audience Advocate",
    color: "#FBBF24",
    // Eye — the reader scrolling past.
    glyph: (
      <>
        <path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12z" strokeLinejoin="round" />
        <circle cx="12" cy="12" r="3" />
      </>
    ),
  },
  trend_scout: {
    label: "Trend Scout",
    color: "#FB7185",
    // Trend line — today's cultural radar.
    glyph: (
      <>
        <path d="M3 17l5.5-5.5 3.5 3.5L20 7" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M15 7h5v5" strokeLinecap="round" strokeLinejoin="round" />
      </>
    ),
  },
  user: {
    label: "You",
    color: "#FF7A45",
    // Person — the human seat.
    glyph: (
      <>
        <circle cx="12" cy="8" r="3.5" />
        <path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5" strokeLinecap="round" />
      </>
    ),
  },
};

function personaMeta(speaker: string): PersonaMeta {
  return (
    PERSONA_META[speaker] ?? {
      label: speaker,
      color: "#9E9893",
      glyph: <circle cx="12" cy="12" r="6" />,
    }
  );
}

// ── Disagreement gauge ────────────────────────────────────────────────────────
// The seats are charted to disagree openly (personas.py DISCUSSION_STYLE), so each
// turn's language is a usable signal. A lexical read of the seat's LATEST turn maps to
// a four-step temperature: aligned (green) → cautious (yellow) → pushing back (orange)
// → strongly opposed (red). Seats that haven't spoken yet read as idle.

type Stance = "idle" | "aligned" | "cautious" | "pushback" | "opposed";

const STANCE_META: Record<Stance, { label: string; color: string }> = {
  idle: { label: "Hasn't spoken", color: "#57534E" },
  aligned: { label: "Aligned", color: "#4ADE80" },
  cautious: { label: "Cautious", color: "#FACC15" },
  pushback: { label: "Pushing back", color: "#FB923C" },
  opposed: { label: "Strongly opposed", color: "#F87171" },
};

const OPPOSED_RE =
  /strongly disagree|veto|must not|won't work|will not work|reject|non-negotiable|hard no|dealbreaker|deal-breaker|unacceptable|violates/i;
const PUSHBACK_RE =
  /\bdisagree\b|push back|pushback|\bobject\b|\binstead\b|that's wrong|off-brand|off brand|breaks the|\bno[,.]|doesn't work|does not work|cut th|drop th|scrap/i;
const CAUTIOUS_RE =
  /\bbut\b|however|\bconcern|not sure|careful|\brisk|\bthough\b|worried|caveat|hesitant|only if|as long as/i;

function stanceOf(text: string): Stance {
  if (OPPOSED_RE.test(text)) return "opposed";
  if (PUSHBACK_RE.test(text)) return "pushback";
  if (CAUTIOUS_RE.test(text)) return "cautious";
  return "aligned";
}

/** Each seat's current stance = the read of their most recent turn (idle before that). */
function seatStances(feed: RoundtableFeedItem[]): Record<string, Stance> {
  const stances: Record<string, Stance> = {};
  for (const item of feed) {
    if (item.kind === "turn") {
      stances[item.turn.speaker] = stanceOf(item.turn.text);
    }
  }
  return stances;
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
    "facebook",
    "linkedin",
  ]);
  const [contentTypes, setContentTypes] = useState<ContentType[]>(["text"]);
  // "manual" pauses each roundtable table at round boundaries for a 4-way user prompt
  // (round_control); "auto" (default) never prompts — the backend's own default.
  const [roundtableMode, setRoundtableMode] = useState<"auto" | "manual">("auto");
  // When on, every turn is a campaign: the classifier still reads the message for a goal and a
  // date window, but its single_post verdict is overridden. Off, the classifier decides alone —
  // which is how a terse "posts for the launch" ends up as one post about a launch.
  const [planningMode, setPlanningMode] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  // Up to 3 reference images the user attaches to the current turn (image-to-video).
  const [attachments, setAttachments] = useState<{ name: string; dataUrl: string }[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // The attachments captured at send time, carried to the storyboard message produced
  // by this run's `final` event (one workflow run == one send, so a ref is enough).
  const pendingRefsRef = useRef<string[]>([]);
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
  // table_id -> the id of that table's RoundtableStage message, so later agent_utterance /
  // round_control events for the same table update the SAME card instead of spawning new ones.
  const roundtableMsgIdRef = useRef<Map<string, string>>(new Map());
  // `${taskId}:${platform}` -> the id of that run's post-mockup message. A LinkedIn or Facebook
  // post is reviewed as ONE evolving card (copy → storyboard → render → publish), so every
  // later event for the same run patches that card instead of stacking another one.
  const socialCardIdRef = useRef<Map<string, string>>(new Map());

  // Roundtable auto-play: when on, each persona's TTS clip plays automatically as it
  // arrives (agent_utterance_audio always lands after that persona's text turn, since
  // synthesis is fire-and-forget in the background — so "auto-play" is inherently
  // "after they've spoken"). Off by default, matching today's click-to-play behaviour.
  // A ref mirrors the state so the SSE handler (a stable closure set up once per
  // workflow run) always reads the live value instead of the one captured at connect time.
  const [autoPlayRoundtableAudio, setAutoPlayRoundtableAudio] = useState(false);
  const autoPlayRoundtableAudioRef = useRef(false);
  function toggleAutoPlayRoundtableAudio() {
    autoPlayRoundtableAudioRef.current = !autoPlayRoundtableAudioRef.current;
    setAutoPlayRoundtableAudio(autoPlayRoundtableAudioRef.current);
  }
  // One shared sequential queue across every table on the page, so two persona clips
  // (possibly from different concurrent tables) never overlap into a garble.
  const roundtableAudioQueueRef = useRef<string[]>([]);
  const roundtableAudioPlayingRef = useRef(false);
  function playNextRoundtableAudio() {
    if (roundtableAudioPlayingRef.current) return;
    const next = roundtableAudioQueueRef.current.shift();
    if (!next) return;
    roundtableAudioPlayingRef.current = true;
    const audio = new Audio(next);
    const advance = () => {
      roundtableAudioPlayingRef.current = false;
      playNextRoundtableAudio();
    };
    audio.addEventListener("ended", advance);
    audio.addEventListener("error", advance);
    audio.play().catch(advance);
  }
  function enqueueRoundtableAudio(url: string) {
    roundtableAudioQueueRef.current.push(url);
    playNextRoundtableAudio();
  }

  /**
   * The JWT, for the routes that need one.
   *
   * The chat's own workflow calls go straight to the LLM service unauthenticated, but every
   * plan route runs through Java, which derives `business_id` from this token — without it a
   * plan is created against no brand, so the brand-voice profile silently never applies.
   */
  function authHeaders(): Record<string, string> {
    const token = localStorage.getItem("starlight_token");
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  // ── Posting-plan path ───────────────────────────────────────────────────────

  /**
   * What to do when the classifier can't be reached, which depends on whether the user asked.
   *
   * Left to itself, a failed classification falls through to the ordinary post path — the right
   * call when the plan was only ever a guess we were making on the user's behalf. With planning
   * mode on it is the wrong call twice over: they asked for a schedule, and quietly handing them
   * a single post instead is the exact failure this toggle exists to prevent.
   */
  function classifyUnavailable(): boolean {
    if (!planningMode) return false;
    const message =
      "I couldn't reach the planner, so I haven't built a posting plan. Try again in a moment — " +
      "or switch Posting plan off in the sidebar and I'll write a single post instead.";
    pushMessage({ role: "assistant", content: message });
    if (sessionIdRef.current) persistMessage(sessionIdRef.current, "assistant", message);
    return true;  // handled — do not fall through to the single-post path
  }

  /**
   * Handles one turn of a campaign request, and reports whether it took it.
   *
   * Returns false for an ordinary "write me a post" turn, which then flows on to `genWorkflow`
   * exactly as it always did — the plan path is a fork in front of the existing behaviour, not
   * a replacement for it.
   */
  async function handleCampaignTurn(text: string): Promise<boolean> {
    // Mid-clarify: this turn is the answer to the planner's questions, not a new request.
    if (campaignRef.current?.phase === "clarifying") {
      await buildPlan(campaignRef.current.known, campaignRef.current.questions, text);
      return true;
    }

    // Cleared up front so a time from an earlier turn can never attach itself to this one —
    // including when classifying fails below and the turn falls through to the ordinary post
    // path with no verdict at all.
    requestedPublishAtRef.current = "";

    let result: Record<string, unknown>;
    try {
      const res = await fetch("/api/intake/classify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          // The browser's own local date — genuinely the user's timezone, which is what makes
          // "next month" resolvable. A server-side guess is a month out at a boundary.
          today: localToday(),
          target_platforms: selectedPlatforms,
          known: campaignRef.current?.known,
          followups_asked: campaignRef.current?.followupsAsked ?? 0,
          // The user asked for a plan outright. The call still happens — it is what reads the
          // goal and the dates out of the sentence — but its verdict is no longer a vote.
          force_plan: planningMode,
        }),
      });
      result = await res.json();
      if (!res.ok || result.error) return classifyUnavailable();
    } catch {
      return classifyUnavailable();  // classifying is an optimisation, never a reason to refuse
    }

    if (result.intent !== "posting_plan") {
      campaignRef.current = null;
      // The one thing the single-post path wants from this call besides the verdict: the time
      // the user asked the post to go out at, if they named one. Carried to the draft card,
      // which opens on Schedule with it filled in — the user still confirms it, so a
      // misheard "Friday" costs a correction rather than a post on the wrong day.
      requestedPublishAtRef.current =
        typeof result.publish_at === "string" ? result.publish_at : "";
      return false;
    }

    const campaign = (result.campaign ?? {}) as Record<string, string>;

    // Still missing the goal or the window — ask, and keep what we have for the next turn.
    if (!result.complete) {
      campaignRef.current = {
        phase: "gathering",
        known: campaign,
        followupsAsked: (result.followups_asked as number) ?? 0,
        questions: [],
      };
      const question = (result.assistant_message as string) ?? "Tell me a bit more.";
      pushMessage({ role: "assistant", content: question });
      if (sessionIdRef.current) persistMessage(sessionIdRef.current, "assistant", question);
      return true;
    }

    await startClarify(campaign);
    return true;
  }

  /**
   * The pre-generation step: propose a cadence and ask what would tailor the schedule.
   *
   * Worth a turn because these answers shape every slot, and they are far cheaper to give now
   * than to fix by refining a plan that was built without them. If the planner has nothing to
   * ask, this falls straight through to building the plan.
   */
  async function startClarify(campaign: Record<string, string>) {
    // Name the session here, the moment the campaign is settled — not after the plan is built.
    // A campaign that reaches this point has a goal by definition (it is one of the planner's
    // required fields), and naming it now means a schedule that fails to generate still leaves
    // a session the user can recognise tomorrow.
    const title = titleFromGoal(campaign.goal ?? "");
    if (title) applySessionTitle(title, { provisional: false });

    pushMessage({ role: "assistant", content: "Working out the shape of this campaign…", variant: "status" });

    let data: Record<string, unknown> = {};
    try {
      const res = await fetch("/api/plans/clarify", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify(campaign),
      });
      data = await res.json();
      if (!res.ok || data.error) data = {};  // a failed clarify is skippable, not fatal
    } catch {
      data = {};
    }

    const questions = Array.isArray(data.follow_up_questions)
      ? (data.follow_up_questions as string[])
      : [];

    if (questions.length === 0) {
      await buildPlan(campaign, [], "");
      return;
    }

    campaignRef.current = {
      phase: "clarifying",
      known: campaign,
      followupsAsked: 0,
      questions,
    };

    const cadence = (data.recommended_cadence as string) ?? "";
    const message = [
      cadence ? `I'd suggest ${cadence}.` : "",
      "Before I build it:",
      ...questions.map((q) => `• ${q}`),
      "",
      "Answer what you can — or just say \"go ahead\" and I'll use my best judgement.",
    ].filter(Boolean).join("\n");

    pushMessage({ role: "assistant", content: message });
    if (sessionIdRef.current) persistMessage(sessionIdRef.current, "assistant", message);
  }

  /** Generates the schedule and shows it as a card. */
  async function buildPlan(
    campaign: Record<string, string>,
    questions: string[],
    answerText: string
  ) {
    campaignRef.current = null;
    pushMessage({ role: "assistant", content: "Designing your campaign schedule…", variant: "status" });

    // The planner renders `answers` as Q/A lines for its prompt, and a free-text reply can't be
    // reliably split across the questions it answers — so the whole block is sent as one pair.
    // It reads correctly in the prompt, which is all the planner needs.
    const answers =
      questions.length > 0 && answerText.trim()
        ? { [questions.join(" / ")]: answerText.trim() }
        : undefined;

    try {
      const res = await fetch("/api/plans", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ ...campaign, ...(answers ? { answers } : {}) }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        pushMessage({
          role: "assistant",
          content: data.error ?? "I couldn't build that schedule. Try giving me the goal and dates again.",
        });
        return;
      }
      pushMessage({
        role: "assistant",
        content: "Here's the campaign I'd run — review it, ask for changes, or confirm to write the posts:",
        variant: "plan-preview",
        plan: data as Plan,
      });
    } catch {
      pushMessage({ role: "assistant", content: "Could not reach the planning service." });
    }
  }

  /** Swaps a plan card's plan in place, so refining and confirming update the same card. */
  function updatePlanMessage(messageId: string, plan: Plan) {
    setMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, plan } : m)));
  }

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
  // Where a campaign request has got to. Null means no campaign conversation is open, which is
  // also what tells the classifier to judge the next turn on its own merits.
  const campaignRef = useRef<CampaignState | null>(null);

  /**
   * The publish moment the classifier read out of the last one-off request, or "" if the user
   * named none.
   *
   * A ref rather than state because nothing renders from it directly: it is set while routing
   * the turn and read once, several seconds later, when the workflow's draft finally lands —
   * and re-rendering the whole chat in between would buy nothing. One request is in flight at
   * a time, so there is no interleaving to guard against.
   */
  const requestedPublishAtRef = useRef<string>("");

  const [pastSessions, setPastSessions] = useState<SessionSummary[]>([]);
  // The sidebar shows the most recent few by default. The list is unbounded and grows for the
  // life of the account, and pushing Platforms and Content Type off the screen costs more than
  // a month-old session is worth — one click brings the rest back.
  const [showAllSessions, setShowAllSessions] = useState(false);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [loadingSessionId, setLoadingSessionId] = useState<string | null>(null);
  const [sessionTitle, setSessionTitle] = useState<string | null>(null);
  // Guards against later prompts in the same session overwriting the name —
  // the session is named once, from the first task's title.
  const sessionTitleRef = useRef<string | null>(null);
  // True while the name is the placeholder POST /tasks derives from the topic, which the LLM's
  // own shorter title (session_title, over SSE) is allowed to replace exactly once.
  const titleIsProvisionalRef = useRef(false);

  // Collapsed, the sidebar shows the newest few — but never hides the session being viewed,
  // which would leave the list with nothing highlighted and the user unable to tell where
  // they are. Sessions are sorted newest-first, so slicing keeps that order.
  const visibleSessions = showAllSessions
    ? pastSessions
    : pastSessions.filter(
        (s, i) => i < SESSIONS_COLLAPSED_COUNT || s.id === activeSessionId
      );
  const hiddenSessionCount = pastSessions.length - visibleSessions.length;
  // Two reasons to show the control, and it needs both: something is hidden and can be
  // revealed, or the list is expanded and can be put back. Testing only the first would take
  // "Show less" away the moment it worked; testing only overflow would offer "Show 0 more" in
  // the case where pinning the active session happens to make the whole list visible anyway.
  const showSessionsToggle = showAllSessions || hiddenSessionCount > 0;

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
	sessionTitleRef.current = session.title ?? null;
	// A saved title is settled, not a placeholder — nothing in this session may rename it.
	titleIsProvisionalRef.current = false;
	setSessionTitle(session.title ?? null);

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

  /**
   * Back to a blank chat, without a page reload.
   *
   * The inverse of `loadSession`, and it has to reset everything that one sets plus everything
   * a run leaves behind — most importantly the live SSE stream, which would otherwise keep
   * writing a dead session's roundtable into the new one. No backend call: a session is
   * registered lazily by the first `handleSend`, so "new chat" is purely forgetting this one.
   *
   * The sidebar list is left alone deliberately. The session being left is still the user's,
   * and it stays there to go back to.
   */
  function startNewChat() {
    if (isLoading || loadingSessionId) return;

    if (workflowEsRef.current) {
      workflowEsRef.current.close();
      workflowEsRef.current = null;
    }

    setMessages(INITIAL_MESSAGES);
    setInput("");
    setAttachments([]);
    pendingRefsRef.current = [];

    historyRef.current = [];
    sessionIdRef.current = null;
    setActiveSessionId(null);

    setSessionTitle(null);
    sessionTitleRef.current = null;
    titleIsProvisionalRef.current = false;

    campaignRef.current = null;
    requestedPublishAtRef.current = "";

    roundtableMsgIdRef.current.clear();
    socialCardIdRef.current.clear();
    streamingAssistantRef.current = null;

    // Platforms, content types, roundtable and planning modes survive: those are how this user
    // works, not part of the conversation they just closed.
  }

  /**
   * Names the session — on screen and in the database.
   *
   * Two titles arrive for one session. `POST /tasks` answers immediately with a deterministic
   * one derived from the topic, and the LLM's short version follows over SSE a moment later.
   * The first is provisional precisely so the second can replace it; anything after that is
   * ignored, because later prompts in the same session must not rename it.
   *
   * The PATCH is fire-and-forget. A session that fails to save its name still works — it just
   * shows its date in the sidebar next time, which is exactly where this started.
   */
  function applySessionTitle(title: string, { provisional = true }: { provisional?: boolean } = {}) {
    // Named already, and not by a placeholder this call is entitled to replace.
    if (sessionTitleRef.current && !(titleIsProvisionalRef.current && !provisional)) return;

    sessionTitleRef.current = title;
    titleIsProvisionalRef.current = provisional;
    setSessionTitle(title);
    setPastSessions((prev) =>
      prev.map((s) => (s.id === sessionIdRef.current ? { ...s, title } : s))
    );

    if (sessionIdRef.current) {
      fetch(`/api/sessions/${sessionIdRef.current}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ title }),
      }).catch(() => {});
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

  function togglePlanningMode() {
    // Switching off abandons any half-gathered campaign. Left in place, a campaign that had
    // asked for its dates would keep claiming turns after the user had visibly opted out of
    // planning — the next message would answer a question they no longer wanted asked.
    if (planningMode) campaignRef.current = null;
    setPlanningMode(!planningMode);
  }

  function readFileAsDataUrl(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });
  }

  // Attach up to 3 images total; used as image-to-video reference images on the render.
  async function handleAttachFiles(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []).filter((f) => f.type.startsWith("image/"));
    if (files.length === 0) return;
    const room = Math.max(0, 3 - attachments.length);
    const chosen = files.slice(0, room);
    const added = await Promise.all(
      chosen.map(async (f) => ({ name: f.name, dataUrl: await readFileAsDataUrl(f) }))
    );
    setAttachments((prev) => [...prev, ...added].slice(0, 3));
    // Reset so re-selecting the same file fires change again.
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function removeAttachment(index: number) {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  }

  /**
   * Sends the user's verdict on a text draft to the human gate.
   *
   * @param editedText the copy as it stands in the card when Approve was clicked. When it
   *   differs from what the agent wrote, the verdict becomes `approve_after_edit` and the gate
   *   swaps the edited copy in as the approved draft — so media_producer storyboards from the
   *   user's words, and the final post publishes them. Unchanged text sends a plain `approve`.
   * @param reason free-text feedback on a rejection, threaded back to the creator for the
   *   re-draft. Optional: rejecting without saying why still works.
   */
  function handleApproval(
    messageId: string,
    approval: ApprovalStatus,
    editedText?: string,
    reason?: string
  ) {
    const msg = messages.find((m) => m.id === messageId);
    const platformLabel = platformMap[msg?.platform ?? ""]?.label ?? "platform";

    const edited = editedText?.trim();
    const wasEdited =
      approval === "approved" && !!edited && edited !== (msg?.draft?.text ?? "").trim();

    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId
          ? {
              ...m,
              approval,
              // Keep the card (and everything downstream that reads it — the video caption, the
              // post body) on the copy the user actually approved, not the draft they replaced.
              ...(wasEdited ? { draft: { ...m.draft, text: edited! } } : {}),
            }
          : m
      )
    );

    // For workflow drafts, submit the verdict to the human gate so the MAF
    // pipeline can continue (media_producer runs after approval, creator re-drafts after reject).
    if (msg?.workflowTaskId && msg.platform) {
      const decision =
        approval !== "approved" ? "reject" : wasEdited ? "approve_after_edit" : "approve";
      fetch(`/api/tasks/${msg.workflowTaskId}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          verdicts: {
            [msg.platform]: {
              decision,
              ...(wasEdited ? { edited_draft: edited } : {}),
              ...(reason?.trim() ? { reason: reason.trim() } : {}),
            },
          },
        }),
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

  // ── In-feed post mockup — one growing card per (task, platform) ──────────────

  /**
   * Applies `patch` to a run's post-mockup card, creating it on first contact.
   *
   * The card is the post itself, not a step in it: the copy arrives first (draft_ready), the
   * storyboard lands in its media slot afterwards (final), and the render replaces that — all
   * in the same mockup, so the user is always looking at the thing they're about to publish.
   * Keyed by task AND platform because one run can draft for several platforms at once, and
   * each gets its own mockup in its own platform's chrome.
   */
  function upsertSocialCard(
    taskId: string,
    platform: MockupPlatform,
    patch: (m: Message) => Partial<Message>
  ) {
    const key = `${taskId}:${platform}`;
    setMessages((prev) => {
      const existingId = socialCardIdRef.current.get(key);
      if (existingId) {
        return prev.map((m) => (m.id === existingId ? { ...m, ...patch(m) } : m));
      }
      const id = newId();
      socialCardIdRef.current.set(key, id);
      const base: Message = {
        id,
        role: "assistant",
        content: `Here's how your ${POST_MOCKUP[platform].label} post is shaping up:`,
        variant: "social-post",
        platform,
        workflowTaskId: taskId,
        timestamp: new Date(),
      };
      return [...prev, { ...base, ...patch(base) }];
    });
  }

  /** Signs off (or sends back) the storyboard stage. Purely local: by the time a storyboard
   *  exists the workflow has already yielded its output, so there is no gate to answer —
   *  approving it just unlocks the render. */
  function setStoryboardApproval(messageId: string, approval: ApprovalStatus) {
    setMessages((prev) =>
      prev.map((m) => (m.id === messageId ? { ...m, storyboardApproval: approval } : m))
    );
  }

  /** Swaps in a revised storyboard after the user asked for changes, leaving it pending so
   *  they can look at the revision and either accept it or push back again. */
  function patchSocialStoryboard(messageId: string, storyboard: VideoStoryboard) {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId
          ? { ...m, videoStoryboard: storyboard, storyboardApproval: "pending" }
          : m
      )
    );
  }

  // ── Roundtable stage helpers — one growing stage per table_id ────────────────

  /** Applies `patch` to a table's stage message, creating the stage on first contact
   *  (usually the moderator's opening speaker_scheduled announcement). */
  function upsertRoundtable(
    taskId: string,
    tableId: string,
    patch: (m: Message) => Partial<Message>
  ) {
    setMessages((prev) => {
      const existingId = roundtableMsgIdRef.current.get(tableId);
      if (existingId) {
        return prev.map((m) => (m.id === existingId ? { ...m, ...patch(m) } : m));
      }
      const id = newId();
      roundtableMsgIdRef.current.set(tableId, id);
      const base: Message = {
        id,
        role: "assistant",
        content: `The roundtable convenes — ${tableId}:`,
        variant: "roundtable",
        platform: tableId as Platform,
        workflowTaskId: taskId,
        roundtableTableId: tableId,
        roundtableFeed: [],
        roundtableFloor: null,
        roundtableConverged: false,
        timestamp: new Date(),
      };
      return [...prev, { ...base, ...patch(base) }];
    });
  }

  /** speaker_scheduled: the moderator hands the mic over — announce it and mark the floor. */
  function scheduleRoundtableSpeaker(taskId: string, tableId: string, floor: RoundtableFloor) {
    upsertRoundtable(taskId, tableId, (m) => ({
      roundtableFeed: [
        ...(m.roundtableFeed ?? []),
        { kind: "announcement", speaker: floor.speaker, roundIndex: floor.roundIndex },
      ],
      roundtableFloor: floor,
    }));
  }

  /** agent_utterance: the turn completed — append it and return the floor to the moderator. */
  function appendRoundtableTurn(taskId: string, tableId: string, turn: RoundtableTurn) {
    upsertRoundtable(taskId, tableId, (m) => ({
      roundtableFeed: [...(m.roundtableFeed ?? []), { kind: "turn", turn }],
      roundtableFloor:
        m.roundtableFloor?.speaker === turn.speaker ? null : m.roundtableFloor ?? null,
    }));
  }

  /** agent_utterance_audio: the background TTS clip for an already-shown turn arrived —
   *  find it by (speaker, roundIndex) and attach the clip; the turn itself doesn't move. */
  function attachRoundtableTurnAudio(
    taskId: string, tableId: string, speaker: string, roundIndex: number, audioUrl: string
  ) {
    upsertRoundtable(taskId, tableId, (m) => ({
      roundtableFeed: (m.roundtableFeed ?? []).map((item) =>
        item.kind === "turn" && item.turn.speaker === speaker && item.turn.roundIndex === roundIndex
          ? { ...item, turn: { ...item.turn, audioUrl } }
          : item
      ),
    }));
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
          ? {
              ...m,
              roundtableConverged: true,
              roundtableStrategy: summary,
              roundtableFloor: null,
              roundControlWaiting: null,
            }
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
    // Keyed by task id, so these can't collide across runs — cleared only to stop the map
    // growing for the length of the session. Storyboard revisions patch by message id, so an
    // earlier run's card stays fully interactive after this.
    socialCardIdRef.current.clear();

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
	  if (data.title) {
	    applySessionTitle(data.title as string);
	  }
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

      // The LLM's own short title, generated off the hot path and arriving a beat after the
      // run begins. It replaces the placeholder the POST /tasks response set, and saves.
      if (type === "session_title") {
        const title = event.title;
        if (typeof title === "string" && title.trim()) {
          applySessionTitle(title, { provisional: false });
        }
        return;
      }

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

      // speaker_scheduled: the moderator handed the mic over — announce the upcoming
      // speaker on the stage (this is also what creates the stage, before anyone speaks).
      // The round-0 "moderator" event is the convening announcement (emitted the moment the
      // table starts, while the manager is still planning): create the stage so it shows
      // "The moderator is convening the table…" instead of dead air, but give nobody the floor.
      if (type === "speaker_scheduled") {
        const tableId = event.table_id as string;
        const speaker = event.speaker as string;
        if (speaker === MODERATOR) {
          upsertRoundtable(taskId, tableId, () => ({}));
        } else {
          scheduleRoundtableSpeaker(taskId, tableId, {
            speaker,
            roundIndex: event.round_index as number,
          });
        }
      }

      // agent_utterance: one roundtable persona (or the user) spoke — grow that table's stage.
      if (type === "agent_utterance") {
        const tableId = event.table_id as string;
        appendRoundtableTurn(taskId, tableId, {
          speaker: event.speaker as string,
          role: event.role as string,
          text: event.text as string,
          roundIndex: event.round_index as number,
        });
      }

      // agent_utterance_audio: the TTS clip for a turn already shown — arrives later,
      // synthesized in the background so it never held up the text discussion.
      if (type === "agent_utterance_audio") {
        const audioB64 = event.audio_b64 as string | undefined;
        if (audioB64) {
          const dataUrl = `data:audio/mpeg;base64,${audioB64}`;
          attachRoundtableTurnAudio(
            taskId,
            event.table_id as string,
            event.speaker as string,
            event.round_index as number,
            dataUrl
          );
          if (autoPlayRoundtableAudioRef.current) {
            enqueueRoundtableAudio(dataUrl);
          }
        }
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
          const draftFields = {
            draft: { text: event.draft as string },
            needsHumanIntervention: (event.needs_human_intervention as boolean) ?? false,
            approval: "pending" as ApprovalStatus,
            // When a video was also requested, the single publish is the native video post
            // (caption = this copy) — so no competing text-only post is offered.
            videoAlsoRequested: contentTypes.includes("video"),
            // Set only when this turn's request actually named a time; the card falls back to
            // Post Now otherwise.
            publishAt: requestedPublishAtRef.current || undefined,
          };
          if (isMockupPlatform(platform as string)) {
            // The publishable platforms review the whole post in one mockup card. Upsert rather
            // than push so a re-draft after "Request changes" lands back in the SAME card as
            // fresh pending copy, instead of leaving the rejected version sitting above it.
            const mockup = platform as MockupPlatform;
            upsertSocialCard(taskId, mockup, () => ({
              content: `Here's how your ${POST_MOCKUP[mockup].label} post is shaping up — edit the copy if you like, then approve:`,
              ...draftFields,
            }));
          } else {
            pushMessage({
              role: "assistant",
              content: `Here's your ${platform} draft — approve or request changes:`,
              variant: "text-preview",
              platform: platform as Platform,
              workflowTaskId: taskId,
              ...draftFields,
            });
          }
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
          const storyboardFields = {
            videoStoryboard: event.video_storyboard as VideoStoryboard,
            referenceImages: pendingRefsRef.current.length ? pendingRefsRef.current : undefined,
          };
          if (isMockupPlatform(platform as string)) {
            // Slot the storyboard into the media area of the card the copy is already in. A
            // video-only run never hit the gate, so there may be no card yet — upsert creates
            // one, carrying the storyboard straight to its own approval step.
            upsertSocialCard(taskId, platform as MockupPlatform, () => ({
              content: "Storyboard's ready — take a look before we render it:",
              ...storyboardFields,
              storyboardApproval: "pending",
              // media_producer generates from the approved (possibly edited) copy, so `draft`
              // here is the text the user signed off — the caption this publishes with.
              draft: contentTypes.includes("text") ? { text: event.draft as string } : undefined,
            }));
          } else {
            pushMessage({
              role: "assistant",
              content: `Brand video storyboard — ${platform}:`,
              platform: platform as Platform,
              workflowTaskId: taskId,
              approval: "approved",
              ...storyboardFields,
              // Carry the approved copy so the video card prefills its caption with it — a text+video
              // task then publishes as one native video post with the generated copy as the caption.
              draft: contentTypes.includes("text") ? { text: event.draft as string } : undefined,
            });
          }
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

    // Snapshot the turn's reference images, then clear the compose tray. They ride
    // the user message and are carried (pendingRefsRef) to this run's storyboard card.
    const refImages = attachments.map((a) => a.dataUrl);
    pendingRefsRef.current = refImages;
    pushMessage({ role: "user", content: trimmed, referenceImages: refImages.length ? refImages : undefined });
    historyRef.current = [...historyRef.current, { role: "user", content: trimmed }];
    setInput("");
    setAttachments([]);
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

    setIsLoading(true);
    try {
      // Is this a campaign rather than a post? Asked first, because the answer decides which
      // of two entirely different pipelines runs. A turn that isn't one — or a classifier that
      // is unreachable — falls straight through to the workflow path below, unchanged.
      if (await handleCampaignTurn(trimmed)) return;

      // Single workflow call — the MAF pipeline generates text drafts, brand
      // animations, and video specs in one pass. genWorkflow() gates which output
      // cards are shown based on the current contentTypes selection.
      await genWorkflow(trimmed);
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

        {/* Pinned above the scrolling list: starting over shouldn't require scrolling past
            however many past sessions the user has. */}
        <div className="px-5 pt-5 flex-shrink-0">
          <button
            onClick={startNewChat}
            disabled={isLoading || loadingSessionId !== null}
            className="w-full bg-[#FF4800] hover:bg-[#E03E00] disabled:opacity-50 text-white text-sm font-medium py-2.5 rounded-xl transition-colors"
          >
            + New chat
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-7">
          {/* Past Sessions */}
          {pastSessions.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-[#9E9893] uppercase tracking-wider mb-3">
                Past Sessions
              </h3>
              <div className="space-y-1.5">
                {visibleSessions.map((s) => {
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
                        {isLoading ? "Loading…" : (s.title ?? formatDate(s.createdAt))}
                      </p>
                      {s.targetPlatforms && s.targetPlatforms.length > 0 && (
                        <p className="text-[10px] text-[#9E9893] mt-0.5 truncate">
                          {s.targetPlatforms.map(platformLabel).join(", ")}
                        </p>
                      )}
                    </button>
                  );
                })}
              </div>

              {showSessionsToggle && (
                <button
                  onClick={() => setShowAllSessions((open) => !open)}
                  aria-expanded={showAllSessions}
                  className="flex items-center gap-1.5 w-full px-3 py-2 mt-1.5 rounded-lg text-[11px] font-medium text-[#9E9893] hover:text-[#1B1A17] hover:bg-[#F2EDE4] transition-colors"
                >
                  <svg
                    width="10"
                    height="10"
                    viewBox="0 0 10 10"
                    fill="none"
                    aria-hidden="true"
                    className={`transition-transform ${showAllSessions ? "rotate-180" : ""}`}
                  >
                    <path
                      d="M2 3.5L5 6.5L8 3.5"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  {showAllSessions ? "Show less" : `Show ${hiddenSessionCount} more`}
                </button>
              )}
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

          {/* Planning mode */}
          <div>
            <h3 className="text-xs font-semibold text-[#9E9893] uppercase tracking-wider mb-3">
              Planning
            </h3>
            <button
              onClick={togglePlanningMode}
              aria-pressed={planningMode}
              className={`flex items-center justify-between w-full px-3 py-2 rounded-lg text-sm transition-colors border ${
                planningMode
                  ? "bg-[#FFF0EB] text-[#FF4800] border-[#FFCBB8]"
                  : "text-[#6B6561] border-[#E8E3DA] hover:bg-[#F2EDE4]"
              }`}
            >
              <span>Posting plan</span>
              <span
                className={`w-9 h-5 rounded-full relative transition-colors flex-shrink-0 ${
                  planningMode ? "bg-[#FF4800]" : "bg-[#E8E3DA]"
                }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                    planningMode ? "translate-x-4" : "translate-x-0"
                  }`}
                />
              </span>
            </button>
            <p className="text-[10px] text-[#BDB6AE] mt-1.5 leading-relaxed">
              When on, your message becomes a dated schedule of posts across a period rather than
              one post. Expect a question or two about the goal and the dates.
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
			    {sessionTitle ?? (activeSessionId ? `Session ${activeSessionId}` : "New Session")}
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
            // Checked before the storyboard branch below, which keys off field presence rather
            // than variant: once a storyboard lands in a mockup card's media area it would
            // otherwise flip the whole post preview over to the bare storyboard card.
            if (msg.variant === "social-post" && isMockupPlatform(msg.platform ?? "")) {
              return (
                <SocialPostCard
                  key={msg.id}
                  message={msg}
                  platform={msg.platform as MockupPlatform}
                  onApprove={(editedText) => handleApproval(msg.id, "approved", editedText)}
                  onReject={(reason) => handleApproval(msg.id, "rejected", undefined, reason)}
                  onStoryboardApprove={() => setStoryboardApproval(msg.id, "approved")}
                  onStoryboardPatch={(storyboard) => patchSocialStoryboard(msg.id, storyboard)}
                  formatTime={formatTime}
                />
              );
            }

            // Workflow final event: storyboard delivered directly (no job polling
            // needed for this part) — actually rendering the MP4 is a separate,
            // explicitly-triggered job the card kicks off on demand.
            if (msg.videoStoryboard) {
              return (
                <VideoStoryboardCard key={msg.id} message={msg} formatTime={formatTime} />
              );
            }

            if (msg.variant === "roundtable") {
              return (
                <RoundtableStage
                  key={msg.id}
                  message={msg}
                  formatTime={formatTime}
                  autoPlayAudio={autoPlayRoundtableAudio}
                  onToggleAutoPlayAudio={toggleAutoPlayRoundtableAudio}
                />
              );
            }

            if (msg.variant === "plan-preview" && msg.plan) {
              return (
                <PlanCard
                  key={msg.id}
                  message={msg}
                  plan={msg.plan}
                  authHeaders={authHeaders}
                  onPlanChanged={(plan) => updatePlanMessage(msg.id, plan)}
                  onNotice={(text) => pushMessage({ role: "assistant", content: text })}
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
          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3">
              {attachments.map((a, i) => (
                <div key={i} className="relative group">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={a.dataUrl}
                    alt={a.name}
                    className="w-14 h-14 object-cover rounded-lg border border-[#E8E3DA]"
                  />
                  <button
                    onClick={() => removeAttachment(i)}
                    aria-label={`Remove ${a.name}`}
                    className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-[#1B1A17] text-white text-xs flex items-center justify-center shadow hover:bg-[#FF4800] transition-colors"
                  >
                    ×
                  </button>
                </div>
              ))}
              <span className="self-center text-[10px] text-[#9E9893]">
                Reference image{attachments.length !== 1 ? "s" : ""} for video · {attachments.length}/3
              </span>
            </div>
          )}
          <div className="flex gap-3 items-end">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              onChange={handleAttachFiles}
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={attachments.length >= 3}
              aria-label="Attach reference image"
              title="Attach reference image (for AI video)"
              className="text-[#9E9893] hover:text-[#FF4800] disabled:opacity-40 disabled:cursor-not-allowed p-3 rounded-xl border border-[#E8E3DA] hover:border-[#FFCBB8] transition-colors flex-shrink-0"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M21.44 11.05l-9.19 9.19a5 5 0 0 1-7.07-7.07l9.19-9.19a3 3 0 0 1 4.24 4.24l-9.2 9.19a1 1 0 0 1-1.41-1.41l8.49-8.49" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
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
 *
 * Preview and download only — there are no publish controls here because the platforms this
 * still serves (X, TikTok) have no posting integration. LinkedIn and Facebook storyboards go
 * to SocialPostCard instead, which reviews and publishes the whole post as one piece.
 */
function VideoStoryboardCard({ message, formatTime }: VideoStoryboardCardProps) {
  const storyboard = message.videoStoryboard!;
  const [renderState, setRenderState] = useState<"idle" | "pending" | "done" | "error">("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  // Reference images carried from the compose box; the user can drop any before rendering.
  const [refs, setRefs] = useState<string[]>(message.referenceImages ?? []);

  async function startRender() {
    if (!message.workflowTaskId || !message.platform) return;
    setRenderState("pending");
    setError(null);
    setElapsed(0);
    try {
      const res = await fetch("/api/video", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          taskId: message.workflowTaskId,
          platform: message.platform,
          ...(refs.length > 0 ? { referenceImages: refs } : {}),
        }),
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
            {refs.length > 0 && (
              <div className="mb-2">
                <p className="text-[10px] text-[#9E9893] mb-1.5">
                  Reference image{refs.length !== 1 ? "s" : ""} — the video is generated from these:
                </p>
                <div className="flex flex-wrap gap-2">
                  {refs.map((src, i) => (
                    <div key={i} className="relative group">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={src}
                        alt={`reference ${i + 1}`}
                        className="w-12 h-12 object-cover rounded-md border border-[#E8E3DA]"
                      />
                      <button
                        onClick={() => setRefs((prev) => prev.filter((_, j) => j !== i))}
                        aria-label={`Remove reference ${i + 1}`}
                        className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-[#1B1A17] text-white text-[10px] flex items-center justify-center shadow hover:bg-[#FF4800] transition-colors"
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
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

// ── Roundtable Stage ──────────────────────────────────────────────────────────

interface RoundtableStageProps {
  message: Message;
  formatTime: (d: Date) => string;
  autoPlayAudio: boolean;
  onToggleAutoPlayAudio: () => void;
}

// The always-present AI seats; trend_scout joins only when it actually appears in the
// stream (the backend seats it behind TREND_SCOUT_ENABLED).
const CORE_SEATS = ["platform_editor", "brand_voice", "user_advocate", "audience_advocate"];

/** Seat order around the table: the moderator chairs from the head (top), the user
 *  sits at the foot (bottom), and the AI seats split evenly along the two sides. */
function seatOrder(aiSeats: string[]): string[] {
  const total = aiSeats.length + 2; // + moderator + user
  const foot = Math.floor(total / 2); // the index that lands at the foot of the table
  return [
    MODERATOR,
    ...aiSeats.slice(0, foot - 1),
    "user",
    ...aiSeats.slice(foot - 1),
  ];
}

/** Evenly spaces `total` seats on the table's ellipse; index 0 lands at the head. */
function seatPosition(index: number, total: number): { left: string; top: string } {
  const angle = ((-90 + (index * 360) / total) * Math.PI) / 180;
  return {
    left: `${50 + 40 * Math.cos(angle)}%`,
    top: `${50 + 37 * Math.sin(angle)}%`,
  };
}

function Seat({
  speaker,
  stance,
  speaking,
  deliberating,
  position,
}: {
  speaker: string;
  stance: Stance;
  speaking: boolean;
  deliberating: boolean;
  position: { left: string; top: string };
}) {
  const meta = personaMeta(speaker);
  const isModerator = speaker === MODERATOR;
  // The ring is the disagreement gauge; the moderator stays neutral by design.
  const ringColor = isModerator ? "rgba(232,227,218,0.55)" : STANCE_META[stance].color;
  return (
    <div
      className="absolute flex flex-col items-center -translate-x-1/2 -translate-y-1/2 w-24 text-center"
      style={position}
    >
      <div className="relative">
        {speaking && (
          <span
            className="absolute -inset-1.5 rounded-full animate-pulse"
            style={{ background: `${meta.color}40` }}
          />
        )}
        <div
          className="relative w-12 h-12 rounded-full flex items-center justify-center transition-shadow"
          style={{
            background: `${meta.color}22`,
            border: `2.5px solid ${ringColor}`,
            boxShadow: speaking ? `0 0 20px ${meta.color}90` : "0 2px 10px rgba(0,0,0,0.45)",
          }}
        >
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke={meta.color}
            strokeWidth="1.8"
            aria-hidden="true"
          >
            {meta.glyph}
          </svg>
        </div>
      </div>
      <span
        className={`mt-1.5 text-[10px] font-medium leading-tight ${
          speaking ? "text-white" : "text-white/60"
        }`}
      >
        {meta.label}
      </span>
      {speaking && (
        <span
          className="text-[9px] font-semibold uppercase tracking-widest animate-pulse"
          style={{ color: meta.color }}
        >
          speaking
        </span>
      )}
      {deliberating && (
        <span className="text-[9px] font-semibold uppercase tracking-widest text-white/45 animate-pulse">
          deliberating
        </span>
      )}
    </div>
  );
}

const CLAMP_3: React.CSSProperties = {
  display: "-webkit-box",
  WebkitLineClamp: 3,
  WebkitBoxOrient: "vertical",
  overflow: "hidden",
};

/**
 * One full-width boardroom per discussion table. The dark stage seats every participant
 * around an elliptical table — moderator at the head, user at the foot — with each seat's
 * ring showing its current disagreement temperature and a pulse on whoever holds the mic
 * (speaker_scheduled announces the handoff before the turn completes). The minutes panel
 * keeps the full transcript, moderator announcements included; below it live the step-mode
 * round controls (manual mode) and the always-available raise-hand seat.
 */
function RoundtableStage({
  message, formatTime, autoPlayAudio, onToggleAutoPlayAudio,
}: RoundtableStageProps) {
  const [handRaised, setHandRaised] = useState(false);
  const [sayText, setSayText] = useState("");
  const [speakText, setSpeakText] = useState("");
  const [busy, setBusy] = useState(false);
  const feedEndRef = useRef<HTMLDivElement>(null);

  const taskId = message.workflowTaskId;
  const tableId = message.roundtableTableId;
  const feed = message.roundtableFeed ?? [];
  const floor = message.roundtableFloor;
  const waiting = message.roundControlWaiting;
  const converged = message.roundtableConverged;

  // Keep the minutes pinned to the latest entry as the discussion streams in.
  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [feed.length]);

  const speakersSeen = new Set(
    feed.map((f) => (f.kind === "turn" ? f.turn.speaker : f.speaker))
  );
  const aiSeats = [...CORE_SEATS];
  if (speakersSeen.has("trend_scout")) aiSeats.push("trend_scout");
  for (const s of speakersSeen) {
    if (!aiSeats.includes(s) && s !== "user" && s !== MODERATOR) aiSeats.push(s);
  }
  const seats = seatOrder(aiSeats);
  const stances = seatStances(feed);

  let lastTurn: RoundtableTurn | null = null;
  for (let i = feed.length - 1; i >= 0; i--) {
    const item = feed[i];
    if (item.kind === "turn") {
      lastTurn = item.turn;
      break;
    }
  }
  const round = feed.reduce(
    (r, f) => Math.max(r, f.kind === "turn" ? f.turn.roundIndex : f.roundIndex),
    0
  );
  const turnCount = feed.filter((f) => f.kind === "turn").length;

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

  // What the centre of the table shows: the consensus, the moderator's handoff, or the
  // latest spoken point — the "who is talking right now" anchor.
  let centre: React.ReactNode;
  if (converged) {
    centre = (
      <>
        <p className="text-sm font-semibold text-green-400">✓ Consensus reached</p>
        {message.roundtableStrategy && (
          <p className="mt-1 text-[11px] text-white/60 leading-relaxed" style={CLAMP_3}>
            {message.roundtableStrategy}
          </p>
        )}
      </>
    );
  } else if (floor) {
    const meta = personaMeta(floor.speaker);
    centre = (
      <p className="text-xs text-white/60 leading-relaxed">
        The moderator gives the floor to{" "}
        <span className="font-semibold" style={{ color: meta.color }}>
          {meta.label}
        </span>
      </p>
    );
  } else if (lastTurn) {
    const meta = personaMeta(lastTurn.speaker);
    centre = (
      <>
        <p className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: meta.color }}>
          {meta.label}
        </p>
        <p className="text-[11px] text-white/75 leading-relaxed" style={CLAMP_3}>
          {lastTurn.text}
        </p>
      </>
    );
  } else {
    centre = (
      <p className="text-xs text-white/40 italic">The moderator is convening the table…</p>
    );
  }

  return (
    <div className="w-full">
      <p className="text-sm text-[#6B6561] mb-2">{message.content}</p>
      <div className="bg-white border border-[#E8E3DA] rounded-2xl overflow-hidden shadow-sm">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2.5 bg-[#1B1A17] text-white">
          <div className="flex items-baseline gap-2.5">
            <span className="text-sm font-semibold">
              Roundtable — {platformMap[tableId ?? ""]?.label ?? tableId}
            </span>
            {round > 0 && !converged && (
              <span className="text-[10px] text-white/50 font-medium">Round {round}</span>
            )}
          </div>
          {converged ? (
            <span className="text-xs bg-green-500 text-white px-2 py-0.5 rounded-full font-medium">
              Consensus reached
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-white/70">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
              Live
            </span>
          )}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          {/* The boardroom */}
          <div className="relative h-[340px] sm:h-[400px] bg-[#161411] overflow-hidden">
            {/* Spotlight over the table */}
            <div
              className="absolute inset-0"
              style={{
                background:
                  "radial-gradient(ellipse 62% 52% at 50% 46%, rgba(255,240,220,0.10), transparent 70%)",
              }}
            />
            {/* The table itself */}
            <div
              className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-[50%]"
              style={{
                width: "60%",
                height: "44%",
                background: "linear-gradient(165deg, #3B372F 0%, #27231e 70%)",
                border: "1px solid rgba(255,255,255,0.09)",
                boxShadow:
                  "inset 0 2px 16px rgba(255,255,255,0.05), 0 20px 44px rgba(0,0,0,0.55)",
              }}
            />
            {/* Centre of the table: who has the floor / the latest point / the consensus */}
            <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[42%] text-center">
              {centre}
            </div>
            {seats.map((s, i) => (
              <Seat
                key={s}
                speaker={s}
                position={seatPosition(i, seats.length)}
                stance={stances[s] ?? "idle"}
                speaking={floor?.speaker === s}
                deliberating={
                  s === MODERATOR && !converged && !floor && feed.length > 0
                }
              />
            ))}
          </div>

          {/* Minutes: the full transcript, announcements included */}
          <div className="flex flex-col h-[280px] lg:h-auto lg:max-h-[400px] border-t lg:border-t-0 lg:border-l border-[#E8E3DA] bg-[#FBF9F4]">
            <div className="flex items-center justify-between px-3 py-2 border-b border-[#E8E3DA] flex-shrink-0">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-[#9E9893]">
                Minutes
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={onToggleAutoPlayAudio}
                  title={
                    autoPlayAudio
                      ? "Auto-play voice: on — each persona's clip plays as it arrives"
                      : "Auto-play voice: off — click a clip's play button to hear it"
                  }
                  className={`flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full border transition-colors ${
                    autoPlayAudio
                      ? "bg-[#1B1A17] text-white border-[#1B1A17]"
                      : "bg-white text-[#9E9893] border-[#E8E3DA] hover:text-[#1B1A17]"
                  }`}
                >
                  <span aria-hidden>{autoPlayAudio ? "\u{1F50A}" : "\u{1F507}"}</span>
                  Auto-play
                </button>
                <span className="text-[10px] text-[#BDB6AE]">
                  {turnCount} {turnCount === 1 ? "turn" : "turns"}
                </span>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {feed.length === 0 && (
                <p className="text-xs text-[#9E9893] italic">
                  The table is being seated…
                </p>
              )}
              {feed.map((item, i) => {
                if (item.kind === "announcement") {
                  const meta = personaMeta(item.speaker);
                  return (
                    <p key={i} className="text-[10px] text-[#9E9893] italic text-center py-0.5">
                      {item.speaker === "user"
                        ? "The moderator invites you to speak"
                        : `The moderator gives the floor to ${meta.label}`}{" "}
                      · round {item.roundIndex}
                    </p>
                  );
                }
                const meta = personaMeta(item.turn.speaker);
                const stance = STANCE_META[stanceOf(item.turn.text)];
                return (
                  <div key={i} className="bg-white border border-[#E8E3DA] rounded-lg px-2.5 py-2">
                    <div className="flex items-center gap-1.5 mb-1">
                      <span
                        className="w-2 h-2 rounded-full flex-shrink-0"
                        style={{ background: meta.color }}
                      />
                      <span className="text-[10px] font-bold text-[#1B1A17]">{meta.label}</span>
                      <span
                        className="w-1.5 h-1.5 rounded-full ml-auto flex-shrink-0"
                        title={stance.label}
                        style={{ background: stance.color }}
                      />
                    </div>
                    <p className="text-xs text-[#1B1A17] whitespace-pre-wrap leading-relaxed">
                      {item.turn.text}
                    </p>
                    {item.turn.audioUrl && (
                      <audio controls src={item.turn.audioUrl} className="mt-1 h-7 w-full" />
                    )}
                  </div>
                );
              })}
              <div ref={feedEndRef} />
            </div>
          </div>
        </div>

        {/* Disagreement legend */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-2 border-t border-[#E8E3DA] bg-white">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-[#9E9893]">
            Seat rings
          </span>
          {(["aligned", "cautious", "pushback", "opposed"] as Stance[]).map((s) => (
            <span key={s} className="flex items-center gap-1.5 text-[10px] text-[#6B6561]">
              <span className="w-2 h-2 rounded-full" style={{ background: STANCE_META[s].color }} />
              {STANCE_META[s].label}
            </span>
          ))}
        </div>

        {waiting && !converged && (
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

        {!converged && !waiting && (
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

        {converged && message.roundtableStrategy && (
          <div className="px-4 pb-3 pt-2 text-xs text-[#6B6561] border-t border-[#E8E3DA]">
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

// ── Posting Plan Card ─────────────────────────────────────────────────────────

interface PlanCardProps {
  message: Message;
  plan: Plan;
  authHeaders: () => Record<string, string>;
  onPlanChanged: (plan: Plan) => void;
  onNotice: (text: string) => void;
  formatTime: (d: Date) => string;
}

/**
 * The campaign schedule, in chat.
 *
 * Shows what would go out and when — strategy, never copy, because the posts themselves are
 * not written until the plan is confirmed. Two actions carry the whole loop: **refine**
 * regenerates the schedule from free-text feedback, and **confirm** activates it and starts
 * writing every post.
 *
 * Per-slot editing lives on the full plans page rather than here. Chat is the right place to
 * say "more Facebook, push harder in the final week" and see the schedule change; it is a
 * poor place to retype one slot's topic, and the plans page already does that well.
 */
function PlanCard({
  message,
  plan,
  authHeaders,
  onPlanChanged,
  onNotice,
  formatTime,
}: PlanCardProps) {
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState<"refining" | "confirming" | null>(null);
  const [draftMode, setDraftMode] = useState<DraftMode>("roundtable");

  const isDraft = plan.status === "draft";

  async function handleRefine() {
    const text = feedback.trim();
    if (!text || busy) return;

    setBusy("refining");
    try {
      const res = await fetch(`/api/plans/${plan.plan_id}/refine`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ feedback: text }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        onNotice(data.error ?? "I couldn't revise that plan.");
        return;
      }
      // Same plan_id, so the card updates in place rather than stacking a second schedule
      // below the first — the user is iterating on one campaign, not collecting drafts.
      onPlanChanged(data as Plan);
      setFeedback("");
    } catch {
      onNotice("Could not reach the planning service.");
    } finally {
      setBusy(null);
    }
  }

  async function handleConfirm() {
    if (busy) return;

    setBusy("confirming");
    try {
      const res = await fetch(`/api/plans/${plan.plan_id}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ draft_mode: draftMode }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        onNotice(data.error ?? "I couldn't confirm that plan.");
        return;
      }
      onPlanChanged(data as Plan);
      onNotice(
        `Confirmed — I'm writing your ${plan.items.length} posts now, one at a time. Follow ` +
        `along in Posting Plans; nothing publishes until you approve it.`
      );
    } catch {
      onNotice("Could not reach the planning service.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="w-full max-w-lg">
      <p className="text-sm text-[#6B6561] mb-2">{message.content}</p>

      <div className="bg-white border border-[#E8E3DA] rounded-2xl overflow-hidden shadow-sm">
        <div className="px-4 py-3 bg-[#1B1A17] text-white">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-semibold truncate">{plan.goal}</p>
            <span
              className={`text-[10px] px-2 py-0.5 rounded-full font-medium flex-shrink-0 ${
                isDraft ? "bg-white/15 text-white" : "bg-green-500 text-white"
              }`}
            >
              {isDraft ? "draft" : plan.status}
            </span>
          </div>
          <p className="text-[11px] text-white/60 mt-0.5">
            {plan.start_date} → {plan.end_date} · {plan.items.length} posts
          </p>
        </div>

        {plan.strategy_summary && (
          <p className="px-4 py-2.5 text-xs text-[#6B6561] leading-relaxed border-b border-[#E8E3DA] bg-[#FFF9F5]">
            {plan.strategy_summary}
          </p>
        )}

        {/* Capped height: a six-week campaign is 20+ slots, and a card that long buries the
            actions the user needs at the bottom of it. */}
        <div className="max-h-72 overflow-y-auto divide-y divide-[#F2EDE4]">
          {plan.items.map((item) => (
            <div key={item.item_id} className="px-4 py-2.5">
              <div className="flex items-center gap-2 flex-wrap mb-0.5">
                <span className="text-xs font-semibold text-[#1B1A17]">{item.planned_date}</span>
                {item.time_of_day && (
                  <span className="text-[10px] text-[#9E9893]">{item.time_of_day}</span>
                )}
                {item.platforms.map((p) => (
                  <span
                    key={p}
                    className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-[#F2EDE4] text-[#6B6561]"
                  >
                    {p}
                  </span>
                ))}
              </div>
              <p className="text-sm text-[#1B1A17]">{item.topic}</p>
              {item.rationale && (
                <p className="text-[11px] text-[#9E9893] mt-0.5 leading-relaxed">{item.rationale}</p>
              )}
            </div>
          ))}
        </div>

        {isDraft ? (
          <div className="p-3 border-t border-[#E8E3DA] bg-[#F8F5EE] space-y-2">
            <div className="flex gap-2">
              <input
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleRefine();
                  }
                }}
                placeholder="Ask for changes — e.g. more Facebook, fewer promos"
                disabled={busy !== null}
                className="flex-1 min-w-0 bg-white border border-[#E8E3DA] rounded-lg px-3 py-1.5 text-xs placeholder:text-[#C8C2BA] disabled:opacity-50"
              />
              <button
                onClick={handleRefine}
                disabled={busy !== null || !feedback.trim()}
                className="text-xs font-medium text-[#FF4800] hover:underline disabled:opacity-40 disabled:no-underline flex-shrink-0 px-1"
              >
                {busy === "refining" ? "Revising…" : "Revise"}
              </button>
            </div>

            {/* The one thing worth deciding before committing: ten posts is the difference
                between half a minute and half an hour of model work. */}
            <div className="flex gap-1.5">
              {(
                [
                  { id: "roundtable", label: "Roundtable", cost: "~3 min a post" },
                  { id: "fast", label: "Fast", cost: "~20 sec a post" },
                ] as const
              ).map((option) => {
                const active = draftMode === option.id;
                return (
                  <button
                    key={option.id}
                    onClick={() => setDraftMode(option.id)}
                    disabled={busy !== null}
                    aria-pressed={active}
                    className={`flex-1 rounded-lg border px-2 py-1.5 text-left transition-colors disabled:opacity-50 ${
                      active
                        ? "border-[#FF4800] bg-[#FFF0EB]"
                        : "border-[#E8E3DA] bg-white hover:border-[#C8C2BA]"
                    }`}
                  >
                    <span className="block text-[11px] font-medium text-[#1B1A17]">
                      {option.label}
                    </span>
                    <span
                      className={`block text-[10px] ${active ? "text-[#FF4800]" : "text-[#9E9893]"}`}
                    >
                      {option.cost}
                    </span>
                  </button>
                );
              })}
            </div>

            <button
              onClick={handleConfirm}
              disabled={busy !== null}
              className="w-full bg-green-600 hover:bg-green-500 disabled:bg-green-300 text-white text-xs font-medium py-2 rounded-lg transition-colors"
            >
              {busy === "confirming"
                ? "Confirming…"
                : `Confirm — write all ${plan.items.length} posts`}
            </button>
            <p className="text-[11px] text-[#9E9893] text-center leading-relaxed">
              Written one at a time, in order, for you to review. Nothing publishes until you
              approve it.
            </p>
          </div>
        ) : (
          <div className="p-3 border-t border-[#E8E3DA] bg-[#F8F5EE] text-center">
            <p className="text-xs text-green-700 font-medium mb-1">
              ✓ Confirmed — writing {plan.items.length} posts
            </p>
            {/* Named, so the link lands on THIS campaign. Without the id it opens on "No plan
                selected" and the user has to find, among every plan they've ever made, the one
                they were looking at a second ago. */}
            <Link
              href={`/plans?plan=${plan.plan_id}`}
              className="text-xs text-[#FF4800] hover:underline"
            >
              Watch them being written →
            </Link>
          </div>
        )}
      </div>

      <p className="text-[10px] text-[#C8C2BA] mt-1">{formatTime(message.timestamp)}</p>
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

/**
 * A generic platform draft: the copy, and approve/reject.
 *
 * Review only — there are no publish controls because the platforms this still serves
 * (X, TikTok) have no posting integration; their copy is drafted here and posted by hand.
 * LinkedIn and Facebook drafts go to SocialPostCard instead, which shows the post in that
 * network's own chrome and carries it all the way through to publishing.
 */
function DraftCard({ message, onApprove, onReject, formatTime }: DraftCardProps) {
  const platform = platformMap[message.platform!];
  const draft = message.draft!;
  const approval = message.approval;

  return (
    <div className="w-full max-w-lg">
      <p className="text-sm text-[#6B6561] mb-2">{message.content}</p>
      <div className="bg-white border border-[#E8E3DA] rounded-2xl overflow-hidden shadow-sm">
        {/* Platform header */}
        <div className={`flex items-center justify-between px-4 py-2.5 ${platform.headerClass}`}>
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

        {/* Approve / Reject */}
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

        {approval === "approved" && (
          <div className="px-4 pb-4">
            <div className="rounded-lg bg-[#F8F5EE] border border-[#E8E3DA] px-3 py-2 text-xs text-[#6B6561]">
              Approved — {platform.label} isn&apos;t connected for publishing, so copy this across
              when you&apos;re ready to post.
            </div>
          </div>
        )}

        <p className="text-xs text-[#9E9893] px-4 pb-3">
          {formatTime(message.timestamp)}
        </p>
      </div>
    </div>
  );
}

// ── LinkedIn Post Card ────────────────────────────────────────────────────────

interface SocialPostCardProps {
  message: Message;
  platform: MockupPlatform;
  /** Approve the copy. Receives the text as it stands in the editor, which may differ from
   *  what the agent wrote — the caller turns that into an `approve_after_edit` verdict. */
  onApprove: (editedText: string) => void;
  onReject: (reason: string) => void;
  onStoryboardApprove: () => void;
  onStoryboardPatch: (storyboard: VideoStoryboard) => void;
  formatTime: (d: Date) => string;
}

/** The publish moment as a feed post would show it: "now", "2h", "3d". */
function relativePostAge(at: Date): string {
  const mins = Math.max(0, Math.floor((Date.now() - at.getTime()) / 60000));
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

/**
 * One post, reviewed in place from first draft to publish, in its own platform's chrome.
 *
 * The card IS the post: the copy sits where the copy will sit, the media (a storyboard, then the
 * rendered MP4, or an attached photo) sits where the media will sit, and each stage's controls
 * hang off the bottom of the same mockup. That replaces a read-only draft card and a separate,
 * ungated storyboard card whose relationship to each other — one post, not two — was never visible.
 *
 * Four stages, driven by the message rather than local state so an SSE re-draft lands correctly:
 *   A. copy       `approval === "pending"`             — editable, Approve / Request changes
 *   B. storyboard `storyboardApproval === "pending"`   — Approve / Request changes (regenerates)
 *   C. render     storyboard approved                  — Render video
 *   D. publish    render done                          — Post, or Post now / Schedule (text only)
 *
 * LinkedIn and Facebook differ only in chrome and in how they publish (POST_MOCKUP + the
 * handlers below); everything about the review itself is shared.
 *
 * **Scheduling is offered on text-only posts.** Media — video or photo — is post-now only,
 * because the scheduler is text-only (`scheduled_post` carries no media column and the sweeper
 * calls only the text endpoints), so a scheduled media post would be a promise nothing
 * downstream could keep. Attaching a photo therefore drops the card back to Post now.
 */
function SocialPostCard({
  message,
  platform,
  onApprove,
  onReject,
  onStoryboardApprove,
  onStoryboardPatch,
  formatTime,
}: SocialPostCardProps) {
  const ui = POST_MOCKUP[platform];
  const draftText = message.draft?.text ?? "";
  const hashtags = message.draft?.hashtags ?? [];
  const approval = message.approval;
  const storyboard = message.videoStoryboard;
  const storyboardApproval = message.storyboardApproval;
  // Video is part of this post either because the run asked for one, or because a storyboard has
  // already landed (a video-only run never sets the flag).
  const hasVideo = !!message.videoAlsoRequested || !!storyboard;

  // The copy editor is uncontrolled and read on submit: there is no save step, so nothing about
  // editing can gate the pipeline. `key` remounts it with fresh text when the agent re-drafts.
  const textRef = useRef<HTMLTextAreaElement>(null);

  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectText, setRejectText] = useState("");

  // Storyboard revision.
  const [sbFeedbackOpen, setSbFeedbackOpen] = useState(false);
  const [sbFeedback, setSbFeedback] = useState("");
  const [sbStatus, setSbStatus] = useState<"idle" | "revising" | "error">("idle");
  const [sbError, setSbError] = useState<string | null>(null);

  // Render — same contract as VideoStoryboardCard: start a job, then poll it.
  const [renderState, setRenderState] = useState<"idle" | "pending" | "done" | "error">("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);

  // Reference images (image-to-video) are DERIVED from the message, not copied into state at
  // mount: this card is created when the copy arrives and the images only land with the later
  // storyboard patch, so a `useState(message.referenceImages)` would freeze an empty list and
  // silently drop them. Removals are tracked instead of the list itself.
  const [droppedRefs, setDroppedRefs] = useState<string[]>([]);
  const refs = (message.referenceImages ?? []).filter((r) => !droppedRefs.includes(r));

  // An optional photo on a text post. File plus its preview URL are one piece of state so the
  // preview can never be left pointing at a file that has been swapped out.
  const [image, setImage] = useState<{ file: File; url: string } | null>(null);

  // What actually went out, kept so the card still shows the post after publishing — on a
  // video-only run the body lives in the (now unmounted) caption box and would otherwise vanish.
  const [postedText, setPostedText] = useState<string | null>(null);

  // Graph captions a Page video from the /videos edge's own title/description fields, so
  // Facebook gets a title box; LinkedIn's video post takes the caption alone.
  const [videoTitle, setVideoTitle] = useState("");

  // Publishing.
  const [postStatus, setPostStatus] = useState<"idle" | "posting" | "posted" | "error">("idle");
  const [postError, setPostError] = useState<string | null>(null);

  // Scheduling (text-only posts). Seeded from the moment the agent read out of the request, so
  // "post this Friday at 10" opens on Schedule with Friday 10:00 already filled in.
  const [agentDate, agentTime] = splitPublishAt(message.publishAt);
  const [postMode, setPostMode] = useState<"now" | "schedule">(agentDate ? "schedule" : "now");
  const [scheduleDate, setScheduleDate] = useState(agentDate);
  const [scheduleTime, setScheduleTime] = useState(agentTime);
  const [scheduleStatus, setScheduleStatus] =
    useState<"idle" | "scheduling" | "scheduled" | "error">("idle");
  const [scheduleError, setScheduleError] = useState<string | null>(null);

  // Release the previous preview URL whenever the pick changes, and the last one on unmount.
  // Cleanup only — no setState, so this never cascades a render.
  useEffect(() => {
    const url = image?.url;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [image]);

  // A video-only run drafts no copy, so there is nothing to approve and nothing to caption the
  // post with — the body doubles as the caption box until the post goes out.
  const captionEntry = !draftText.trim() && postStatus !== "posted";
  const bodyEditable = approval === "pending" || captionEntry;
  // Anything in the media well makes this post-now only (see the class comment).
  const mediaAttached = hasVideo || !!image;

  /** The copy as it will actually publish: body plus hashtags. Reads the editor while it is
   *  open, so an in-progress edit (or a caption typed on a video-only run) is what publishes. */
  function captionText() {
    const live = textRef.current?.value;
    const body = live !== undefined && live !== null ? live : draftText;
    return hashtags.length > 0 ? `${body}\n\n${hashtags.join(" ")}` : body;
  }

  function autoGrow(el: HTMLTextAreaElement) {
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }

  function pickImage(file: File | null) {
    setImage(file ? { file, url: URL.createObjectURL(file) } : null);
    // A photo can't be scheduled, so don't leave the user staring at a date picker that would
    // quietly publish without it.
    if (file) setPostMode("now");
    setPostStatus("idle");
    setPostError(null);
  }

  /** The auth token plus, for Facebook, the Pages to publish to — or an error explaining what
   *  the user still has to connect. Checked before every publish and before scheduling: finding
   *  out a Page was missing when the post came due days later would be far worse. */
  function publishCredentials(
    action: "posting" | "scheduling"
  ): { token: string; pageIds: number[] } | { error: string } {
    const token = localStorage.getItem("starlight_token");
    if (!token) {
      return {
        error: `Log in, then connect ${ui.label} from your Brand Profile before ${action}.`,
      };
    }
    if (!ui.needsPages) return { token, pageIds: [] };
    const pageIds = getSelectedPageIds();
    if (pageIds.length === 0) {
      return { error: "Connect Facebook and pick a Page in your Brand Profile first." };
    }
    return { token, pageIds };
  }

  async function reviseStoryboard() {
    if (!message.workflowTaskId || !message.platform || !sbFeedback.trim()) return;
    setSbStatus("revising");
    setSbError(null);
    try {
      const res = await fetch("/api/storyboard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          taskId: message.workflowTaskId,
          platform: message.platform,
          feedback: sbFeedback.trim(),
        }),
      });
      const data = await res.json();
      if (!res.ok || data.error || !data.storyboard) {
        setSbStatus("error");
        setSbError(data.error ?? "Could not revise the storyboard.");
        return;
      }
      onStoryboardPatch(data.storyboard as VideoStoryboard);
      setSbStatus("idle");
      setSbFeedback("");
      setSbFeedbackOpen(false);
    } catch {
      setSbStatus("error");
      setSbError("Could not reach the backend.");
    }
  }

  async function startRender() {
    if (!message.workflowTaskId || !message.platform) return;
    setRenderState("pending");
    setRenderError(null);
    setElapsed(0);
    try {
      const res = await fetch("/api/video", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          taskId: message.workflowTaskId,
          platform: message.platform,
          ...(refs.length > 0 ? { referenceImages: refs } : {}),
        }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        setRenderState("error");
        setRenderError(data.error ?? "Could not start the render.");
        return;
      }
      setJobId(data.jobId as string);
    } catch {
      setRenderState("error");
      setRenderError("Could not reach the video backend.");
    }
  }

  useEffect(() => {
    if (renderState !== "pending" || !jobId) return;

    // The render is a Remotion CLI subprocess (asset fetch + headless Chromium) — tens of
    // seconds, so poll on a 3s cadence rather than anything tighter.
    const poll = setInterval(async () => {
      try {
        const res = await fetch(`/api/video/${jobId}`);
        const data = await res.json();
        if (data.status === "done") {
          setDownloadUrl(data.downloadUrl as string);
          setRenderState("done");
        } else if (data.status === "error") {
          setRenderState("error");
          setRenderError(data.error ?? "Render failed.");
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

  /**
   * Publishes the post as it stands: video if one was rendered, else photo if one is attached,
   * else plain text. One button, because from the user's side there is only ever one post here.
   */
  async function handlePost() {
    const creds = publishCredentials("posting");
    if ("error" in creds) {
      setPostStatus("error");
      setPostError(creds.error);
      return;
    }
    const { token, pageIds } = creds;

    // Read once: the editor is the source of truth while it's open, and both platforms reject an
    // empty post anyway — better to say so here than round-trip for the same answer.
    const body = captionText();
    if (!body.trim()) {
      setPostStatus("error");
      setPostError("Write a caption for this post first.");
      return;
    }

    setPostStatus("posting");
    setPostError(null);
    try {
      const auth = { Authorization: `Bearer ${token}` };
      const json = { "Content-Type": "application/json", ...auth };
      let res: Response;

      if (hasVideo) {
        // A text+video post publishes ONCE, as a native video post with this copy as the caption.
        res =
          platform === "facebook"
            ? await fetch("/api/meta/post-video", {
                method: "POST",
                headers: json,
                body: JSON.stringify({
                  jobId,
                  // Graph captions a Page video from `description` on the /videos edge and from
                  // `message` on /feed, so send the caption as both and let the one endpoint use
                  // whichever edge the media type picks.
                  message: body,
                  title: videoTitle.trim(),
                  description: body,
                  pageIds,
                }),
              })
            : await fetch("/api/linkedin/post-video", {
                method: "POST",
                headers: json,
                body: JSON.stringify({ jobId, message: body }),
              });
      } else if (image) {
        const form = new FormData();
        form.append("image", image.file);
        form.append("message", body);
        if (platform === "facebook") for (const id of pageIds) form.append("pageId", String(id));
        res = await fetch(platform === "facebook" ? "/api/meta/post" : "/api/linkedin/post-image", {
          method: "POST",
          headers: auth,
          body: form,
        });
      } else if (platform === "facebook") {
        // Java's /meta/post is @ModelAttribute multipart, so even the text-only post goes as a form.
        const form = new FormData();
        form.append("message", body);
        for (const id of pageIds) form.append("pageId", String(id));
        res = await fetch("/api/meta/post", { method: "POST", headers: auth, body: form });
      } else {
        res = await fetch("/api/linkedin/post", {
          method: "POST",
          headers: json,
          body: JSON.stringify({ message: body }),
        });
      }

      const data = await res.json();
      if (!res.ok || data.error) {
        setPostStatus("error");
        setPostError(data.error ?? `Failed to post to ${ui.label}.`);
        return;
      }
      setPostedText(body);
      setPostStatus("posted");
    } catch {
      setPostStatus("error");
      setPostError("Could not reach the backend.");
    }
  }

  /**
   * Queues a text-only post instead of publishing it now.
   *
   * Goes through the shared scheduling API so it lands in the same persisted queue the content
   * calendar reads — one place to see, edit and cancel it, and a schedule that survives a backend
   * restart. The browser's timezone rides along so "10:00" means 10:00 where the user is, not in
   * whatever zone the server runs in.
   */
  async function handleSchedule() {
    const creds = publishCredentials("scheduling");
    if ("error" in creds) {
      setScheduleStatus("error");
      setScheduleError(creds.error);
      return;
    }
    if (!scheduleDate || !scheduleTime) {
      setScheduleStatus("error");
      setScheduleError("Pick a date and time first.");
      return;
    }
    setScheduleStatus("scheduling");
    setScheduleError(null);
    try {
      const res = await fetch("/api/schedule/posts", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${creds.token}`,
        },
        body: JSON.stringify({
          platform,
          message: captionText(),
          date: scheduleDate,
          time: scheduleTime,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          page_ids: creds.pageIds,
        }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        setScheduleStatus("error");
        setScheduleError(data.error ?? "Failed to schedule the post.");
        return;
      }
      setScheduleStatus("scheduled");
    } catch {
      setScheduleStatus("error");
      setScheduleError("Could not reach the backend.");
    }
  }

  // The storyboard names the brand, so the mockup's author row can too once one exists.
  const brandName = storyboard?.brandName?.trim() || "Your brand";
  const initial = brandName.charAt(0).toUpperCase();

  const stageLabel =
    postStatus === "posted"
      ? "Published"
      : scheduleStatus === "scheduled"
        ? "Scheduled"
        : approval === "pending"
          ? "Copy — needs your approval"
          : approval === "rejected"
            ? "Rewriting the copy…"
            : storyboardApproval === "pending"
              ? "Storyboard — needs your approval"
              : renderState === "done"
                ? "Ready to publish"
                : hasVideo && !storyboard
                  ? "Building the storyboard…"
                  : "Ready to post";

  return (
    <div className="w-full max-w-lg">
      <p className="text-sm text-[#6B6561] mb-2">{message.content}</p>

      <div className="bg-white border border-[#E8E3DA] rounded-2xl overflow-hidden shadow-sm">
        {/* Preview strip — this is a composition mockup, never a live post. */}
        <div className="flex items-center justify-between px-4 py-2 bg-[#F8F5EE] border-b border-[#E8E3DA]">
          <span className="flex items-center gap-1.5 text-xs font-semibold text-[#6B6561]">
            <span
              className={`w-4 h-4 rounded-sm ${ui.markClass} text-white text-[10px] font-bold flex items-center justify-center`}
            >
              {ui.mark}
            </span>
            {ui.label} preview
          </span>
          <span className="text-[10px] font-medium text-[#6B6561] bg-white border border-[#E8E3DA] px-2 py-0.5 rounded-full">
            {stageLabel}
          </span>
        </div>

        {/* Author row */}
        <div className="flex items-center gap-3 px-4 pt-4">
          <div
            className={`w-12 h-12 rounded-full ${ui.markClass} text-white text-lg font-semibold flex items-center justify-center shrink-0`}
          >
            {initial}
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-[#1B1A17] truncate">{brandName}</div>
            <div className="text-xs text-[#6B6561] truncate">{storyboard?.theme || ui.byline}</div>
            <div className="flex items-center gap-1 text-xs text-[#9E9893]">
              {relativePostAge(message.timestamp)} ·
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                <path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm7 9h-3a15 15 0 0 0-1.1-5.2A8 8 0 0 1 19 11ZM12 4c.9 1.3 1.7 3.6 1.9 7h-3.8C10.3 7.6 11.1 5.3 12 4ZM9.1 5.8A15 15 0 0 0 8 11H5a8 8 0 0 1 4.1-5.2ZM5 13h3a15 15 0 0 0 1.1 5.2A8 8 0 0 1 5 13Zm7 7c-.9-1.3-1.7-3.6-1.9-7h3.8c-.2 3.4-1 5.7-1.9 7Zm2.9-1.8A15 15 0 0 0 16 13h3a8 8 0 0 1-4.1 5.2Z" />
              </svg>
            </div>
          </div>
        </div>

        {/* Post body — editable while the copy is still up for approval. */}
        <div className="px-4 pt-3">
          {message.needsHumanIntervention && approval === "pending" && (
            <div className="mb-3 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-700">
              The AI reviewer flagged this draft after multiple attempts — your direct input is needed.
            </div>
          )}

          {bodyEditable ? (
            <textarea
              // Callback ref so the box is already sized to the draft on mount — `rows` alone
              // would scroll a long post until the first keystroke grew it.
              ref={(el) => {
                textRef.current = el;
                if (el) autoGrow(el);
              }}
              key={draftText}
              defaultValue={draftText}
              onInput={(e) => autoGrow(e.currentTarget)}
              rows={3}
              aria-label="Post copy"
              placeholder={captionEntry ? "Write the caption for this post…" : undefined}
              className={`w-full bg-transparent text-sm text-[#1B1A17] leading-relaxed resize-none rounded-lg px-2 py-1 -mx-2 border border-transparent placeholder:text-[#9E9893] hover:border-[#E8E3DA] focus:bg-[#F8F5EE] ${ui.focusClass} focus:outline-none transition-colors`}
            />
          ) : (
            (draftText || postedText) && (
              <p className="text-sm text-[#1B1A17] whitespace-pre-wrap leading-relaxed">
                {draftText || postedText}
              </p>
            )
          )}

          {hashtags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {hashtags.map((tag) => (
                <span key={tag} className={`text-xs ${ui.accentTextClass} font-medium`}>
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Media well — video once rendered, else the storyboard standing in for it, else the
            attached photo. */}
        {(storyboard || image || renderState !== "idle") && (
          <div className="mt-3 bg-[#F8F5EE] border-y border-[#E8E3DA] p-3">
            {renderState === "done" && downloadUrl ? (
              <video src={downloadUrl} controls className="w-full rounded-lg bg-black" />
            ) : storyboard ? (
              <StoryboardPreview storyboard={storyboard} />
            ) : image ? (
              <div className="relative">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={image.url} alt="Attached photo" className="w-full rounded-lg" />
                <button
                  onClick={() => pickImage(null)}
                  aria-label="Remove photo"
                  disabled={postStatus === "posting"}
                  className="absolute top-2 right-2 w-6 h-6 rounded-full bg-[#1B1A17]/80 text-white text-xs flex items-center justify-center hover:bg-[#FF4800] disabled:opacity-50 transition-colors"
                >
                  ×
                </button>
              </div>
            ) : null}

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
              <p className="text-xs text-red-600 text-center mt-3">{renderError}</p>
            )}
          </div>
        )}

        {/* Engagement bar — deliberately count-free: this post doesn't exist yet, and inventing
            reactions for it would be inventing data. */}
        <div className="flex items-center justify-around px-2 py-1.5 mt-1 border-t border-[#E8E3DA] text-[#9E9893]">
          {ui.actions.map((action) => (
            <span key={action} className="flex-1 text-center text-xs font-medium py-1.5 select-none">
              {action}
            </span>
          ))}
        </div>

        {/* ── Review controls ─────────────────────────────────────────────────── */}
        <div className="bg-[#F8F5EE] border-t border-[#E8E3DA] px-4 py-3 space-y-2">
          {/* Stage A — the copy */}
          {approval === "pending" && (
            <>
              <p className="text-[11px] text-[#9E9893]">
                Edit the copy above if you want — your changes go through with the approval.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => onApprove(textRef.current?.value ?? draftText)}
                  className="flex-1 bg-green-600 hover:bg-green-500 text-white text-sm font-medium py-2 rounded-lg transition-colors"
                >
                  Approve copy
                </button>
                <button
                  onClick={() => setRejectOpen((open) => !open)}
                  className="flex-1 bg-white hover:bg-[#E8E3DA] text-[#1B1A17] text-sm font-medium py-2 rounded-lg transition-colors border border-[#E8E3DA]"
                >
                  Request changes
                </button>
              </div>
              {rejectOpen && (
                <div className="space-y-2 pt-1">
                  <textarea
                    value={rejectText}
                    onChange={(e) => setRejectText(e.target.value)}
                    placeholder="What should change? (optional)"
                    rows={2}
                    className={`w-full bg-white border border-[#E8E3DA] rounded-lg px-3 py-2 text-xs text-[#1B1A17] placeholder:text-[#9E9893] resize-none focus:outline-none ${ui.focusClass}`}
                  />
                  <button
                    onClick={() => onReject(rejectText)}
                    className="w-full bg-[#1B1A17] hover:bg-black text-white text-sm font-medium py-2 rounded-lg transition-colors"
                  >
                    Send back for a rewrite
                  </button>
                </div>
              )}
            </>
          )}

          {approval === "rejected" && (
            <p className="text-xs text-[#6B6561]">
              Sent back — the new draft will land in this same post.
            </p>
          )}

          {/* Between approving the copy and the storyboard arriving. */}
          {approval === "approved" && hasVideo && !storyboard && (
            <p className="text-xs text-[#6B6561]">
              Copy approved. Building the video storyboard from it…
            </p>
          )}

          {/* Stage B — the storyboard */}
          {storyboard && storyboardApproval === "pending" && (
            <>
              <div className="flex gap-2">
                <button
                  onClick={onStoryboardApprove}
                  disabled={sbStatus === "revising"}
                  className="flex-1 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white text-sm font-medium py-2 rounded-lg transition-colors"
                >
                  Approve storyboard
                </button>
                <button
                  onClick={() => setSbFeedbackOpen((open) => !open)}
                  disabled={sbStatus === "revising"}
                  className="flex-1 bg-white hover:bg-[#E8E3DA] disabled:opacity-50 text-[#1B1A17] text-sm font-medium py-2 rounded-lg transition-colors border border-[#E8E3DA]"
                >
                  Request changes
                </button>
              </div>
              {sbFeedbackOpen && (
                <div className="space-y-2 pt-1">
                  <textarea
                    value={sbFeedback}
                    onChange={(e) => setSbFeedback(e.target.value)}
                    placeholder="What should change? e.g. 'open on the stat, drop the pie chart'"
                    rows={2}
                    disabled={sbStatus === "revising"}
                    className={`w-full bg-white border border-[#E8E3DA] rounded-lg px-3 py-2 text-xs text-[#1B1A17] placeholder:text-[#9E9893] resize-none focus:outline-none ${ui.focusClass} disabled:opacity-60`}
                  />
                  <button
                    onClick={reviseStoryboard}
                    disabled={sbStatus === "revising" || !sbFeedback.trim()}
                    className="w-full bg-[#FF4800] hover:bg-[#E03E00] disabled:opacity-50 text-white text-sm font-medium py-2 rounded-lg transition-colors"
                  >
                    {sbStatus === "revising" ? "Reworking the storyboard…" : "Rework storyboard"}
                  </button>
                  <p className="text-[11px] text-[#9E9893]">
                    Only the storyboard changes — your approved copy stays as it is.
                  </p>
                </div>
              )}
              {sbStatus === "error" && sbError && <p className="text-xs text-red-600">{sbError}</p>}
            </>
          )}

          {/* Stage C — render */}
          {storyboard &&
            storyboardApproval === "approved" &&
            (renderState === "idle" || renderState === "error") && (
              <>
                {refs.length > 0 && (
                  <div className="mb-1">
                    <p className="text-[10px] text-[#9E9893] mb-1.5">
                      Reference image{refs.length !== 1 ? "s" : ""} — the video is generated from these:
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {refs.map((src, i) => (
                        <div key={i} className="relative">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={src}
                            alt={`reference ${i + 1}`}
                            className="w-12 h-12 object-cover rounded-md border border-[#E8E3DA]"
                          />
                          <button
                            onClick={() => setDroppedRefs((prev) => [...prev, src])}
                            aria-label={`Remove reference ${i + 1}`}
                            className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-[#1B1A17] text-white text-[10px] flex items-center justify-center shadow hover:bg-[#FF4800] transition-colors"
                          >
                            ×
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <button
                  onClick={startRender}
                  className="w-full bg-[#FF4800] hover:bg-[#E03E00] text-white text-sm font-medium py-2 rounded-lg transition-colors"
                >
                  {renderState === "error" ? "Retry render" : "Render video"}
                </button>
              </>
            )}

          {/* Stage D — publish */}
          {postStatus === "posted" ? (
            <div className="text-center py-2 rounded-xl text-sm font-medium bg-green-50 text-green-700 border border-green-200">
              ✓ Posted to {ui.label}
            </div>
          ) : scheduleStatus === "scheduled" ? (
            <div className="text-center py-2 rounded-xl text-sm font-medium bg-green-50 text-green-700 border border-green-200">
              ✓ Scheduled for {scheduleDate} at {scheduleTime}
            </div>
          ) : (
            <>
              {/* Video: one publish, now. The scheduler is text-only, so there is nothing
                  honest to offer here beyond posting it. */}
              {hasVideo && renderState === "done" && (
                <>
                  {ui.videoTitle && (
                    <input
                      type="text"
                      value={videoTitle}
                      onChange={(e) => setVideoTitle(e.target.value)}
                      placeholder="Video title (optional)"
                      disabled={postStatus === "posting"}
                      className={`w-full bg-white border border-[#E8E3DA] rounded-lg px-3 py-2 text-xs text-[#1B1A17] placeholder:text-[#9E9893] focus:outline-none ${ui.focusClass} disabled:opacity-60`}
                    />
                  )}
                  <button
                    onClick={handlePost}
                    disabled={postStatus === "posting"}
                    className={`w-full ${ui.buttonClass} disabled:opacity-50 text-white text-sm font-medium py-2 rounded-lg transition-colors`}
                  >
                    {postStatus === "posting" ? "Uploading & posting…" : `Post to ${ui.label}`}
                  </button>
                </>
              )}

              {/* Text post: optionally with a photo, published now or queued for a future date. */}
              {!hasVideo && approval === "approved" && (
                <>
                  {!mediaAttached && (
                    <div className="flex gap-1 p-1 bg-white border border-[#E8E3DA] rounded-lg">
                      {(["now", "schedule"] as const).map((mode) => (
                        <button
                          key={mode}
                          onClick={() => setPostMode(mode)}
                          className={`flex-1 text-xs font-medium py-1.5 rounded-md transition-colors ${
                            postMode === mode
                              ? ui.toggleActiveClass
                              : "text-[#6B6561] hover:bg-[#F8F5EE]"
                          }`}
                        >
                          {mode === "now" ? "Post now" : "Schedule"}
                        </button>
                      ))}
                    </div>
                  )}

                  {postMode === "now" || mediaAttached ? (
                    <>
                      <label className="block">
                        <span className="sr-only">Attach a photo</span>
                        <input
                          type="file"
                          accept="image/*"
                          onChange={(e) => pickImage(e.target.files?.[0] ?? null)}
                          disabled={postStatus === "posting"}
                          className="w-full text-xs text-[#6B6561] file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border file:border-[#E8E3DA] file:bg-white file:text-xs file:font-medium file:text-[#1B1A17] hover:file:bg-[#E8E3DA] disabled:opacity-60"
                        />
                      </label>
                      {image && (
                        <p className="text-[11px] text-[#9E9893]">
                          Photo posts publish immediately — scheduling carries text only.
                        </p>
                      )}
                      <button
                        onClick={handlePost}
                        disabled={postStatus === "posting"}
                        className={`w-full ${ui.buttonClass} disabled:opacity-50 text-white text-sm font-medium py-2 rounded-lg transition-colors`}
                      >
                        {postStatus === "posting"
                          ? image
                            ? "Uploading & posting…"
                            : "Posting…"
                          : `Post to ${ui.label}`}
                      </button>
                    </>
                  ) : (
                    <>
                      {agentDate && (
                        <p className="text-[11px] text-[#9E9893]">
                          Timed from your request — adjust it here if that&apos;s not what you meant.
                        </p>
                      )}
                      <div className="flex gap-2">
                        <input
                          type="date"
                          value={scheduleDate}
                          onChange={(e) => setScheduleDate(e.target.value)}
                          aria-label="Publish date"
                          className={`flex-1 bg-white border border-[#E8E3DA] rounded-lg px-2 py-1.5 text-xs text-[#1B1A17] focus:outline-none ${ui.focusClass}`}
                        />
                        <input
                          type="time"
                          value={scheduleTime}
                          onChange={(e) => setScheduleTime(e.target.value)}
                          aria-label="Publish time"
                          className={`flex-1 bg-white border border-[#E8E3DA] rounded-lg px-2 py-1.5 text-xs text-[#1B1A17] focus:outline-none ${ui.focusClass}`}
                        />
                      </div>
                      <button
                        onClick={handleSchedule}
                        disabled={scheduleStatus === "scheduling"}
                        className={`w-full ${ui.buttonClass} disabled:opacity-50 text-white text-sm font-medium py-2 rounded-lg transition-colors`}
                      >
                        {scheduleStatus === "scheduling" ? "Scheduling…" : "Schedule post"}
                      </button>
                    </>
                  )}
                </>
              )}

              {postStatus === "error" && postError && (
                <p className="text-xs text-red-600 text-center">{postError}</p>
              )}
              {scheduleStatus === "error" && scheduleError && (
                <p className="text-xs text-red-600 text-center">{scheduleError}</p>
              )}
            </>
          )}
        </div>

        <p className="text-xs text-[#9E9893] px-4 pb-3 pt-2">{formatTime(message.timestamp)}</p>
      </div>
    </div>
  );
}
