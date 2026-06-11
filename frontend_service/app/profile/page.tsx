"use client";

import { useState } from "react";
import Link from "next/link";

type Section = "approval" | "stats" | "brand";
type PostStatus = "pending" | "approved" | "rejected";

// ─── Mock data ────────────────────────────────────────────────────────────────

const MOCK_POSTS = [
  {
    id: "p1",
    platform: "Instagram",
    platformColor: "bg-gradient-to-r from-purple-600 to-pink-600",
    platformBadge: "bg-pink-600",
    abbr: "IG",
    date: "Jun 9, 2026",
    status: "pending" as PostStatus,
    text: "🌿 Meet your kitchen's new best friend — the Bamboo Kitchen Collection.\n\nCrafted from 100% organic bamboo, each piece is naturally antimicrobial, carbon-negative in production, and built to last a decade. Because sustainable living shouldn't mean settling for less. 🏡",
    hashtags: ["#EcoHome", "#BambooKitchen", "#SustainableLiving", "#ZeroWaste", "#GreenHome"],
  },
  {
    id: "p2",
    platform: "LinkedIn",
    platformColor: "bg-blue-700",
    platformBadge: "bg-blue-600",
    abbr: "in",
    date: "Jun 9, 2026",
    status: "pending" as PostStatus,
    text: "The sustainable homewares market is projected to reach $150B by 2030 — and EcoHome Solutions is proud to be part of that shift.\n\nToday we're launching the Bamboo Kitchen Collection: premium products that prove sustainable materials can exceed conventional standards.",
    hashtags: [],
  },
  {
    id: "p3",
    platform: "TikTok",
    platformColor: "bg-[#1B1A17]",
    platformBadge: "bg-[#1B1A17]",
    abbr: "TK",
    date: "Jun 8, 2026",
    status: "pending" as PostStatus,
    text: "Hook: POV — you just replaced every plastic utensil in your kitchen 🎋\nBody: Bamboo is 3× stronger than steel by weight, grows back in months, and looks stunning on any countertop.\nCTA: Link in bio to shop the Bamboo Kitchen Collection.\nSound: Upbeat acoustic indie track",
    hashtags: ["#BambooLife", "#SustainableKitchen", "#EcoTok", "#GreenLiving"],
  },
  {
    id: "p4",
    platform: "X (Twitter)",
    platformColor: "bg-[#1B1A17]",
    platformBadge: "bg-[#1B1A17]",
    abbr: "X",
    date: "Jun 8, 2026",
    status: "pending" as PostStatus,
    text: "Your kitchen deserves better than plastic. 🌿\n\nThe EcoHome Bamboo Kitchen Collection — antimicrobial, carbon-negative, built to last. Shop now →",
    hashtags: ["#EcoHome", "#SustainableLiving"],
  },
  {
    id: "p5",
    platform: "Instagram",
    platformColor: "bg-gradient-to-r from-purple-600 to-pink-600",
    platformBadge: "bg-pink-600",
    abbr: "IG",
    date: "Jun 7, 2026",
    status: "pending" as PostStatus,
    text: "Small swaps, big impact. ♻️\n\nSwitch to bamboo and reduce your kitchen's plastic footprint by up to 80%. Our new collection makes it easy — and beautiful.",
    hashtags: ["#ZeroWaste", "#PlasticFree", "#EcoHome", "#BambooKitchen", "#ConsciousLiving", "#GreenHome"],
  },
];

const STATS = {
  postsCreated: 47,
  impressions: 128400,
  engagementRate: 4.2,
  approvalRate: 89,
  avgTimeToApprove: "14 min",
  topPlatform: "Instagram",
  weeklyData: [
    { day: "Mon", posts: 3, impressions: 12400 },
    { day: "Tue", posts: 7, impressions: 18900 },
    { day: "Wed", posts: 5, impressions: 14200 },
    { day: "Thu", posts: 9, impressions: 27300 },
    { day: "Fri", posts: 11, impressions: 31800 },
    { day: "Sat", posts: 6, impressions: 15600 },
    { day: "Sun", posts: 6, impressions: 8200 },
  ],
  platformBreakdown: [
    { platform: "Instagram", posts: 18, color: "bg-pink-500" },
    { platform: "LinkedIn", posts: 12, color: "bg-blue-500" },
    { platform: "TikTok", posts: 9, color: "bg-zinc-600" },
    { platform: "X (Twitter)", posts: 8, color: "bg-[#FF4800]" },
  ],
};

const DEFAULT_BRAND = {
  name: "EcoHome Solutions",
  competitors: "Grove Collaborative, Package Free Shop, Bambu",
  description:
    "We sell sustainable bamboo home products designed for eco-conscious households. Our mission is to make sustainable living accessible and beautiful.",
  demographic:
    "Eco-conscious millennials aged 25–40, primarily urban, middle-to-high income, interested in sustainability and home design.",
  tone: "Warm, aspirational, and educational — we inspire rather than hard-sell.",
  topics: "Bamboo homewares, sustainable kitchen products, zero-waste living tips, product launches.",
  avoid: "Greenwashing language, aggressive CTAs, overly technical jargon.",
  notes:
    "Always emphasise carbon-negative production and the decade-long lifespan of our products.",
};

// ─── Approval Queue ───────────────────────────────────────────────────────────

function ApprovalQueue() {
  const [posts, setPosts] = useState(MOCK_POSTS.map((p) => ({ ...p })));
  const [selected, setSelected] = useState<string | null>(null);

  function act(id: string, action: PostStatus) {
    setPosts((prev) =>
      prev.map((p) => (p.id === id ? { ...p, status: action } : p))
    );
    setSelected(null);
  }

  const selectedPost = posts.find((p) => p.id === selected);

  return (
    <div className="flex gap-5 h-full overflow-hidden">
      {/* Post list */}
      <div className="w-72 flex-shrink-0 overflow-y-auto space-y-2 pr-1">
        {posts.map((post) => (
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
            <p className="text-xs text-[#9E9893] line-clamp-2 leading-relaxed">
              {post.text.split("\n")[0]}
            </p>
            <p className="text-xs text-[#C8C2BA] mt-1.5">{post.date}</p>
          </button>
        ))}
      </div>

      {/* Post detail */}
      <div className="flex-1 min-w-0 overflow-hidden">
        {selectedPost ? (
          <div className="bg-white border border-[#E8E3DA] rounded-2xl overflow-hidden h-full flex flex-col shadow-sm">
            <div
              className={`flex items-center justify-between px-5 py-3.5 text-white ${selectedPost.platformColor}`}
            >
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

// ─── Feedback & Stats ─────────────────────────────────────────────────────────

function FeedbackStats() {
  const maxImpressions = Math.max(...STATS.weeklyData.map((d) => d.impressions));
  const maxPosts = Math.max(...STATS.weeklyData.map((d) => d.posts));
  const totalPlatformPosts = STATS.platformBreakdown.reduce((s, p) => s + p.posts, 0);

  return (
    <div className="h-full overflow-y-auto space-y-6 pb-6 pr-1">
      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "Posts Created", value: STATS.postsCreated, sub: "all time" },
          {
            label: "Total Impressions",
            value: STATS.impressions.toLocaleString(),
            sub: "all platforms",
          },
          { label: "Avg Engagement", value: `${STATS.engagementRate}%`, sub: "likes + comments" },
          { label: "Approval Rate", value: `${STATS.approvalRate}%`, sub: "of generated posts" },
        ].map((kpi) => (
          <div
            key={kpi.label}
            className="bg-white border border-[#E8E3DA] rounded-2xl p-5 shadow-sm"
          >
            <p className="text-xs text-[#9E9893] mb-1 font-medium">{kpi.label}</p>
            <p className="text-3xl font-bold text-[#1B1A17]">{kpi.value}</p>
            <p className="text-xs text-[#C8C2BA] mt-1">{kpi.sub}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Impressions timeline */}
        <div className="bg-white border border-[#E8E3DA] rounded-2xl p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-[#1B1A17] mb-5">
            Impressions — Last 7 Days
          </h3>
          <div className="flex items-end gap-2 h-32">
            {STATS.weeklyData.map((d) => (
              <div key={d.day} className="flex-1 flex flex-col items-center gap-1">
                <div
                  className="w-full bg-[#FF4800] rounded-t min-h-[4px] transition-all opacity-80"
                  style={{ height: `${(d.impressions / maxImpressions) * 100}%` }}
                />
                <span className="text-xs text-[#9E9893]">{d.day}</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-[#C8C2BA] mt-3 text-right">
            Peak:{" "}
            {Math.max(...STATS.weeklyData.map((d) => d.impressions)).toLocaleString()}{" "}
            impressions
          </p>
        </div>

        {/* Posts per day */}
        <div className="bg-white border border-[#E8E3DA] rounded-2xl p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-[#1B1A17] mb-5">
            Posts Generated — Last 7 Days
          </h3>
          <div className="flex items-end gap-2 h-32">
            {STATS.weeklyData.map((d) => (
              <div key={d.day} className="flex-1 flex flex-col items-center gap-1">
                <span className="text-xs text-[#6B6561] font-medium mb-0.5">{d.posts}</span>
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Platform breakdown */}
        <div className="bg-white border border-[#E8E3DA] rounded-2xl p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-[#1B1A17] mb-4">
            Platform Breakdown
          </h3>
          <div className="space-y-4">
            {STATS.platformBreakdown.map((p) => (
              <div key={p.platform}>
                <div className="flex justify-between text-xs mb-1.5">
                  <span className="text-[#1B1A17] font-medium">{p.platform}</span>
                  <span className="text-[#9E9893]">{p.posts} posts</span>
                </div>
                <div className="w-full bg-[#F2EDE4] rounded-full h-1.5">
                  <div
                    className={`h-1.5 rounded-full ${p.color}`}
                    style={{ width: `${(p.posts / totalPlatformPosts) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Quick stats */}
        <div className="bg-white border border-[#E8E3DA] rounded-2xl p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-[#1B1A17] mb-4">Quick Stats</h3>
          <div className="divide-y divide-[#F2EDE4]">
            {[
              { label: "Avg time to approve", value: STATS.avgTimeToApprove },
              { label: "Top performing platform", value: STATS.topPlatform },
              { label: "Posts awaiting approval", value: "5" },
              { label: "Rejected & regenerated", value: "6 posts" },
              { label: "Avg hashtags per post", value: "4.8" },
            ].map((s) => (
              <div key={s.label} className="flex justify-between py-2.5 text-sm">
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

// ─── Brand Profile ────────────────────────────────────────────────────────────

function BrandProfile() {
  const [brand, setBrand] = useState(DEFAULT_BRAND);
  const [saved, setSaved] = useState(false);

  function handleChange(field: keyof typeof DEFAULT_BRAND, value: string) {
    setBrand((prev) => ({ ...prev, [field]: value }));
    setSaved(false);
  }

  function handleSave() {
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  }

  return (
    <div className="h-full overflow-y-auto pr-1">
      <p className="text-sm text-[#6B6561] leading-relaxed mb-6">
        This information is passed to the AI as context when generating content. Keep it
        accurate to improve output quality.
      </p>

      <div className="grid grid-cols-2 gap-x-8 gap-y-6">
        {/* Row 1: Brand Name + Competitors */}
        <Field
          label="Brand Name"
          hint="Your business or brand name"
          value={brand.name}
          onChange={(v) => handleChange("name", v)}
        />
        <Field
          label="Competitors"
          hint="Comma-separated list for tone differentiation"
          value={brand.competitors}
          onChange={(v) => handleChange("competitors", v)}
        />

        {/* Row 2: Description — full width */}
        <Field
          label="Brand Description"
          hint="What you do and what makes you unique"
          value={brand.description}
          onChange={(v) => handleChange("description", v)}
          rows={3}
          span
        />

        {/* Row 3: Demographic + Tone */}
        <Field
          label="Target Demographic"
          hint="Age, interests, location — describe your ideal customer"
          value={brand.demographic}
          onChange={(v) => handleChange("demographic", v)}
          rows={3}
        />
        <Field
          label="Brand Tone"
          hint="How you speak — e.g. playful, authoritative, warm"
          value={brand.tone}
          onChange={(v) => handleChange("tone", v)}
          rows={3}
        />

        {/* Row 4: Topics + Avoid */}
        <Field
          label="Content Topics"
          hint="Products, themes, or subjects you typically post about"
          value={brand.topics}
          onChange={(v) => handleChange("topics", v)}
          rows={3}
        />
        <Field
          label="What to Avoid"
          hint="Language, themes, or formats the AI should never use"
          value={brand.avoid}
          onChange={(v) => handleChange("avoid", v)}
          rows={3}
        />

        {/* Row 5: Notes — full width */}
        <Field
          label="Additional Notes"
          hint="Any other context the AI should keep in mind"
          value={brand.notes}
          onChange={(v) => handleChange("notes", v)}
          rows={3}
          span
        />
      </div>

      <div className="flex items-center gap-3 pt-6 pb-4">
        <button
          onClick={handleSave}
          className="bg-[#FF4800] hover:bg-[#E03E00] text-white text-sm font-semibold px-6 py-2.5 rounded-lg transition-colors shadow-sm"
        >
          Save Profile
        </button>
        {saved && (
          <span className="text-sm text-green-700 bg-green-50 border border-green-200 px-3 py-1.5 rounded-lg flex items-center gap-1.5">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="M2 7l3.5 3.5 6.5-7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Saved
          </span>
        )}
      </div>
    </div>
  );
}

interface FieldProps {
  label: string;
  hint: string;
  value: string;
  onChange: (v: string) => void;
  rows?: number;
  span?: boolean;
}

function Field({ label, hint, value, onChange, rows, span }: FieldProps) {
  return (
    <div className={span ? "col-span-2" : "col-span-1"}>
      <label className="block text-sm font-semibold text-[#1B1A17] mb-1">
        {label}
      </label>
      <p className="text-xs text-[#9E9893] mb-2">{hint}</p>
      {rows ? (
        <textarea
          rows={rows}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full bg-white border border-[#E8E3DA] rounded-xl px-4 py-3 text-sm text-[#1B1A17] placeholder:text-[#C8C2BA] resize-none focus:outline-none focus:border-[#FF4800] transition-colors"
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full bg-white border border-[#E8E3DA] rounded-xl px-4 py-3 text-sm text-[#1B1A17] placeholder:text-[#C8C2BA] focus:outline-none focus:border-[#FF4800] transition-colors"
        />
      )}
    </div>
  );
}

// ─── Sidebar nav config ───────────────────────────────────────────────────────

const NAV_ITEMS = [
  {
    id: "generate" as const,
    label: "Generate",
    href: "/chat",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    id: "approval" as Section,
    label: "Approval Queue",
    badge: "5",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <rect x="2" y="2" width="12" height="12" rx="2" stroke="currentColor" strokeWidth="1.5" />
        <path d="M5 8l2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    id: "stats" as Section,
    label: "Feedback & Stats",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M2 12l3-4 3 2 3-5 3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
];

const SETTINGS_ITEMS = [
  {
    id: "brand" as Section,
    label: "Manage Brand Profile",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <circle cx="8" cy="5" r="3" stroke="currentColor" strokeWidth="1.5" />
        <path d="M2 14c0-3.314 2.686-5 6-5s6 1.686 6 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
  },
];

const SECTION_TITLES: Record<Section, string> = {
  approval: "Approval Queue",
  stats: "Feedback & Stats",
  brand: "Manage Brand Profile",
};

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ProfilePage() {
  const [active, setActive] = useState<Section>("approval");

  return (
    <div className="flex h-screen bg-[#F8F5EE] text-[#1B1A17] overflow-hidden">
      {/* Sidebar */}
      <aside className="w-64 flex-shrink-0 border-r border-[#E8E3DA] flex flex-col bg-white overflow-hidden">
        <div className="p-5 border-b border-[#E8E3DA] flex-shrink-0">
          <Link
            href="/"
            className="flex items-center gap-2 font-bold text-lg text-[#1B1A17] hover:text-[#FF4800] transition-colors"
          >
            ✦ Starlight
          </Link>
          <p className="text-xs text-[#9E9893] mt-0.5">Brand Dashboard</p>
        </div>

        <nav className="flex-1 overflow-y-auto p-3 space-y-0.5">
          {NAV_ITEMS.map((item) =>
            item.href ? (
              <Link
                key={item.id}
                href={item.href}
                className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-[#6B6561] hover:text-[#1B1A17] hover:bg-[#F2EDE4] transition-colors"
              >
                <span className="flex-shrink-0 text-[#9E9893]">{item.icon}</span>
                {item.label}
              </Link>
            ) : (
              <button
                key={item.id}
                onClick={() => setActive(item.id as Section)}
                className={`flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm transition-colors ${
                  active === item.id
                    ? "bg-[#FFF0EB] text-[#FF4800]"
                    : "text-[#6B6561] hover:text-[#1B1A17] hover:bg-[#F2EDE4]"
                }`}
              >
                <span
                  className={`flex-shrink-0 ${
                    active === item.id ? "text-[#FF4800]" : "text-[#9E9893]"
                  }`}
                >
                  {item.icon}
                </span>
                {item.label}
                {"badge" in item && item.badge && (
                  <span className="ml-auto text-xs bg-amber-50 text-amber-700 border border-amber-200 px-1.5 py-0.5 rounded-full font-medium">
                    {item.badge}
                  </span>
                )}
              </button>
            )
          )}

          <div className="pt-5 pb-1">
            <p className="px-3 text-xs font-semibold text-[#C8C2BA] uppercase tracking-wider">
              Settings
            </p>
          </div>

          {SETTINGS_ITEMS.map((item) => (
            <button
              key={item.id}
              onClick={() => setActive(item.id)}
              className={`flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm transition-colors ${
                active === item.id
                  ? "bg-[#FFF0EB] text-[#FF4800]"
                  : "text-[#6B6561] hover:text-[#1B1A17] hover:bg-[#F2EDE4]"
              }`}
            >
              <span
                className={`flex-shrink-0 ${
                  active === item.id ? "text-[#FF4800]" : "text-[#9E9893]"
                }`}
              >
                {item.icon}
              </span>
              {item.label}
            </button>
          ))}
        </nav>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <header className="flex-shrink-0 px-8 py-5 border-b border-[#E8E3DA] bg-white">
          <h1 className="text-lg font-semibold text-[#1B1A17]">
            {SECTION_TITLES[active]}
          </h1>
        </header>

        <main className="flex-1 overflow-hidden px-8 py-6">
          {active === "approval" && <ApprovalQueue />}
          {active === "stats" && <FeedbackStats />}
          {active === "brand" && <BrandProfile />}
        </main>
      </div>
    </div>
  );
}
