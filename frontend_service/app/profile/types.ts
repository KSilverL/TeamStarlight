/** Identifies which sidebar section is currently active in the profile page. */
export type Section = "approval" | "stats" | "brand" | "calendar";

/** Lifecycle state of a post sitting in the approval queue. */
export type PostStatus = "pending" | "approved" | "rejected";

/** Supported social media platforms across the system. */
export type Platform = "instagram" | "facebook" | "linkedin" | "tiktok" | "x";

/**
 * The platforms a post can actually be scheduled to.
 *
 * <p>The wider `Platform` union covers what the app can draft copy for; only these two have a
 * publishing integration behind them, so the modal offers the rest as drafting targets but
 * won't let a post be queued against a platform that has nothing to publish it.
 */
export const SCHEDULABLE_PLATFORMS = ["linkedin", "facebook"] as const;
export type SchedulablePlatform = (typeof SCHEDULABLE_PLATFORMS)[number];

export function isSchedulable(platform: Platform): platform is SchedulablePlatform {
  return (SCHEDULABLE_PLATFORMS as readonly string[]).includes(platform);
}

/** Lifecycle state of a post that has been placed on the content calendar. Mirrors the
 * backend's ScheduledPostStatus; `publishing` is the transient state while a post is being
 * pushed to its platform. */
export type ScheduledPostStatus =
  | "scheduled"
  | "publishing"
  | "published"
  | "failed"
  | "cancelled";

/**
 * A post queued to publish at a specific date and time, as returned by `/api/schedule/posts`.
 *
 * `date`/`time` are resolved server-side into the timezone the post was scheduled in, rather
 * than derived in the browser from `scheduledAt` — otherwise a viewer in another timezone would
 * see the post on a different day than the one it was placed on.
 */
export interface ScheduledPost {
  /** Row id from the backend. */
  id: string;
  /** ISO date string, e.g. "2026-06-15", in the post's own timezone. */
  date: string;
  /** 24-hour time string, e.g. "09:00", in the post's own timezone. */
  time: string;
  /** The unambiguous publish moment, ISO-8601 with offset. */
  scheduledAt: string;
  /** IANA zone the time above was chosen in, e.g. "Europe/Dublin". */
  timezone: string;
  platform: Platform;
  /** Main body copy of the post, including any platform-specific formatting (e.g. TikTok script structure). */
  text: string;
  /** Hashtags to append; intentionally empty for LinkedIn where hashtag use is minimal. */
  hashtags: string[];
  status: ScheduledPostStatus;
  /** Facebook Page ids this publishes to. Empty for other platforms. */
  pageIds: number[];
  /** True when the platform is holding the schedule itself (Facebook) rather than our sweeper. */
  nativeScheduled: boolean;
  /** Why the last publish attempt failed. Present on `failed` posts. */
  lastError?: string | null;
}

/**
 * A single turn in the SchedulePostModal inline chat interface.
 *
 * Assistant messages that carry an AI-generated post draft include `draftData` so
 * the "Use this content" button can extract structured copy and hashtags separately
 * from the rendered message text. This field is absent on the greeting message and
 * all user messages.
 */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  /** Only present on AI response messages that contain a generated draft. */
  draftData?: { text: string; hashtags: string[] };
}
