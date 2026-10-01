import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { Team } from "@/api/types";

export function useTeams(leagueId?: string) {
  return useQuery({
    queryKey: ["teams", leagueId ?? "default"],
    queryFn: () => api.get<Team[]>("/api/teams", { league_id: leagueId }),
  });
}
