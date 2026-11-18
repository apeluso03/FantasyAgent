import type { MockPick, MockSettings, MockState, Position, PoolPlayer, SlotName } from "@/api/mockTypes";

/** Sleeper-style position colors: one hue per position, used for board
 * cells, filter chips and badges so a glance at the board reads the run. */
export const POSITION_STYLES: Record<Position, { cell: string; chip: string; text: string }> = {
  QB: {
    cell: "bg-rose-500/90 text-white",
    chip: "bg-rose-100 text-rose-800 dark:bg-rose-500/20 dark:text-rose-300",
    text: "text-rose-600 dark:text-rose-400",
  },
  RB: {
    cell: "bg-emerald-500/90 text-white",
    chip: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-300",
    text: "text-emerald-600 dark:text-emerald-400",
  },
  WR: {
    cell: "bg-sky-500/90 text-white",
    chip: "bg-sky-100 text-sky-800 dark:bg-sky-500/20 dark:text-sky-300",
    text: "text-sky-600 dark:text-sky-400",
  },
  TE: {
    cell: "bg-amber-500/90 text-white",
    chip: "bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300",
    text: "text-amber-600 dark:text-amber-400",
  },
  K: {
    cell: "bg-violet-500/90 text-white",
    chip: "bg-violet-100 text-violet-800 dark:bg-violet-500/20 dark:text-violet-300",
    text: "text-violet-600 dark:text-violet-400",
  },
  DEF: {
    cell: "bg-stone-500/90 text-white",
    chip: "bg-stone-200 text-stone-800 dark:bg-stone-500/20 dark:text-stone-300",
    text: "text-stone-600 dark:text-stone-400",
  },
};

export const SLOT_LABELS: Record<SlotName, string> = {
  QB: "QB",
  RB: "RB",
  WR: "WR",
  TE: "TE",
  FLEX: "FLEX",
  SUPER_FLEX: "SF",
  K: "K",
  DEF: "DEF",
  BN: "BN",
};

export const SLOT_ORDER: SlotName[] = ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF", "BN"];

const FLEX = new Set<Position>(["RB", "WR", "TE"]);
const SUPER_FLEX = new Set<Position>(["QB", "RB", "WR", "TE"]);

export function pickLabel(p: Pick<MockPick, "round" | "slot">): string {
  return `${p.round}.${String(p.slot).padStart(2, "0")}`;
}

export function shortName(name: string): string {
  const parts = name.split(" ");
  if (parts.length < 2) return name;
  return `${parts[0][0]}. ${parts.slice(1).join(" ")}`;
}

export function formatClock(seconds: number): string {
  const s = Math.ceil(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function teamName(state: MockState, teamId: number | null | undefined): string {
  return state.teams.find((t) => t.team_id === teamId)?.name ?? `Team ${teamId}`;
}

export function playerSubtitle(p: PoolPlayer): string {
  if (p.is_rookie) return `${p.college ?? "College"} · '27 rookie`;
  return p.team ?? "FA";
}

/** Mirror of engine.assign_lineup: slot a roster (draft order) into
 * starters then bench, dedicated slots first, then FLEX, then SUPER_FLEX. */
export function assignLineup(
  players: PoolPlayer[],
  slots: MockSettings["roster_slots"],
): { slot: SlotName; player: PoolPlayer | null }[] {
  const remaining = [...players];
  const take = (ok: (p: Position) => boolean) => {
    const i = remaining.findIndex((p) => ok(p.position));
    return i === -1 ? null : remaining.splice(i, 1)[0];
  };
  const out: { slot: SlotName; player: PoolPlayer | null }[] = [];
  for (const slot of ["QB", "RB", "WR", "TE"] as const) {
    for (let i = 0; i < (slots[slot] ?? 0); i++) out.push({ slot, player: take((p) => p === slot) });
  }
  for (let i = 0; i < (slots.FLEX ?? 0); i++) out.push({ slot: "FLEX", player: take((p) => FLEX.has(p)) });
  for (let i = 0; i < (slots.SUPER_FLEX ?? 0); i++)
    out.push({ slot: "SUPER_FLEX", player: take((p) => SUPER_FLEX.has(p)) });
  for (const slot of ["K", "DEF"] as const) {
    for (let i = 0; i < (slots[slot] ?? 0); i++) out.push({ slot, player: take((p) => p === slot) });
  }
  for (const p of remaining) out.push({ slot: "BN", player: p });
  return out;
}

export function picksForTeam(state: MockState, teamId: number): MockPick[] {
  return state.picks.filter((p) => p.owner_team_id === teamId);
}

/** How many picks until `teamId` is on the clock (0 = now), or null. */
export function picksUntil(state: MockState, teamId: number | null): number | null {
  if (teamId == null || state.current_overall == null) return null;
  const next = state.picks.find((p) => p.player_id == null && p.owner_team_id === teamId);
  return next ? next.overall - state.current_overall : null;
}

/** Positions the roster settings actually use (hides DEF chips when there's no DEF slot, etc). */
export function usedPositions(slots: MockSettings["roster_slots"]): Position[] {
  const all: Position[] = ["QB", "RB", "WR", "TE", "K", "DEF"];
  return all.filter(
    (p) =>
      (slots[p] ?? 0) > 0 ||
      (FLEX.has(p) && (slots.FLEX ?? 0) > 0) ||
      (SUPER_FLEX.has(p) && (slots.SUPER_FLEX ?? 0) > 0),
  );
}
