import { useEffect, useRef, useState } from "react";

import type { MockState, PoolPlayer } from "@/api/mockTypes";
import { PlayerAvatar } from "@/components/ui/PlayerAvatar";
import { cn } from "@/lib/cn";

import { POSITION_STYLES, SLOT_LABELS, assignLineup, pickLabel, playerSubtitle, teamName } from "./mockUtils";

export function QueuePanel({
  state,
  poolById,
  drafted,
  onChange,
  canPick,
  onPick,
}: {
  state: MockState;
  poolById: Map<string, PoolPlayer>;
  drafted: Set<string>;
  onChange: (ids: string[]) => void;
  canPick: boolean;
  onPick: (p: PoolPlayer) => void;
}) {
  const queue = state.me.queue;
  const move = (i: number, d: number) => {
    const next = [...queue];
    const [x] = next.splice(i, 1);
    next.splice(Math.max(0, Math.min(next.length, i + d)), 0, x);
    onChange(next);
  };
  return (
    <div className="p-2">
      <p className="mb-2 text-xs text-neutral-500">
        If your clock runs out (or autopick is on), you get the first player here who's still available.
      </p>
      {queue.length === 0 && <p className="p-4 text-center text-sm text-neutral-500">Star players in the list to queue them.</p>}
      <ol className="space-y-1">
        {queue.map((id, i) => {
          const p = poolById.get(id);
          if (!p) return null;
          const gone = drafted.has(id);
          return (
            <li
              key={id}
              className={cn("flex items-center gap-2 rounded-md border border-neutral-200 px-2 py-1.5 dark:border-neutral-800", gone && "opacity-40")}
            >
              <span className="w-5 text-xs text-neutral-400">{i + 1}</span>
              <PlayerAvatar playerId={p.player_id} name={p.name} size={24} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{p.name}</div>
                <div className={cn("text-[11px]", POSITION_STYLES[p.position].text)}>
                  {p.pos_rank} · ADP {p.adp.toFixed(0)}
                </div>
              </div>
              {canPick && !gone && (
                <button className="btn-primary px-2 py-1 text-xs" onClick={() => onPick(p)}>
                  Draft
                </button>
              )}
              <button className="px-1 text-neutral-400 hover:text-neutral-700" onClick={() => move(i, -1)} aria-label="Move up">
                ↑
              </button>
              <button className="px-1 text-neutral-400 hover:text-neutral-700" onClick={() => move(i, 1)} aria-label="Move down">
                ↓
              </button>
              <button
                className="px-1 text-neutral-400 hover:text-rose-600"
                onClick={() => onChange(queue.filter((q) => q !== id))}
                aria-label="Remove"
              >
                ✕
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function RosterPanel({ state, poolById }: { state: MockState; poolById: Map<string, PoolPlayer> }) {
  const [teamId, setTeamId] = useState<number>(state.me.team_id ?? state.teams[0].team_id);
  const picks = state.picks.filter((p) => p.owner_team_id === teamId);
  const players = picks
    .filter((p) => p.player_id)
    .map((p) => poolById.get(p.player_id!))
    .filter((p): p is PoolPlayer => !!p);
  const lineup = assignLineup(players, state.settings.roster_slots);
  const upcoming = picks.filter((p) => !p.player_id);

  return (
    <div className="space-y-3 p-2">
      <select className="input" value={teamId} onChange={(e) => setTeamId(Number(e.target.value))}>
        {state.teams.map((t) => (
          <option key={t.team_id} value={t.team_id}>
            {t.name}
            {t.team_id === state.me.team_id ? " (you)" : ""}
          </option>
        ))}
      </select>
      <ul className="space-y-1">
        {lineup.map(({ slot, player }, i) => (
          <li key={i} className="flex items-center gap-2 text-sm">
            <span
              className={cn(
                "w-10 shrink-0 rounded px-1 py-0.5 text-center text-[10px] font-semibold",
                slot === "BN" ? "bg-neutral-100 text-neutral-500 dark:bg-neutral-800" : "bg-celadon-light text-hunter-dark dark:bg-hunter-dark dark:text-celadon-light",
              )}
            >
              {SLOT_LABELS[slot]}
            </span>
            {player ? (
              <>
                <span className="truncate font-medium">{player.name}</span>
                <span className={cn("text-xs", POSITION_STYLES[player.position].text)}>{player.position}</span>
                <span className="truncate text-xs text-neutral-400">{playerSubtitle(player)}</span>
              </>
            ) : (
              <span className="text-xs text-neutral-400">empty</span>
            )}
          </li>
        ))}
      </ul>
      <div>
        <div className="mb-1 text-xs font-semibold uppercase text-neutral-400">
          Picks left ({upcoming.length})
        </div>
        <div className="flex flex-wrap gap-1">
          {upcoming.map((p) => (
            <span
              key={p.overall}
              className={cn(
                "rounded px-1.5 py-0.5 text-[11px]",
                p.original_team_id !== teamId
                  ? "bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300"
                  : "bg-neutral-100 dark:bg-neutral-800",
              )}
              title={p.original_team_id !== teamId ? `Acquired from ${teamName(state, p.original_team_id)}` : undefined}
            >
              {pickLabel(p)}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ChatPanel({ state, onSend }: { state: MockState; onSend: (text: string) => Promise<void> }) {
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [state.chat.length]);
  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto p-2">
        {state.chat.map((m, i) => (
          <div key={i} className="text-sm">
            {m.participant_id == null ? (
              <span className="text-xs italic text-neutral-500">{m.text}</span>
            ) : (
              <>
                <span className={cn("font-semibold", m.participant_id === state.me.participant_id && "text-hunter dark:text-celadon")}>
                  {m.name}:
                </span>{" "}
                <span className="break-words">{m.text}</span>
              </>
            )}
          </div>
        ))}
        <div ref={end} />
      </div>
      <form
        className="flex gap-2 border-t border-neutral-200 p-2 dark:border-neutral-800"
        onSubmit={async (e) => {
          e.preventDefault();
          const t = text.trim();
          if (!t) return;
          setText("");
          await onSend(t);
        }}
      >
        <input className="input" maxLength={300} value={text} onChange={(e) => setText(e.target.value)} placeholder="Say something" />
        <button className="btn-primary" type="submit">
          Send
        </button>
      </form>
    </div>
  );
}
