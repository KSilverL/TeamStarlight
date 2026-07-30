"use client";

import { useState, useEffect } from "react";
import Link from "next/link";

type Platform = "x" | "instagram" | "tiktok" | "linkedin";
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
  { id: "instagram", label: "Instagram", abbr: "IG", badgeClass: "bg-pink-600 text-white" },
  { id: "tiktok", label: "TikTok", abbr: "TK", badgeClass: "bg-[#1B1A17] text-white" },
  { id: "linkedin", label: "LinkedIn", abbr: "in", badgeClass: "bg-blue-600 text-white" },
];
const platformMap = Object.fromEntries(PLATFORMS.map((p) => [p.id, p]));

const CONTENT_TYPES: { id: ContentType; label: string }[] = [
  { id: "text", label: "Text" },
  { id: "video", label: "Video" },
  { id: "brand", label: "Brand Animation" },
];

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

  function authHeaders(): Record<string, string> {
    const token = localStorage.getItem("starlight_token");
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

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

  function handlePlanUpdated(plan: Plan) {
    setSelectedPlan(plan);
    setPlans((prev) => prev.map((p) => (p.plan_id === plan.plan_id ? plan : p)));
  }

  return (
    <div className="flex h-screen bg-[#F8F5EE] text-[#1B1A17] overflow-hidden">
      {/* Sidebar: plan list */}
      <aside className="w-80 flex-shrink-0 border-r border-[#E8E3DA] flex flex-col bg-white">
        <div className="p-5 border-b border-[#E8E3DA] flex-shrink-0">
          <Link
            href="/"
            className="flex items-center gap-2 font-bold text-lg text-[#1B1A17] hover:text-[#FF4800] transition-colors"
          >
            ✦ Starlight
          </Link>
          <p className="text-xs text-[#9E9893] mt-0.5">Posting Plans</p>
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
      </p>

      {plan.strategy_summary && (
        <div className="bg-[#FFF0EB] border border-[#FFCBB8] rounded-xl px-4 py-3 mb-5 text-sm text-[#1B1A17]">
          {plan.strategy_summary}
        </div>
      )}

      {plan.status === "draft" && (
        <button
          onClick={handleConfirm}
          disabled={confirming}
          className="mb-5 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          {confirming ? "Confirming…" : "Confirm Plan — start auto-drafting"}
        </button>
      )}
      {plan.status === "active" && (
        <p className="mb-5 text-xs text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2 inline-block">
          ✓ Active — items will auto-draft on their scheduled day. You&apos;ll review each one before
          it&apos;s approved or posted.
        </p>
      )}

      <h2 className="text-sm font-semibold text-[#6B6561] mb-3">Schedule</h2>
      <div className="space-y-3">
        {plan.items.map((item) => (
          <PlanItemCard
            key={item.item_id}
            planId={plan.plan_id}
            item={item}
            editable={plan.status === "draft"}
            planActive={plan.status === "active"}
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
  authHeaders: () => Record<string, string>;
  onUpdated: (plan: Plan) => void;
  onError: (msg: string | null) => void;
}

function PlanItemCard({ planId, item, editable, planActive, authHeaders, onUpdated, onError }: PlanItemCardProps) {
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
  const canShowDraft =
    planActive &&
    (
      item.status === "generating" ||
      item.status === "awaiting_review" ||
      item.status === "done"
    );

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
		  {canShowDraft && (
		    <ItemDraftPreview
		      planId={planId}
		      itemId={item.item_id}
		      existingTaskId={item.task_id}
		      itemStatus={item.status}
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
  authHeaders: () => Record<string, string>;
  onError: (msg: string | null) => void;
}

function ItemDraftPreview({
  existingTaskId,
  itemStatus,
  authHeaders,
  onError,
}: ItemDraftPreviewProps) {
  const [status, setStatus] = useState<
    "idle" | "generating" | "ready" | "approved" | "rejected"
  >("idle");

  const [statusLabel, setStatusLabel] = useState("");
  const [draftText, setDraftText] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(existingTaskId);

  useEffect(() => {
    if (
      existingTaskId &&
      (
        itemStatus === "generating" ||
        itemStatus === "awaiting_review" ||
        itemStatus === "done"
      )
    ) {
      setTaskId(existingTaskId);

      setStatus(
        itemStatus === "done"
          ? "approved"
          : "generating"
      );

      watchTask(existingTaskId);
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existingTaskId, itemStatus]);


  function watchTask(id: string) {
    const es = new EventSource(`/api/tasks/${id}/events`);

    let lastSeq = -1;

    es.onmessage = (e) => {
      let event: Record<string, unknown>;

      try {
        event = JSON.parse(e.data);
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
        setStatusLabel("Writing draft...");
      }


      if (type === "result" && evtStatus === "draft_ready") {
        setDraftText(event.draft as string);
        setStatus("ready");
      }


      if (type === "result" && evtStatus === "final") {
        setStatus("approved");
      }
    };


    es.onerror = () => {
      es.close();
    };
  }


  async function handleDecision(
    decision: "approve" | "reject"
  ) {
    if (!taskId) return;


    try {
      await fetch(`/api/tasks/${taskId}/review`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders(),
        },
        body: JSON.stringify({
          verdicts: {
            linkedin: {
              decision,
            },
          },
        }),
      });


      setStatus(
        decision === "approve"
          ? "approved"
          : "rejected"
      );

    } catch {
      onError("Could not submit the review decision.");
    }
  }


  if (status === "idle") {
    return (
      <div className="mt-3 text-xs text-[#9E9893] italic">
        Waiting for scheduled generation...
      </div>
    );
  }


  return (
    <div className="mt-3 pt-3 border-t border-[#E8E3DA]">

      {status === "generating" && !draftText && (
        <div className="flex items-center gap-2 text-xs text-[#9E9893] italic">
          <span className="w-1.5 h-1.5 rounded-full bg-[#FF4800] animate-pulse" />
          {statusLabel || "Generating draft..."}
        </div>
      )}


      {draftText && (
        <div className="bg-[#F8F5EE] border border-[#E8E3DA] rounded-lg p-3">

          <p className="text-sm whitespace-pre-wrap leading-relaxed mb-3">
            {draftText}
          </p>


          {status === "ready" && (
            <div className="flex gap-2">

              <button
                onClick={() => handleDecision("approve")}
                className="flex-1 bg-green-600 hover:bg-green-500 text-white text-xs py-1.5 rounded-lg"
              >
                Approve
              </button>


              <button
                onClick={() => handleDecision("reject")}
                className="flex-1 bg-[#F2EDE4] hover:bg-[#E8E3DA] text-xs py-1.5 rounded-lg"
              >
                Reject
              </button>

            </div>
          )}


          {status === "approved" && (
            <p className="text-xs text-green-700 font-medium">
              ✓ Approved
            </p>
          )}


          {status === "rejected" && (
            <p className="text-xs text-[#9E9893]">
              Rejected
            </p>
          )}

        </div>
      )}

    </div>
  );
}