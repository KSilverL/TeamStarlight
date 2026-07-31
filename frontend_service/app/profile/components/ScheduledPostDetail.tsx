"use client";

import { useState } from "react";
import { PLATFORM_CONFIG } from "../data";
import { formatDisplayDate } from "../format";
import type { ScheduledPost } from "../types";

interface ScheduledPostDetailProps {
  post: ScheduledPost;
  onClose: () => void;
  /** Cancels the post upstream. Rejects (or throws) if the backend refused, so this component
   * can surface the reason instead of closing on a cancel that didn't happen. */
  onCancel: (postId: string) => Promise<void>;
}

/**
 * Read-only view of one scheduled post, with the option to call it off.
 *
 * Cancelling is a two-step confirm because it is irreversible from the user's side and the
 * click target sits one tap away from the post they were only trying to read.
 */
export default function ScheduledPostDetail({
  post,
  onClose,
  onCancel,
}: ScheduledPostDetailProps) {
  const [isConfirming, setIsConfirming] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const platform = PLATFORM_CONFIG[post.platform];

  async function handleCancel() {
    setIsCancelling(true);
    setError(null);
    try {
      await onCancel(post.id);
      // The parent closes this modal and refetches on success — nothing to do here.
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel that post.");
      setIsConfirming(false);
    } finally {
      setIsCancelling(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 p-6">
      <div className="bg-[#F8F5EE] rounded-2xl shadow-2xl w-full max-w-lg flex flex-col overflow-hidden max-h-[80vh]">
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
                {platform.label}
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

          {/* Timezone is shown explicitly: the same post reads as a different wall-clock time
              to someone in another zone, so the time above is ambiguous without it. */}
          <dl className="text-xs space-y-2">
            <div className="flex justify-between gap-4">
              <dt className="text-[#9E9893]">Publishes</dt>
              <dd className="text-[#6B6561] text-right">
                {post.time} · {post.timezone}
              </dd>
            </div>
            {post.pageIds.length > 0 && (
              <div className="flex justify-between gap-4">
                <dt className="text-[#9E9893]">Facebook Page{post.pageIds.length > 1 ? "s" : ""}</dt>
                <dd className="text-[#6B6561] text-right">{post.pageIds.length}</dd>
              </div>
            )}
            <div className="flex justify-between gap-4">
              <dt className="text-[#9E9893]">Held by</dt>
              <dd className="text-[#6B6561] text-right">
                {post.nativeScheduled ? "Facebook" : "Starlight"}
              </dd>
            </div>
          </dl>

          {post.nativeScheduled && (
            <p className="text-xs text-[#9E9893] leading-relaxed">
              Facebook is holding this one and will publish it at the time above even if
              Starlight is offline. Cancelling here removes it from Facebook too.
            </p>
          )}

          {error && (
            <p className="text-xs text-red-600 leading-relaxed bg-red-50 border border-red-200 rounded-xl px-3 py-2">
              {error}
            </p>
          )}
        </div>

        {/* ── Footer ────────────────────────────────────────────────────────── */}
        <div className="flex-shrink-0 px-6 py-4 border-t border-[#E8E3DA] bg-white">
          {isConfirming ? (
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
            <button
              onClick={() => setIsConfirming(true)}
              className="w-full py-2.5 rounded-xl text-sm font-semibold border border-red-200 text-red-600 hover:bg-red-50 transition-colors"
            >
              Cancel post
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
