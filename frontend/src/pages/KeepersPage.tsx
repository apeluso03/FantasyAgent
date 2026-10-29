import { Badge } from "@/components/ui/Badge";
import { NeedsTeamPrompt } from "@/components/ui/NeedsTeamPrompt";
import { PlayerAvatar } from "@/components/ui/PlayerAvatar";
import { QueryBoundary } from "@/components/ui/QueryBoundary";
import { Skeleton } from "@/components/ui/Skeleton";
import { useKeepers } from "@/hooks/useKeepers";
import { useLeagueOverride } from "@/state/LeagueContext";
import { usePlayerPanel } from "@/state/PlayerPanelContext";

export function KeepersPage() {
  const { override } = useLeagueOverride();
  const needsTeamPick = override != null && override.ownerUserId == null;
  const keepers = useKeepers({
    leagueId: override?.leagueId,
    ownerUserId: override?.ownerUserId ?? undefined,
    enabled: !needsTeamPick,
  });
  const { openPlayer } = usePlayerPanel();

  return (
    <div>
      <h1 className="page-title">Keepers</h1>

      <div className="mt-4">
        {needsTeamPick ? (
          <NeedsTeamPrompt />
        ) : (
        <QueryBoundary
          query={keepers}
          loading={
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          }
        >
          {(candidates) => (
            <div className="space-y-2">
              {candidates.map((c) => (
                <button
                  key={c.player_id}
                  className="card block w-full text-left"
                  onClick={() =>
                    openPlayer({
                      playerId: c.player_id,
                      name: c.name,
                      position: c.position,
                      team: c.team,
                      rankEcr: c.rank_ecr,
                      posRank: c.pos_rank,
                    })
                  }
                >
                  <div className="flex items-center gap-3">
                    <PlayerAvatar playerId={c.player_id} name={c.name} />
                    <div className="flex-1">
                      <p className="text-sm font-medium">{c.name}</p>
                      <p className="text-xs text-neutral-500">
                        {[c.position, c.team].filter(Boolean).join(" · ")}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge>Cost R{c.cost_round}</Badge>
                      {c.value_surplus != null && (
                        <Badge tone={c.value_surplus >= 0 ? "good" : "bad"}>
                          {c.value_surplus >= 0 ? "+" : ""}
                          {c.value_surplus}
                        </Badge>
                      )}
                    </div>
                  </div>
                  <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-300">{c.reasoning}</p>
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
