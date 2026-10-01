import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { getAccessCode, setAccessCode } from "@/api/client";
import { QueryBoundary } from "@/components/ui/QueryBoundary";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAuth } from "@/state/AuthContext";
import { useLogoutRequest } from "@/hooks/useAuthApi";
import { useLeague } from "@/hooks/useLeague";
import { useJob, useStartRankingsSync, useStartSync, useSyncStatus } from "@/hooks/useSync";
import { useTeams } from "@/hooks/useTeams";
import { useLeagueOverride } from "@/state/LeagueContext";

function AccountSection() {
  const { account, logout } = useAuth();
  const logoutRequest = useLogoutRequest();

  function handleLogout() {
    // Best-effort server-side revoke -- the local session clears either way.
    logoutRequest.mutate(undefined, { onSettled: () => logout() });
  }

  if (!account) return null;

  return (
    <section className="card mt-4">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-500">Account</h2>
      <p className="text-sm">
        Signed in as <strong>{account.display_name || account.email}</strong>
      </p>
      <button className="btn-secondary mt-3" onClick={handleLogout} disabled={logoutRequest.isPending}>
        Log out
      </button>
    </section>
  );
}

function JobProgress({ jobId, label }: { jobId: string | null; label: string }) {
  const job = useJob(jobId);
  const queryClient = useQueryClient();
  const announcedDone = useRef(false);

  useEffect(() => {
    if (job.data?.status === "done" && !announcedDone.current) {
      announcedDone.current = true;
      // The sync that just finished may have changed data every other page
      // reads -- refresh it all rather than guessing which queries care.
      queryClient.invalidateQueries();
    }
    if (job.data?.status !== "done") announcedDone.current = false;
  }, [job.data?.status, queryClient]);

  if (!jobId || !job.data) return null;

  if (job.data.status === "failed") {
    return <p className="mt-2 text-sm text-rose-600 dark:text-rose-400">{label} failed: {job.data.error}</p>;
  }
  if (job.data.status === "done") {
    return <p className="mt-2 text-sm text-emerald-600 dark:text-emerald-400">{label} complete.</p>;
  }
  return <p className="mt-2 text-sm text-neutral-500">{label}: {job.data.status}...</p>;
}

function LeagueOverrideSection() {
  const { override, setLeagueId, setOwnerUserId, clear } = useLeagueOverride();
  const [leagueIdInput, setLeagueIdInput] = useState(override?.leagueId ?? "");
  const league = useLeague(override?.leagueId);
  const teams = useTeams(override?.leagueId);

  return (
    <section className="card mt-4">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-500">League</h2>
      <p className="mb-2 text-sm text-neutral-500">
        By default this app shows whichever league the server is configured for. Enter a different Sleeper
        league ID below to try the app out against another league instead -- useful for testing without
        restarting the backend.
      </p>

      <div className="flex gap-2">
        <input
          className="input"
          placeholder="Sleeper league ID"
          value={leagueIdInput}
          onChange={(event) => setLeagueIdInput(event.target.value)}
        />
        <button className="btn-primary" onClick={() => setLeagueId(leagueIdInput)} disabled={!leagueIdInput.trim()}>
          Use this league
        </button>
        {override && (
          <button
            className="btn-secondary"
            onClick={() => {
              setLeagueIdInput("");
              clear();
            }}
          >
            Clear
          </button>
        )}
      </div>

      {override && (
        <div className="mt-3 space-y-2 border-t border-neutral-100 pt-3 dark:border-neutral-800">
          {league.isError ? (
            <p className="text-sm text-rose-600 dark:text-rose-400">{league.error.message}</p>
          ) : (
            <p className="text-sm">
              Now viewing: <strong>{league.data?.name ?? "loading..."}</strong>
              {league.data && ` (season ${league.data.season}, ${league.data.total_rosters} teams)`}
            </p>
          )}

          <label className="block text-sm">
            My team in this league
            <select
              className="input mt-1"
              value={override.ownerUserId ?? ""}
              onChange={(event) => setOwnerUserId(event.target.value || null)}
              disabled={!teams.data}
            >
              <option value="">Select your team...</option>
              {teams.data?.map((t) => (
                <option key={t.owner_user_id} value={t.owner_user_id}>
                  {t.team_name}
                </option>
              ))}
            </select>
          </label>
          <p className="text-xs text-neutral-500">
            Needed for My Roster, Keepers, and Draft Board. Chat still answers for the server's configured
            league regardless of this override.
          </p>
        </div>
      )}
    </section>
  );
}

export function SettingsPage() {
  const { override } = useLeagueOverride();
  const status = useSyncStatus();
  const startSync = useStartSync();
  const startRankingsSync = useStartRankingsSync();
  const [syncJobId, setSyncJobId] = useState<string | null>(null);
  const [rankingsJobId, setRankingsJobId] = useState<string | null>(null);
  const [accessCode, setAccessCodeInput] = useState(getAccessCode());

  return (
    <div>
      <h1 className="page-title">Settings</h1>

      <AccountSection />
      <LeagueOverrideSection />

      <section className="card mt-4">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-500">Sync status</h2>
        <QueryBoundary
          query={status}
          loading={<Skeleton className="h-10 w-full" />}
          emptyMessage="Nothing synced yet."
        >
          {(entries) =>
            entries.length === 0 ? (
              <p className="text-sm text-neutral-500">Nothing synced yet.</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {entries.map((e) => (
                  <li key={e.resource} className="flex justify-between">
                    <span className="text-neutral-500">{e.resource}</span>
                    <span>{new Date(e.last_synced_at).toLocaleString()}</span>
                  </li>
                ))}
              </ul>
            )
          }
        </QueryBoundary>

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            className="btn-primary"
            disabled={startSync.isPending}
            onClick={() =>
              startSync.mutate(
                { forcePlayers: false, leagueId: override?.leagueId },
                { onSuccess: (job) => setSyncJobId(job.job_id) },
              )
            }
          >
            Sync league
          </button>
          <button
            className="btn-secondary"
            disabled={startRankingsSync.isPending}
            onClick={() =>
              startRankingsSync.mutate(false, { onSuccess: (job) => setRankingsJobId(job.job_id) })
            }
          >
            Sync rankings
          </button>
        </div>
        {startSync.isError && <p className="mt-2 text-sm text-rose-600">{startSync.error.message}</p>}
        <JobProgress jobId={syncJobId} label="League sync" />
        {startRankingsSync.isError && <p className="mt-2 text-sm text-rose-600">{startRankingsSync.error.message}</p>}
        <JobProgress jobId={rankingsJobId} label="Rankings sync" />
      </section>

      <section className="card mt-4">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-500">Access code</h2>
        <p className="mb-2 text-sm text-neutral-500">
          Only needed if this server has a demo access code configured -- required for chat and sync.
        </p>
        <div className="flex gap-2">
          <input
            className="input"
            type="password"
            placeholder="Access code"
            value={accessCode}
            onChange={(event) => setAccessCodeInput(event.target.value)}
          />
          <button className="btn-secondary" onClick={() => setAccessCode(accessCode)}>
            Save
          </button>
        </div>
      </section>
    </div>
  );
}
