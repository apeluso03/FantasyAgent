import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { Ranking } from "@/api/types";

export function useRankings(search?: string) {
  return useQuery({
    queryKey: ["rankings", search ?? ""],
    queryFn: () => api.get<Ranking[]>("/api/rankings", { search, limit: 50 }),
  });
}
