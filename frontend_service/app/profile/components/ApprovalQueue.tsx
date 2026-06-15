"use client";

import { useState } from "react";
import { MOCK_POSTS } from "../data";
import type { PostStatus } from "../types";

/**
 * Pill badge that reflects the current approval state of a post.
 * Colour-coded: amber = pending, green = approved, red = rejected.
 */
function StatusBadge({ status }: { status: PostStatus }) {
  if (status === "approved")
    return (
      <span className="text-xs bg-green-50 text-green-700 border border-green-200 px-2 py-0.5 rounded-full font-medium whitespace-nowrap">
        Approved
      </span>
    );
  if (status === "rejected")
    return (
      <span className="text-xs bg-red-50 text-red-700 border border-red-200 px-2 py-0.5 rounded-full font-medium whitespace-nowrap">
        Rejected
      </span>
    );
  return (
    <span className="text-xs bg-amber-50 text-amber-700 border border-amber-200 px-2 py-0.5 rounded-full font-medium whitespace-nowrap">
      Pending
    </span>
  );
}

/**
 * Two-panel approval workflow:
 * - Left  (w-72): scrollable list of post summary cards.
 * - Right (flex-1): full post detail with Approve / Reject actions.
 *
 * Clicking a card that is already selected deselects it (toggling the detail panel closed).
 */
export default function ApprovalQueue() {
  // Shallow copy so local status changes don't mutate the imported MOCK_POSTS constant.
  const [posts, setPosts] = useState(MOCK_POSTS.map((p) => ({ ...p })));
  const [selected, setSelected] = useState<string | null>(null);

  /**
   * Applies an approval action to a single post by ID, then clears the selection
   * so the detail panel returns to its empty state.
   *
   * @param id     ID of the post being actioned.
   * @param action The new status to apply ("approved" or "rejected").
   */
  function act(id: string, action: PostStatus) {
    setPosts((prev) =>
      prev.map((p) => (p.id === id ? { ...p, status: action } : p)),
    );
    setSelected(null);
  }

  const selectedPost = posts.find((p) => p.id === selected);

  return (
    // Outer flex row: list on the left, detail panel on the right.
    <div className="flex gap-5 h-full overflow-hidden">
      {/* ── Post list ────────────────────────────────────────────────────── */}
      <div className="w-72 flex-shrink-0 overflow-y-auto space-y-2 pr-1">
        {posts.map((post) => (
          <button
            key={post.id}
            // Toggle selection: clicking the active card collapses the detail panel.
            onClick={() => setSelected(selected === post.id ? null : post.id)}
            className={`w-full text-left p-4 rounded-xl border transition-colors ${
              selected === post.id
                ? "bg-[#FFF0EB] border-[#FFCBB8]" // highlighted when selected
                : "bg-white border-[#E8E3DA] hover:border-[#FF4800]/40 hover:bg-[#FFFAF8] shadow-sm"
            }`}
          >
            {/* Platform badge + name + status */}
            <div className="flex items-center gap-2.5 mb-2">
              <span
                className={`w-6 h-6 rounded flex items-center justify-center text-xs font-bold flex-shrink-0 text-white ${post.platformBadge}`}
              >
                {post.abbr}
              </span>
              <span className="text-sm font-medium text-[#1B1A17] truncate flex-1">
                {post.platform}
              </span>
              <StatusBadge status={post.status} />
            </div>
            {/* Show only the first line of multi-line post copy */}
            <p className="text-xs text-[#9E9893] line-clamp-2 leading-relaxed">
              {post.text.split("\n")[0]}
            </p>
            <p className="text-xs text-[#C8C2BA] mt-1.5">{post.date}</p>
          </button>
        ))}
      </div>

      {/* ── Post detail panel ────────────────────────────────────────────── */}
      <div className="flex-1 min-w-0 overflow-hidden">
        {selectedPost ? (
          <div className="bg-white border border-[#E8E3DA] rounded-2xl overflow-hidden h-full flex flex-col shadow-sm">
            {/* Coloured platform header bar */}
            <div
              className={`flex items-center justify-between px-5 py-3.5 text-white ${selectedPost.platformColor}`}
            >
              <span className="font-semibold">{selectedPost.platform}</span>
              <span className="text-xs text-white/70">{selectedPost.date}</span>
            </div>

            {/* Scrollable post body and hashtags */}
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              <p className="text-sm text-[#1B1A17] whitespace-pre-wrap leading-relaxed">
                {selectedPost.text}
              </p>
              {selectedPost.hashtags.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {selectedPost.hashtags.map((tag) => (
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

            {/*
              Footer: action buttons for pending posts; read-only status banner
              for posts that have already been actioned.
            */}
            {selectedPost.status === "pending" ? (
              <div className="flex gap-3 px-5 pb-5 pt-2 border-t border-[#E8E3DA]">
                <button
                  onClick={() => act(selectedPost.id, "approved")}
                  className="flex-1 bg-green-600 hover:bg-green-500 text-white text-sm font-medium py-2.5 rounded-xl transition-colors"
                >
                  Approve
                </button>
                <button
                  onClick={() => act(selectedPost.id, "rejected")}
                  className="flex-1 bg-[#F2EDE4] hover:bg-[#E8E3DA] text-[#1B1A17] border border-[#E8E3DA] text-sm font-medium py-2.5 rounded-xl transition-colors"
                >
                  Reject
                </button>
              </div>
            ) : (
              // Read-only confirmation banner for already-actioned posts.
              <div className="px-5 pb-5 pt-2 border-t border-[#E8E3DA]">
                <div
                  className={`text-center py-2.5 rounded-xl text-sm font-medium ${
                    selectedPost.status === "approved"
                      ? "bg-green-50 text-green-700 border border-green-200"
                      : "bg-red-50 text-red-700 border border-red-200"
                  }`}
                >
                  {selectedPost.status === "approved" ? "Approved" : "Rejected"}
                </div>
              </div>
            )}
          </div>
        ) : (
          /* Empty state — shown when no post is selected */
          <div className="flex flex-col items-center justify-center h-full text-[#9E9893] text-sm gap-2">
            <svg
              width="40"
              height="40"
              viewBox="0 0 40 40"
              fill="none"
              aria-hidden="true"
            >
              <rect
                x="6"
                y="6"
                width="28"
                height="28"
                rx="6"
                stroke="#E8E3DA"
                strokeWidth="2"
              />
              <path
                d="M13 20l5 5 9-10"
                stroke="#E8E3DA"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            Select a post to review
          </div>
        )}
      </div>
    </div>
  );
}
