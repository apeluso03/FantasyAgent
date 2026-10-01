import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { KeeperCandidate } from "@/api/types";

export function useKeepers(options: { leagueId?: string; ownerUserId?: string; enabled?: boolean } = {}) {
  const { leagueId, ownerUserId, enabled = true } = options;
  return useQuery({
    queryKey: ["keepers", leagueId ?? "default", ownerUserId ?? "default"],
    queryFn: () => api.get<KeeperCandidate[]>("/api/keepers", { league_id: leagueId, owner_user_id: ownerUserId }),
    enabled,
  });
}
