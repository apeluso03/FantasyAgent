import { useMutation } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { AgentAskRequest, AgentResult } from "@/api/types";

export function useAskAgent() {
  return useMutation({
    mutationFn: (body: AgentAskRequest) => api.post<AgentResult>("/api/agent/ask", body),
  });
}
