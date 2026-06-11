"use client";

import { useState } from "react";
import { DEFAULT_BRAND } from "../data";

/** Props for the reusable Field input/textarea component. */
interface FieldProps {
  label: string;
  /** Short hint displayed beneath the label to guide the user's input. */
  hint: string;
  value: string;
  onChange: (v: string) => void;
  /** When provided, renders a resizable textarea with this many visible rows instead of a single-line input. */
  rows?: number;
  /** When true, the field spans both columns of the two-column grid layout. */
  span?: boolean;
}

/**
 * Labelled form field that switches between a single-line `<input>` and a
 * multi-line `<textarea>` based on the `rows` prop. Grid column span is
 * controlled by the `span` prop so the parent grid doesn't need per-field wrappers.
 */
function Field({ label, hint, value, onChange, rows, span }: FieldProps) {
  return (
    <div className={span ? "col-span-2" : "col-span-1"}>
      <label className="block text-sm font-semibold text-[#1B1A17] mb-1">
        {label}
      </label>
      <p className="text-xs text-[#9E9893] mb-2">{hint}</p>
      {rows ? (
        <textarea
          rows={rows}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full bg-white border border-[#E8E3DA] rounded-xl px-4 py-3 text-sm text-[#1B1A17] placeholder:text-[#C8C2BA] resize-none focus:outline-none focus:border-[#FF4800] transition-colors"
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full bg-white border border-[#E8E3DA] rounded-xl px-4 py-3 text-sm text-[#1B1A17] placeholder:text-[#C8C2BA] focus:outline-none focus:border-[#FF4800] transition-colors"
        />
      )}
    </div>
  );
}

/**
 * Editable brand profile form.
 *
 * All fields are passed to the LLM service as system-level context when
 * generating social media content. Keeping this data accurate directly
 * improves output quality.
 *
 * Currently persisted only in local component state; will be wired to the
 * Spring Boot /api/brand endpoint once the backend is ready.
 */
export default function BrandProfile() {
  const [brand, setBrand] = useState(DEFAULT_BRAND);
  // Controls the transient "Saved" confirmation banner shown after saving.
  const [saved, setSaved] = useState(false);

  /**
   * Updates a single field in the brand state and clears the "Saved" banner
   * so it doesn't linger after further edits.
   *
   * @param field Key of the field being changed.
   * @param value New string value entered by the user.
   */
  function handleChange(field: keyof typeof DEFAULT_BRAND, value: string) {
    setBrand((prev) => ({ ...prev, [field]: value }));
    setSaved(false);
  }

  /**
   * Triggers the "Saved" confirmation banner and auto-dismisses it after 2.5 s.
   * In production this will dispatch a PATCH request to the brand profile API.
   */
  function handleSave() {
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  }

  return (
    <div className="h-full overflow-y-auto pr-1">
      <p className="text-sm text-[#6B6561] leading-relaxed mb-6">
        This information is passed to the AI as context when generating content.
        Keep it accurate to improve output quality.
      </p>

      {/* Two-column form grid; full-width fields use the span prop */}
      <div className="grid grid-cols-2 gap-x-8 gap-y-6">
        <Field
          label="Brand Name"
          hint="Your business or brand name"
          value={brand.name}
          onChange={(v) => handleChange("name", v)}
        />
        <Field
          label="Competitors"
          hint="Comma-separated list for tone differentiation"
          value={brand.competitors}
          onChange={(v) => handleChange("competitors", v)}
        />
        <Field
          label="Brand Description"
          hint="What you do and what makes you unique"
          value={brand.description}
          onChange={(v) => handleChange("description", v)}
          rows={3}
          span
        />
        <Field
          label="Target Demographic"
          hint="Age, interests, location — describe your ideal customer"
          value={brand.demographic}
          onChange={(v) => handleChange("demographic", v)}
          rows={3}
        />
        <Field
          label="Brand Tone"
          hint="How you speak — e.g. playful, authoritative, warm"
          value={brand.tone}
          onChange={(v) => handleChange("tone", v)}
          rows={3}
        />
        <Field
          label="Content Topics"
          hint="Products, themes, or subjects you typically post about"
          value={brand.topics}
          onChange={(v) => handleChange("topics", v)}
          rows={3}
        />
        <Field
          label="What to Avoid"
          hint="Language, themes, or formats the AI should never use"
          value={brand.avoid}
          onChange={(v) => handleChange("avoid", v)}
          rows={3}
        />
        <Field
          label="Additional Notes"
          hint="Any other context the AI should keep in mind"
          value={brand.notes}
          onChange={(v) => handleChange("notes", v)}
          rows={3}
          span
        />
      </div>

      {/* Save row with transient confirmation banner */}
      <div className="flex items-center gap-3 pt-6 pb-4">
        <button
          onClick={handleSave}
          className="bg-[#FF4800] hover:bg-[#E03E00] text-white text-sm font-semibold px-6 py-2.5 rounded-lg transition-colors shadow-sm"
        >
          Save Profile
        </button>

        {/* Confirmation banner — only visible for 2.5 s after saving */}
        {saved && (
          <span className="text-sm text-green-700 bg-green-50 border border-green-200 px-3 py-1.5 rounded-lg flex items-center gap-1.5">
            <svg
              width="14"
              height="14"
              viewBox="0 0 14 14"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M2 7l3.5 3.5 6.5-7"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            Saved
          </span>
        )}
      </div>
    </div>
  );
}
