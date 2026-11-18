import type { MockPick, MockState, PoolPlayer } from "@/api/mockTypes";
import { cn } from "@/lib/cn";

import { POSITION_STYLES, pickLabel, shortName, teamName } from "./mockUtils";

/**
 * The big board: one column per draft slot, one row per round. A traded pick
 * stays in its original team's column (that's where it falls in the order)
 * and shows who owns it now, the way Sleeper's board does.
 */
export function DraftGrid({
  state,
  poolById,
  onPickClick,
}: {
  state: MockState;
  poolById: Map<string, PoolPlayer>;
  onPickClick?: (pick: MockPick) => void;
}) {
  const rounds = state.settings.rounds;
  const cell = new Map<string, MockPick>();
  for (const p of state.picks) cell.set(`${p.round}:${p.original_team_id}`, p);
  const myTeam = state.me.team_id;

  return (
    <div className="overflow-auto">
      <table className="w-full min-w-max border-separate border-spacing-1 text-xs">
        <thead className="sticky top-0 z-10 bg-neutral-50 dark:bg-neutral-950">
          <tr>
            <th className="w-8" />
            {state.teams.map((t, i) => (
              <th key={t.team_id} className="min-w-[92px] max-w-[120px] px-1 pb-1 text-left align-bottom font-medium">
                <div className="flex items-center gap-1 text-[10px] text-neutral-400">
                  <span>{i + 1}</span>
                  <span
                    className={cn(
                      "inline-block h-1.5 w-1.5 rounded-full",
                      t.is_cpu ? "bg-neutral-300 dark:bg-neutral-700" : t.online ? "bg-emerald-500" : "bg-amber-500",
                    )}
                    title={t.is_cpu ? "CPU" : t.online ? "Online" : "Offline"}
                  />
                  {t.is_cpu ? "CPU" : t.autopick ? "AUTO" : ""}
                </div>
                <div
                  className={cn(
                    "truncate text-[11px]",
                    t.team_id === myTeam && "font-bold text-hunter dark:text-celadon",
                  )}
                  title={t.name}
                >
                  {t.name}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rounds }, (_, r) => r + 1).map((round) => (
            <tr key={round}>
              <td className="pr-1 text-right text-[10px] font-medium text-neutral-400">{round}</td>
              {state.teams.map((t) => {
                const pick = cell.get(`${round}:${t.team_id}`);
                return (
                  <td key={t.team_id} className="p-0">
                    <BoardCell
                      pick={pick}
                      state={state}
                      player={pick?.player_id ? poolById.get(pick.player_id) : undefined}
                      onClick={pick && onPickClick ? () => onPickClick(pick) : undefined}
                    />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BoardCell({
  pick,
  player,
  state,
  onClick,
}: {
  pick: MockPick | undefined;
  player: PoolPlayer | undefined;
  state: MockState;
  onClick?: () => void;
}) {
  if (!pick) {
    return (
      <div className="flex h-14 items-center justify-center rounded-md border border-dashed border-neutral-200 text-[10px] text-neutral-300 dark:border-neutral-800 dark:text-neutral-700">
        removed
      </div>
    );
  }
  const isCurrent = state.current_overall === pick.overall && state.status !== "complete";
  const traded = pick.owner_team_id !== pick.original_team_id;
  const mine = pick.owner_team_id === state.me.team_id;
  const Comp = onClick ? "button" : "div";

  if (pick.player_id) {
    const pos = player?.position;
    return (
      <Comp
        onClick={onClick}
        className={cn(
          "flex h-14 w-full flex-col justify-between rounded-md px-1.5 py-1 text-left",
          pos ? POSITION_STYLES[pos].cell : "bg-neutral-400 text-white",
        )}
      >
        <div className="flex items-center justify-between text-[9px] opacity-90">
          <span>{pickLabel(pick)}</span>
          {pick.is_keeper ? (
            <span className="rounded bg-black/25 px-1 font-semibold">KEEP</span>
          ) : traded ? (
            <span className="truncate pl-1" title={`Owned by ${teamName(state, pick.owner_team_id)}`}>
              → {teamName(state, pick.owner_team_id)}
            </span>
          ) : null}
        </div>
        <div className="truncate text-[11px] font-semibold leading-tight">
          {player ? shortName(player.name) : pick.player_id}
        </div>
        <div className="truncate text-[9px] opacity-90">
          {player ? `${player.position} · ${player.team ?? (player.is_rookie ? "R" : "FA")}` : ""}
        </div>
      </Comp>
    );
  }

  return (
    <Comp
      onClick={onClick}
      className={cn(
        "flex h-14 w-full flex-col justify-between rounded-md border px-1.5 py-1 text-left",
        isCurrent
          ? "animate-pulse border-hunter bg-celadon-light/60 dark:border-celadon dark:bg-hunter-dark/60"
          : mine
            ? "border-hunter/40 bg-celadon-light/20 dark:border-celadon/30 dark:bg-hunter-dark/20"
            : "border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900",
        onClick && "hover:border-hunter",
      )}
    >
      <span className="text-[9px] text-neutral-400">{pickLabel(pick)}</span>
      {traded ? (
        <span className="truncate text-[10px] font-medium text-amber-700 dark:text-amber-400" title="Traded pick">
          → {teamName(state, pick.owner_team_id)}
        </span>
      ) : (
        <span className="text-[10px] text-neutral-300 dark:text-neutral-700">{isCurrent ? "on the clock" : ""}</span>
      )}
    </Comp>
  );
}
