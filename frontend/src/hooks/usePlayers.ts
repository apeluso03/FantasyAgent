import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { PlayerAnalysis, PlayerSearchResult } from "@/api/types";

export function usePlayerSearch(query: string) {
  return useQuery({
    queryKey: ["player-search", query],
    queryFn: () => api.get<PlayerSearchResult[]>("/api/players/search", { q: query, limit: 8 }),
    enabled: query.trim().length > 0,
  });
}

export function usePlayerAnalysis(playerId: string | null) {
  return useQuery({
    queryKey: ["player-analysis", playerId],
    queryFn: () => api.get<PlayerAnalysis>(`/api/players/${playerId}/analysis`, { games_back: 5 }),
    enabled: playerId != null,
  });
}
