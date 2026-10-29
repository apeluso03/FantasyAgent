import { Badge } from "@/components/ui/Badge";
import { InjuryTag } from "@/components/ui/InjuryTag";
import { QueryBoundary } from "@/components/ui/QueryBoundary";
import { Skeleton } from "@/components/ui/Skeleton";
import { usePowerRankings } from "@/hooks/usePowerRankings";
import { useLeagueOverride } from "@/state/LeagueContext";

const POSITIONS = ["QB", "RB", "WR", "TE"] as const;

export function PowerRankingsPage() {
  const { override } = useLeagueOverride();
  const rankings = usePowerRankings(override?.leagueId);

  return (
    <div>
      <h1 className="page-title">Power Rankings</h1>

      <div className="mt-4">
        <QueryBoundary
          query={rankings}
          loading={
            <div className="space-y-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          }
        >
          {(teams) => (
            <div className="space-y-2">
              {teams.map((team) => (
                <details key={team.owner_user_id} className="card group">
                  <summary className="flex cursor-pointer list-none items-center gap-3">
                    <span className="w-6 shrink-0 text-center text-sm font-semibold text-neutral-400">
                      {team.rank}
                    </span>
                    <div className="flex-1">
                      <p className="text-sm font-medium">{team.team_name}</p>
                      <p className="text-xs text-neutral-500">
                        Power {team.starting_lineup_value.toFixed(0)}
                        {team.average_starter_rank != null && ` · avg starter #${team.average_starter_rank.toFixed(0)}`}
                      </p>
                    </div>
                    <div className="hidden gap-1 sm:flex">
                      {POSITIONS.map((pos) => (
                        <Badge key={pos} tone="brand">
                          {pos} #{team.positional_rank[pos]}
                        </Badge>
                      ))}
                    </div>
                  </summary>

                  <div className="mt-3 divide-y divide-neutral-100 border-t border-neutral-100 pt-2 dark:divide-neutral-800 dark:border-neutral-800">
                    {team.starters.map((slot, i) => (
                      <div key={i} className="flex items-center justify-between py-1.5 text-sm">
                        <span className="w-20 shrink-0 text-xs font-medium text-neutral-500">{slot.slot}</span>
                        <span className="flex flex-1 items-center gap-1.5">
                          {slot.name ?? "(empty)"}
                          <InjuryTag status={slot.injury_status} />
                        </span>
                        <span className="text-xs text-neutral-500">
                          {slot.rank_ecr != null ? `#${slot.rank_ecr}` : "unranked"}
                        </span>
                      </div>
                    ))}
                  </div>

                  {team.injured_players.length > 0 && (
                    <div className="mt-3 border-t border-neutral-100 pt-2 dark:border-neutral-800">
                      <p className="text-xs font-medium text-neutral-500">Injuries</p>
                      <div className="mt-1.5 space-y-1">
                        {team.injured_players.map((note) => (
                          <div key={note.player_id} className="flex items-center gap-1.5 text-sm">
                            <InjuryTag status={note.injury_status} />
                            <span className="font-medium">{note.name}</span>
                            <span className="text-xs text-neutral-500">{note.reason}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </details>
              ))}
            </div>
          )}
        </QueryBoundary>
      </div>
    </div>
  );
}
