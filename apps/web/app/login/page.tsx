"use client";

import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { login, getAuthStatus } from "@/lib/auth-api";

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [mode, setMode] = useState<"candidate" | "admin">("candidate");
  const [isSignUp, setIsSignUp] = useState(false);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    getAuthStatus().then((status) => {
      if (!status.authRequired || status.authenticated) {
        router.replace(searchParams.get("next") || "/dashboard");
      }
    });
  }, [router, searchParams]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "admin") {
        await login(username, password);
        router.replace(searchParams.get("next") || "/dashboard");
      } else if (isSignUp) {
        const { candidateSignUp } = await import("@/lib/auth-api");
        const res = await candidateSignUp(email, password, fullName);
        if (res.needsOnboarding) {
          router.replace("/profile?onboard=1");
        } else {
          router.replace(searchParams.get("next") || "/dashboard");
        }
      } else {
        const { candidateLogin } = await import("@/lib/auth-api");
        const res = await candidateLogin(email, password);
        if (res.needsOnboarding) {
          router.replace("/profile?onboard=1");
        } else {
          router.replace(searchParams.get("next") || "/dashboard");
        }
      }
    } catch (err: any) {
      setError(err?.message || "Authentication failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#070b12] px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-2xl border border-white/10 bg-[#0a101b] p-8 space-y-6 shadow-2xl"
      >
        <div className="text-center space-y-1.5">
          <div className="mx-auto w-10 h-10 rounded-xl bg-[#2ee8c9]/15 border border-[#2ee8c9]/40 flex items-center justify-center text-[#2ee8c9] font-black text-lg">
            C
          </div>
          <h1 className="text-lg font-bold text-slate-100">CareerOS</h1>
          <p className="text-xs text-slate-500">
            {mode === "admin"
              ? "Sign in to admin workspace"
              : isSignUp
              ? "Create your candidate account"
              : "Sign in to your candidate account"}
          </p>
        </div>

        {/* Tab switch between Candidate and Admin */}
        <div className="grid grid-cols-2 rounded-xl bg-black/40 p-1 border border-white/5 text-xs font-semibold text-slate-400">
          <button
            type="button"
            onClick={() => {
              setMode("candidate");
              setError(null);
            }}
            className={`py-1.5 rounded-lg transition-all ${
              mode === "candidate" ? "bg-white/10 text-slate-100 shadow-sm" : "hover:text-slate-200"
            }`}
          >
            Candidate
          </button>
          <button
            type="button"
            onClick={() => {
              setMode("admin");
              setError(null);
            }}
            className={`py-1.5 rounded-lg transition-all ${
              mode === "admin" ? "bg-white/10 text-slate-100 shadow-sm" : "hover:text-slate-200"
            }`}
          >
            Admin Gate
          </button>
        </div>

        <div className="space-y-3">
          {mode === "candidate" ? (
            <>
              {isSignUp && (
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] font-bold uppercase text-slate-500">Full Name</label>
                  <input
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="e.g. Alex Rivera"
                    className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400/50"
                  />
                </div>
              )}
              <div className="flex flex-col gap-1">
                <label className="text-[10px] font-bold uppercase text-slate-500">Email Address</label>
                <input
                  type="email"
                  autoFocus
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="candidate@example.com"
                  className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400/50"
                  required
                />
              </div>
            </>
          ) : (
            <div className="flex flex-col gap-1">
              <label className="text-[10px] font-bold uppercase text-slate-500">Username</label>
              <input
                type="text"
                autoFocus
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400/50"
                required
              />
            </div>
          )}

          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-bold uppercase text-slate-500">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400/50"
              required
            />
          </div>
        </div>

        {error && (
          <div className="text-xs text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-xl bg-[#2ee8c9]/15 border border-[#2ee8c9]/40 text-[#2ee8c9] text-sm font-bold py-2.5 hover:bg-[#2ee8c9]/25 transition-all cursor-pointer disabled:opacity-50"
        >
          {submitting
            ? "Authenticating..."
            : mode === "admin"
            ? "Sign in as Admin"
            : isSignUp
            ? "Create Candidate Account"
            : "Sign In"}
        </button>

        {mode === "candidate" && (
          <div className="text-center pt-1">
            <button
              type="button"
              onClick={() => {
                setIsSignUp(!isSignUp);
                setError(null);
              }}
              className="text-xs text-slate-400 hover:text-[#2ee8c9] transition-colors"
            >
              {isSignUp ? "Already have an account? Sign in" : "New candidate? Create account"}
            </button>
          </div>
        )}
      </form>
    </div>
  );
}
