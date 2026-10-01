import { usePlayerAnalysis } from "@/hooks/usePlayers";
import { usePlayerPanel } from "@/state/PlayerPanelContext";

import { CloseIcon } from "./icons";
import { Badge } from "./ui/Badge";
import { ErrorState } from "./ui/ErrorState";
import { PlayerAvatar } from "./ui/PlayerAvatar";
import { Skeleton } from "./ui/Skeleton";

/** Shared side drawer (CLAUDE.md section 6.2) -- every page that lists
 * players opens this via usePlayerPanel().openPlayer() instead of rolling
 * its own detail view. */
export function PlayerPanel() {
  const { target, closePlayer } = usePlayerPanel();
  const analysis = usePlayerAnalysis(target?.playerId ?? null);

  if (!target) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={closePlayer}>
      <aside
        className="h-full w-full max-w-sm overflow-y-auto bg-white p-5 shadow-xl dark:bg-neutral-900"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <PlayerAvatar playerId={target.playerId} name={target.name} size={56} />
            <div>
              <h2 className="text-lg font-semibold">{target.name}</h2>
              <p className="text-sm text-neutral-500">
                {[target.position, target.team].filter(Boolean).join(" · ") || "Free agent"}
              </p>
            </div>
          </div>
          <button className="btn-secondary px-2 py-2" onClick={closePlayer} aria-label="Close">
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>

        {(target.rankEcr != null || target.posRank) && (
          <div className="mt-3 flex gap-2">
            {target.rankEcr != null && <Badge tone="brand">#{target.rankEcr} overall</Badge>}
            {target.posRank && <Badge>{target.posRank}</Badge>}
          </div>
        )}

        <h3 className="mt-6 text-sm font-semibold uppercase tracking-wide text-neutral-500">Last 5 games</h3>

        {analysis.isPending && (
          <div className="mt-2 space-y-2">
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-5/6" />
            <Skeleton className="h-5 w-4/6" />
          </div>
        )}

        {analysis.isError && (
          <ErrorState message={analysis.error.message} onRetry={() => analysis.refetch()} />
        )}

        {analysis.data && (
          <>
            <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-300">{analysis.data.blurb}</p>
            {analysis.data.games.length > 0 ? (
              <ul className="mt-3 divide-y divide-neutral-200 dark:divide-neutral-800">
                {analysis.data.games.map((game) => (
                  <li key={game.week} className="flex items-center justify-between gap-2 py-2 text-sm">
                    <span className="w-10 shrink-0 text-neutral-500">Wk {game.week}</span>
                    <span className="flex-1 text-neutral-600 dark:text-neutral-300">{game.stat_line}</span>
                    <span className="shrink-0 font-medium">
                      {game.points_ppr != null ? `${game.points_ppr.toFixed(1)} pts` : "-"}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-neutral-500">No recent game logs found.</p>
            )}
          </>
        )}
      </aside>
    </div>
  );
}
