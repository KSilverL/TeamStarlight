import Link from "next/link";

export default function Home() {
  return (
    <div className="min-h-screen bg-zinc-950 text-white flex flex-col">
      <nav className="flex items-center justify-between px-8 py-5 border-b border-white/10">
        <span className="text-lg font-bold tracking-tight">✦ Starlight</span>
        <Link
          href="/chat"
          className="text-sm text-zinc-400 hover:text-white transition-colors"
        >
          Open App →
        </Link>
      </nav>

      <main className="flex-1 flex flex-col items-center justify-center text-center px-6 py-24">
        <div className="inline-flex items-center gap-2 bg-indigo-500/10 border border-indigo-500/20 rounded-full px-4 py-1.5 text-sm text-indigo-300 mb-8">
          <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
          Multi-agent AI · Human-in-the-loop approvals
        </div>

        <h1 className="text-5xl sm:text-6xl md:text-7xl font-bold tracking-tight mb-6 max-w-3xl leading-tight">
          Create{" "}
          <span className="bg-gradient-to-r from-indigo-400 to-violet-400 bg-clip-text text-transparent">
            brilliant content
          </span>{" "}
          for every platform
        </h1>

        <p className="text-lg text-zinc-400 max-w-xl mb-10 leading-relaxed">
          Starlight is an AI multi-agent system that generates, reviews, and refines
          social media content tailored to your brand — across X, Instagram, TikTok,
          and LinkedIn.
        </p>

        <Link
          href="/chat"
          className="inline-flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold px-8 py-3.5 rounded-full transition-colors text-base"
        >
          Start Generating
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </Link>

        <div className="flex flex-wrap items-center justify-center gap-4 mt-12 text-sm text-zinc-500">
          <span>Supports</span>
          {["X (Twitter)", "Instagram", "TikTok", "LinkedIn"].map((p) => (
            <span key={p} className="text-zinc-300 font-medium">
              {p}
            </span>
          ))}
        </div>
      </main>

      <section className="px-8 pb-24 w-full max-w-5xl mx-auto grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[
          {
            title: "Multi-Platform",
            desc: "Generate tailored content for X, Instagram, TikTok, and LinkedIn simultaneously in a single campaign.",
          },
          {
            title: "Human-in-the-Loop",
            desc: "Review and approve each draft before anything goes live. Reject to regenerate, or refine via conversation.",
          },
          {
            title: "Brand-Aware",
            desc: "Input your tone, topics, examples, and preferences — the AI adapts every draft to your brand voice.",
          },
        ].map((f) => (
          <div
            key={f.title}
            className="bg-zinc-900 border border-white/10 rounded-2xl p-6"
          >
            <h3 className="font-semibold text-white mb-2">{f.title}</h3>
            <p className="text-zinc-400 text-sm leading-relaxed">{f.desc}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
