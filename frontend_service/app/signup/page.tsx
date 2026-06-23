"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function SignUpPage() {
  const router = useRouter();

  const [form, setForm] = useState({
    name: "",
    email: "",
    password: "",
    inputData: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  function handleChange(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.error ?? "Sign up failed. Please try again.");
        return;
      }

      /* Account created — send them to login. */
      router.push("/login?registered=true");
    } catch {
      setError("Could not reach the server. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#F8F5EE] text-[#1B1A17] flex flex-col">
      {/* Nav */}
      <nav className="sticky top-0 z-10 bg-white border-b border-[#E8E3DA] flex items-center justify-between px-8 py-4">
        <Link href="/" className="text-xl font-bold tracking-tight text-[#1B1A17]">
          ✦ Starlight
        </Link>
        <span className="text-sm text-[#6B6561]">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-[#FF4800] hover:underline">
            Log in
          </Link>
        </span>
      </nav>

      {/* Form */}
      <main className="flex-1 flex items-center justify-center px-6 py-16">
        <div className="w-full max-w-md bg-white border border-[#E8E3DA] rounded-2xl p-8 shadow-sm">
          <h1 className="text-2xl font-bold text-[#1B1A17] mb-1">Create your account</h1>
          <p className="text-sm text-[#6B6561] mb-6">
            Start generating brand-aware social content in minutes.
          </p>

          {error && (
            <div className="mb-5 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            {/* Business name */}
            <div className="flex flex-col gap-1.5">
              <label htmlFor="name" className="text-sm font-medium text-[#1B1A17]">
                Business name
              </label>
              <input
                id="name"
                name="name"
                type="text"
                required
                placeholder="EcoHome Solutions"
                value={form.name}
                onChange={handleChange}
                className="rounded-lg border border-[#E8E3DA] bg-[#F8F5EE] px-3 py-2.5 text-sm text-[#1B1A17] placeholder-[#9E9893] focus:outline-none focus:ring-2 focus:ring-[#FF4800]/40 focus:border-[#FF4800]"
              />
            </div>

            {/* Email */}
            <div className="flex flex-col gap-1.5">
              <label htmlFor="email" className="text-sm font-medium text-[#1B1A17]">
                Email address
              </label>
              <input
                id="email"
                name="email"
                type="email"
                required
                placeholder="you@company.com"
                value={form.email}
                onChange={handleChange}
                className="rounded-lg border border-[#E8E3DA] bg-[#F8F5EE] px-3 py-2.5 text-sm text-[#1B1A17] placeholder-[#9E9893] focus:outline-none focus:ring-2 focus:ring-[#FF4800]/40 focus:border-[#FF4800]"
              />
            </div>

            {/* Password */}
            <div className="flex flex-col gap-1.5">
              <label htmlFor="password" className="text-sm font-medium text-[#1B1A17]">
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                required
                placeholder="••••••••"
                value={form.password}
                onChange={handleChange}
                className="rounded-lg border border-[#E8E3DA] bg-[#F8F5EE] px-3 py-2.5 text-sm text-[#1B1A17] placeholder-[#9E9893] focus:outline-none focus:ring-2 focus:ring-[#FF4800]/40 focus:border-[#FF4800]"
              />
            </div>

            {/* Business description */}
            <div className="flex flex-col gap-1.5">
              <label htmlFor="inputData" className="text-sm font-medium text-[#1B1A17]">
                Business description
                <span className="ml-1 font-normal text-[#9E9893]">(optional)</span>
              </label>
              <textarea
                id="inputData"
                name="inputData"
                rows={3}
                placeholder="We sell sustainable bamboo home products targeting eco-conscious millennials…"
                value={form.inputData}
                onChange={handleChange}
                className="rounded-lg border border-[#E8E3DA] bg-[#F8F5EE] px-3 py-2.5 text-sm text-[#1B1A17] placeholder-[#9E9893] focus:outline-none focus:ring-2 focus:ring-[#FF4800]/40 focus:border-[#FF4800] resize-none"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="mt-1 w-full bg-[#FF4800] hover:bg-[#E03E00] disabled:opacity-60 text-white font-semibold px-4 py-3 rounded-lg transition-colors text-sm shadow-sm"
            >
              {loading ? "Creating account…" : "Create account"}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
