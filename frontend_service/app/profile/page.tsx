// Sidebar, Nav Config & page shell
"use client";

import { useState, useEffect } from "react";
import type { Section } from "./types";
import DashboardSidebar from "../components/DashboardSidebar";
import FeedbackStats from "./components/FeedbackStats";
import BrandProfile from "./components/BrandProfile";
import ContentCalendar from "./components/ContentCalendar";

// ─── Sidebar nav config ───────────────────────────────────────────────────────

const SECTION_TITLES: Record<Section, string> = {
  stats: "Feedback & Stats",
  brand: "Manage Brand Profile",
  calendar: "Content Calendar",
};

// ─── Page ─────────────────────────────────────────────────────────────────────

/** The sections a ?section= link is allowed to name — guards against putting an arbitrary
 * query value into state and rendering nothing at all. */
const SECTIONS: Section[] = ["stats", "brand", "calendar"];

/**
 * Which tab a link into this page is asking for, or null to keep the default.
 *
 * <p>Two callers, one answer. The LinkedIn and Facebook OAuth round-trips come back with
 * ?linkedin= / ?meta= connected|error, and the banner reporting that result lives on Brand
 * Profile — landing on the default tab would hide the very thing the user just did. ?section=
 * serves plain links from elsewhere in the app (the plans page points at ?section=calendar once
 * a slot is scheduled), so following one arrives where it said it would rather than a tab away.
 */
function requestedSection(search: string): Section | null {
  const params = new URLSearchParams(search);
  if (params.get("linkedin") || params.get("meta")) {
    return "brand";
  }
  const section = params.get("section");
  return SECTIONS.includes(section as Section) ? (section as Section) : null;
}

export default function ProfilePage() {
  // The calendar is the landing tab now that the Approval Queue is gone — it is the one view
  // that answers "what is my content doing?" from real data.
  const [active, setActive] = useState<Section>("calendar");

  useEffect(() => {
    const target = requestedSection(window.location.search);
    if (target) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time client-only URL read on mount, not a state sync loop
      setActive(target);
    }
  }, []);

  return (
    <div className="flex h-screen bg-[#F8F5EE] text-[#1B1A17] overflow-hidden">
      <DashboardSidebar active={active} onSelectSection={setActive} />

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <header className="flex-shrink-0 px-8 py-5 border-b border-[#E8E3DA] bg-white">
          <h1 className="text-lg font-semibold text-[#1B1A17]">
            {SECTION_TITLES[active]}
          </h1>
        </header>

        <main className="flex-1 overflow-hidden px-8 py-6">
          {active === "stats" && <FeedbackStats />}
          {active === "brand" && <BrandProfile />}
          {active === "calendar" && <ContentCalendar />}
        </main>
      </div>
    </div>
  );
}
