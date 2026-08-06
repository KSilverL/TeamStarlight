"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { readToken, useSession } from "../_lib/session";
import AlreadySignedIn from "../components/AlreadySignedIn";

/** Inner component reads search params (must be wrapped in Suspense). */
function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const justRegistered = searchParams.get("registered") === "true";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Three states, not a boolean — see useSession: "checking" is the server render, where the
  // honest answer is that localStorage hasn't been read yet.
  const { status, email: signedInAs } = useSession();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      // Sent so the backend can refuse a second login on its own account. The panel this page
      // shows a signed-in visitor is the friendly half of that rule; this is the enforced half.
      const token = readToken();
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ email, password }),
      });

      const data = await res.json();

      if (!res.ok) {
        // A 409 ("already signed in") can only land if a session appeared after this form
        // rendered — another tab. That tab's write fires a `storage` event, so useSession has
        // already swapped this page over to the panel by the time the message would be read.
        setError(data.error ?? "Login failed. Please try again.");
        return;
      }

      localStorage.setItem("starlight_user", email);
      localStorage.setItem("starlight_token", data.token);
      router.push("/chat");
    } catch {
      setError("Could not reach the server. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  if (status === "checking") return null;
  if (status === "signed-in") return <AlreadySignedIn email={signedInAs} />;

  return (
    <div className="w-full max-w-md bg-white border border-[#E8E3DA] rounded-2xl p-8 shadow-sm">
      <h1 className="text-2xl font-bold text-[#1B1A17] mb-1">Welcome back</h1>
      <p className="text-sm text-[#6B6561] mb-6">Log in to your Starlight account.</p>

      {justRegistered && (
        <div className="mb-5 rounded-lg bg-green-50 border border-green-200 px-4 py-3 text-sm text-green-700">
          Account created — you can now log in.
        </div>
      )}

      {error && (
        <div className="mb-5 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {/* Email */}
        <div className="flex flex-col gap-1.5">
          <label htmlFor="email" className="text-sm font-medium text-[#1B1A17]">
            Email address
          </label>
          <input
            id="email"
            type="email"
            required
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
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
            type="password"
            required
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded-lg border border-[#E8E3DA] bg-[#F8F5EE] px-3 py-2.5 text-sm text-[#1B1A17] placeholder-[#9E9893] focus:outline-none focus:ring-2 focus:ring-[#FF4800]/40 focus:border-[#FF4800]"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="mt-1 w-full bg-[#FF4800] hover:bg-[#E03E00] disabled:opacity-60 text-white font-semibold px-4 py-3 rounded-lg transition-colors text-sm shadow-sm"
        >
          {loading ? "Logging in…" : "Log in"}
        </button>
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="min-h-screen bg-[#F8F5EE] text-[#1B1A17] flex flex-col">
      {/* Nav */}
      <nav className="sticky top-0 z-10 bg-white border-b border-[#E8E3DA] flex items-center justify-between px-8 py-4">
        <Link href="/" className="text-xl font-bold tracking-tight text-[#1B1A17]">
          ✦ Starlight
        </Link>
        <span className="text-sm text-[#6B6561]">
          No account yet?{" "}
          <Link href="/signup" className="font-medium text-[#FF4800] hover:underline">
            Sign up
          </Link>
        </span>
      </nav>

      {/* Form */}
      <main className="flex-1 flex items-center justify-center px-6 py-16">
        {/* useSearchParams() requires Suspense in Next.js app router */}
        <Suspense>
          <LoginForm />
        </Suspense>
      </main>
    </div>
  );
}
