/**
 * Client-side mirrors of the scheduling rules the backend enforces.
 *
 * These are a courtesy, not the enforcement: Java re-checks every one of them, and the answer
 * that reaches the user on a real conflict is still Java's. Checking here just means the
 * disabled button explains itself before the round trip rather than after it — picking a time
 * that has already passed is a slip worth catching under the input, not in a red banner.
 */

/** Graph will not accept a scheduled_publish_time closer than 10 minutes out. */
const META_MIN_LEAD_MS = 10 * 60 * 1000;

/** Graph's upper bound on scheduled_publish_time is six months. */
const META_MAX_LEAD_MS = 180 * 24 * 60 * 60 * 1000;

/**
 * How far `timeZone` is ahead of UTC at `instant`, in milliseconds.
 *
 * Formatting the instant *into* the zone and reading the result back as if it were UTC gives
 * the offset without a date library, and gets DST right because Intl resolves the rule that
 * was actually in force at that moment rather than the one in force today.
 */
function zoneOffsetMs(instant: Date, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23", // plain "hour12: false" can render midnight as 24 in some engines
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(instant);

  const at = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((part) => part.type === type)?.value);

  const asIfUTC = Date.UTC(
    at("year"),
    at("month") - 1,
    at("day"),
    at("hour"),
    at("minute"),
    at("second")
  );
  return asIfUTC - instant.getTime();
}

/**
 * Turns the calendar's separate date and time controls into a moment.
 *
 * Built from the numeric parts rather than by parsing the composed "YYYY-MM-DDTHH:mm" string,
 * which some engines read as UTC — the same off-by-an-offset the backend fixed by pinning the
 * zone at the edge.
 *
 * @param timeZone the IANA zone the wall-clock time is written in. Omit for the browser's own
 *        zone, which is right when scheduling something new (the browser zone is what gets
 *        sent alongside it) and wrong when editing a post placed in a different one — an
 *        existing post keeps the zone it was scheduled in, and its 09:00 stays that zone's
 *        09:00 however far the person editing it has travelled since.
 */
export function toInstant(date: string, time: string, timeZone?: string): Date | null {
  const [year, month, day] = date.split("-").map(Number);
  const [hour, minute] = time.split(":").map(Number);
  if ([year, month, day, hour, minute].some((n) => !Number.isFinite(n))) {
    return null;
  }

  if (!timeZone) {
    return new Date(year, month - 1, day, hour, minute, 0, 0);
  }

  // Read the wall-clock as UTC first, then correct by the zone's offset. The offset is looked
  // up at that provisional instant, which is within a day of the real one — close enough that
  // it lands on the correct side of any DST transition.
  const provisional = new Date(Date.UTC(year, month - 1, day, hour, minute, 0, 0));
  return new Date(provisional.getTime() - zoneOffsetMs(provisional, timeZone));
}

interface TimeRules {
  /** True when Facebook is already holding the post, which is the only case where Graph's
   * lead-time bounds bite. A *new* post outside them isn't rejected — the backend just keeps
   * it on the sweeper instead of handing it to Facebook. */
  nativeScheduled?: boolean;
  /** The zone the wall-clock time is written in; see {@link toInstant}. */
  timeZone?: string;
}

/** Why this date/time can't be scheduled, or null if it can. */
export function describeTimeProblem(
  date: string,
  time: string,
  { nativeScheduled = false, timeZone }: TimeRules = {}
): string | null {
  const when = toInstant(date, time, timeZone);
  if (!when) {
    return "Pick a date and a time.";
  }

  const leadMs = when.getTime() - Date.now();
  if (leadMs <= 0) {
    return "That time has already passed — pick a time in the future.";
  }

  if (nativeScheduled) {
    if (leadMs < META_MIN_LEAD_MS) {
      return "Facebook is holding this post and needs at least 10 minutes' notice to move it. Pick a later time.";
    }
    if (leadMs > META_MAX_LEAD_MS) {
      return "Facebook won't hold a post more than 6 months out. Pick an earlier time.";
    }
  }

  return null;
}

/**
 * Normalises a free-text hashtag field into the array the API takes.
 *
 * Accepts whatever the user types — spaces, commas, with or without the leading # — because
 * the field sits next to copy they just pasted from, and rejecting "eco, bamboo" for missing
 * hashes would be pedantry rather than validation.
 */
export function parseHashtags(input: string): string[] {
  return input
    .split(/[\s,]+/)
    .map((tag) => tag.trim())
    .filter((tag) => tag !== "" && tag !== "#")
    .map((tag) => (tag.startsWith("#") ? tag : `#${tag}`));
}
