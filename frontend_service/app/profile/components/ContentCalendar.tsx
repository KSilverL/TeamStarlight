"use client";

import { useCallback, useEffect, useState } from "react";
import { PLATFORM_CONFIG } from "../data";
import type { Platform, ScheduledPost, ScheduledPostStatus } from "../types";
import SchedulePostModal from "./SchedulePostModal";
import ScheduledPostDetail from "./ScheduledPostDetail";
import type { ScheduledPostPatch } from "./ScheduledPostDetail";

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

/** Platforms that get their own dot colour in the legend — the ones that can be scheduled. */
const LEGEND_PLATFORMS: Platform[] = ["linkedin", "facebook"];

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

/** Zero-pads a month/day for the ISO range the list endpoint expects. */
function isoDate(year: number, month: number, day: number) {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** The API's snake_case payload, mapped onto the camelCase shape the components use. */
type ApiScheduledPost = {
  id: string;
  platform: Platform;
  date: string;
  time: string;
  scheduled_at: string;
  timezone: string;
  message: string;
  hashtags: string[] | null;
  page_ids: number[] | null;
  status: ScheduledPostStatus;
  native_scheduled: boolean;
  last_error: string | null;
};

function toScheduledPost(post: ApiScheduledPost): ScheduledPost {
  return {
    id: post.id,
    date: post.date,
    time: post.time,
    scheduledAt: post.scheduled_at,
    timezone: post.timezone,
    platform: post.platform,
    text: post.message,
    hashtags: post.hashtags ?? [],
    status: post.status,
    pageIds: post.page_ids ?? [],
    nativeScheduled: post.native_scheduled,
    lastError: post.last_error,
  };
}

/** How many post chips fit in a day cell before the rest collapse into a "+N more" link. */
const CHIPS_PER_CELL = 2;

export default function ContentCalendar() {
  const today = new Date();
  const [viewYear, setViewYear] = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth());
  const [posts, setPosts] = useState<ScheduledPost[]>([]);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [selectedPost, setSelectedPost] = useState<ScheduledPost | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const days = getCalendarDays(viewYear, viewMonth);

  /**
   * Loads the visible month from the backend.
   *
   * The range is sent with the browser's timezone so the server resolves the day boundaries
   * the same way the grid draws them — without it, a post late on the last day of the month
   * can fall outside the range and vanish from the view it belongs to.
   */
  const loadMonth = useCallback(async (signal?: AbortSignal) => {
    const token = localStorage.getItem("starlight_token");
    if (!token) {
      setIsLoading(false);
      setError("Log in to see your content calendar.");
      return;
    }

    setIsLoading(true);
    setError(null);

    const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
    const params = new URLSearchParams({
      from: isoDate(viewYear, viewMonth, 1),
      to: isoDate(viewYear, viewMonth, daysInMonth),
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    });

    try {
      const res = await fetch(`/api/schedule/posts?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
        signal,
      });
      const data = await res.json();

      if (!res.ok || data.error) {
        setError(data.error ?? "Could not load your scheduled posts.");
        setPosts([]);
        return;
      }
      setPosts((data.posts ?? []).map(toScheduledPost));
    } catch (err) {
      // An abort means the user moved to another month before this landed — its result is no
      // longer wanted, and reporting it would flash a spurious error over the new view.
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError("Could not reach the backend.");
      setPosts([]);
    } finally {
      if (!signal?.aborted) setIsLoading(false);
    }
  }, [viewYear, viewMonth]);

  useEffect(() => {
    // Aborting on month change keeps a slow earlier request from resolving after a later one
    // and repainting the grid with the wrong month's posts.
    const controller = new AbortController();
    /* eslint-disable-next-line react-hooks/set-state-in-effect -- loading the visible month IS
       synchronising with an external system; the setState is the request's own pending flag. */
    loadMonth(controller.signal);
    return () => controller.abort();
  }, [loadMonth]);

  // Group posts by date string so each day cell can look up its posts in O(1).
  // `??=` initialises the array on first encounter then pushes to it.
  //
  // Pending and failed posts are shown; published and cancelled rows stay in the backend as an
  // audit record but would otherwise accumulate in the grid until the month was mostly history
  // — the calendar is for what's coming, not what happened. Failures are the exception: the
  // business is emailed about them, but a post that silently disappeared from the day it was
  // meant to go out is exactly the state that looks like the schedule losing work.
  const postsByDate = posts
    .filter((post) => post.status === "scheduled" || post.status === "failed")
    .reduce<Record<string, ScheduledPost[]>>((acc, post) => {
      (acc[post.date] ??= []).push(post);
      return acc;
    }, {});

  const hasFailures = posts.some((post) => post.status === "failed");

  // Build today's ISO string for the highlight ring — compared against each cell's dateStr.
  const todayStr = isoDate(today.getFullYear(), today.getMonth(), today.getDate());

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

  /**
   * Cancels a post and refreshes the month.
   *
   * Refetching rather than splicing the row out locally is deliberate: for a Facebook post the
   * backend also has to delete the schedule Graph is holding, and if that fails the post is
   * still going out — so the calendar shows whatever the server ended up with, not what the
   * click hoped for.
   */
  async function cancelPost(postId: string) {
    const token = localStorage.getItem("starlight_token");
    if (!token) {
      throw new Error("Log in again before cancelling a post.");
    }

    let res: Response;
    try {
      res = await fetch(`/api/schedule/posts/${postId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch {
      throw new Error("Could not reach the backend.");
    }

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      // Thrown rather than set on the calendar's own error banner so the detail modal can show
      // it in place — the modal stays open, and the user sees why next to the post it refers to.
      throw new Error(data.error ?? "Could not cancel that post.");
    }

    setSelectedPost(null);
    await loadMonth();
  }

  /**
   * Applies an edit and refreshes the month.
   *
   * Refetched rather than merged locally for the same reason as a cancel, and one more: an
   * edited date moves the post to another cell — or out of the visible month entirely — and
   * only the server knows the wall-clock time the new instant resolves back to in the post's
   * own timezone.
   */
  async function updatePost(postId: string, patch: ScheduledPostPatch) {
    const token = localStorage.getItem("starlight_token");
    if (!token) {
      throw new Error("Log in again before editing a post.");
    }

    let res: Response;
    try {
      res = await fetch(`/api/schedule/posts/${postId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(patch),
      });
    } catch {
      throw new Error("Could not reach the backend.");
    }

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      // Thrown so the detail modal keeps the user's edits on screen next to the reason it was
      // refused — a Facebook post whose new time Graph won't take is a fixable mistake, and
      // closing the modal would throw away the copy they just rewrote along with it.
      throw new Error(data.error ?? "Could not save those changes.");
    }

    setSelectedPost(null);
    await loadMonth();
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
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold text-[#1B1A17]">
            {MONTH_NAMES[viewMonth]} {viewYear}
          </h2>
          {isLoading && (
            <span className="text-xs text-[#9E9893]">loading…</span>
          )}
        </div>
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

      {/* Load/cancel failures — shown inline rather than swallowed, so an expired session or a
          backend that's down doesn't just render as an empty month. */}
      {error && (
        <div className="flex-shrink-0 mb-3 px-3 py-2 rounded-xl bg-red-50 border border-red-200 flex items-start justify-between gap-3">
          <p className="text-xs text-red-700 leading-relaxed">{error}</p>
          <button
            onClick={() => loadMonth()}
            className="text-xs font-semibold text-red-700 hover:text-red-900 flex-shrink-0"
          >
            Retry
          </button>
        </div>
      )}

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

          const dateStr = day.dateStr;
          const dayPosts = postsByDate[dateStr] ?? [];
          const isToday = dateStr === todayStr;
          const overflow = dayPosts.length - CHIPS_PER_CELL;

          // The cell is a div, not a button: the post chips inside are themselves buttons, and
          // nesting interactive elements is invalid and breaks keyboard navigation. The day
          // number carries the "schedule here" action instead.
          return (
            <div
              key={dateStr}
              className={`flex flex-col p-1.5 rounded-xl border transition-all group overflow-hidden ${
                isToday
                  ? "border-[#FF4800] bg-[#FFF0EB]" // orange ring for today
                  : "border-[#E8E3DA] bg-white hover:border-[#FF4800]/50 hover:shadow-sm"
              }`}
            >
              {/* Day number — click anywhere on this row to schedule something new. */}
              <button
                onClick={() => setSelectedDay(dateStr)}
                title={`Schedule a post on ${dateStr}`}
                className={`text-sm font-semibold leading-none py-0.5 rounded-md transition-colors ${
                  isToday
                    ? "text-[#FF4800]"
                    : "text-[#1B1A17] group-hover:text-[#FF4800]"
                }`}
              >
                {day.date}
              </button>

              {/* Scheduled posts, most imminent first — each opens its own detail view. */}
              <div className="flex-1 flex flex-col gap-0.5 mt-1 min-h-0 w-full">
                {dayPosts.slice(0, CHIPS_PER_CELL).map((post) => {
                  // A failure is drawn in red rather than its platform colour: the point of the
                  // chip is no longer "a LinkedIn post goes out here", it's "something that was
                  // meant to go out here didn't", and the detail view carries the reason.
                  const failed = post.status === "failed";
                  return (
                    <button
                      key={post.id}
                      onClick={() => setSelectedPost(post)}
                      title={
                        failed
                          ? `${post.time} · ${PLATFORM_CONFIG[post.platform].label} — did not publish, click for the reason`
                          : `${post.time} · ${PLATFORM_CONFIG[post.platform].label} — click to view`
                      }
                      className={`flex items-center gap-1 px-1 py-0.5 rounded-md border transition-colors w-full overflow-hidden ${
                        failed
                          ? "bg-red-50 border-red-200 hover:bg-red-100"
                          : "bg-[#F8F5EE] border-transparent hover:bg-[#FFE4D9] hover:border-[#FFCBB8]"
                      }`}
                    >
                      <span
                        className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                          failed ? "bg-red-500" : PLATFORM_CONFIG[post.platform].dot
                        }`}
                      />
                      <span
                        className={`text-[10px] font-medium truncate ${
                          failed ? "text-red-700" : "text-[#6B6561]"
                        }`}
                      >
                        {post.time}
                      </span>
                    </button>
                  );
                })}

                {/* The day modal lists the rest in full, each row clickable through to detail. */}
                {overflow > 0 && (
                  <button
                    onClick={() => setSelectedDay(dateStr)}
                    className="text-[10px] font-medium text-[#9E9893] hover:text-[#FF4800] transition-colors text-left px-1"
                  >
                    +{overflow} more
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Legend ────────────────────────────────────────────────────────── */}
      {/* Published and cancelled posts are never drawn, so the legend is the two platforms plus
          the one other state that reaches the grid — and that entry only appears when there is
          actually a failure to explain. */}
      <div className="flex-shrink-0 flex items-center gap-4 pt-3 mt-1 border-t border-[#E8E3DA] flex-wrap">
        <span className="text-xs text-[#9E9893] font-medium">Upcoming posts:</span>
        {LEGEND_PLATFORMS.map((p) => (
          <span
            key={p}
            className="flex items-center gap-1.5 text-xs text-[#6B6561]"
          >
            <span
              className={`w-2 h-2 rounded-full ${PLATFORM_CONFIG[p].dot}`}
            />
            {PLATFORM_CONFIG[p].label}
          </span>
        ))}
        {hasFailures && (
          <span className="flex items-center gap-1.5 text-xs text-red-700">
            <span className="w-2 h-2 rounded-full bg-red-500" />
            Didn&apos;t publish
          </span>
        )}
        <span className="text-xs text-[#C8C2BA] ml-auto">
          Click a date to schedule · click a post to view it
        </span>
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
          // Hands off rather than stacking a second modal on the first — the day view closes
          // and the post opens in its place, so there's only ever one dialog on screen.
          onOpenPost={(post) => {
            setSelectedDay(null);
            setSelectedPost(post);
          }}
          onScheduled={async () => {
            setSelectedDay(null);
            await loadMonth();
          }}
        />
      )}

      {/* ── Post detail ───────────────────────────────────────────────────── */}
      {selectedPost && (
        <ScheduledPostDetail
          post={selectedPost}
          onClose={() => setSelectedPost(null)}
          onCancel={cancelPost}
          onUpdate={updatePost}
        />
      )}
    </div>
  );
}
