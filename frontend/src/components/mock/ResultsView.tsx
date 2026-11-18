import type { MockState, PoolPlayer } from "@/api/mockTypes";
import { cn } from "@/lib/cn";

import { POSITION_STYLES, SLOT_LABELS, assignLineup } from "./mockUtils";

const GRADES = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D"];

/**
 * Post-draft recap. "Value" is how far after their ADP a team's players went
 * (positive = got them later than the market says), summed over non-keeper
 * picks and shown against the room average -- a rough but honest "who drafted
 * the board well" score, graded on a curve within this draft.
 */
export function ResultsView({ state, poolById }: { state: MockState; poolById: Map<string, PoolPlayer> }) {
  const raw = state.teams.map((t) => {
    const picks = state.picks.filter((p) => p.owner_team_id === t.team_id && p.player_id);
    let value = 0;
    let steals: { name: string; delta: number } | null = null;
    for (const p of picks) {
      const pl = poolById.get(p.player_id!);
      // K/DEF always go far ahead of their ADP (every team needs one at the
      // end) -- counting them would just penalize everyone equally.
      if (!pl || p.is_keeper || pl.position === "K" || pl.position === "DEF") continue;
      const delta = p.overall - pl.adp;
      value += delta;
      if (!steals || delta > steals.delta) steals = { name: pl.name, delta };
    }
    const players = picks.map((p) => poolById.get(p.player_id!)).filter((p): p is PoolPlayer => !!p);
    return { team: t, value, steals, lineup: assignLineup(players, state.settings.roster_slots) };
  });
  // Relative to this room's average, so + means "drafted the board better than the table".
  const avg = raw.reduce((s, r) => s + r.value, 0) / Math.max(1, raw.length);
  const rows = raw.map((r) => ({ ...r, value: r.value - avg }));
  const ranked = [...rows].sort((a, b) => b.value - a.value);

  return (
    <div className="grid gap-3 p-2 md:grid-cols-2 xl:grid-cols-3">
      {ranked.map((r, i) => {
        const grade = GRADES[Math.min(GRADES.length - 1, Math.floor((i / ranked.length) * GRADES.length))];
        return (
          <div key={r.team.team_id} className={cn("card space-y-2", r.team.team_id === state.me.team_id && "ring-2 ring-hunter")}>
            <div className="flex items-center justify-between">
              <div>
                <div className="font-semibold">{r.team.name}</div>
                <div className="text-xs text-neutral-500">
                  Value vs room: {r.value >= 0 ? "+" : ""}
                  {r.value.toFixed(0)}
                  {r.steals && r.steals.delta > 0 && ` · best value: ${r.steals.name} (+${r.steals.delta.toFixed(0)})`}
                </div>
              </div>
              <div className="text-2xl font-bold text-hunter dark:text-celadon">{grade}</div>
            </div>
            <ul className="space-y-0.5 text-sm">
              {r.lineup.map(({ slot, player }, j) => (
                <li key={j} className="flex items-center gap-2">
                  <span className="w-9 text-[10px] font-semibold text-neutral-400">{SLOT_LABELS[slot]}</span>
                  {player ? (
                    <>
                      <span className="truncate">{player.name}</span>
                      <span className={cn("text-[11px]", POSITION_STYLES[player.position].text)}>{player.pos_rank}</span>
                    </>
                  ) : (
                    <span className="text-xs text-neutral-400">—</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
