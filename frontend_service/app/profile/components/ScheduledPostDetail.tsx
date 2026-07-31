"use client";

import { useState } from "react";
import { PLATFORM_CONFIG } from "../data";
import { formatDisplayDate } from "../format";
import { namesForPageIds } from "../metaPages";
import { describeTimeProblem, parseHashtags } from "../scheduling";
import type { ScheduledPost, ScheduledPostStatus } from "../types";

/** The patch the calendar sends upstream. Every field is optional — the backend leaves out
 * what isn't sent, so only what actually changed goes over the wire. */
export interface ScheduledPostPatch {
  date?: string;
  time?: string;
  message?: string;
  hashtags?: string[];
}

interface ScheduledPostDetailProps {
  post: ScheduledPost;
  onClose: () => void;
  /** Cancels the post upstream. Rejects (or throws) if the backend refused, so this component
   * can surface the reason instead of closing on a cancel that didn't happen. */
  onCancel: (postId: string) => Promise<void>;
  /** Applies an edit upstream. Same contract as onCancel: it throws on refusal, because for a
   * Facebook post the change also has to reach Graph and may not. */
  onUpdate: (postId: string, patch: ScheduledPostPatch) => Promise<void>;
}

/** How a post that is no longer pending is described, and the colours it's drawn in. */
const STATUS_NOTE: Record<
  Exclude<ScheduledPostStatus, "scheduled">,
  { label: string; tone: string }
> = {
  publishing: {
    label: "Publishing right now — it can't be edited or cancelled mid-flight.",
    tone: "bg-amber-50 border-amber-200 text-amber-700",
  },
  published: {
    label: "Already published. Editing it here wouldn't change what went out.",
    tone: "bg-green-50 border-green-200 text-green-700",
  },
  failed: {
    label: "This post did not go out. Schedule a new one to try again.",
    tone: "bg-red-50 border-red-200 text-red-700",
  },
  cancelled: {
    label: "Cancelled — it will not publish.",
    tone: "bg-[#F2EDE4] border-[#E8E3DA] text-[#6B6561]",
  },
};

/**
 * One scheduled post: what it says, when it goes out, and the two things you can do to it.
 *
 * Editing and cancelling are both gated on the post still being pending, mirroring the
 * backend's own rule — a published post can't be un-published and a failed one can't be
 * retried in place, so offering either button would only produce a 409. Cancelling stays a
 * two-step confirm because it's irreversible and the click target sits one tap away from the
 * post the user was only trying to read.
 */
export default function ScheduledPostDetail({
  post,
  onClose,
  onCancel,
  onUpdate,
}: ScheduledPostDetailProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Seeded from the post's own wall-clock strings, which the backend already resolved into the
  // zone the post was scheduled in — so the fields open showing the time the user chose.
  const [date, setDate] = useState(post.date);
  const [time, setTime] = useState(post.time);
  const [message, setMessage] = useState(post.text);
  const [hashtagInput, setHashtagInput] = useState(post.hashtags.join(" "));

  const platform = PLATFORM_CONFIG[post.platform];
  const isPending = post.status === "scheduled";
  // Compared inline rather than through isPending so the status narrows for the lookup —
  // a boolean const doesn't carry the narrowing with it.
  const statusNote = post.status === "scheduled" ? null : STATUS_NOTE[post.status];
  const pageNames = post.pageIds.length > 0 ? namesForPageIds(post.pageIds) : [];

  const timeProblem = describeTimeProblem(date, time, {
    nativeScheduled: post.nativeScheduled,
    timeZone: post.timezone,
  });

  const hashtags = parseHashtags(hashtagInput);
  const timeChanged = date !== post.date || time !== post.time;
  const textChanged = message.trim() !== post.text;
  const tagsChanged = hashtags.join(" ") !== post.hashtags.join(" ");
  const hasChanges = timeChanged || textChanged || tagsChanged;

  const canSave = hasChanges && !timeProblem && message.trim() !== "" && !isSaving;

  function startEditing() {
    // Re-seed from the post so a previous cancelled edit doesn't reopen half-typed.
    setDate(post.date);
    setTime(post.time);
    setMessage(post.text);
    setHashtagInput(post.hashtags.join(" "));
    setError(null);
    setIsEditing(true);
  }

  async function handleSave() {
    if (!canSave) return;

    setIsSaving(true);
    setError(null);
    try {
      // Only the fields that moved. The date and time go together because the API composes
      // them into one wall-clock string, and sending half of a pair would compose it against
      // whatever the other half happened to be.
      await onUpdate(post.id, {
        ...(timeChanged ? { date, time } : {}),
        ...(textChanged ? { message: message.trim() } : {}),
        ...(tagsChanged ? { hashtags } : {}),
      });
      // The parent closes this modal and refetches on success — nothing to do here.
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save those changes.");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleCancel() {
    setIsCancelling(true);
    setError(null);
    try {
      await onCancel(post.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel that post.");
      setIsConfirming(false);
    } finally {
      setIsCancelling(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 p-6">
      <div className="bg-[#F8F5EE] rounded-2xl shadow-2xl w-full max-w-lg flex flex-col overflow-hidden max-h-[85vh]">
        {/* ── Header ────────────────────────────────────────────────────────── */}
        <div className="flex items-start justify-between px-6 py-4 border-b border-[#E8E3DA] bg-white rounded-t-2xl flex-shrink-0">
          <div className="flex items-center gap-3">
            <span
              className={`w-9 h-9 rounded-lg flex items-center justify-center text-xs font-bold text-white flex-shrink-0 ${platform.badge}`}
            >
              {platform.abbr}
            </span>
            <div>
              <h2 className="text-base font-semibold text-[#1B1A17]">
                {isEditing ? `Edit ${platform.label} post` : platform.label}
              </h2>
              <p className="text-xs text-[#9E9893] mt-0.5">
                {formatDisplayDate(post.date)} at {post.time}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="w-8 h-8 flex items-center justify-center rounded-lg text-[#9E9893] hover:text-[#1B1A17] hover:bg-[#F2EDE4] transition-colors flex-shrink-0"
          >
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

        {/* ── Body ──────────────────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {/* Why this post can't be acted on, when it can't. Shown first because it explains
              the absence of the buttons the user came here to press. */}
          {statusNote && (
            <p className={`text-xs leading-relaxed border rounded-xl px-3 py-2 ${statusNote.tone}`}>
              {statusNote.label}
            </p>
          )}

          {/* The platform's own explanation of a failure, kept verbatim by the backend so it
              names the actual fix rather than saying the post merely "failed". */}
          {post.status === "failed" && post.lastError && (
            <div className="bg-white rounded-xl border border-red-200 p-4">
              <p className="text-xs font-semibold text-red-700 mb-1">What went wrong</p>
              <p className="text-xs text-[#6B6561] leading-relaxed">{post.lastError}</p>
            </div>
          )}

          {isEditing ? (
            <>
              {/* Date and time sit side by side: moving a post to another day is the same
                  edit as moving it an hour, and splitting them across sections implies
                  otherwise. */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label
                    htmlFor="edit-date"
                    className="block text-xs font-semibold text-[#1B1A17] mb-2"
                  >
                    Date
                  </label>
                  <input
                    id="edit-date"
                    type="date"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                    className={`w-full border rounded-xl px-3 py-2.5 text-sm text-[#1B1A17] bg-white focus:outline-none transition-colors ${
                      timeProblem
                        ? "border-red-300 focus:border-red-500"
                        : "border-[#E8E3DA] focus:border-[#FF4800]"
                    }`}
                  />
                </div>
                <div>
                  <label
                    htmlFor="edit-time"
                    className="block text-xs font-semibold text-[#1B1A17] mb-2"
                  >
                    Time <span className="font-normal text-[#9E9893]">({post.timezone})</span>
                  </label>
                  <input
                    id="edit-time"
                    type="time"
                    value={time}
                    onChange={(e) => setTime(e.target.value)}
                    className={`w-full border rounded-xl px-3 py-2.5 text-sm text-[#1B1A17] bg-white focus:outline-none transition-colors ${
                      timeProblem
                        ? "border-red-300 focus:border-red-500"
                        : "border-[#E8E3DA] focus:border-[#FF4800]"
                    }`}
                  />
                </div>
              </div>

              {timeProblem && (
                <p className="text-xs text-red-600 leading-relaxed -mt-1">{timeProblem}</p>
              )}

              <div>
                <label
                  htmlFor="edit-message"
                  className="block text-xs font-semibold text-[#1B1A17] mb-2"
                >
                  Post copy
                </label>
                <textarea
                  id="edit-message"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  rows={8}
                  className="w-full border border-[#E8E3DA] rounded-xl px-3 py-2.5 text-sm text-[#1B1A17] bg-white leading-relaxed resize-y focus:outline-none focus:border-[#FF4800] transition-colors"
                />
              </div>

              <div>
                <label
                  htmlFor="edit-hashtags"
                  className="block text-xs font-semibold text-[#1B1A17] mb-2"
                >
                  Hashtags
                </label>
                <input
                  id="edit-hashtags"
                  type="text"
                  value={hashtagInput}
                  onChange={(e) => setHashtagInput(e.target.value)}
                  placeholder="#bamboo #zerowaste"
                  className="w-full border border-[#E8E3DA] rounded-xl px-3 py-2.5 text-sm text-[#1B1A17] bg-white placeholder:text-[#C8C2BA] focus:outline-none focus:border-[#FF4800] transition-colors"
                />
                <p className="text-xs text-[#9E9893] mt-1.5 leading-relaxed">
                  Separated by spaces or commas. They publish as a block under the copy.
                </p>
              </div>

              {/* An edit to a Facebook-held post is not a local change — it has to reach Graph
                  or the calendar and the thing that actually publishes would disagree. Say so
                  before the save, not in the error if it fails. */}
              {post.nativeScheduled && (
                <p className="text-xs text-[#9E9893] leading-relaxed bg-white border border-[#E8E3DA] rounded-xl px-3 py-2">
                  Saving pushes these changes to Facebook, which is holding the post.
                </p>
              )}
            </>
          ) : (
            <>
              {/* The post copy, exactly as it will publish. */}
              <div className="bg-white rounded-xl border border-[#E8E3DA] p-4">
                <p className="text-sm text-[#1B1A17] whitespace-pre-wrap leading-relaxed">
                  {post.text}
                </p>

                {post.hashtags.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-3 pt-3 border-t border-[#F2EDE4]">
                    {post.hashtags.map((tag) => (
                      <span
                        key={tag}
                        className="text-xs text-[#FF4800] bg-[#FFF0EB] px-2 py-0.5 rounded-full"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Timezone is shown explicitly: the same post reads as a different wall-clock
                  time to someone in another zone, so the time above is ambiguous without it. */}
              <dl className="text-xs space-y-2">
                <div className="flex justify-between gap-4">
                  <dt className="text-[#9E9893]">Publishes</dt>
                  <dd className="text-[#6B6561] text-right">
                    {post.time} · {post.timezone}
                  </dd>
                </div>
                {pageNames.length > 0 && (
                  <div className="flex justify-between gap-4">
                    <dt className="text-[#9E9893]">
                      Facebook Page{pageNames.length > 1 ? "s" : ""}
                    </dt>
                    {/* Named, not counted — "2" tells the user nothing they can verify. */}
                    <dd className="text-[#6B6561] text-right">{pageNames.join(", ")}</dd>
                  </div>
                )}
                <div className="flex justify-between gap-4">
                  <dt className="text-[#9E9893]">Held by</dt>
                  <dd className="text-[#6B6561] text-right">
                    {post.nativeScheduled ? "Facebook" : "Starlight"}
                  </dd>
                </div>
              </dl>

              {post.nativeScheduled && isPending && (
                <p className="text-xs text-[#9E9893] leading-relaxed">
                  Facebook is holding this one and will publish it at the time above even if
                  Starlight is offline. Editing or cancelling here reaches Facebook too.
                </p>
              )}
            </>
          )}

          {error && (
            <p className="text-xs text-red-600 leading-relaxed bg-red-50 border border-red-200 rounded-xl px-3 py-2">
              {error}
            </p>
          )}
        </div>

        {/* ── Footer ────────────────────────────────────────────────────────── */}
        {/* A post that isn't pending has no actions at all — the note in the body already says
            why, so an empty footer is the honest rendering rather than a disabled button. */}
        {isPending && (
          <div className="flex-shrink-0 px-6 py-4 border-t border-[#E8E3DA] bg-white">
            {isEditing ? (
              <div className="flex items-center gap-2">
                <button
                  onClick={handleSave}
                  disabled={!canSave}
                  className={`flex-1 py-2.5 rounded-xl text-sm font-semibold transition-colors ${
                    canSave
                      ? "bg-[#FF4800] hover:bg-[#E03E00] text-white"
                      : "bg-[#F2EDE4] text-[#C8C2BA] cursor-not-allowed"
                  }`}
                >
                  {isSaving ? "Saving…" : hasChanges ? "Save changes" : "No changes"}
                </button>
                <button
                  onClick={() => {
                    setIsEditing(false);
                    setError(null);
                  }}
                  disabled={isSaving}
                  className="px-4 py-2.5 rounded-xl text-sm font-semibold text-[#6B6561] hover:bg-[#F2EDE4] transition-colors"
                >
                  Discard
                </button>
              </div>
            ) : isConfirming ? (
              <div className="flex items-center gap-2">
                <button
                  onClick={handleCancel}
                  disabled={isCancelling}
                  className="flex-1 py-2.5 rounded-xl text-sm font-semibold bg-red-600 hover:bg-red-700 text-white transition-colors disabled:bg-red-300"
                >
                  {isCancelling ? "Cancelling…" : "Yes, cancel this post"}
                </button>
                <button
                  onClick={() => setIsConfirming(false)}
                  disabled={isCancelling}
                  className="px-4 py-2.5 rounded-xl text-sm font-semibold text-[#6B6561] hover:bg-[#F2EDE4] transition-colors"
                >
                  Keep it
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <button
                  onClick={startEditing}
                  className="flex-1 py-2.5 rounded-xl text-sm font-semibold bg-[#1B1A17] hover:bg-[#332F2A] text-white transition-colors"
                >
                  Edit post
                </button>
                <button
                  onClick={() => setIsConfirming(true)}
                  className="px-4 py-2.5 rounded-xl text-sm font-semibold border border-red-200 text-red-600 hover:bg-red-50 transition-colors"
                >
                  Cancel post
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
