import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { BestAvailablePlayer } from "@/api/types";

export function useBestAvailable(options: {
  leagueId?: string;
  ownerUserId?: string;
  limit?: number;
  live: boolean;
  enabled?: boolean;
}) {
  const { leagueId, ownerUserId, limit = 15, live, enabled = true } = options;
  return useQuery({
    queryKey: ["best-available", leagueId ?? "default", ownerUserId ?? "default", limit],
    queryFn: () =>
      api.get<BestAvailablePlayer[]>("/api/draft/best-available", {
        league_id: leagueId,
        owner_user_id: ownerUserId,
        limit,
      }),
    enabled,
    // Live polling only while the toggle is on and the tab is in the
    // foreground (CLAUDE.md section 6.3) -- refetchIntervalInBackground
    // defaults to false, so a hidden tab just stops polling on its own.
    refetchInterval: live ? 15_000 : false,
  });
}
