import type { RosterPlayer } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { NeedsTeamPrompt } from "@/components/ui/NeedsTeamPrompt";
import { PlayerAvatar } from "@/components/ui/PlayerAvatar";
import { QueryBoundary } from "@/components/ui/QueryBoundary";
import { Skeleton } from "@/components/ui/Skeleton";
import { useMyRoster } from "@/hooks/useMyRoster";
import { useLeagueOverride } from "@/state/LeagueContext";
import { usePlayerPanel } from "@/state/PlayerPanelContext";

const GROUP_LABELS: Record<RosterPlayer["group"], string> = {
  starter: "Starters",
  bench: "Bench",
  ir: "IR",
  taxi: "Taxi",
};

function PlayerRow({ player }: { player: RosterPlayer }) {
  const { openPlayer } = usePlayerPanel();

  return (
    <button
      className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-left hover:bg-neutral-100 dark:hover:bg-neutral-800"
      onClick={() =>
        openPlayer({
          playerId: player.player_id,
          name: player.name,
          position: player.position,
          team: player.team,
          rankEcr: player.rank_ecr,
          posRank: player.pos_rank,
        })
      }
    >
      <PlayerAvatar playerId={player.player_id} name={player.name} />
      <div className="flex-1">
        <p className="text-sm font-medium">{player.name}</p>
        <p className="text-xs text-neutral-500">
          {[player.slot ?? player.position, player.team].filter(Boolean).join(" · ")}
        </p>
      </div>
      {player.rank_ecr != null && <Badge>#{player.rank_ecr}</Badge>}
    </button>
  );
}

function RosterSkeleton() {
  return (
    <div className="card space-y-2">
      {Array.from({ length: 6 }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function MyRosterPage() {
  const { override } = useLeagueOverride();
  const needsTeamPick = override != null && override.ownerUserId == null;
  const roster = useMyRoster({
    leagueId: override?.leagueId,
    ownerUserId: override?.ownerUserId ?? undefined,
    enabled: !needsTeamPick,
  });

  return (
    <div>
      <h1 className="page-title">My Roster</h1>

      <div className="mt-4">
        {needsTeamPick ? (
          <NeedsTeamPrompt />
        ) : (
          <QueryBoundary query={roster} loading={<RosterSkeleton />}>
            {(data) => {
              const groups: RosterPlayer["group"][] = ["starter", "bench", "ir", "taxi"];
              return (
                <div className="space-y-5">
                  <p className="text-sm text-neutral-500">{data.team_name}</p>
                  {groups.map((group) => {
                    const players = data.players.filter((p) => p.group === group);
                    if (players.length === 0) return null;
                    return (
                      <section key={group} className="card">
                        <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-neutral-500">
                          {GROUP_LABELS[group]}
                        </h2>
                        <div className="divide-y divide-neutral-100 dark:divide-neutral-800">
                          {players.map((player) => (
                            <PlayerRow key={player.player_id} player={player} />
                          ))}
                        </div>
                      </section>
                    );
                  })}
                </div>
              );
            }}
          </QueryBoundary>
        )}
      </div>
    </div>
  );
}
