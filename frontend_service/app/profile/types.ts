/** Identifies which sidebar section is currently active in the profile page. */
export type Section = "approval" | "stats" | "brand" | "calendar";

/** Lifecycle state of a post sitting in the approval queue. */
export type PostStatus = "pending" | "approved" | "rejected";

/** Supported social media platforms across the system. */
export type Platform = "instagram" | "linkedin" | "tiktok" | "x";

/** Lifecycle state of a post that has been placed on the content calendar. */
export type ScheduledPostStatus = "scheduled" | "published" | "failed";

/**
 * Represents a social media post that has been scheduled for a specific date and time.
 * Currently held in ContentCalendar's local state; intended to be persisted via
 * the Spring Boot scheduling API (Quartz) once the backend is wired up.
 */
export interface ScheduledPost {
  /** Unique identifier — timestamp-based string for mock data, UUID from API in production. */
  id: string;
  /** ISO date string, e.g. "2026-06-15". Parsed manually to avoid UTC offset issues. */
  date: string;
  /** 24-hour time string, e.g. "09:00". Displayed in the calendar dot tooltip and modal. */
  time: string;
  platform: Platform;
  /** Main body copy of the post, including any platform-specific formatting (e.g. TikTok script structure). */
  text: string;
  /** Hashtags to append; intentionally empty for LinkedIn where hashtag use is minimal. */
  hashtags: string[];
  status: ScheduledPostStatus;
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
