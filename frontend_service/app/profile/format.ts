/**
 * Converts an ISO date string ("YYYY-MM-DD") to a human-readable label.
 *
 * Date parts are parsed manually rather than passing the raw string to `new Date()`
 * because the Date constructor treats "YYYY-MM-DD" as UTC midnight, which shifts
 * the displayed day by one in negative UTC-offset timezones.
 *
 * @param dateStr ISO date string, e.g. "2026-06-15"
 * @returns e.g. "Monday, June 15, 2026"
 */
export function formatDisplayDate(dateStr: string): string {
  const [year, month, day] = dateStr.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}
