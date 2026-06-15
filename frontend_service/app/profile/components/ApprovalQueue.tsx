"use client";

import { useState } from "react";
import { MOCK_POSTS } from "../data";
import type { PostStatus } from "../types";

// Mock safety data - will be replaced with real Safety Agent output later
const SAFETY_SCORES: Record<string, {
  score: number;
  risk: "Low" | "Medium" | "High";
  brandAlignment: number;
  compliance: "Passed" | "Review needed";
  flags: string[];
}> = {
  "p1": { score: 98, risk: "Low", brandAlignment: 94, compliance: "Passed", flags: [] },
  "p2": { score: 85, risk: "Medium", brandAlignment: 78, compliance: "Passed", flags: ["Competitor name mentioned"] },
  "p3": { score: 91, risk: "Low", brandAlignment: 88, compliance: "Passed", flags: [] },
  "p4": { score: 72, risk: "High", brandAlignment: 58, compliance: "Review needed", flags: ["Potentially misleading claim detected", "Tone mismatch with brand profile"] },
  "p5": { score: 96, risk: "Low", brandAlignment: 93, compliance: "Passed", flags: [] },
};

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

function SafetyPanel({ postId }: { postId: string }) {
  const safety = SAFETY_SCORES[postId] ?? {
    score: 95, risk: "Low", brandAlignment: 90, compliance: "Passed", flags: []
  };

  const scoreColor =
    safety.score >= 90 ? "text-green-700" :
    safety.score >= 75 ? "text-amber-700" : "text-red-700";

  const scoreBg =
    safety.score >= 90 ? "bg-green-50 border-green-200" :
    safety.score >= 75 ? "bg-amber-50 border-amber-200" : "bg-red-50 border-red-200";

  const riskColor =
    safety.risk === "Low" ? "text-green-700" :
    safety.risk === "Medium" ? "text-amber-700" : "text-red-700";

  return (
    <div className="border border-[#E8E3DA] rounded-xl p-4 bg-[#FAFAF8]">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-1.5">
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
            <path d="M6.5 1L2 3v3.5C2 9.6 3.9 11.9 6.5 12.5 9.1 11.9 11 9.6 11 6.5V3L6.5 1z"
              stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"
              className="text-[#9E9893]" />
          </svg>
          <span className="text-xs font-semibold text-[#6B6561] uppercase tracking-wider">
            Safety Check
          </span>
        </div>
        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${scoreBg} ${scoreColor}`}>
          {safety.score}/100
        </span>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-3">
        <div>
          <p className="text-xs text-[#9E9893] mb-0.5">Risk level</p>
          <p className={`text-sm font-semibold ${riskColor}`}>{safety.risk}</p>
        </div>
        <div>
          <p className="text-xs text-[#9E9893] mb-0.5">Brand alignment</p>
          <p className="text-sm font-semibold text-[#1B1A17]">{safety.brandAlignment}%</p>
        </div>
        <div>
          <p className="text-xs text-[#9E9893] mb-0.5">Compliance</p>
          <p className={`text-sm font-semibold ${
            safety.compliance === "Passed" ? "text-green-700" : "text-amber-700"
          }`}>{safety.compliance}</p>
        </div>
      </div>

      {safety.flags.length > 0 ? (
        <div className="space-y-1.5">
          {safety.flags.map((flag, i) => (
            <div key={i} className="flex items-start gap-1.5 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1.5">
              <span className="mt-px flex-shrink-0">⚠</span>
              <span>{flag}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="flex items-center gap-1.5 text-xs text-green-700">
          <span>✓</span>
          <span>No issues detected</span>
        </div>
      )}
    </div>
  );
}

type FilterTab = "all" | PostStatus;

function FilterTabs({
  active, onChange, counts
}: {
  active: FilterTab;
  onChange: (t: FilterTab) => void;
  counts: Record<FilterTab, number>;
}) {
  const tabs: { id: FilterTab; label: string }[] = [
    { id: "all", label: "All" },
    { id: "pending", label: "Pending" },
    { id: "approved", label: "Approved" },
    { id: "rejected", label: "Rejected" },
  ];

  return (
    <div className="flex gap-1 mb-3 bg-[#F2EDE4] rounded-lg p-1">
      {tabs.map(tab => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={`flex-1 flex items-center justify-center gap-1.5 text-xs font-medium py-1.5 rounded-md transition-colors ${
            active === tab.id
              ? "bg-white text-[#1B1A17] shadow-sm"
              : "text-[#6B6561] hover:text-[#1B1A17]"
          }`}
        >
          {tab.label}
          {counts[tab.id] > 0 && (
            <span className={`text-xs px-1.5 py-0.5 rounded-full font-semibold ${
              tab.id === "pending"
                ? "bg-amber-100 text-amber-700"
                : active === tab.id
                ? "bg-[#F2EDE4] text-[#6B6561]"
                : "bg-white text-[#6B6561]"
            }`}>
              {counts[tab.id]}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

export default function ApprovalQueue() {
  const [posts, setPosts] = useState(MOCK_POSTS.map((p) => ({ ...p })));
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterTab>("all");

  function act(id: string, action: PostStatus) {
    setPosts((prev) =>
      prev.map((p) => (p.id === id ? { ...p, status: action } : p))
    );
    setSelected(null);
  }

  function regenerate(id: string) {
    setPosts((prev) =>
      prev.map((p) => (p.id === id ? { ...p, status: "pending" } : p))
    );
    setSelected(null);
  }

  const counts: Record<FilterTab, number> = {
    all: posts.length,
    pending: posts.filter(p => p.status === "pending").length,
    approved: posts.filter(p => p.status === "approved").length,
    rejected: posts.filter(p => p.status === "rejected").length,
  };

  const filtered = filter === "all" ? posts : posts.filter(p => p.status === filter);
  const selectedPost = posts.find((p) => p.id === selected);
  const pendingCount = counts.pending;

  return (
    <div className="flex gap-5 h-full overflow-hidden">
      <div className="w-72 flex-shrink-0 flex flex-col overflow-hidden">
        {pendingCount > 0 ? (
          <div className="flex items-center gap-2 mb-3 px-1">
            <span className="w-2 h-2 rounded-full bg-amber-400 flex-shrink-0" />
            <span className="text-xs text-[#6B6561]">
              <span className="font-semibold text-[#1B1A17]">{pendingCount}</span>
              {" "}post{pendingCount !== 1 ? "s" : ""} waiting for review
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-2 mb-3 px-1">
            <span className="w-2 h-2 rounded-full bg-green-400 flex-shrink-0" />
            <span className="text-xs text-green-700 font-medium">All posts reviewed</span>
          </div>
        )}

        <FilterTabs active={filter} onChange={setFilter} counts={counts} />

        <div className="flex-1 overflow-y-auto space-y-2 pr-1">
          {filtered.length === 0 && (
            <div className="text-center py-8 text-xs text-[#9E9893]">
              No {filter} posts
            </div>
          )}
          {filtered.map((post) => (
            <button
              key={post.id}
              onClick={() => setSelected(selected === post.id ? null : post.id)}
              className={`w-full text-left p-4 rounded-xl border transition-colors ${
                selected === post.id
                  ? "bg-[#FFF0EB] border-[#FFCBB8]"
                  : "bg-white border-[#E8E3DA] hover:border-[#FF4800]/40 hover:bg-[#FFFAF8] shadow-sm"
              }`}
            >
              <div className="flex items-center gap-2.5 mb-2">
                <span className={`w-6 h-6 rounded flex items-center justify-center text-xs font-bold flex-shrink-0 text-white ${post.platformBadge}`}>
                  {post.abbr}
                </span>
                <span className="text-sm font-medium text-[#1B1A17] truncate flex-1">
                  {post.platform}
                </span>
                <StatusBadge status={post.status} />
              </div>
              <p className="text-xs text-[#9E9893] line-clamp-2 leading-relaxed">
                {post.text.split("\n")[0]}
              </p>
              <div className="flex items-center justify-between mt-1.5">
                <p className="text-xs text-[#C8C2BA]">{post.date}</p>
                {SAFETY_SCORES[post.id] && (
                  <span className={`text-xs font-medium ${
                    SAFETY_SCORES[post.id].score >= 90 ? "text-green-600" :
                    SAFETY_SCORES[post.id].score >= 75 ? "text-amber-600" : "text-red-600"
                  }`}>
                    Safety {SAFETY_SCORES[post.id].score}/100
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 min-w-0 overflow-hidden">
        {selectedPost ? (
          <div className="bg-white border border-[#E8E3DA] rounded-2xl overflow-hidden h-full flex flex-col shadow-sm">
            <div className={`flex items-center justify-between px-5 py-3.5 text-white ${selectedPost.platformColor}`}>
              <span className="font-semibold">{selectedPost.platform}</span>
              <span className="text-xs text-white/70">{selectedPost.date}</span>
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              <p className="text-sm text-[#1B1A17] whitespace-pre-wrap leading-relaxed">
                {selectedPost.text}
              </p>
              {selectedPost.hashtags.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {selectedPost.hashtags.map((tag) => (
                    <span key={tag} className="text-xs text-[#FF4800] bg-[#FFF0EB] border border-[#FFCBB8] px-2 py-0.5 rounded-full">
                      {tag}
                    </span>
                  ))}
                </div>
              )}
              <SafetyPanel postId={selectedPost.id} />
            </div>

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
              <div className="px-5 pb-5 pt-2 border-t border-[#E8E3DA] space-y-2">
                <div className={`text-center py-2.5 rounded-xl text-sm font-medium ${
                  selectedPost.status === "approved"
                    ? "bg-green-50 text-green-700 border border-green-200"
                    : "bg-red-50 text-red-700 border border-red-200"
                }`}>
                  {selectedPost.status === "approved" ? "✓ Approved" : "✕ Rejected"}
                </div>
                {selectedPost.status === "rejected" && (
                  <button
                    onClick={() => regenerate(selectedPost.id)}
                    className="w-full bg-[#FFF0EB] hover:bg-[#FFE0D0] text-[#FF4800] border border-[#FFCBB8] text-sm font-medium py-2.5 rounded-xl transition-colors"
                  >
                    ↺ Regenerate post
                  </button>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-[#9E9893] text-sm gap-2">
            <svg width="40" height="40" viewBox="0 0 40 40" fill="none" aria-hidden="true">
              <rect x="6" y="6" width="28" height="28" rx="6" stroke="#E8E3DA" strokeWidth="2" />
              <path d="M13 20l5 5 9-10" stroke="#E8E3DA" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Select a post to review
          </div>
        )}
      </div>
    </div>
  );
}
