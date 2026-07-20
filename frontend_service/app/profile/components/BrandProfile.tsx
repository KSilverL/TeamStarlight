"use client";

import { useState, useEffect } from "react";
import { DEFAULT_BRAND } from "../data";

interface FieldProps {
  label: string;
  hint: string;
  value: string;
  onChange: (v: string) => void;
  rows?: number;
  span?: boolean;
}

function Field({ label, hint, value, onChange, rows, span }: FieldProps) {
  return (
    <div className={span ? "col-span-2" : "col-span-1"}>
      <label className="block text-sm font-semibold text-[#1B1A17] mb-1">{label}</label>
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

function FileSlot({
  label, icon, accept, file, onAdd, onRemove,
}: {
  label: string;
  icon: React.ReactNode;
  accept: string;
  file: File | null;
  onAdd: (f: File) => void;
  onRemove: () => void;
}) {
  const inputId = `file-${label.replace(/\s/g, "-")}`;
  return (
    <div>
      <p className="text-xs font-semibold text-[#1B1A17] mb-2">{label}</p>
      {file ? (
        <div className="flex items-center gap-3 bg-white border border-[#E8E3DA] rounded-xl px-4 py-3">
          <span className="text-[#9E9893] flex-shrink-0">{icon}</span>
          <span className="text-sm text-[#1B1A17] truncate flex-1">{file.name}</span>
          <span className="text-xs text-green-700 bg-green-50 border border-green-200 px-2 py-0.5 rounded-full font-medium flex-shrink-0">
            ✓ Added
          </span>
          <button
            onClick={onRemove}
            className="text-[#C8C2BA] hover:text-[#FF4800] transition-colors flex-shrink-0 ml-1"
            aria-label="Remove file"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            </svg>
          </button>
        </div>
      ) : (
        <label
          htmlFor={inputId}
          className="flex flex-col items-center justify-center gap-2 bg-white border border-dashed border-[#E8E3DA] rounded-xl px-4 py-5 cursor-pointer hover:border-[#FF4800]/50 hover:bg-[#FFFAF8] transition-colors text-center"
        >
          <span className="text-[#C8C2BA]">{icon}</span>
          <span className="text-xs text-[#9E9893]">
            Click to upload <span className="text-[#FF4800] font-medium">{label}</span>
          </span>
          <input
            id={inputId}
            type="file"
            accept={accept}
            className="sr-only"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onAdd(f);
            }}
          />
        </label>
      )}
    </div>
  );
}

const PdfIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
    <rect x="3" y="2" width="14" height="16" rx="2" stroke="currentColor" strokeWidth="1.4"/>
    <path d="M7 7h6M7 10h6M7 13h4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
  </svg>
);

const PptIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
    <rect x="2" y="5" width="16" height="11" rx="2" stroke="currentColor" strokeWidth="1.4"/>
    <path d="M7 18h6M10 16v2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
    <rect x="5" y="8" width="4" height="3" rx="0.5" fill="currentColor" opacity="0.3"/>
    <path d="M11 9h3M11 11h2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
  </svg>
);

const WebIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
    <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="1.4"/>
    <path d="M10 2c0 0-3 3-3 8s3 8 3 8M10 2c0 0 3 3 3 8s-3 8-3 8M2 10h16" stroke="currentColor" strokeWidth="1.4"/>
  </svg>
);

export default function BrandProfile() {
  const [brand, setBrand] = useState(DEFAULT_BRAND);
  const [saved, setSaved] = useState(false);
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [websiteAdded, setWebsiteAdded] = useState(false);
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [pptFile, setPptFile] = useState<File | null>(null);

  // LinkedIn connect — client id/secret entry + the connect/post-OAuth status banner.
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [linkedInStatus, setLinkedInStatus] = useState<"connected" | "error" | null>(null);

  const totalSources = (websiteAdded ? 1 : 0) + (pdfFile ? 1 : 0) + (pptFile ? 1 : 0);

  // The LinkedIn OAuth round-trip redirects the browser back here with ?linkedin=connected
  // (or =error) — surface it once, then strip the param so a refresh doesn't re-show it. A
  // lazy useState initializer would avoid the extra render but reads `window` during the
  // component's first render, which mismatches the server-rendered HTML on this SSR-capable
  // (output: "standalone") app — safer to read it in an effect, client-only, after mount.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const status = params.get("linkedin");
    if (status === "connected" || status === "error") {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time client-only URL read on mount, not a state sync loop
      setLinkedInStatus(status);
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, []);

  async function handleConnectLinkedIn() {
    if (!clientId.trim() || !clientSecret.trim()) {
      setConnectError("Enter both the client ID and client secret from your LinkedIn Developer app.");
      return;
    }
    const token = localStorage.getItem("starlight_token");
    if (!token) {
      setConnectError("You need to be logged in to connect LinkedIn.");
      return;
    }

    setConnecting(true);
    setConnectError(null);
    try {
      const res = await fetch("/api/linkedin/creds", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ clientId: clientId.trim(), clientSecret: clientSecret.trim() }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        setConnectError(data.error ?? "Failed to save LinkedIn credentials.");
        setConnecting(false);
        return;
      }
      // Hand the browser a real top-level navigation so it can follow the OAuth
      // redirect chain — a fetch() here would just follow it silently and go nowhere.
      window.location.href = `/api/linkedin/connect?token=${encodeURIComponent(token)}`;
    } catch {
      setConnectError("Could not reach the backend.");
      setConnecting(false);
    }
  }

  function handleChange(field: keyof typeof DEFAULT_BRAND, value: string) {
    setBrand((prev) => ({ ...prev, [field]: value }));
    setSaved(false);
  }

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

      <div className="border border-[#E8E3DA] rounded-2xl p-5 mb-8 bg-white">
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-sm font-semibold text-[#1B1A17]">Connected Accounts</h2>
          {linkedInStatus === "connected" && (
            <span className="text-xs bg-green-50 text-green-700 border border-green-200 px-2 py-0.5 rounded-full font-medium">
              ✓ LinkedIn connected
            </span>
          )}
        </div>
        <p className="text-xs text-[#9E9893] mb-4">
          Connect a LinkedIn Developer app so approved drafts can post directly to LinkedIn.
        </p>

        {linkedInStatus === "error" && (
          <div className="mb-4 bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-xs text-red-700">
            LinkedIn connection failed. Double-check your client ID/secret and try again.
          </div>
        )}

        <div className="grid grid-cols-2 gap-4 mb-3">
          <div>
            <label className="block text-xs font-semibold text-[#1B1A17] mb-1">Client ID</label>
            <input
              type="text"
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              placeholder="From your LinkedIn Developer app"
              className="w-full bg-white border border-[#E8E3DA] rounded-xl px-4 py-2.5 text-sm text-[#1B1A17] placeholder:text-[#C8C2BA] focus:outline-none focus:border-[#FF4800] transition-colors"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-[#1B1A17] mb-1">Client Secret</label>
            <input
              type="password"
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
              placeholder="••••••••••••"
              className="w-full bg-white border border-[#E8E3DA] rounded-xl px-4 py-2.5 text-sm text-[#1B1A17] placeholder:text-[#C8C2BA] focus:outline-none focus:border-[#FF4800] transition-colors"
            />
          </div>
        </div>

        {connectError && <p className="text-xs text-red-600 mb-3">{connectError}</p>}

        <button
          onClick={handleConnectLinkedIn}
          disabled={connecting}
          className="bg-[#0A66C2] hover:bg-[#0952A0] disabled:opacity-50 text-white text-sm font-semibold px-5 py-2.5 rounded-lg transition-colors"
        >
          {connecting
            ? "Connecting…"
            : linkedInStatus === "connected"
              ? "Reconnect LinkedIn"
              : "Connect LinkedIn"}
        </button>
      </div>

      <div className="grid grid-cols-2 gap-x-8 gap-y-6 mb-8">
        <Field label="Brand Name" hint="Your business or brand name"
          value={brand.name} onChange={(v) => handleChange("name", v)} />
        <Field label="Competitors" hint="Comma-separated list for tone differentiation"
          value={brand.competitors} onChange={(v) => handleChange("competitors", v)} />
        <Field label="Brand Description" hint="What you do and what makes you unique"
          value={brand.description} onChange={(v) => handleChange("description", v)} rows={3} span />
        <Field label="Target Demographic" hint="Age, interests, location — describe your ideal customer"
          value={brand.demographic} onChange={(v) => handleChange("demographic", v)} rows={3} />
        <Field label="Brand Tone" hint="How you speak — e.g. playful, authoritative, warm"
          value={brand.tone} onChange={(v) => handleChange("tone", v)} rows={3} />
        <Field label="Content Topics" hint="Products, themes, or subjects you typically post about"
          value={brand.topics} onChange={(v) => handleChange("topics", v)} rows={3} />
        <Field label="What to Avoid" hint="Language, themes, or formats the AI should never use"
          value={brand.avoid} onChange={(v) => handleChange("avoid", v)} rows={3} />
        <Field label="Additional Notes" hint="Any other context the AI should keep in mind"
          value={brand.notes} onChange={(v) => handleChange("notes", v)} rows={3} span />
      </div>

      <div className="border-t border-[#E8E3DA] pt-6 mb-6">
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-sm font-semibold text-[#1B1A17]">Knowledge Sources</h2>
          {totalSources > 0 && (
            <span className="text-xs bg-green-50 text-green-700 border border-green-200 px-2 py-0.5 rounded-full font-medium">
              {totalSources} source{totalSources !== 1 ? "s" : ""} added
            </span>
          )}
        </div>
        <p className="text-xs text-[#9E9893] mb-4">
          Upload documents or add a website the AI will read to understand your brand.
        </p>

        <div className="mb-4">
          <p className="text-xs font-semibold text-[#1B1A17] mb-2">Website URL</p>
          {websiteAdded ? (
            <div className="flex items-center gap-3 bg-white border border-[#E8E3DA] rounded-xl px-4 py-3">
              <span className="text-[#9E9893] flex-shrink-0">{WebIcon}</span>
              <span className="text-sm text-[#1B1A17] truncate flex-1">{websiteUrl}</span>
              <span className="text-xs text-green-700 bg-green-50 border border-green-200 px-2 py-0.5 rounded-full font-medium flex-shrink-0">
                ✓ Added
              </span>
              <button
                onClick={() => { setWebsiteAdded(false); setWebsiteUrl(""); }}
                className="text-[#C8C2BA] hover:text-[#FF4800] transition-colors ml-1"
                aria-label="Remove website"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
                </svg>
              </button>
            </div>
          ) : (
            <div className="flex gap-2">
              <input
                type="url"
                placeholder="https://yourwebsite.com"
                value={websiteUrl}
                onChange={(e) => setWebsiteUrl(e.target.value)}
                className="flex-1 bg-white border border-[#E8E3DA] rounded-xl px-4 py-2.5 text-sm text-[#1B1A17] placeholder:text-[#C8C2BA] focus:outline-none focus:border-[#FF4800] transition-colors"
              />
              <button
                onClick={() => { if (websiteUrl) setWebsiteAdded(true); }}
                disabled={!websiteUrl}
                className="px-4 py-2.5 bg-[#1B1A17] text-white text-sm font-medium rounded-xl disabled:opacity-30 disabled:cursor-not-allowed hover:bg-[#333] transition-colors"
              >
                Add
              </button>
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 gap-4">
          <FileSlot
            label="PDF Document"
            icon={PdfIcon}
            accept=".pdf"
            file={pdfFile}
            onAdd={setPdfFile}
            onRemove={() => setPdfFile(null)}
          />
          <FileSlot
            label="PowerPoint Slides"
            icon={PptIcon}
            accept=".ppt,.pptx"
            file={pptFile}
            onAdd={setPptFile}
            onRemove={() => setPptFile(null)}
          />
        </div>

        {totalSources > 0 && (
          <div className="mt-4 bg-green-50 border border-green-200 rounded-xl px-4 py-3">
            <p className="text-xs font-semibold text-green-800 mb-2">
              ✓ Knowledge base will include:
            </p>
            <div className="space-y-1">
              {websiteAdded && (
                <div className="flex items-center gap-2 text-xs text-green-700">
                  <span>{WebIcon}</span>
                  <span className="truncate">{websiteUrl}</span>
                </div>
              )}
              {pdfFile && (
                <div className="flex items-center gap-2 text-xs text-green-700">
                  <span>{PdfIcon}</span>
                  <span>{pdfFile.name}</span>
                </div>
              )}
              {pptFile && (
                <div className="flex items-center gap-2 text-xs text-green-700">
                  <span>{PptIcon}</span>
                  <span>{pptFile.name}</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center gap-3 pt-2 pb-4">
        <button
          onClick={handleSave}
          className="bg-[#FF4800] hover:bg-[#E03E00] text-white text-sm font-semibold px-6 py-2.5 rounded-lg transition-colors shadow-sm"
        >
          Save Profile
        </button>
        {saved && (
          <span className="text-sm text-green-700 bg-green-50 border border-green-200 px-3 py-1.5 rounded-lg flex items-center gap-1.5">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="M2 7l3.5 3.5 6.5-7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            Saved
          </span>
        )}
      </div>
    </div>
  );
}
