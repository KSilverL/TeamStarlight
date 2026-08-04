/**
 * The Facebook Page selection made in the Brand Profile.
 *
 * BrandProfile writes the chosen ids and their names as two parallel arrays in localStorage;
 * every surface that publishes or schedules to Facebook reads them back from here rather than
 * re-parsing that pair itself. Keeping the read in one place means a post scheduled from the
 * calendar targets exactly the Pages the chat and the plan handoff use.
 */

const IDS_KEY = "starlight_meta_page_ids";
const NAMES_KEY = "starlight_meta_page_names";

export interface MetaPage {
  id: number;
  /** The Page's name, or its id as a string when the stored names have drifted out of step. */
  name: string;
}

/**
 * Reads the selected Pages, pairing each id with its name.
 *
 * The two arrays are written together but read defensively: a build that predates the names
 * key, a half-cleared storage, or hand-edited JSON would otherwise mismatch and label a Page
 * with another Page's name — worse than showing the bare id, because it is confidently wrong.
 */
export function getSelectedMetaPages(): MetaPage[] {
  if (typeof window === "undefined") return [];

  try {
    const rawIds = JSON.parse(localStorage.getItem(IDS_KEY) || "[]");
    if (!Array.isArray(rawIds)) return [];

    const ids = rawIds.map(Number).filter((n) => Number.isFinite(n));

    const rawNames = JSON.parse(localStorage.getItem(NAMES_KEY) || "[]");
    const names =
      Array.isArray(rawNames) && rawNames.length === ids.length ? rawNames : null;

    return ids.map((id, i) => ({
      id,
      name: names ? String(names[i]) : String(id),
    }));
  } catch {
    // Corrupt or absent selection — treat it as "nothing picked" so the caller shows its
    // "pick a Page first" hint rather than crashing the modal it sits in.
    return [];
  }
}

/** Names for a set of Page ids stored on a post, for the read-only views. Ids the current
 * selection no longer covers fall back to the id, which is still enough to identify them. */
export function namesForPageIds(pageIds: number[]): string[] {
  const selected = getSelectedMetaPages();
  return pageIds.map(
    (id) => selected.find((page) => page.id === id)?.name ?? String(id)
  );
}
