import { useMutation } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { TradeEvaluateRequest, TradeEvaluation } from "@/api/types";

export function useTradeEvaluate() {
  return useMutation({
    mutationFn: (body: TradeEvaluateRequest) => api.post<TradeEvaluation>("/api/trade/evaluate", body),
  });
}
