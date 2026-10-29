import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { League } from "@/api/types";

export function useLeague(leagueId?: string) {
  return useQuery({
    queryKey: ["league", leagueId ?? "default"],
    queryFn: () => api.get<League>("/api/league", { league_id: leagueId }),
  });
}
