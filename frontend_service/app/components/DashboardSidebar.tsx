"use client";

import Link from "next/link";
import type { Section } from "../profile/types";

/**
 * The brand dashboard's left-hand navigation.
 *
 * <p>Shared rather than owned by the profile page, because Posting Plans is a route of its own
 * (`/plans`) rather than a tab inside the profile. Without this, selecting it navigated away
 * from the dashboard entirely and the nav vanished — the user had to go back to reach anything
 * else. Now the same rail renders on both, so moving between them feels like changing tabs
 * rather than leaving.
 *
 * <p>Sections behave differently depending on where the rail is rendered, which is the whole
 * reason for `onSelectSection`. On the profile page they switch a panel in place; anywhere
 * else there is no panel to switch, so they navigate to `/profile?section=…` — the query
 * parameter that page already reads on mount.
 */

/** Every destination in the rail. `href` marks a real route; the rest are profile sections. */
interface NavEntry {
  id: Section | "generate" | "plans";
  label: string;
  href?: string;
  icon: React.ReactNode;
}

const NAV_ITEMS: NavEntry[] = [
  {
    id: "generate",
    label: "Generate",
    href: "/chat",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
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
    // Replaced the Approval Queue, which was a mock: hardcoded posts, invented safety scores,
    // no API behind it — and it was the landing tab, so every user's first screen was fake
    // data. Reviewing and approving real content happens on a plan's slots, so this points
    // there instead.
    id: "plans",
    label: "Posting Plans",
    href: "/plans",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M6 4h8M6 8h8M6 12h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="2.5" cy="4" r="1" fill="currentColor" />
        <circle cx="2.5" cy="8" r="1" fill="currentColor" />
        <circle cx="2.5" cy="12" r="1" fill="currentColor" />
      </svg>
    ),
  },
  {
    id: "calendar",
    label: "Content Calendar",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <rect x="2" y="3" width="12" height="11" rx="2" stroke="currentColor" strokeWidth="1.5" />
        <path d="M2 7h12" stroke="currentColor" strokeWidth="1.5" />
        <path d="M5 1v3M11 1v3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <rect x="5" y="9.5" width="2" height="2" rx="0.5" fill="currentColor" />
        <rect x="9" y="9.5" width="2" height="2" rx="0.5" fill="currentColor" />
      </svg>
    ),
  },
  {
    id: "stats",
    label: "Feedback & Stats",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
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

const SETTINGS_ITEMS: NavEntry[] = [
  {
    id: "brand",
    label: "Manage Brand Profile",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
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

interface DashboardSidebarProps {
  /** Which entry to highlight. `"plans"` on the plans route; a Section on the profile page. */
  active?: Section | "plans";
  /** Supplied only by the page that owns the section panels. Absent → sections navigate. */
  onSelectSection?: (section: Section) => void;
}

export default function DashboardSidebar({ active, onSelectSection }: DashboardSidebarProps) {
  function renderEntry(item: NavEntry) {
    const isActive = active === item.id;
    const iconClass = `flex-shrink-0 ${isActive ? "text-[#FF4800]" : "text-[#9E9893]"}`;
    const rowClass = `flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm transition-colors ${
      isActive
        ? "bg-[#FFF0EB] text-[#FF4800]"
        : "text-[#6B6561] hover:text-[#1B1A17] hover:bg-[#F2EDE4]"
    }`;

    // A section with nowhere to switch to in place becomes a link that carries the section in
    // the URL, so the rail works identically whichever page it is rendered on.
    const href = item.href ?? (onSelectSection ? undefined : `/profile?section=${item.id}`);

    if (href) {
      return (
        <Link key={item.id} href={href} className={rowClass}>
          <span className={iconClass}>{item.icon}</span>
          {item.label}
        </Link>
      );
    }

    return (
      <button
        key={item.id}
        onClick={() => onSelectSection?.(item.id as Section)}
        className={rowClass}
      >
        <span className={iconClass}>{item.icon}</span>
        {item.label}
      </button>
    );
  }

  return (
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
        {NAV_ITEMS.map(renderEntry)}

        <div className="pt-5 pb-1">
          <p className="px-3 text-xs font-semibold text-[#C8C2BA] uppercase tracking-wider">
            Settings
          </p>
        </div>

        {SETTINGS_ITEMS.map(renderEntry)}
      </nav>
    </aside>
  );
}
