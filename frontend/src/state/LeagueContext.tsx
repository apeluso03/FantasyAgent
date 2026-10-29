import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

const STORAGE_KEY = "fantasy-agent-league-override";

export interface LeagueOverride {
  leagueId: string;
  ownerUserId: string | null;
}

interface LeagueContextValue {
  override: LeagueOverride | null;
  setLeagueId: (leagueId: string) => void;
  setOwnerUserId: (ownerUserId: string | null) => void;
  clear: () => void;
}

const LeagueContext = createContext<LeagueContextValue | null>(null);

function loadOverride(): LeagueOverride | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as LeagueOverride) : null;
  } catch {
    return null;
  }
}

/**
 * Lets this single local deployment point at a different Sleeper league than
 * the one baked into the backend's SLEEPER_LEAGUE_ID env var, for trying the
 * app out against another league without editing .env and restarting the
 * backend. Set from the Settings page; read by every other page's hooks.
 *
 * This is a per-request query param threaded through the API (see
 * api/client.ts's `withLeague` helper), not a server-side setting -- so it
 * stays safe even though the backend's global `settings.sleeper_league_id`
 * singleton isn't (CLAUDE.md section 9). No override set (the common case)
 * means every request omits league_id and the backend uses its own default,
 * completely unchanged from before this existed.
 */
export function LeagueProvider({ children }: { children: ReactNode }) {
  const [override, setOverride] = useState<LeagueOverride | null>(loadOverride);

  useEffect(() => {
    try {
      if (override) localStorage.setItem(STORAGE_KEY, JSON.stringify(override));
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      // localStorage unavailable (private browsing, etc.) -- override still
      // works for the rest of this session, it just won't persist a reload.
    }
  }, [override]);

  const value = useMemo<LeagueContextValue>(
    () => ({
      override,
      setLeagueId: (leagueId) => {
        const trimmed = leagueId.trim();
        setOverride(trimmed ? { leagueId: trimmed, ownerUserId: null } : null);
      },
      setOwnerUserId: (ownerUserId) => setOverride((prev) => (prev ? { ...prev, ownerUserId } : prev)),
      clear: () => setOverride(null),
    }),
    [override],
  );

  return <LeagueContext.Provider value={value}>{children}</LeagueContext.Provider>;
}

export function useLeagueOverride(): LeagueContextValue {
  const ctx = useContext(LeagueContext);
  if (!ctx) throw new Error("useLeagueOverride must be used within a LeagueProvider");
  return ctx;
}
