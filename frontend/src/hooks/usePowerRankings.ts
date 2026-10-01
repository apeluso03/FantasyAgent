import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { TeamPowerRanking } from "@/api/types";

export function usePowerRankings(leagueId?: string) {
  return useQuery({
    queryKey: ["power-rankings", leagueId ?? "default"],
    queryFn: () => api.get<TeamPowerRanking[]>("/api/power-rankings", { league_id: leagueId }),
  });
}
