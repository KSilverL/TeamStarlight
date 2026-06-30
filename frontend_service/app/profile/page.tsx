// Sidebar, Nav Config & page shell
"use client";

import { useState } from "react";
import Link from "next/link";
import type { Section } from "./types";
import ApprovalQueue from "./components/ApprovalQueue";
import FeedbackStats from "./components/FeedbackStats";
import BrandProfile from "./components/BrandProfile";
import ContentCalendar from "./components/ContentCalendar";

// ── Sidebar nav config ────────────────────────────────────────────────────────

const NAV_ITEMS = [
  {
    id: "generate" as const,
    label: "Generate",
    href: "/chat",
    icon: (
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M3 8h10M9 4l4 4-4 4"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
  {
    id: "approval" as Section,
    label: "Approval Queue",
    badge: "5",
    icon: (
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
      >
        <rect
          x="2"
          y="2"
          width="12"
          height="12"
          rx="2"
          stroke="currentColor"
          strokeWidth="1.5"
        />
        <path
          d="M5 8l2 2 4-4"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
  {
    id: "calendar" as Section,
    label: "Content Calendar",
    icon: (
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
      >
        <rect
          x="2"
          y="3"
          width="12"
          height="11"
          rx="2"
          stroke="currentColor"
          strokeWidth="1.5"
        />
        <path d="M2 7h12" stroke="currentColor" strokeWidth="1.5" />
        <path
          d="M5 1v3M11 1v3"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
        <rect x="5" y="9.5" width="2" height="2" rx="0.5" fill="currentColor" />
        <rect x="9" y="9.5" width="2" height="2" rx="0.5" fill="currentColor" />
      </svg>
    ),
  },
  {
    id: "stats" as Section,
    label: "Feedback & Stats",
    icon: (
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M2 12l3-4 3 2 3-5 3 3"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
];

const SETTINGS_ITEMS = [
  {
    id: "brand" as Section,
    label: "Manage Brand Profile",
    icon: (
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
      >
        <circle cx="8" cy="5" r="3" stroke="currentColor" strokeWidth="1.5" />
        <path
          d="M2 14c0-3.314 2.686-5 6-5s6 1.686 6 5"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
];

const SECTION_TITLES: Record<Section, string> = {
  approval: "Approval Queue",
  stats: "Feedback & Stats",
  brand: "Manage Brand Profile",
  calendar: "Content Calendar",
};

// ── Page ──────────────────────────────────────────────────────────────────────

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
                <span className="flex-shrink-0 text-[#9E9893]">
                  {item.icon}
                </span>
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
                  className={`flex-shrink-0 ${active === item.id ? "text-[#FF4800]" : "text-[#9E9893]"}`}
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
            ),
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
                className={`flex-shrink-0 ${active === item.id ? "text-[#FF4800]" : "text-[#9E9893]"}`}
              >
                {item.icon}
              </span>
              {item.label}
            </button>
          ))}
        </nav>

        {/* FIX 1: Sign out button at the bottom of the sidebar. */}
        <div className="p-3 border-t border-[#E8E3DA] flex-shrink-0">
          <button
            onClick={() => {
              localStorage.removeItem("starlight_user");
              localStorage.removeItem("starlight_token");
              window.location.href = "/login";
            }}
            className="w-full text-xs text-[#9E9893] hover:text-[#FF4800] transition-colors py-2 rounded-lg hover:bg-[#FFF0EB] font-medium"
          >
            Sign out
          </button>
        </div>
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
          {active === "calendar" && <ContentCalendar />}
        </main>
      </div>
    </div>
  );
}
