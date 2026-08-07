"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import DashboardSidebar from "../components/DashboardSidebar";
import { useTaskEvents, type TaskEvent } from "../_lib/useTaskEvents";

type Platform = "x" | "facebook" | "tiktok" | "linkedin";
type ContentType = "text" | "video" | "brand";

/** How much deliberation each slot's copy gets. Chosen when the campaign is commissioned;
 * see LLM_service/core/plan_schema.py. */
type DraftMode = "roundtable" | "fast";

interface PlanItem {
  item_id: string;
  planned_date: string;
  time_of_day?: string | null;
  platforms: string[];
  topic: string;
  angle?: string | null;
  rationale?: string | null;
  status: string;
  content_types: string[];
  task_id: string | null;
}

interface Plan {
  plan_id: string;
  goal: string;
  target_platforms: string[];
  start_date: string;
  end_date: string;
  status: "draft" | "active" | string;
  draft_mode?: DraftMode;
  strategy_summary?: string;
  items: PlanItem[];
  created_at: string;
  updated_at: string;
}

const PLATFORMS: { id: Platform; label: string; abbr: string; badgeClass: string }[] = [
  { id: "x", label: "X (Twitter)", abbr: "X", badgeClass: "bg-[#1B1A17] text-white" },
  { id: "facebook", label: "Facebook", abbr: "f", badgeClass: "bg-[#1877F2] text-white" },
  { id: "tiktok", label: "TikTok", abbr: "TK", badgeClass: "bg-[#1B1A17] text-white" },
  { id: "linkedin", label: "LinkedIn", abbr: "in", badgeClass: "bg-blue-600 text-white" },
];
const platformMap = Object.fromEntries(PLATFORMS.map((p) => [p.id, p]));

const CONTENT_TYPES: { id: ContentType; label: string }[] = [
  { id: "text", label: "Text" },
  { id: "video", label: "Video" },
  { id: "brand", label: "Brand Animation" },
];

/** One post a plan slot put on the content calendar. The slice of the calendar's own record
 * that the plan view needs: which platform, when it publishes, and where it got to. */
interface ScheduledSlotPost {
  id: string;
  platform: string;
  scheduled_at: string;
  status: string;
}

/** How each calendar status reads on a plan slot. The plan view's question is "is this post
 * going to go out?", so the wording is about the post's future, not its database row. */
const DELIVERY_STATE: Record<string, { verb: string; className: string; icon: string }> = {
  scheduled: { verb: "publishes", className: "text-green-700", icon: "✓" },
  publishing: { verb: "publishing now", className: "text-green-700", icon: "↗" },
  published: { verb: "published", className: "text-green-700", icon: "✓" },
  failed: { verb: "failed to publish", className: "text-red-600", icon: "✕" },
  cancelled: { verb: "cancelled", className: "text-[#9E9893] line-through", icon: "–" },
};

/** How often to re-read a plan while its campaign is being written. */
const POLL_INTERVAL_MS = 5000;

/** Consecutive polls that may return an unchanged plan before we stop asking.
 *
 * Slots are drafted one at a time, so a campaign is legitimately "in progress" while several
 * of its slots are still `planned` and nothing at all is happening on screen. Polling on that
 * alone would never stop for a campaign whose chain died (a backend restart mid-run leaves the
 * rest `planned` until the next daily sweep). Any status change resets the count, so a live
 * campaign polls indefinitely and a stalled one gives up after a couple of quiet minutes. */
const IDLE_POLL_LIMIT = 24;

const STATUS_BADGE: Record<string, string> = {
  planned: "bg-[#F2EDE4] text-[#6B6561]",
  generating: "bg-amber-100 text-amber-700",
  awaiting_review: "bg-blue-100 text-blue-700",
  done: "bg-green-100 text-green-700",
  skipped: "bg-[#F2EDE4] text-[#9E9893] line-through",
  error: "bg-red-100 text-red-700",
};

/** The stages a slot passes through while its copy is written, in order.
 *
 * Writing one post is minutes of work behind a single "generating" status, and a spinner
 * held for that long reads as a hang. These are the stages the task stream already reports
 * — the agents discussing, the copy being written, the reviewer checking it — named so the
 * wait says what is being waited for. */
const DRAFT_PHASES = ["discussing", "writing", "reviewing", "ready"] as const;
type DraftPhase = (typeof DRAFT_PHASES)[number];

const PHASE_LABEL: Record<DraftPhase, string> = {
  discussing: "Agents discussing",
  writing: "Writing the post",
  reviewing: "Checking it over",
  ready: "Ready for you",
};

/** The fast path skips the discussion, so its stepper must not show a stage that will never
 * happen — an step that stays grey forever looks like something went wrong. */
function phasesFor(mode: DraftMode): readonly DraftPhase[] {
  return mode === "fast" ? DRAFT_PHASES.filter((p) => p !== "discussing") : DRAFT_PHASES;
}

/** Seconds elapsed since `since`, ticking once a second while `running`.
 *
 * Every wait in this view is long enough that a user starts wondering whether it is stuck.
 * A number that visibly moves is the cheapest possible answer to that. */
function useElapsedSeconds(since: number | null, running: boolean): number {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    if (since === null || !running) return;
    const tick = () => setSeconds(Math.floor((Date.now() - since) / 1000));
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [since, running]);

  return seconds;
}

/** `useSearchParams` opts the tree into client-side rendering, which Next requires a Suspense
 * boundary around. The fallback matches the loading state the page shows anyway. */
export default function PlansPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen bg-[#F8F5EE] text-[#1B1A17] overflow-hidden">
          <DashboardSidebar active="plans" />
          <p className="p-8 text-sm text-[#9E9893] italic">Loading plans…</p>
        </div>
      }
    >
      <PlansView />
    </Suspense>
  );
}

function PlansView() {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loadingPlans, setLoadingPlans] = useState(true);
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null);
  const [loadingPlan, setLoadingPlan] = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Stable across renders so children can safely depend on it. Without useCallback this is a
  // new function every render, and any child effect listing it as a dependency re-runs every
  // render — for a child that fetches, that is a request loop. It reads the token when called,
  // so there is nothing for the empty dependency list to make stale.
  const authHeaders = useCallback((): Record<string, string> => {
    const token = localStorage.getItem("starlight_token");
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  async function loadPlans() {
    setLoadingPlans(true);
    setError(null);
    try {
      const res = await fetch("/api/plans", { headers: authHeaders() });
      const data = await res.json();
      if (!res.ok || data.error) {
        setError(data.error ?? "Failed to load plans.");
        setPlans([]);
        return;
      }
      setPlans(Array.isArray(data.plans) ? data.plans : []);
    } catch {
      setError("Could not reach the backend.");
    } finally {
      setLoadingPlans(false);
    }
  }

  const loadPlan = useCallback(
    async (planId: string) => {
      setLoadingPlan(true);
      setSelectedPlanId(planId);
      setError(null);
      try {
        const res = await fetch(`/api/plans/${planId}`, { headers: authHeaders() });
        const data = await res.json();
        if (!res.ok || data.error) {
          setError(data.error ?? "Failed to load plan.");
          setSelectedPlan(null);
          return;
        }
        setSelectedPlan(data as Plan);
      } catch {
        setError("Could not reach the backend.");
      } finally {
        setLoadingPlan(false);
      }
    },
    [authHeaders]
  );

  useEffect(() => {
    loadPlans();
  }, []);

  // Arriving from the chat's "Track them in Posting Plans" link, which names the campaign the
  // user just confirmed. Without this they land on "No plan selected" and have to find, in a
  // list of every campaign they have ever made, the one they were looking at a second ago.
  const requestedPlanId = useSearchParams().get("plan");
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetches first; the plan lands in the promise callback, not synchronously
    if (requestedPlanId) loadPlan(requestedPlanId);
  }, [requestedPlanId, loadPlan]);

  function handlePlanCreated(plan: Plan) {
    setPlans((prev) => [plan, ...prev]);
    setShowCreateForm(false);
    setSelectedPlanId(plan.plan_id);
    setSelectedPlan(plan);
  }

  // Stable for the same reason as authHeaders above: PlanDetail polls through this while a
  // campaign drafts, and a new identity each render would reset its timer before it ever fired.
  const handlePlanUpdated = useCallback((plan: Plan) => {
    setSelectedPlan(plan);
    setPlans((prev) => prev.map((p) => (p.plan_id === plan.plan_id ? plan : p)));
  }, []);

  return (
    <div className="flex h-screen bg-[#F8F5EE] text-[#1B1A17] overflow-hidden">
      {/* The dashboard rail, so reaching plans from the profile doesn't strand the user on a
          page with no way back to the calendar or the brand profile. */}
      <DashboardSidebar active="plans" />

      {/* Plan list. Slightly narrower than it was, to pay for the rail beside it — and it no
          longer repeats the Starlight header, which the rail now carries. */}
      <aside className="w-72 flex-shrink-0 border-r border-[#E8E3DA] flex flex-col bg-white">
        <div className="p-5 border-b border-[#E8E3DA] flex-shrink-0">
          <h1 className="font-semibold text-[#1B1A17]">Posting Plans</h1>
          <p className="text-xs text-[#9E9893] mt-0.5">Campaign schedules</p>
        </div>

        <div className="p-4">
          <button
            onClick={() => {
              setShowCreateForm(true);
              setSelectedPlanId(null);
              setSelectedPlan(null);
            }}
            className="w-full bg-[#FF4800] hover:bg-[#E03E00] text-white text-sm font-medium py-2.5 rounded-xl transition-colors"
          >
            + New Plan
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 pb-4 space-y-1.5">
          {loadingPlans ? (
            <p className="text-xs text-[#9E9893] italic px-1">Loading plans…</p>
          ) : plans.length === 0 ? (
            <p className="text-xs text-[#9E9893] italic px-1">No plans yet — create one to get started.</p>
          ) : (
            plans.map((p) => {
              const active = p.plan_id === selectedPlanId;
              return (
                <button
                  key={p.plan_id}
                  onClick={() => {
                    setShowCreateForm(false);
                    loadPlan(p.plan_id);
                  }}
                  className={`w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors ${
                    active
                      ? "bg-[#FFF0EB] border border-[#FFCBB8] text-[#FF4800]"
                      : "text-[#6B6561] hover:text-[#1B1A17] hover:bg-[#F2EDE4]"
                  }`}
                >
                  <p className="font-medium text-xs truncate">{p.goal}</p>
                  <div className="flex items-center gap-1.5 mt-1">
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                        p.status === "active" ? "bg-green-100 text-green-700" : "bg-[#F2EDE4] text-[#6B6561]"
                      }`}
                    >
                      {p.status}
                    </span>
                    <span className="text-[10px] text-[#9E9893]">
                      {p.start_date} → {p.end_date}
                    </span>
                  </div>
                </button>
              );
            })
          )}
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 overflow-y-auto p-8">
        {error && (
          <div className="mb-4 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-2.5 rounded-lg">
            {error}
          </div>
        )}

        {showCreateForm ? (
          <CreatePlanForm authHeaders={authHeaders} onCreated={handlePlanCreated} onError={setError} />
        ) : loadingPlan ? (
          <p className="text-sm text-[#9E9893] italic">Loading plan…</p>
        ) : selectedPlan ? (
          <PlanDetail
            plan={selectedPlan}
            authHeaders={authHeaders}
            onUpdated={handlePlanUpdated}
            onError={setError}
          />
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-center text-[#9E9893]">
            <p className="text-lg font-medium mb-1">No plan selected</p>
            <p className="text-sm">Pick a plan from the left, or create a new one.</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Create Plan Form ─────────────────────────────────────────────────────────

interface CreatePlanFormProps {
  authHeaders: () => Record<string, string>;
  onCreated: (plan: Plan) => void;
  onError: (msg: string | null) => void;
}

function CreatePlanForm({ authHeaders, onCreated, onError }: CreatePlanFormProps) {
  const [goal, setGoal] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [platforms, setPlatforms] = useState<Platform[]>(["linkedin"]);
  const [cadenceHint, setCadenceHint] = useState("");
  const [toneHint, setToneHint] = useState("");
  const [contentTypes, setContentTypes] = useState<ContentType[]>(["text"]);
  const [submitting, setSubmitting] = useState(false);

  function togglePlatform(p: Platform) {
    setPlatforms((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]));
  }
  function toggleContentType(c: ContentType) {
    setContentTypes((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));
  }

  async function handleSubmit() {
    onError(null);
    if (!goal.trim()) {
      onError("A goal is required.");
      return;
    }
    if (!startDate || !endDate) {
      onError("Pick a start and end date.");
      return;
    }
    if (platforms.length === 0) {
      onError("Pick at least one platform.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch("/api/plans", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({
          goal: goal.trim(),
          target_platforms: platforms,
          start_date: startDate,
          end_date: endDate,
          ...(cadenceHint.trim() ? { cadence_hint: cadenceHint.trim() } : {}),
          ...(toneHint.trim() ? { tone_hint: toneHint.trim() } : {}),
          content_types: contentTypes,
        }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        onError(data.error ?? "Failed to create plan.");
        return;
      }
      onCreated(data as Plan);
    } catch {
      onError("Could not reach the backend.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-xl">
      <h1 className="text-lg font-semibold mb-1">Create a Posting Plan</h1>
      <p className="text-sm text-[#9E9893] mb-6">
        Describe a campaign goal and a date range — Starlight will lay out which topics to post,
        on which days and platforms, and why. You&apos;ll review and confirm before anything drafts.
      </p>

      <div className="space-y-4 bg-white border border-[#E8E3DA] rounded-2xl p-5">
        <div>
          <label className="text-xs font-semibold text-[#6B6561] mb-1 block">Goal</label>
          <textarea
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="e.g. Launch our new coffee subscription"
            rows={2}
            className="w-full bg-[#F8F5EE] border border-[#E8E3DA] rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:border-[#FF4800]"
          />
        </div>

        <div className="flex gap-3">
          <div className="flex-1">
            <label className="text-xs font-semibold text-[#6B6561] mb-1 block">Start Date</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full bg-[#F8F5EE] border border-[#E8E3DA] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-[#FF4800]"
            />
          </div>
          <div className="flex-1">
            <label className="text-xs font-semibold text-[#6B6561] mb-1 block">End Date</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full bg-[#F8F5EE] border border-[#E8E3DA] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-[#FF4800]"
            />
          </div>
        </div>

        <div>
          <label className="text-xs font-semibold text-[#6B6561] mb-1.5 block">Platforms</label>
          <div className="flex flex-wrap gap-2">
            {PLATFORMS.map((p) => {
              const active = platforms.includes(p.id);
              return (
                <button
                  key={p.id}
                  onClick={() => togglePlatform(p.id)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
                    active
                      ? "bg-[#FFF0EB] border-[#FFCBB8] text-[#FF4800]"
                      : "bg-[#F8F5EE] border-[#E8E3DA] text-[#6B6561]"
                  }`}
                >
                  <span
                    className={`w-4 h-4 rounded flex items-center justify-center text-[9px] font-bold ${p.badgeClass}`}
                  >
                    {p.abbr}
                  </span>
                  {p.label}
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <label className="text-xs font-semibold text-[#6B6561] mb-1.5 block">Content Type</label>
          <div className="flex flex-wrap gap-2">
            {CONTENT_TYPES.map((c) => {
              const active = contentTypes.includes(c.id);
              return (
                <button
                  key={c.id}
                  onClick={() => toggleContentType(c.id)}
                  className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                    active ? "bg-[#FF4800] text-white" : "bg-[#F8F5EE] text-[#6B6561] border border-[#E8E3DA]"
                  }`}
                >
                  {c.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex gap-3">
          <div className="flex-1">
            <label className="text-xs font-semibold text-[#6B6561] mb-1 block">Cadence (optional)</label>
            <input
              value={cadenceHint}
              onChange={(e) => setCadenceHint(e.target.value)}
              placeholder="about 2 posts a week"
              className="w-full bg-[#F8F5EE] border border-[#E8E3DA] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-[#FF4800]"
            />
          </div>
          <div className="flex-1">
            <label className="text-xs font-semibold text-[#6B6561] mb-1 block">Tone (optional)</label>
            <input
              value={toneHint}
              onChange={(e) => setToneHint(e.target.value)}
              placeholder="warm, confident"
              className="w-full bg-[#F8F5EE] border border-[#E8E3DA] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-[#FF4800]"
            />
          </div>
        </div>

        <button
          onClick={handleSubmit}
          disabled={submitting}
          className="w-full bg-[#FF4800] hover:bg-[#E03E00] disabled:opacity-50 text-white text-sm font-medium py-2.5 rounded-lg transition-colors"
        >
          {submitting ? "Generating plan…" : "Generate Plan"}
        </button>
      </div>
    </div>
  );
}

// ── Plan Detail ───────────────────────────────────────────────────────────────

interface PlanDetailProps {
  plan: Plan;
  authHeaders: () => Record<string, string>;
  onUpdated: (plan: Plan) => void;
  onError: (msg: string | null) => void;
}

function PlanDetail({ plan, authHeaders, onUpdated, onError }: PlanDetailProps) {
  const [confirming, setConfirming] = useState(false);
  // How the user wants this campaign written. Only settable while it is still a draft —
  // afterwards it is a fact about work already commissioned, and the header just reports it.
  const [draftMode, setDraftMode] = useState<DraftMode>(plan.draft_mode ?? "roundtable");
  // What each slot actually put on the content calendar. Kept here rather than per-card so it
  // costs one request per plan instead of one per slot, and so any card that schedules
  // something refreshes the whole plan's view of the truth.
  const [scheduledByItem, setScheduledByItem] = useState<Record<string, ScheduledSlotPost[]>>({});

  const planId = plan.plan_id;
  const planActive = plan.status === "active";

  const loadScheduled = useCallback(async () => {
    if (!planActive) return;
    try {
      const res = await fetch(`/api/plans/${planId}/scheduled`, { headers: authHeaders() });
      const data = await res.json();
      if (!res.ok || data.error) return;  // a failed read must not blank out the plan itself
      setScheduledByItem(data.items ?? {});
    } catch {
      // Same: leave whatever we already know rather than claiming nothing is scheduled.
    }
  }, [planId, planActive, authHeaders]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetches first; the state lands in the promise callback, not synchronously
    loadScheduled();
  }, [loadScheduled]);

  const reloadPlan = useCallback(async () => {
    try {
      const res = await fetch(`/api/plans/${planId}`, { headers: authHeaders() });
      const data = await res.json();
      if (res.ok && !data.error) onUpdated(data as Plan);
    } catch {
      // A dropped poll is not worth reporting — the next one picks the change up.
    }
  }, [planId, authHeaders, onUpdated]);

  // Confirming commissions the whole campaign, and the slots are then written one at a time
  // in the background — so the statuses on screen go stale the moment it returns, and stay
  // that way for as long as there is a post still to write.
  //
  // The gate is deliberately "anything left to write", not "something is writing right now".
  // Between one slot finishing and the next starting there is a real gap with nothing
  // `generating`; a poll that stopped there would freeze the page mid-campaign and only
  // recover if the user reloaded it.
  const queue = plan.items.filter((i) => i.status !== "skipped");
  const writingIndex = queue.findIndex((i) => i.status === "generating");
  const unwritten = queue.filter((i) => i.status === "planned" || i.status === "generating");
  const campaignRunning = planActive && unwritten.length > 0;
  // "Ready" means the copy exists and is yours to look at — drafted, reviewed, or already
  // scheduled. Skipped slots aren't in the queue at all: they were never going to be written.
  const writtenCount = queue.length - unwritten.length;

  const pollSignature = plan.items.map((i) => i.status).join(",");
  const [poll, setPoll] = useState({ signature: pollSignature, idle: 0 });
  if (poll.signature !== pollSignature) {
    // Adjusting state during render, rather than in an effect: the campaign moved, so it has
    // earned a fresh budget of polls, and waiting a render to say so would spend one of them.
    setPoll({ signature: pollSignature, idle: 0 });
  }

  useEffect(() => {
    if (!campaignRunning || poll.idle >= IDLE_POLL_LIMIT) return;

    const timer = setTimeout(() => {
      // A new object each tick, so this effect re-runs and schedules the following poll —
      // the tick count is what keeps the chain going as well as what bounds it.
      setPoll((prev) => ({ ...prev, idle: prev.idle + 1 }));
      reloadPlan();
    }, POLL_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [campaignRunning, poll, reloadPlan]);

  async function handleConfirm() {
    onError(null);
    setConfirming(true);
    try {
      const res = await fetch(`/api/plans/${plan.plan_id}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ draft_mode: draftMode }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        onError(data.error ?? "Failed to confirm plan.");
        return;
      }
      // The response still shows every slot as `planned` — the first one starts writing a
      // beat later. The poll above is what turns that into a live view.
      onUpdated(data as Plan);
    } catch {
      onError("Could not reach the backend.");
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="max-w-2xl">
      <div className="flex items-start justify-between mb-1">
        <h1 className="text-lg font-semibold">{plan.goal}</h1>
        <span
          className={`text-xs px-2.5 py-1 rounded-full font-medium ${
            plan.status === "active" ? "bg-green-100 text-green-700" : "bg-[#F2EDE4] text-[#6B6561]"
          }`}
        >
          {plan.status}
        </span>
      </div>
      <p className="text-xs text-[#9E9893] mb-4">
        {plan.start_date} → {plan.end_date}
        {plan.status === "active" && (
          <> · written {plan.draft_mode === "fast" ? "in fast mode" : "by the roundtable"}</>
        )}
      </p>

      {plan.strategy_summary && (
        <div className="bg-[#FFF0EB] border border-[#FFCBB8] rounded-xl px-4 py-3 mb-5 text-sm text-[#1B1A17]">
          {plan.strategy_summary}
        </div>
      )}

      {plan.status === "draft" && (
        <>
          <DraftModePicker value={draftMode} onChange={setDraftMode} postCount={plan.items.length} />
          <button
            onClick={handleConfirm}
            disabled={confirming}
            className="mb-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            {confirming ? "Confirming…" : `Confirm Plan — write all ${plan.items.length} posts`}
          </button>
          <p className="mb-5 text-xs text-[#9E9893] leading-relaxed">
            The posts are written one at a time, in order, so you can watch each one take shape.
            Nothing publishes until you approve it.
          </p>
        </>
      )}
      {plan.status === "active" && (
        <div className="mb-5">
          {campaignRunning ? (
            <CampaignProgress
              written={writtenCount}
              total={queue.length}
              // Between one post finishing and the next starting nothing is `generating`.
              // Naming the post that just finished is truer than naming none: the campaign
              // has reached that point, it just hasn't left it yet.
              current={writingIndex >= 0 ? writingIndex : writtenCount}
              live={writingIndex >= 0}
              topic={queue[writingIndex >= 0 ? writingIndex : Math.min(writtenCount, queue.length - 1)]?.topic}
            />
          ) : (
            <p className="text-xs text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2 inline-block">
              ✓ Active — approve a post to queue it for its planned date. Nothing publishes until
              you do.
            </p>
          )}
        </div>
      )}

      <h2 className="text-sm font-semibold text-[#6B6561] mb-3">Schedule</h2>
      <div className="space-y-3">
        {plan.items.map((item) => {
          // Where this slot sits in the writing queue, so a slot that has not started can say
          // how long it expects to wait rather than showing nothing at all.
          const position = queue.findIndex((i) => i.item_id === item.item_id);
          return (
            <PlanItemCard
              key={item.item_id}
              planId={plan.plan_id}
              item={item}
              editable={plan.status === "draft"}
              planActive={planActive}
              draftMode={plan.draft_mode ?? "roundtable"}
              queuePosition={position}
              queueLength={queue.length}
              campaignRunning={campaignRunning}
              scheduledPosts={scheduledByItem[item.item_id] ?? []}
              onScheduled={loadScheduled}
              authHeaders={authHeaders}
              onUpdated={onUpdated}
              onError={onError}
            />
          );
        })}
      </div>
    </div>
  );
}

// ── How the campaign gets written ─────────────────────────────────────────────

const DRAFT_MODE_OPTIONS: { id: DraftMode; label: string; blurb: string; perPost: string }[] = [
  {
    id: "roundtable",
    label: "Roundtable",
    blurb: "A table of agents argues each post out before it's written.",
    perPost: "~3 min a post",
  },
  {
    id: "fast",
    label: "Fast",
    blurb: "Straight to the writing. Same brand voice, no deliberation.",
    perPost: "~20 sec a post",
  },
];

/**
 * The one decision worth making before committing to a campaign.
 *
 * It is offered here, at the confirm, rather than back when the schedule was generated: the
 * schedule is cheap and endlessly editable, while this governs minutes of work per post and
 * only starts mattering the moment the user says go. Ten posts is the difference between half
 * a minute and half an hour, which is far too large to decide on the user's behalf.
 */
function DraftModePicker({
  value,
  onChange,
  postCount,
}: {
  value: DraftMode;
  onChange: (mode: DraftMode) => void;
  postCount: number;
}) {
  return (
    <div className="mb-4">
      <p className="text-xs font-semibold text-[#6B6561] mb-2">How should these be written?</p>
      <div className="grid sm:grid-cols-2 gap-2">
        {DRAFT_MODE_OPTIONS.map((option) => {
          const active = option.id === value;
          return (
            <button
              key={option.id}
              onClick={() => onChange(option.id)}
              aria-pressed={active}
              className={`text-left rounded-xl border px-3 py-2.5 transition-colors ${
                active
                  ? "border-[#FF4800] bg-[#FFF0EB]"
                  : "border-[#E8E3DA] bg-white hover:border-[#C8C2BA]"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-[#1B1A17]">{option.label}</span>
                <span className={`text-[10px] font-medium ${active ? "text-[#FF4800]" : "text-[#9E9893]"}`}>
                  {option.perPost}
                </span>
              </div>
              <p className="text-[11px] text-[#6B6561] mt-0.5 leading-relaxed">{option.blurb}</p>
            </button>
          );
        })}
      </div>
      <p className="text-[11px] text-[#9E9893] mt-1.5">
        {postCount} posts, written in turn — roughly{" "}
        {value === "fast" ? `${Math.ceil((postCount * 20) / 60)} min` : `${postCount * 3} min`} in all.
      </p>
    </div>
  );
}

/** Where the campaign has got to, as a position in a queue rather than a proportion.
 *
 * "3 of 8" is the honest shape of sequential drafting, and it is only honest because the
 * backend really does write one post at a time — there is always exactly one to point at. */
function CampaignProgress({
  written,
  total,
  current,
  live,
  topic,
}: {
  written: number;
  total: number;
  current: number;
  live: boolean;
  topic?: string;
}) {
  return (
    <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="w-1.5 h-1.5 rounded-full bg-[#FF4800] animate-pulse flex-shrink-0" />
        <p className="text-xs font-medium text-amber-900">
          {live ? `Writing post ${current + 1} of ${total}` : `Post ${current} of ${total} done — starting the next`}
        </p>
      </div>
      <div className="h-1.5 rounded-full bg-amber-200/70 overflow-hidden">
        <div
          className="h-full bg-[#FF4800] rounded-full transition-[width] duration-700 ease-out"
          style={{ width: `${total ? (written / total) * 100 : 0}%` }}
        />
      </div>
      <p className="text-[11px] text-amber-800 mt-1.5 leading-relaxed">
        {topic ? <span className="font-medium">{topic}</span> : "Getting started"} · they arrive in
        order, and you can review each one as it lands.
      </p>
    </div>
  );
}

// ── Plan Item Card ────────────────────────────────────────────────────────────

interface PlanItemCardProps {
  planId: string;
  item: PlanItem;
  editable: boolean;
  planActive: boolean;
  draftMode: DraftMode;
  /** This slot's place in the writing queue (skipped slots excluded), or -1 if it isn't in one. */
  queuePosition: number;
  queueLength: number;
  campaignRunning: boolean;
  scheduledPosts: ScheduledSlotPost[];
  onScheduled: () => void;
  authHeaders: () => Record<string, string>;
  onUpdated: (plan: Plan) => void;
  onError: (msg: string | null) => void;
}

function PlanItemCard({
  planId,
  item,
  editable,
  planActive,
  draftMode,
  queuePosition,
  queueLength,
  campaignRunning,
  scheduledPosts,
  onScheduled,
  authHeaders,
  onUpdated,
  onError,
}: PlanItemCardProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [plannedDate, setPlannedDate] = useState(item.planned_date);
  const [topic, setTopic] = useState(item.topic);
  const [angle, setAngle] = useState(item.angle ?? "");
  const [platforms, setPlatforms] = useState<Platform[]>(item.platforms as Platform[]);
  const [saving, setSaving] = useState(false);

  function togglePlatform(p: Platform) {
    setPlatforms((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]));
  }

  async function patchItem(body: Record<string, unknown>) {
    setSaving(true);
    onError(null);
    try {
      const res = await fetch(`/api/plans/${planId}/items/${item.item_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        onError(data.error ?? "Failed to update item.");
        return;
      }
      onUpdated(data as Plan);
      setIsEditing(false);
    } catch {
      onError("Could not reach the backend.");
    } finally {
      setSaving(false);
    }
  }

  function handleSave() {
    patchItem({
      planned_date: plannedDate,
      topic: topic.trim(),
      angle: angle.trim(),
      platforms,
    });
  }

  function handleSkip() {
    patchItem({ status: item.status === "skipped" ? "planned" : "skipped" });
  }

  const badgeClass = STATUS_BADGE[item.status] ?? "bg-[#F2EDE4] text-[#6B6561]";

  // Decide whether this item can show "Generate Draft Now" (untouched, still "planned"), or
  // should auto-load an already-existing draft (the cron already executed it, or you
  // generated it earlier and reloaded the page).
  const canGenerateNow = planActive && item.status === "planned";
  const canShowDraft = planActive && item.status !== "planned" && item.status !== "skipped";
  // A slot the campaign has not reached yet. It shows its place in the queue rather than the
  // "Generate Draft Now" button: offering that here invites the user to jump the queue and
  // start a second run alongside the one already going, which is the thing writing in turn
  // exists to avoid. The button is still there once the campaign has finished its pass.
  const isQueued = canGenerateNow && campaignRunning;

  return (
    <div className="bg-white border border-[#E8E3DA] rounded-xl px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          {isEditing ? (
            <div className="space-y-2">
              <input
                type="date"
                value={plannedDate}
                onChange={(e) => setPlannedDate(e.target.value)}
                className="bg-[#F8F5EE] border border-[#E8E3DA] rounded-lg px-2 py-1 text-xs"
              />
              <input
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="Topic"
                className="w-full bg-[#F8F5EE] border border-[#E8E3DA] rounded-lg px-2 py-1.5 text-sm"
              />
              <input
                value={angle}
                onChange={(e) => setAngle(e.target.value)}
                placeholder="Angle (e.g. educate, convert)"
                className="w-full bg-[#F8F5EE] border border-[#E8E3DA] rounded-lg px-2 py-1.5 text-xs"
              />
              <div className="flex flex-wrap gap-1.5">
                {PLATFORMS.map((p) => {
                  const active = platforms.includes(p.id);
                  return (
                    <button
                      key={p.id}
                      onClick={() => togglePlatform(p.id)}
                      className={`text-[10px] font-bold px-2 py-1 rounded-full ${
                        active ? p.badgeClass : "bg-[#F2EDE4] text-[#9E9893]"
                      }`}
                    >
                      {p.abbr}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <span className="text-xs font-semibold text-[#1B1A17]">{item.planned_date}</span>
                {item.time_of_day && <span className="text-[10px] text-[#9E9893]">{item.time_of_day}</span>}
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${badgeClass}`}>
                  {item.status}
                </span>
                {item.platforms.map((pid) => {
                  const p = platformMap[pid as Platform];
                  return p ? (
                    <span key={pid} className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${p.badgeClass}`}>
                      {p.abbr}
                    </span>
                  ) : null;
                })}
              </div>
              <p className="text-sm text-[#1B1A17] font-medium">{item.topic}</p>
              {item.rationale && <p className="text-xs text-[#9E9893] mt-1">{item.rationale}</p>}
            </>
          )}
        </div>

        {editable && (
          <div className="flex flex-col gap-1.5 flex-shrink-0">
            {isEditing ? (
              <>
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="text-xs font-medium text-white bg-[#FF4800] hover:bg-[#E03E00] px-2.5 py-1 rounded-lg disabled:opacity-50"
                >
                  {saving ? "Saving…" : "Save"}
                </button>
                <button
                  onClick={() => setIsEditing(false)}
                  className="text-xs font-medium text-[#6B6561] hover:text-[#1B1A17]"
                >
                  Cancel
                </button>
              </>
            ) : (
              <>
                <button onClick={() => setIsEditing(true)} className="text-xs font-medium text-[#FF4800] hover:underline">
                  Edit
                </button>
                <button
                  onClick={handleSkip}
                  disabled={saving}
                  className="text-xs font-medium text-[#9E9893] hover:text-[#1B1A17] disabled:opacity-50"
                >
                  {item.status === "skipped" ? "Un-skip" : "Skip"}
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Its place in the queue while the campaign works towards it, "Generate Draft Now" for
          an untouched slot once the campaign is done, or the live draft for a slot the
          campaign has reached (or that the cron / an earlier manual run already wrote). */}
      {isQueued ? (
        <p className="mt-3 pt-3 border-t border-[#E8E3DA] text-xs text-[#9E9893] flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-[#C8C2BA] flex-shrink-0" />
          Queued — post {queuePosition + 1} of {queueLength}
        </p>
      ) : (
        (canGenerateNow || canShowDraft) && (
          <ItemDraftPreview
            planId={planId}
            itemId={item.item_id}
            existingTaskId={item.task_id}
            itemStatus={item.status}
            draftMode={draftMode}
            scheduledPosts={scheduledPosts}
            onScheduled={onScheduled}
            authHeaders={authHeaders}
            onError={onError}
          />
        )
      )}
    </div>
  );
}

// ── Item Draft Preview — auto-connects to existing tasks, or manually triggers a new one ────

interface ItemDraftPreviewProps {
  planId: string;
  itemId: string;
  existingTaskId: string | null;
  itemStatus: string;
  draftMode: DraftMode;
  scheduledPosts: ScheduledSlotPost[];
  onScheduled: () => void;
  authHeaders: () => Record<string, string>;
  onError: (msg: string | null) => void;
}

/** One thing an agent said at the roundtable, kept to show the discussion happening. */
type Utterance = { key: string; speaker: string; text: string; platform: string };

/** How many turns of the discussion to keep on screen. Enough to read as a conversation
 * in progress; few enough that a twelve-round table doesn't push the plan off the page. */
const UTTERANCE_WINDOW = 5;

/** Tidy an agent id ("brand_voice") into something worth reading ("Brand voice"). */
function speakerName(raw: string): string {
  const words = raw.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The Facebook Page ids picked in the Brand Profile. Java falls back to every Page on the
 * connection when this is empty, so an unset selection still schedules. */
function getSelectedPageIds(): number[] {
  try {
    const ids = JSON.parse(localStorage.getItem("starlight_meta_page_ids") || "[]");
    return Array.isArray(ids) ? ids.map(Number).filter((n) => Number.isFinite(n)) : [];
  } catch {
    return [];
  }
}

/** Why the handoff passed over a platform — the part of its answer that isn't already visible
 * as a row on the calendar ("TikTok has no publishing integration yet").
 *
 * `reason_code` is what decides whether anything can be done about it. Only `time_passed` is
 * recoverable, and only it gets the reschedule controls; matching the English sentence instead
 * would break the first time someone improved the wording. */
type SkipReason = { platform: string; reason: string; reason_code?: string };

/** What the schedule call should do about a slot whose planned time has gone. */
type RescheduleChoice =
  | { auto_reschedule: true }              // let the planner pick the next slot in the window
  | { scheduled_at: string };              // the user named a moment

function ItemDraftPreview({
  planId,
  itemId,
  existingTaskId,
  itemStatus,
  draftMode,
  scheduledPosts,
  onScheduled,
  authHeaders,
  onError,
}: ItemDraftPreviewProps) {
  const [status, setStatus] = useState<"idle" | "starting" | "generating" | "ready" | "approved" | "rejected">("idle");
  // Keyed by platform: a slot can target several, and each gets its own draft and verdict.
  // While the copy is streaming these hold the text so far; `draft_ready` replaces them with
  // the finished version, which is what the review is actually against.
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [streaming, setStreaming] = useState(false);
  // The fast path never discusses anything, so it opens on the stage it really starts at —
  // a stepper whose first step can never light up reads as something having gone wrong.
  const [phase, setPhase] = useState<DraftPhase>(draftMode === "fast" ? "writing" : "discussing");
  const [utterances, setUtterances] = useState<Utterance[]>([]);
  const [speakerUp, setSpeakerUp] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<SkipReason[]>([]);
  const [isReviewing, setIsReviewing] = useState(false);
  const [isScheduling, setIsScheduling] = useState(false);

  const draftEntries = Object.entries(drafts);
  const settled = status === "ready" || status === "approved" || status === "rejected";
  const elapsed = useElapsedSeconds(startedAt, !settled);

  // Attach as soon as this item has a task — because the campaign reached it, the cron ran it,
  // or it was generated earlier and the page has been reloaded since. The stream replays its
  // whole history, so the copy written while nobody was watching still arrives: the deltas
  // first, retyping the post as it was written, then the `draft_ready` that supersedes them.
  //
  // Adjusted during render rather than in an effect, so the card never paints its idle state
  // for a slot that is visibly mid-flight before correcting itself a frame later.
  const watchable =
    itemStatus === "generating" || itemStatus === "awaiting_review" || itemStatus === "done";
  if (existingTaskId && watchable && existingTaskId !== taskId) {
    setTaskId(existingTaskId);
    setStartedAt(Date.now());
    if (status === "idle") setStatus(itemStatus === "done" ? "approved" : "generating");
  }

  useTaskEvents(taskId, (event: TaskEvent) => {
    switch (event.type) {
      case "speaker_scheduled":
        setPhase("discussing");
        setSpeakerUp(String(event.speaker ?? ""));
        break;

      case "agent_utterance":
        setPhase("discussing");
        setSpeakerUp(null);
        setUtterances((prev) =>
          [
            ...prev,
            {
              key: `${event.seq ?? prev.length}`,
              speaker: String(event.speaker ?? "agent"),
              text: String(event.text ?? ""),
              platform: event.platform ?? "",
            },
          ].slice(-UTTERANCE_WINDOW)
        );
        break;

      case "draft_delta": {
        // The copy, as it is written. Appended in `seq` order — the hook guarantees that, and
        // guarantees each event arrives once, which is what makes plain concatenation safe.
        setPhase("writing");
        setStreaming(true);
        const platform = String(event.platform ?? "linkedin");
        const text = String(event.text ?? "");
        setDrafts((prev) => ({ ...prev, [platform]: (prev[platform] ?? "") + text }));
        break;
      }

      case "progress":
        // The reviewer running is the only progress event worth a stage of its own; the rest
        // are already covered by what the discussion and the copy are visibly doing.
        if (event.node === "reviewer" && event.status === "running") {
          setStreaming(false);
          setPhase("reviewing");
        }
        break;

      case "result":
        if (event.status === "draft_ready") {
          // The authoritative copy. It REPLACES the streamed accumulation rather than adding
          // to it, so a delta lost to a dropped connection can't leave a mangled post on
          // screen — the worst case is the text settling into its final form on arrival.
          // Recording the platform also matters for the review: approving has to send a
          // verdict for every drafted platform, or the task stays half-reviewed and can
          // never be scheduled.
          const platform = String(event.platform ?? "linkedin");
          setDrafts((prev) => ({ ...prev, [platform]: String(event.draft ?? "") }));
          setStreaming(false);
          setPhase("ready");
          setStatus((prev) => (prev === "approved" ? "approved" : "ready"));
        }
        if (event.status === "final") {
          setStreaming(false);
          setStatus("approved");
        }
        break;
    }
  });

  async function handleGenerateNow() {
    setStatus("starting");
    setStartedAt(Date.now());
    onError(null);
    try {
      const res = await fetch(`/api/plans/${planId}/items/${itemId}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        onError(data.error ?? "Failed to start draft generation.");
        setStatus("idle");
        setStartedAt(null);
        return;
      }
      const newTaskId = data.task?.task_id as string | undefined;
      if (!newTaskId) {
        onError("No task returned from execute.");
        setStatus("idle");
        setStartedAt(null);
        return;
      }
      setTaskId(newTaskId);
      setStatus("generating");
    } catch {
      onError("Could not reach the backend.");
      setStatus("idle");
      setStartedAt(null);
    }
  }

  async function handleDecision(decision: "approve" | "reject") {
    if (!taskId || draftEntries.length === 0) return;

    // One verdict per drafted platform. Sending only one leaves the others pending, which keeps
    // the task in awaiting_review — the slot then looks approved here but can never be scheduled.
    const verdicts = Object.fromEntries(
      draftEntries.map(([platform]) => [platform, { decision }])
    );

    setIsReviewing(true);
    try {
      const res = await fetch(`/api/tasks/${taskId}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verdicts }),
      });
      if (!res.ok) {
        onError("Could not submit the review decision.");
        return;
      }
      setStatus(decision === "approve" ? "approved" : "rejected");
    } catch {
      onError("Could not submit the review decision.");
      return;
    } finally {
      setIsReviewing(false);
    }

    // Approving and scheduling are two steps and are reported as two steps — the button says
    // which one is in flight, so a slow handoff doesn't look like a stuck approval.
    if (decision === "approve") {
      await scheduleApprovedItem();
    }
  }

  /**
   * Queues the approved copy to publish at the slot's planned date and time.
   *
   * Fires straight after the approve so the user sees the outcome immediately, and can be run
   * again by hand from the panel below. It is no longer the only way a slot gets scheduled —
   * the backend sweeps for approved-but-unscheduled slots every couple of minutes — so a
   * failure here is a delay, not a loss, and says so.
   */
  async function scheduleApprovedItem(reschedule?: RescheduleChoice) {
    setIsScheduling(true);
    try {
      const res = await fetch(`/api/plans/${planId}/items/${itemId}/schedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ page_ids: getSelectedPageIds(), ...reschedule }),
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok || data.error) {
        onError(
          `${data.error ?? "The post could not be scheduled just now."} ` +
            "It will be picked up automatically within a few minutes."
        );
        return;
      }
      // A 200 can still mean nothing was queued (e.g. every platform unsupported). Rather than
      // trust the response as the record, keep only its skip reasons and re-read what actually
      // landed on the calendar — that way the panel shows the same thing on a fresh page load.
      setSkipped(data.skipped ?? []);
      onScheduled();
    } catch {
      onError(
        "The scheduling request could not be sent. It will be picked up automatically " +
          "within a few minutes."
      );
    } finally {
      setIsScheduling(false);
    }
  }

  if (status === "idle") {
    return (
      <button
        onClick={handleGenerateNow}
        className="mt-3 text-xs font-medium text-[#FF4800] hover:underline"
      >
        ✨ Generate Draft Now
      </button>
    );
  }

  return (
    <div className="mt-3 pt-3 border-t border-[#E8E3DA]">
      {!settled && (
        <PhaseStepper phase={phase} mode={draftMode} elapsed={elapsed} starting={status === "starting"} />
      )}

      {/* The discussion, while there is one to watch. It collapses the moment the copy starts
          arriving: by then the interesting thing on screen is the post, not how it was argued. */}
      {!settled && phase === "discussing" && (
        <RoundtableFeed utterances={utterances} speakerUp={speakerUp} />
      )}

      {draftEntries.length > 0 && (
        <div className="bg-[#F8F5EE] border border-[#E8E3DA] rounded-lg p-3">
          {draftEntries.map(([platform, text]) => (
            <div key={platform} className="mb-2 last:mb-2">
              {/* Only label the platform when there's more than one to tell apart. */}
              {draftEntries.length > 1 && (
                <p className="text-[10px] font-semibold uppercase tracking-wide text-[#9E9893] mb-1">
                  {platform}
                </p>
              )}
              <p className="text-sm text-[#1B1A17] whitespace-pre-wrap leading-relaxed">
                {text}
                {/* A caret while the words are still coming, so a pause between chunks reads
                    as the model thinking rather than the post being finished. */}
                {streaming && (
                  <span className="inline-block w-[2px] h-[1em] align-[-0.15em] ml-0.5 bg-[#FF4800] animate-pulse" />
                )}
              </p>
            </div>
          ))}

          {status === "ready" && (
            <div className="flex gap-2">
              {/* Labelled for what it does: approving also queues the post to publish at the
                  slot's planned time, which is a bigger commitment than "approve" alone. */}
              <button
                onClick={() => handleDecision("approve")}
                disabled={isReviewing || isScheduling}
                className="flex-1 bg-green-600 hover:bg-green-500 disabled:bg-green-300 text-white text-xs font-medium py-1.5 rounded-lg transition-colors"
              >
                {isReviewing ? "Approving…" : isScheduling ? "Scheduling…" : "Approve & Schedule"}
              </button>
              <button
                onClick={() => handleDecision("reject")}
                disabled={isReviewing || isScheduling}
                className="flex-1 bg-[#F2EDE4] hover:bg-[#E8E3DA] text-[#1B1A17] text-xs font-medium py-1.5 rounded-lg transition-colors border border-[#E8E3DA]"
              >
                Reject
              </button>
            </div>
          )}

          {status === "rejected" && <p className="text-xs text-[#9E9893] font-medium">Rejected</p>}
        </div>
      )}

      {/* Outside the draft panel on purpose. The draft text comes from the task's SSE replay,
          which is gone once the LLM service restarts — an approved slot would then render an
          empty card with no hint of whether it was ever scheduled. Where it's going to publish
          is the part that must survive, so it reads from the calendar instead. */}
      {status === "approved" && (
        <SlotDelivery
          posts={scheduledPosts}
          skipped={skipped}
          isScheduling={isScheduling}
          onSchedule={scheduleApprovedItem}
        />
      )}
    </div>
  );
}

// ── What is happening while a post is being written ──────────────────────────

/**
 * The stages of writing one post, with the live one named and timed.
 *
 * This replaces a single pulsing dot reading "Loading draft…" — which was accurate and
 * useless, because it looked identical two seconds and four minutes in. The stages come
 * straight off the task stream, so the thing on screen is what the backend is actually
 * doing rather than an animation running on a timer.
 */
function PhaseStepper({
  phase,
  mode,
  elapsed,
  starting,
}: {
  phase: DraftPhase;
  mode: DraftMode;
  elapsed: number;
  starting: boolean;
}) {
  const phases = phasesFor(mode);
  const currentIndex = phases.indexOf(phase);

  return (
    <div className="mb-3">
      <div className="flex items-center gap-2 mb-2">
        <svg className="animate-spin flex-shrink-0" width={14} height={14} viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" stroke="#E8E3DA" strokeWidth="3" />
          <path d="M12 2a10 10 0 0 1 10 10" stroke="#FF4800" strokeWidth="3" strokeLinecap="round" />
        </svg>
        <p className="text-xs font-medium text-[#1B1A17]">
          {starting ? "Starting…" : PHASE_LABEL[phase]}
        </p>
        {/* Only once it has been long enough to wonder — a counter that starts at zero on
            every card is noise, not reassurance. */}
        {elapsed >= 3 && <span className="text-[11px] text-[#9E9893]">{elapsed}s</span>}
      </div>

      {/* One column per stage, so each label sits under the bar it describes. */}
      <div className="flex items-start gap-1.5">
        {phases.map((step, index) => {
          const done = currentIndex > index;
          const live = currentIndex === index;
          return (
            <div key={step} className="flex-1 min-w-0">
              <span
                className={`block h-1 rounded-full ${
                  done ? "bg-[#FF4800]" : live ? "bg-[#FF4800]/40 animate-pulse" : "bg-[#E8E3DA]"
                }`}
              />
              <span
                className={`block text-[10px] mt-1 truncate ${
                  live ? "text-[#FF4800] font-medium" : done ? "text-[#9E9893]" : "text-[#C8C2BA]"
                }`}
              >
                {PHASE_LABEL[step]}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * The roundtable, while it is sitting.
 *
 * The agents' turns already stream on the same connection as everything else and were simply
 * being dropped, which left the longest part of writing a post — the discussion — as dead air.
 * Showing them turns the wait into the reason the post is worth waiting for.
 */
function RoundtableFeed({
  utterances,
  speakerUp,
}: {
  utterances: Utterance[];
  speakerUp: string | null;
}) {
  if (utterances.length === 0 && !speakerUp) {
    return (
      <p className="mb-3 text-xs text-[#9E9893] italic flex items-center gap-2">
        <span className="w-1.5 h-1.5 rounded-full bg-[#FF4800] animate-pulse flex-shrink-0" />
        Gathering the table…
      </p>
    );
  }

  // A slot targeting several platforms seats one table per platform, and their turns arrive
  // interleaved on the one stream. Tag the speaker with its table when there is more than one
  // in play, or the feed reads as a single conversation talking past itself.
  const manyTables = new Set(utterances.map((u) => u.platform)).size > 1;

  return (
    <div className="mb-3 space-y-1.5">
      {utterances.map((u) => (
        <div key={u.key} className="text-xs leading-relaxed">
          <span className="font-semibold text-[#FF4800]">{speakerName(u.speaker)}</span>
          {manyTables && u.platform && (
            <span className="text-[10px] text-[#9E9893]"> · {u.platform}</span>
          )}
          <span className="text-[#6B6561]"> — {u.text}</span>
        </div>
      ))}
      {speakerUp && (
        <p className="text-xs text-[#9E9893] italic flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-[#FF4800] animate-pulse flex-shrink-0" />
          {speakerName(speakerUp)} is thinking…
        </p>
      )}
    </div>
  );
}

// ── Slot Delivery — what an approved slot actually put on the calendar ────────

interface SlotDeliveryProps {
  posts: ScheduledSlotPost[];
  skipped: SkipReason[];
  isScheduling: boolean;
  onSchedule: (reschedule?: RescheduleChoice) => void;
}

/**
 * Answers one question for an approved slot: is this going to be posted, and when?
 *
 * Approval alone used to be the whole story here — a slot read "✓ Approved" whether its copy
 * was queued to publish or had gone nowhere at all. The two states look nothing alike now:
 * scheduled slots name their platform and publish time, and an unscheduled one says so and
 * offers the button that fixes it.
 */
function SlotDelivery({ posts, skipped, isScheduling, onSchedule }: SlotDeliveryProps) {
  // A slot whose window has gone is the one skip the user can actually fix, so it gets its own
  // controls rather than sitting in the muted list with the reasons nobody can act on.
  const missed = skipped.filter((s) => s.reason_code === "time_passed");
  const other = skipped.filter((s) => s.reason_code !== "time_passed");

  if (isScheduling) {
    return (
      <div className="mt-2 flex items-center gap-2 text-xs text-[#9E9893] italic">
        <span className="w-1.5 h-1.5 rounded-full bg-[#FF4800] animate-pulse flex-shrink-0" />
        Adding to your content calendar…
      </div>
    );
  }

  if (missed.length > 0) {
    return (
      <div className="mt-2 space-y-1.5">
        {posts.map((post) => (
          <ScheduledLine key={post.id} post={post} />
        ))}
        <MissedSlot missed={missed} onSchedule={onSchedule} />
        {other.map((s) => (
          <p key={s.platform} className="text-xs text-[#9E9893] leading-relaxed">
            {platformLabel(s.platform)}: {s.reason}
          </p>
        ))}
      </div>
    );
  }

  return (
    <div className="mt-2 space-y-1.5">
      {posts.length > 0 ? (
        <>
          {posts.map((post) => (
            <ScheduledLine key={post.id} post={post} />
          ))}
          <Link
            href="/profile?section=calendar"
            className="inline-block text-xs text-[#FF4800] hover:underline"
          >
            View in content calendar →
          </Link>
        </>
      ) : (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          <p className="text-xs text-amber-800 font-medium">Approved — not on the calendar yet</p>
          <p className="text-[11px] text-amber-700 mt-0.5 leading-relaxed">
            This will be picked up automatically within a few minutes, or you can add it now.
          </p>
          <button
            onClick={() => onSchedule()}
            className="mt-1.5 text-xs font-medium text-white bg-amber-600 hover:bg-amber-500 px-2.5 py-1 rounded-lg transition-colors"
          >
            Schedule now
          </button>
        </div>
      )}

      {/* A platform we can't publish to is the ordinary case, not a failure — stated plainly
          so "only LinkedIn was scheduled" never reads as something having gone wrong. */}
      {skipped.map((s) => (
        <p key={s.platform} className="text-xs text-[#9E9893] leading-relaxed">
          {platformLabel(s.platform)}: {s.reason}
        </p>
      ))}
    </div>
  );
}

/** One post on the calendar: which platform, where it got to, and when it goes out. */
function ScheduledLine({ post }: { post: ScheduledSlotPost }) {
  const state = DELIVERY_STATE[post.status] ?? {
    verb: post.status,
    className: "text-[#6B6561]",
    icon: "•",
  };
  return (
    <p className={`text-xs font-medium ${state.className}`}>
      {state.icon} {platformLabel(post.platform)} {state.verb} {formatSlot(post.scheduled_at)}
    </p>
  );
}

/**
 * A slot whose posting window has already gone, and the two ways out of it.
 *
 * Approving a draft after its slot has passed used to be a dead end: the post was dropped with
 * "that time has already passed" and the only thing the UI offered was the button that had
 * just failed. The copy is fine — it is the clock that moved — so the choice is only ever
 * *when*, and both answers live here: let the planner take the next occurrence of the slot's
 * own window, or name a time.
 */
function MissedSlot({
  missed,
  onSchedule,
}: {
  missed: SkipReason[];
  onSchedule: (reschedule?: RescheduleChoice) => void;
}) {
  const [customTime, setCustomTime] = useState("");
  const [showPicker, setShowPicker] = useState(false);

  return (
    <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
      <p className="text-xs text-amber-800 font-medium">
        {missed.length === 1
          ? `${platformLabel(missed[0].platform)}: that posting time has passed`
          : "Those posting times have passed"}
      </p>
      <p className="text-[11px] text-amber-700 mt-0.5 leading-relaxed">
        The post is written and approved — it just needs a new time.
      </p>

      <div className="flex flex-wrap items-center gap-2 mt-1.5">
        {/* The default action, because it keeps the window the plan chose and only moves the
            day — a morning post stays a morning post. */}
        <button
          onClick={() => onSchedule({ auto_reschedule: true })}
          className="text-xs font-medium text-white bg-amber-600 hover:bg-amber-500 px-2.5 py-1 rounded-lg transition-colors"
        >
          Post at the next best time
        </button>
        {!showPicker && (
          <button
            onClick={() => setShowPicker(true)}
            className="text-xs font-medium text-amber-800 hover:underline"
          >
            or pick a time
          </button>
        )}
      </div>

      {showPicker && (
        <div className="flex flex-wrap items-center gap-2 mt-2">
          <input
            type="datetime-local"
            value={customTime}
            min={minSchedulableTime()}
            onChange={(e) => setCustomTime(e.target.value)}
            className="bg-white border border-amber-200 rounded-lg px-2 py-1 text-xs text-[#1B1A17]"
          />
          <button
            onClick={() => onSchedule({ scheduled_at: customTime })}
            disabled={!customTime}
            className="text-xs font-medium text-white bg-amber-600 hover:bg-amber-500 disabled:bg-amber-300 px-2.5 py-1 rounded-lg transition-colors"
          >
            Schedule
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * The earliest time the picker will accept, as a `datetime-local` value.
 *
 * Matches the backend's own 15-minute lead, so the browser rules out a time the server would
 * only reject after a round trip. Formatted from local components — `toISOString` would give
 * UTC and offer the user a time in the wrong timezone.
 */
function minSchedulableTime(): string {
  const soonest = new Date(Date.now() + 15 * 60 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${soonest.getFullYear()}-${pad(soonest.getMonth() + 1)}-${pad(soonest.getDate())}` +
    `T${pad(soonest.getHours())}:${pad(soonest.getMinutes())}`
  );
}

/** Platform ids are lowercase throughout the API; capitalise for prose. */
function platformLabel(platform: string): string {
  return platform.charAt(0).toUpperCase() + platform.slice(1);
}

/** Renders an ISO instant in the reader's own locale — the stored slot time is authoritative,
 * this is only how it reads back. */
function formatSlot(scheduledAt: string): string {
  const when = new Date(scheduledAt);
  return Number.isNaN(when.getTime())
    ? scheduledAt
    : when.toLocaleString(undefined, {
        weekday: "short",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
}