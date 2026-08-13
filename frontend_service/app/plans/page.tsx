"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import DashboardSidebar from "../components/DashboardSidebar";

type Platform = "x" | "facebook" | "tiktok" | "linkedin";
type ContentType = "text" | "video" | "brand";

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

/** How often to re-read a plan while its campaign is being drafted. */
const POLL_INTERVAL_MS = 5000;

/** Polls to keep running after a confirm even with nothing yet `generating`. Slots are started
 * one at a time with a pause between them, so the first can take a few seconds to appear —
 * this covers that gap, and is bounded so a campaign that fails to start can't poll forever. */
const CONFIRM_GRACE_TICKS = 6;

const STATUS_BADGE: Record<string, string> = {
  planned: "bg-[#F2EDE4] text-[#6B6561]",
  generating: "bg-amber-100 text-amber-700",
  awaiting_review: "bg-blue-100 text-blue-700",
  done: "bg-green-100 text-green-700",
  skipped: "bg-[#F2EDE4] text-[#9E9893] line-through",
  error: "bg-red-100 text-red-700",
};

export default function PlansPage() {
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

  async function loadPlan(planId: string) {
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
  }

  useEffect(() => {
    loadPlans();
  }, []);

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
  // Polls remaining in the post-confirm grace window (see the effect below).
  const [graceTicks, setGraceTicks] = useState(0);
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

  // Confirming starts every slot drafting in the background, so the statuses on screen go
  // stale the moment it returns. Poll while there is visibly work in flight, plus a short
  // grace window after a confirm to cover the seconds before the first slot flips to
  // `generating` — without that the page looks like nothing happened.
  const isDrafting = planActive && plan.items.some((i) => i.status === "generating");
  // "Ready" means the copy exists and is yours to look at — drafted, reviewed, or already
  // scheduled. Skipped slots count too: they are settled, just not by writing anything.
  const draftedCount = plan.items.filter(
    (i) => i.status !== "planned" && i.status !== "generating"
  ).length;

  useEffect(() => {
    if (!isDrafting && graceTicks === 0) return;

    const timer = setTimeout(() => {
      setGraceTicks((n) => Math.max(0, n - 1));
      reloadPlan();
    }, POLL_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [isDrafting, graceTicks, reloadPlan]);

  async function handleConfirm() {
    onError(null);
    setConfirming(true);
    try {
      const res = await fetch(`/api/plans/${plan.plan_id}/confirm`, {
        method: "POST",
        headers: authHeaders(),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        onError(data.error ?? "Failed to confirm plan.");
        return;
      }
      // The response still shows every slot as `planned` — drafting starts after it returns.
      // The grace window is what turns that into a live view.
      onUpdated(data as Plan);
      setGraceTicks(CONFIRM_GRACE_TICKS);
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
      </p>

      {plan.strategy_summary && (
        <div className="bg-[#FFF0EB] border border-[#FFCBB8] rounded-xl px-4 py-3 mb-5 text-sm text-[#1B1A17]">
          {plan.strategy_summary}
        </div>
      )}

      {plan.status === "draft" && (
        <>
          <button
            onClick={handleConfirm}
            disabled={confirming}
            className="mb-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            {confirming ? "Confirming…" : `Confirm Plan — write all ${plan.items.length} posts`}
          </button>
          <p className="mb-5 text-xs text-[#9E9893] leading-relaxed">
            Every slot gets drafted now, so you can review the whole campaign at once. Nothing
            publishes until you approve it.
          </p>
        </>
      )}
      {plan.status === "active" && (
        <div className="mb-5">
          {isDrafting ? (
            <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 inline-flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[#FF4800] animate-pulse flex-shrink-0" />
              Writing your campaign — {draftedCount} of {plan.items.length} posts ready. You can
              review each one as it lands.
            </p>
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
        {plan.items.map((item) => (
          <PlanItemCard
            key={item.item_id}
            planId={plan.plan_id}
            item={item}
            editable={plan.status === "draft"}
            planActive={planActive}
            scheduledPosts={scheduledByItem[item.item_id] ?? []}
            onScheduled={loadScheduled}
            authHeaders={authHeaders}
            onUpdated={onUpdated}
            onError={onError}
          />
        ))}
      </div>
    </div>
  );
}

// ── Plan Item Card ────────────────────────────────────────────────────────────

interface PlanItemCardProps {
  planId: string;
  item: PlanItem;
  editable: boolean;
  planActive: boolean;
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

  // NEW: decide whether this item can show "Generate Draft Now" (untouched, still
  // "planned"), or should auto-load an already-existing draft (the cron already
  // executed it, or you generated it earlier and reloaded the page).
  const canGenerateNow = planActive && item.status === "planned";
  const canShowDraft = planActive && item.status !== "planned" && item.status !== "skipped";

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

      {/* NEW: shows "Generate Draft Now" for untouched items, or auto-loads the
          draft (from the cron or an earlier manual run) for executed items. */}
      {(canGenerateNow || canShowDraft) && (
        <ItemDraftPreview
          planId={planId}
          itemId={item.item_id}
          existingTaskId={item.task_id}
          itemStatus={item.status}
          scheduledPosts={scheduledPosts}
          onScheduled={onScheduled}
          authHeaders={authHeaders}
          onError={onError}
        />
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
  scheduledPosts: ScheduledSlotPost[];
  onScheduled: () => void;
  authHeaders: () => Record<string, string>;
  onError: (msg: string | null) => void;
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
  scheduledPosts,
  onScheduled,
  authHeaders,
  onError,
}: ItemDraftPreviewProps) {
  const [status, setStatus] = useState<"idle" | "starting" | "generating" | "ready" | "approved" | "rejected">("idle");
  const [statusLabel, setStatusLabel] = useState("");
  // Keyed by platform: a slot can target several, and each gets its own draft and verdict.
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [taskId, setTaskId] = useState<string | null>(existingTaskId);
  const [skipped, setSkipped] = useState<SkipReason[]>([]);
  const [isReviewing, setIsReviewing] = useState(false);
  const [isScheduling, setIsScheduling] = useState(false);

  const draftEntries = Object.entries(drafts);

  // Auto-connect on mount if this item already has a task (e.g. the cron executed
  // it in the background, or you generated it earlier and reloaded the page) — the
  // SSE stream replays its full history, so we still catch draft_ready even though
  // we weren't watching when it first happened.
  useEffect(() => {
    if (existingTaskId && (itemStatus === "generating" || itemStatus === "awaiting_review" || itemStatus === "done")) {
      setTaskId(existingTaskId);
      setStatus(itemStatus === "done" ? "approved" : "generating");
      watchTask(existingTaskId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existingTaskId, itemStatus]);

  async function handleGenerateNow() {
    setStatus("starting");
    setStatusLabel("Starting draft…");
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
        return;
      }
      const newTaskId = data.task?.task_id as string | undefined;
      if (!newTaskId) {
        onError("No task returned from execute.");
        setStatus("idle");
        return;
      }
      setTaskId(newTaskId);
      setStatus("generating");
      watchTask(newTaskId);
    } catch {
      onError("Could not reach the backend.");
      setStatus("idle");
    }
  }

  function watchTask(id: string) {
    // EventSource cannot set headers, so the token rides as a query parameter — the backend
    // accepts it there for exactly this case. Without it, the stream for a run this business
    // owns is refused and the card never leaves "generating".
    const token = localStorage.getItem("starlight_token");
    const query = token ? `?access_token=${encodeURIComponent(token)}` : "";
    const es = new EventSource(`/api/tasks/${id}/events${query}`);
    let lastSeq = -1;

    es.onmessage = (e) => {
      let event: Record<string, unknown>;
      try {
        event = JSON.parse(e.data as string);
      } catch {
        return;
      }
      const seq = event.seq as number | undefined;
      if (typeof seq === "number") {
        if (seq <= lastSeq) return;
        lastSeq = seq;
      }

      const type = event.type as string;
      const evtStatus = event.status as string;

      if (type === "progress" && evtStatus === "running") {
        setStatusLabel("Writing draft…");
      }

      if (type === "result" && evtStatus === "draft_ready") {
        // Record which platform this draft is for — approving has to send a verdict for every
        // one of them, or the task stays half-reviewed and can never be scheduled.
        const platform = (event.platform as string) || "linkedin";
        setDrafts((prev) => ({ ...prev, [platform]: event.draft as string }));
        setStatus((prev) => (prev === "approved" ? "approved" : "ready"));
      }

      if (type === "result" && evtStatus === "final") {
        setStatus("approved");
      }
    };

    es.onerror = () => {
      es.close();
    };
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
        // The token is required, not optional: a run started by this business is refused to
        // anyone else, and an unauthenticated request counts as anyone else.
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
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
      {(status === "starting" || (status === "generating" && draftEntries.length === 0)) && (
        <div className="flex items-center gap-2 text-xs text-[#9E9893] italic">
          <span className="w-1.5 h-1.5 rounded-full bg-[#FF4800] animate-pulse flex-shrink-0" />
          {statusLabel || "Loading draft…"}
        </div>
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
              <p className="text-sm text-[#1B1A17] whitespace-pre-wrap leading-relaxed">{text}</p>
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