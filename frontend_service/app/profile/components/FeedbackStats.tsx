"use client";

import { STATS } from "../data";

/**
 * Analytics dashboard displaying KPI cards and simple CSS bar charts.
 *
 * Bar heights are normalised: each bar's height = (value / max) * 100%.
 * The max values are computed once here so every bar in a chart shares the
 * same scale, making relative differences visually accurate.
 */
export default function FeedbackStats() {
  // Normalisation denominators — the tallest bar in each chart renders at 100%.
  const maxImpressions = Math.max(
    ...STATS.weeklyData.map((d) => d.impressions),
  );
  const maxPosts = Math.max(...STATS.weeklyData.map((d) => d.posts));
  // Used to express each platform's share as a percentage-width progress bar.
  const totalPlatformPosts = STATS.platformBreakdown.reduce(
    (s, p) => s + p.posts,
    0,
  );

  return (
    <div className="h-full overflow-y-auto space-y-6 pb-6 pr-1">
      {/* ── KPI summary cards ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          {
            label: "Posts Created",
            value: STATS.postsCreated,
            sub: "all time",
          },
          {
            label: "Total Impressions",
            value: STATS.impressions.toLocaleString(),
            sub: "all platforms",
          },
          {
            label: "Avg Engagement",
            value: `${STATS.engagementRate}%`,
            sub: "likes + comments",
          },
          {
            label: "Approval Rate",
            value: `${STATS.approvalRate}%`,
            sub: "of generated posts",
          },
        ].map((kpi) => (
          <div
            key={kpi.label}
            className="bg-white border border-[#E8E3DA] rounded-2xl p-5 shadow-sm"
          >
            <p className="text-xs text-[#9E9893] mb-1 font-medium">
              {kpi.label}
            </p>
            <p className="text-3xl font-bold text-[#1B1A17]">{kpi.value}</p>
            <p className="text-xs text-[#C8C2BA] mt-1">{kpi.sub}</p>
          </div>
        ))}
      </div>

      {/* ── Weekly bar charts ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Impressions chart — bars grow upward from a shared baseline */}
        <div className="bg-white border border-[#E8E3DA] rounded-2xl p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-[#1B1A17] mb-5">
            Impressions — Last 7 Days
          </h3>
          <div className="flex items-end gap-2 h-32">
            {STATS.weeklyData.map((d) => (
              <div
                key={d.day}
                className="flex-1 flex flex-col items-center gap-1"
              >
                {/* Height is a percentage of the container; normalised against maxImpressions */}
                <div
                  className="w-full bg-[#FF4800] rounded-t min-h-[4px] transition-all opacity-80"
                  style={{
                    height: `${(d.impressions / maxImpressions) * 100}%`,
                  }}
                />
                <span className="text-xs text-[#9E9893]">{d.day}</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-[#C8C2BA] mt-3 text-right">
            Peak:{" "}
            {Math.max(
              ...STATS.weeklyData.map((d) => d.impressions),
            ).toLocaleString()}{" "}
            impressions
          </p>
        </div>

        {/* Posts-per-day chart — value labels sit above each bar */}
        <div className="bg-white border border-[#E8E3DA] rounded-2xl p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-[#1B1A17] mb-5">
            Posts Generated — Last 7 Days
          </h3>
          <div className="flex items-end gap-2 h-32">
            {STATS.weeklyData.map((d) => (
              <div
                key={d.day}
                className="flex-1 flex flex-col items-center gap-1"
              >
                <span className="text-xs text-[#6B6561] font-medium mb-0.5">
                  {d.posts}
                </span>
                {/* Height normalised against maxPosts */}
                <div
                  className="w-full bg-[#1B1A17] rounded-t min-h-[4px] transition-all opacity-70"
                  style={{ height: `${(d.posts / maxPosts) * 100}%` }}
                />
                <span className="text-xs text-[#9E9893]">{d.day}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Platform breakdown + quick stats ─────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Horizontal progress bars — width = platform share of total posts */}
        <div className="bg-white border border-[#E8E3DA] rounded-2xl p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-[#1B1A17] mb-4">
            Platform Breakdown
          </h3>
          <div className="space-y-4">
            {STATS.platformBreakdown.map((p) => (
              <div key={p.platform}>
                <div className="flex justify-between text-xs mb-1.5">
                  <span className="text-[#1B1A17] font-medium">
                    {p.platform}
                  </span>
                  <span className="text-[#9E9893]">{p.posts} posts</span>
                </div>
                <div className="w-full bg-[#F2EDE4] rounded-full h-1.5">
                  {/* Width = this platform's share of all posts across all platforms */}
                  <div
                    className={`h-1.5 rounded-full ${p.color}`}
                    style={{
                      width: `${(p.posts / totalPlatformPosts) * 100}%`,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Key/value stat rows */}
        <div className="bg-white border border-[#E8E3DA] rounded-2xl p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-[#1B1A17] mb-4">
            Quick Stats
          </h3>
          <div className="divide-y divide-[#F2EDE4]">
            {[
              { label: "Avg time to approve", value: STATS.avgTimeToApprove },
              { label: "Top performing platform", value: STATS.topPlatform },
              { label: "Posts awaiting approval", value: "5" },
              { label: "Rejected & regenerated", value: "6 posts" },
              { label: "Avg hashtags per post", value: "4.8" },
            ].map((s) => (
              <div
                key={s.label}
                className="flex justify-between py-2.5 text-sm"
              >
                <span className="text-[#6B6561]">{s.label}</span>
                <span className="text-[#1B1A17] font-semibold">{s.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
