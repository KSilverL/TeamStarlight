import Link from "next/link";

const FEATURES = [
  {
    title: "Multi-Platform",
    desc: "Generate tailored content for X, Instagram, TikTok, and LinkedIn simultaneously in a single campaign.",
    icon: (
      <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">
        <rect x="1" y="1" width="8" height="8" rx="2" stroke="#FF4800" strokeWidth="1.6" />
        <rect x="13" y="1" width="8" height="8" rx="2" stroke="#FF4800" strokeWidth="1.6" />
        <rect x="1" y="13" width="8" height="8" rx="2" stroke="#FF4800" strokeWidth="1.6" />
        <rect x="13" y="13" width="8" height="8" rx="2" stroke="#FF4800" strokeWidth="1.6" />
      </svg>
    ),
  },
  {
    title: "Human-in-the-Loop",
    desc: "Review and approve each draft before anything goes live. Reject to regenerate, or refine via conversation.",
    icon: (
      <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">
        <circle cx="11" cy="7" r="4" stroke="#FF4800" strokeWidth="1.6" />
        <path d="M3 19c0-4.418 3.582-7 8-7s8 2.582 8 7" stroke="#FF4800" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    title: "Brand-Aware",
    desc: "Input your tone, topics, examples, and preferences — the AI adapts every draft to your brand voice.",
    icon: (
      <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">
        <path d="M11 2l2.09 6.26L19 9.27l-5 4.73 1.18 6.86L11 17.77l-4.18 3.09L8 13.9 3 9.27l5.91-.91L11 2z" stroke="#FF4800" strokeWidth="1.6" strokeLinejoin="round" />
      </svg>
    ),
  },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-[#F8F5EE] text-[#1B1A17] flex flex-col">
      {/* Nav */}
      <nav className="sticky top-0 z-10 bg-white border-b border-[#E8E3DA] flex items-center justify-between px-8 py-4">
        <span className="text-xl font-bold tracking-tight text-[#1B1A17]">
          ✦ Starlight
        </span>
        <div className="flex items-center gap-4">
          <Link
            href="/login"
            className="text-sm font-medium text-[#6B6561] hover:text-[#1B1A17] transition-colors"
          >
            Log in
          </Link>
          <Link
            href="/signup"
            className="text-sm font-semibold bg-[#FF4800] hover:bg-[#E03E00] text-white px-4 py-2 rounded-lg transition-colors"
          >
            Sign up
          </Link>
        </div>
      </nav>

      {/* Hero */}
      <main className="flex-1 flex flex-col items-center justify-center text-center px-6 py-24">
        <div className="inline-flex items-center gap-2 bg-[#FFF0EB] border border-[#FFCBB8] rounded-full px-4 py-1.5 text-sm text-[#FF4800] font-medium mb-8">
          <span className="w-1.5 h-1.5 rounded-full bg-[#FF4800] animate-pulse" />
          Multi-agent AI · Human-in-the-loop approvals
        </div>

        <h1 className="text-5xl sm:text-6xl md:text-7xl font-bold tracking-tight mb-6 max-w-3xl leading-tight text-[#1B1A17]">
          Create{" "}
          <span className="text-[#FF4800]">brilliant content</span>{" "}
          for every platform
        </h1>

        <p className="text-lg text-[#6B6561] max-w-xl mb-10 leading-relaxed">
          Starlight is an AI multi-agent system that generates, reviews, and refines
          social media content tailored to your brand — across X, Instagram, TikTok,
          and LinkedIn.
        </p>

        <div className="flex flex-col sm:flex-row items-center gap-3">
          <Link
            href="/chat"
            className="inline-flex items-center gap-2 bg-[#FF4800] hover:bg-[#E03E00] text-white font-semibold px-8 py-3.5 rounded-lg transition-colors text-base shadow-sm"
          >
            Start Generating
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </Link>
          <Link
            href="/profile"
            className="inline-flex items-center gap-2 bg-white hover:bg-[#F2EDE4] border border-[#E8E3DA] text-[#1B1A17] font-semibold px-8 py-3.5 rounded-lg transition-colors text-base shadow-sm"
          >
            Manage Profile
          </Link>
        </div>

        <div className="flex flex-wrap items-center justify-center gap-4 mt-12 text-sm text-[#9E9893]">
          <span>Supports</span>
          {["X (Twitter)", "Instagram", "TikTok", "LinkedIn"].map((p) => (
            <span key={p} className="text-[#6B6561] font-medium">
              {p}
            </span>
          ))}
        </div>
      </main>

      {/* Feature cards */}
      <section className="px-8 pb-24 w-full max-w-5xl mx-auto grid grid-cols-1 sm:grid-cols-3 gap-5">
        {FEATURES.map((f) => (
          <div
            key={f.title}
            className="bg-white border border-[#E8E3DA] rounded-2xl p-6 shadow-sm"
          >
            <div className="w-10 h-10 rounded-xl bg-[#FFF0EB] flex items-center justify-center mb-4">
              {f.icon}
            </div>
            <h3 className="font-semibold text-[#1B1A17] mb-2">{f.title}</h3>
            <p className="text-[#6B6561] text-sm leading-relaxed">{f.desc}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
