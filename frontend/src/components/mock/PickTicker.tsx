import { useEffect, useRef } from "react";

import type { MockState, PoolPlayer } from "@/api/mockTypes";
import { useCountdown } from "@/hooks/useMockDraft";
import { cn } from "@/lib/cn";

import { POSITION_STYLES, formatClock, pickLabel, shortName, teamName } from "./mockUtils";

/** Header strip: who's on the clock and the countdown, then a scrolling
 * row of the picks just made and coming up. */
export function PickTicker({
  state,
  poolById,
  clockOffset,
}: {
  state: MockState;
  poolById: Map<string, PoolPlayer>;
  clockOffset: number;
}) {
  const remaining = useCountdown(state.deadline, clockOffset);
  const current = state.picks.find((p) => p.overall === state.current_overall);
  const onClockTeam = current ? state.teams.find((t) => t.team_id === current.owner_team_id) : undefined;
  const myTurn = current != null && current.owner_team_id === state.me.team_id;
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scroller.current?.querySelector<HTMLElement>("[data-current='true']");
    el?.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
  }, [state.current_overall]);

  const start = Math.max(0, (state.current_overall ?? 1) - 4);
  const visible = state.picks.slice(start, start + 24);

  let clockText = "";
  if (state.status === "paused") clockText = "Paused";
  else if (state.status === "complete") clockText = "Done";
  else if (remaining != null) clockText = formatClock(remaining);
  else if (onClockTeam?.is_cpu || onClockTeam?.autopick) clockText = "Auto";
  else if (current) clockText = "No limit";

  return (
    <div className="flex items-stretch gap-2 border-b border-neutral-200 bg-white px-2 py-2 dark:border-neutral-800 dark:bg-neutral-900">
      <div
        className={cn(
          "flex w-36 shrink-0 flex-col justify-center rounded-md px-3 py-1",
          myTurn ? "bg-hunter text-white" : "bg-neutral-100 dark:bg-neutral-800",
        )}
      >
        <div className="text-[10px] uppercase tracking-wide opacity-75">
          {state.status === "complete" ? "Draft complete" : myTurn ? "You're on the clock" : "On the clock"}
        </div>
        <div className="truncate text-sm font-semibold">
          {current ? `${pickLabel(current)} ${onClockTeam?.name ?? ""}` : state.name}
        </div>
        <div
          className={cn(
            "font-mono text-xl font-bold tabular-nums",
            remaining != null && remaining <= 10 && "text-rose-500",
            myTurn && remaining != null && remaining <= 10 && "text-rose-200",
          )}
        >
          {clockText}
        </div>
      </div>

      <div ref={scroller} className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto">
        {visible.map((p) => {
          const player = p.player_id ? poolById.get(p.player_id) : undefined;
          const isCurrent = p.overall === state.current_overall;
          const mine = p.owner_team_id === state.me.team_id;
          return (
            <div
              key={p.overall}
              data-current={isCurrent}
              className={cn(
                "flex w-28 shrink-0 flex-col justify-between rounded-md border px-2 py-1 text-[11px]",
                player
                  ? cn(POSITION_STYLES[player.position].cell, "border-transparent")
                  : isCurrent
                    ? "border-hunter bg-celadon-light/50 dark:border-celadon dark:bg-hunter-dark/50"
                    : mine
                      ? "border-hunter/40 dark:border-celadon/40"
                      : "border-neutral-200 dark:border-neutral-800",
              )}
            >
              <div className="flex justify-between text-[10px] opacity-80">
                <span>{pickLabel(p)}</span>
                {p.owner_team_id !== p.original_team_id && <span title="Traded pick">via {teamName(state, p.original_team_id).slice(0, 8)}</span>}
              </div>
              <div className="truncate font-semibold">
                {player ? shortName(player.name) : teamName(state, p.owner_team_id)}
              </div>
              {player && <div className="truncate text-[10px] opacity-80">{teamName(state, p.owner_team_id)}</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
