import { useMutation, useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { JobStatus, SyncStatusEntry } from "@/api/types";

export function useSyncStatus() {
  return useQuery({
    queryKey: ["sync-status"],
    queryFn: () => api.get<SyncStatusEntry[]>("/api/sync/status"),
  });
}

export function useStartSync() {
  return useMutation({
    mutationFn: (args: { forcePlayers: boolean; leagueId?: string }) =>
      api.post<JobStatus>("/api/sync", { force_players: args.forcePlayers, league_id: args.leagueId }),
  });
}

export function useStartRankingsSync() {
  return useMutation({
    mutationFn: (force: boolean) => api.post<JobStatus>("/api/rankings/sync", { force, page: null }),
  });
}

export function useJob(jobId: string | null) {
  // Polls every second while the job is in flight, stops on its own once it
  // lands on "done"/"failed" -- see SettingsPage for what happens next
  // (invalidating the rest of the app's cached data), kept out of this hook
  // so refetchInterval here stays a pure function of the query state.
  return useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.get<JobStatus>(`/api/jobs/${jobId}`),
    enabled: jobId != null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? 1_000 : false;
    },
  });
}
