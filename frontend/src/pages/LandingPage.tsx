import { useState, type FormEvent } from "react";

import { useLogin, useSignup } from "@/hooks/useAuthApi";
import { useAuth } from "@/state/AuthContext";

type Mode = "signin" | "signup";

export function LandingPage() {
  const { setSession } = useAuth();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const login = useLogin();
  const signup = useSignup();

  const pending = login.isPending || signup.isPending;
  const error = login.error ?? signup.error;

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const onSuccess = (result: { token: string; account: Parameters<typeof setSession>[1] }) =>
      setSession(result.token, result.account);

    if (mode === "signin") {
      login.mutate({ email, password }, { onSuccess });
    } else {
      signup.mutate({ email, password, display_name: displayName || undefined }, { onSuccess });
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50 px-4 dark:bg-neutral-950">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-bold text-hunter-dark dark:text-celadon">FantasyAgent</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Keeper, trade, and draft decisions for your Sleeper league -- grounded in real data, not vibes.
          </p>
        </div>

        <div className="card">
          <div className="mb-4 flex gap-1 rounded-md bg-neutral-100 p-1 dark:bg-neutral-800">
            <button
              className={`flex-1 rounded px-3 py-1.5 text-sm font-medium transition-colors ${
                mode === "signin"
                  ? "bg-white shadow-sm dark:bg-neutral-900"
                  : "text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300"
              }`}
              onClick={() => setMode("signin")}
            >
              Sign in
            </button>
            <button
              className={`flex-1 rounded px-3 py-1.5 text-sm font-medium transition-colors ${
                mode === "signup"
                  ? "bg-white shadow-sm dark:bg-neutral-900"
                  : "text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300"
              }`}
              onClick={() => setMode("signup")}
            >
              Create account
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-3">
            {mode === "signup" && (
              <label className="block text-sm">
                Name (optional)
                <input
                  className="input mt-1"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  autoComplete="name"
                />
              </label>
            )}
            <label className="block text-sm">
              Email
              <input
                type="email"
                required
                className="input mt-1"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
              />
            </label>
            <label className="block text-sm">
              Password
              <input
                type="password"
                required
                minLength={8}
                className="input mt-1"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete={mode === "signin" ? "current-password" : "new-password"}
              />
            </label>

            {error && <p className="text-sm text-rose-600 dark:text-rose-400">{error.message}</p>}

            <button type="submit" className="btn-primary w-full" disabled={pending}>
              {pending ? "Please wait..." : mode === "signin" ? "Sign in" : "Create account"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
