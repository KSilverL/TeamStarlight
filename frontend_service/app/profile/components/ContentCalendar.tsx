"use client";

import { useState } from "react";
import { PLATFORM_CONFIG, SEED_SCHEDULED_POSTS } from "../data";
import type { Platform, ScheduledPost } from "../types";
import SchedulePostModal from "./SchedulePostModal";

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];
const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/**
 * Builds the flat array of day cells needed to render a calendar month grid.
 *
 * Prepends `null` entries for the blank cells before the 1st so the first real
 * day lands in the correct weekday column (0 = Sunday). Each real day carries
 * both its numeric date and a zero-padded ISO string used as a lookup key into
 * the `postsByDate` map.
 *
 * @param year  Full four-digit year.
 * @param month 0-indexed month (0 = January, 11 = December).
 * @returns Ordered array of cells; null entries represent leading blank padding.
 */
function getCalendarDays(year: number, month: number) {
  const firstDay = new Date(year, month, 1).getDay();
  // Day 0 of the next month resolves to the last day of the current month.
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const days: Array<{ date: number | null; dateStr: string | null }> = [];

  // Pad the start so day 1 falls on the correct column.
  for (let i = 0; i < firstDay; i++) days.push({ date: null, dateStr: null });

  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    days.push({ date: d, dateStr });
  }
  return days;
}

export default function ContentCalendar() {
  const [viewYear, setViewYear] = useState(2026);
  const [viewMonth, setViewMonth] = useState(5); // 5 = June (0-indexed)
  const [posts, setPosts] = useState<ScheduledPost[]>(SEED_SCHEDULED_POSTS);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);

  const days = getCalendarDays(viewYear, viewMonth);

  // Group posts by date string so each day cell can look up its posts in O(1).
  // `??=` initialises the array on first encounter then pushes to it.
  const postsByDate = posts.reduce<Record<string, ScheduledPost[]>>(
    (acc, post) => {
      (acc[post.date] ??= []).push(post);
      return acc;
    },
    {},
  );

  // Build today's ISO string for the highlight ring — compared against each cell's dateStr.
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  /**
   * Navigates to the previous month, wrapping back to December of the prior year
   * when the current month is January (index 0).
   */
  function prevMonth() {
    if (viewMonth === 0) {
      setViewMonth(11);
      setViewYear((y) => y - 1);
    } else {
      setViewMonth((m) => m - 1);
    }
  }

  /**
   * Navigates to the next month, wrapping forward to January of the next year
   * when the current month is December (index 11).
   */
  function nextMonth() {
    if (viewMonth === 11) {
      setViewMonth(0);
      setViewYear((y) => y + 1);
    } else {
      setViewMonth((m) => m + 1);
    }
  }

  // Number of rows in the grid varies by month (4–6 weeks).
  // We pass this to gridTemplateRows so every row shares the available height equally.
  const numRows = Math.ceil(days.length / 7);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* ── Month navigation ─────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <button
          onClick={prevMonth}
          className="w-8 h-8 flex items-center justify-center rounded-lg text-[#6B6561] hover:text-[#1B1A17] hover:bg-[#F2EDE4] transition-colors"
          aria-label="Previous month"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path
              d="M9 2L4 7l5 5"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
        <h2 className="text-base font-semibold text-[#1B1A17]">
          {MONTH_NAMES[viewMonth]} {viewYear}
        </h2>
        <button
          onClick={nextMonth}
          className="w-8 h-8 flex items-center justify-center rounded-lg text-[#6B6561] hover:text-[#1B1A17] hover:bg-[#F2EDE4] transition-colors"
          aria-label="Next month"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path
              d="M5 2l5 5-5 5"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </div>

      {/* ── Day-of-week column headers ────────────────────────────────────── */}
      <div className="grid grid-cols-7 gap-1.5 mb-1.5 flex-shrink-0">
        {DAY_NAMES.map((d) => (
          <div
            key={d}
            className="text-center text-xs font-semibold text-[#9E9893] py-1"
          >
            {d}
          </div>
        ))}
      </div>

      {/* ── Calendar grid ─────────────────────────────────────────────────── */}
      {/*
        gridTemplateRows is set dynamically so the rows fill the remaining flex
        space evenly regardless of whether the month spans 4, 5, or 6 weeks.
      */}
      <div
        className="grid grid-cols-7 gap-1.5 flex-1"
        style={{ gridTemplateRows: `repeat(${numRows}, 1fr)` }}
      >
        {days.map((day, i) => {
          // Padding cells — empty divs to push day 1 into the right column.
          if (!day.dateStr) return <div key={`pad-${i}`} />;

          const dayPosts = postsByDate[day.dateStr] ?? [];
          const isToday = day.dateStr === todayStr;

          return (
            <button
              key={day.dateStr}
              onClick={() => setSelectedDay(day.dateStr)}
              className={`flex flex-col items-center p-2 rounded-xl border transition-all group ${
                isToday
                  ? "border-[#FF4800] bg-[#FFF0EB]" // orange ring for today
                  : "border-[#E8E3DA] bg-white hover:border-[#FF4800]/50 hover:bg-[#FFFAF8] hover:shadow-sm"
              }`}
            >
              {/* Day number */}
              <span
                className={`text-sm font-semibold leading-none mb-1.5 ${
                  isToday
                    ? "text-[#FF4800]"
                    : "text-[#1B1A17] group-hover:text-[#FF4800]"
                }`}
              >
                {day.date}
              </span>

              {/* Platform-coloured dot for each scheduled post; capped at 4 to avoid overflow */}
              {dayPosts.length > 0 && (
                <div className="flex gap-0.5 flex-wrap justify-center">
                  {dayPosts.slice(0, 4).map((post) => (
                    <span
                      key={post.id}
                      className={`w-1.5 h-1.5 rounded-full ${PLATFORM_CONFIG[post.platform].dot}`}
                    />
                  ))}
                </div>
              )}
            </button>
          );
        })}
      </div>

      {/* ── Platform colour legend ────────────────────────────────────────── */}
      <div className="flex-shrink-0 flex items-center gap-4 pt-3 mt-1 border-t border-[#E8E3DA]">
        <span className="text-xs text-[#9E9893] font-medium">Platforms:</span>
        {(["instagram", "linkedin", "tiktok", "x"] as Platform[]).map((p) => (
          <span
            key={p}
            className="flex items-center gap-1.5 text-xs text-[#6B6561]"
          >
            <span
              className={`w-2 h-2 rounded-full ${PLATFORM_CONFIG[p].dot}`}
            />
            {/* Strip "(Twitter)" suffix for X to keep the legend compact */}
            {PLATFORM_CONFIG[p].label.split(" ")[0]}
          </span>
        ))}
      </div>

      {/* ── Schedule Post modal ───────────────────────────────────────────── */}
      {/*
        Rendered into a React portal via fixed positioning so it sits above
        the sidebar. Passing `postsByDate[selectedDay]` shows posts already
        scheduled on that day inside the left panel of the modal.
      */}
      {selectedDay && (
        <SchedulePostModal
          day={selectedDay}
          existingPosts={postsByDate[selectedDay] ?? []}
          onClose={() => setSelectedDay(null)}
          onSchedule={(post) => {
            setPosts((prev) => [...prev, post]);
            setSelectedDay(null);
          }}
        />
      )}
    </div>
  );
}
