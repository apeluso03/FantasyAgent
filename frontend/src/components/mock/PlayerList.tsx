import { useMemo, useState } from "react";

import type { MockState, Position, PoolPlayer } from "@/api/mockTypes";
import { PlayerAvatar } from "@/components/ui/PlayerAvatar";
import { cn } from "@/lib/cn";

import { POSITION_STYLES, playerSubtitle, usedPositions } from "./mockUtils";

type Filter = "ALL" | Position | "FLEX" | "ROOKIES";

export function PlayerList({
  state,
  pool,
  drafted,
  canPick,
  onPick,
  onToggleQueue,
  busy,
}: {
  state: MockState;
  pool: PoolPlayer[];
  drafted: Set<string>;
  canPick: boolean;
  onPick: (p: PoolPlayer) => void;
  onToggleQueue: (p: PoolPlayer) => void;
  busy: boolean;
}) {
  const [filter, setFilter] = useState<Filter>("ALL");
  const [search, setSearch] = useState("");
  const [showDrafted, setShowDrafted] = useState(false);
  const queue = new Set(state.me.queue);
  const positions = usedPositions(state.settings.roster_slots);
  const filters: Filter[] = ["ALL", ...positions, "FLEX", "ROOKIES"];

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return pool.filter((p) => {
      if (!showDrafted && drafted.has(p.player_id)) return false;
      if (needle && !p.name.toLowerCase().includes(needle)) return false;
      if (filter === "ALL") return true;
      if (filter === "ROOKIES") return p.is_rookie;
      if (filter === "FLEX") return p.position === "RB" || p.position === "WR" || p.position === "TE";
      return p.position === filter;
    });
  }, [pool, drafted, filter, search, showDrafted]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-1.5 border-b border-neutral-200 p-2 dark:border-neutral-800">
        {filters.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              "rounded-full px-2.5 py-1 text-xs font-medium",
              filter === f
                ? "bg-hunter text-white"
                : f in POSITION_STYLES
                  ? POSITION_STYLES[f as Position].chip
                  : "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-200",
            )}
          >
            {f === "ROOKIES" ? "2027 Rookies" : f}
          </button>
        ))}
        <input
          className="input ml-auto h-8 w-40 py-1 text-xs sm:w-56"
          placeholder="Search players"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <label className="flex items-center gap-1 text-xs text-neutral-500">
          <input type="checkbox" checked={showDrafted} onChange={(e) => setShowDrafted(e.target.checked)} />
          Show drafted
        </label>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* Flex rows, not a table: long names truncate and the Draft button
            always stays on screen at phone width. */}
        <div className="sticky top-0 z-10 flex gap-2 bg-neutral-50 px-2 py-1 text-[11px] uppercase text-neutral-400 dark:bg-neutral-950">
          <span className="w-8">ADP</span>
          <span>Player</span>
        </div>
        <ul className="text-sm">
          {rows.slice(0, 300).map((p) => {
            const isDrafted = drafted.has(p.player_id);
            const queued = queue.has(p.player_id);
            return (
              <li
                key={p.player_id}
                className={cn(
                  "flex items-center gap-2 border-t border-neutral-100 px-2 py-1.5 dark:border-neutral-800/60",
                  isDrafted && "opacity-40",
                )}
              >
                <span className="w-8 shrink-0 tabular-nums text-neutral-500">{p.adp.toFixed(0)}</span>
                <PlayerAvatar playerId={p.player_id} name={p.name} size={28} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate font-medium">{p.name}</span>
                    {p.is_rookie && (
                      <span className="shrink-0 rounded bg-amber-100 px-1 text-[10px] font-semibold text-amber-800 dark:bg-amber-500/20 dark:text-amber-300">
                        R
                      </span>
                    )}
                  </div>
                  <div className="truncate text-xs text-neutral-500">{playerSubtitle(p)}</div>
                </div>
                <span
                  className={cn("shrink-0 rounded px-1.5 py-0.5 text-[11px] font-semibold", POSITION_STYLES[p.position].chip)}
                >
                  {p.pos_rank ?? p.position}
                </span>
                {!isDrafted && (
                  <div className="flex shrink-0 gap-1">
                    <button
                      onClick={() => onToggleQueue(p)}
                      className={cn(
                        "rounded-md px-2 py-1 text-xs",
                        queued
                          ? "bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300"
                          : "btn-secondary py-1",
                      )}
                      title={queued ? "Remove from queue" : "Add to queue"}
                      aria-label={queued ? "Remove from queue" : "Add to queue"}
                    >
                      {queued ? "★" : "☆"}
                    </button>
                    {canPick && (
                      <button disabled={busy} onClick={() => onPick(p)} className="btn-primary px-2.5 py-1 text-xs">
                        Draft
                      </button>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
        {rows.length === 0 && <p className="p-6 text-center text-sm text-neutral-500">No players match.</p>}
      </div>
    </div>
  );
}
