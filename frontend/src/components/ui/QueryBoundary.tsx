import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";

import { ApiError } from "@/api/client";

import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";

/**
 * Every page's loading/empty/error handling (CLAUDE.md section 6.3) funneled
 * through one component -- restyle a skeleton, an empty message, or a retry
 * button once here and every page picks it up, instead of five copies of the
 * same isPending/isError branching with slightly different markup.
 */
export function QueryBoundary<T>({
  query,
  loading,
  emptyMessage = "No data yet. Run a sync first.",
  children,
}: {
  query: UseQueryResult<T, Error>;
  loading: ReactNode;
  emptyMessage?: string;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <>{loading}</>;

  if (query.isError) {
    const { error } = query;
    if (error instanceof ApiError && error.status === 409) {
      return <EmptyState message={error.message || emptyMessage} />;
    }
    return <ErrorState message={error.message} onRetry={() => query.refetch()} />;
  }

  return <>{children(query.data)}</>;
}
