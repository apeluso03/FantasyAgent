import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { MyRoster } from "@/api/types";

export function useMyRoster(options: { leagueId?: string; ownerUserId?: string; enabled?: boolean } = {}) {
  const { leagueId, ownerUserId, enabled = true } = options;
  return useQuery({
    queryKey: ["my-roster", leagueId ?? "default", ownerUserId ?? "default"],
    queryFn: () => api.get<MyRoster>("/api/my-roster", { league_id: leagueId, owner_user_id: ownerUserId }),
    enabled,
  });
}
