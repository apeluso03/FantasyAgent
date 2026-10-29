import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { NeedsTeamPrompt } from "@/components/ui/NeedsTeamPrompt";
import { PlayerAvatar } from "@/components/ui/PlayerAvatar";
import { QueryBoundary } from "@/components/ui/QueryBoundary";
import { Skeleton } from "@/components/ui/Skeleton";
import { useBestAvailable } from "@/hooks/useDraft";
import { useLeagueOverride } from "@/state/LeagueContext";
import { usePlayerPanel } from "@/state/PlayerPanelContext";

export function DraftBoardPage() {
  const [live, setLive] = useState(false);
  const { override } = useLeagueOverride();
  const needsTeamPick = override != null && override.ownerUserId == null;
  const board = useBestAvailable({
    leagueId: override?.leagueId,
    ownerUserId: override?.ownerUserId ?? undefined,
    limit: 20,
    live,
    enabled: !needsTeamPick,
  });
  const { openPlayer } = usePlayerPanel();

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="page-title">Draft Board</h1>
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4 accent-hunter"
            checked={live}
            onChange={(event) => setLive(event.target.checked)}
          />
          Live (polls every 15s)
        </label>
      </div>

      <div className="mt-4">
        {needsTeamPick ? (
          <NeedsTeamPrompt />
        ) : (
        <QueryBoundary
          query={board}
          loading={
            <div className="space-y-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          }
        >
          {(players) => (
            <div className="space-y-2">
              {players.map((p) => (
                <button
                  key={p.player_id}
                  className="card block w-full text-left"
                  onClick={() =>
                    openPlayer({
                      playerId: p.player_id,
                      name: p.name,
                      position: p.position,
                      team: p.team,
                      rankEcr: p.rank_ecr,
                      posRank: p.pos_rank,
                    })
                  }
                >
                  <div className="flex items-center gap-3">
                    <PlayerAvatar playerId={p.player_id} name={p.name} />
                    <div className="flex-1">
                      <p className="text-sm font-medium">{p.name}</p>
                      <p className="text-xs text-neutral-500">
                        {[p.position, p.team].filter(Boolean).join(" · ")}
                      </p>
                    </div>
                    <Badge tone="brand">#{p.rank_ecr}</Badge>
                  </div>
                  <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-300">{p.reasoning}</p>
                </button>
              ))}
            </div>
          )}
        </QueryBoundary>
        )}
      </div>
    </div>
  );
}
