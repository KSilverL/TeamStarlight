"use client";

import { useRouter } from "next/navigation";

import { signOut } from "../_lib/session";

/**
 * What /login and /signup show instead of their form when the visitor already has a session.
 *
 * The "Log out" half is not decoration. Signing in twice is blocked precisely because a second
 * login silently overwrites the first one's token, but that block would trap anyone holding a
 * session they no longer want — this app has no other way to end one. signOut() notifies
 * useSession, so the host page swaps its own form back in without a navigation: logging out
 * lands you on the form you came for.
 */
export default function AlreadySignedIn({ email }: { email: string | null }) {
  const router = useRouter();

  return (
    <div className="w-full max-w-md bg-white border border-[#E8E3DA] rounded-2xl p-8 shadow-sm">
      <h1 className="text-2xl font-bold text-[#1B1A17] mb-1">You&rsquo;re already signed in</h1>
      <p className="text-sm text-[#6B6561] mb-6">
        {email ? (
          <>
            Signed in as <span className="font-medium text-[#1B1A17]">{email}</span>. Log out first
            to use a different account.
          </>
        ) : (
          <>You already have an active session. Log out first to use a different account.</>
        )}
      </p>

      <div className="flex flex-col gap-3">
        <button
          type="button"
          onClick={() => router.push("/chat")}
          className="w-full bg-[#FF4800] hover:bg-[#E03E00] text-white font-semibold px-4 py-3 rounded-lg transition-colors text-sm shadow-sm"
        >
          Continue to chat
        </button>
        <button
          type="button"
          onClick={signOut}
          className="w-full border border-[#E8E3DA] text-[#6B6561] hover:bg-[#F2EDE4] hover:text-[#1B1A17] font-medium px-4 py-3 rounded-lg transition-colors text-sm"
        >
          Log out
        </button>
      </div>
    </div>
  );
}
