import { useState } from "react";

import type { InjuryNote, Team, TradeSideResult } from "@/api/types";
import { InjuryTag } from "@/components/ui/InjuryTag";
import { PlayerAvatar } from "@/components/ui/PlayerAvatar";
import { QueryBoundary } from "@/components/ui/QueryBoundary";
import { Skeleton } from "@/components/ui/Skeleton";
import { useMyRoster } from "@/hooks/useMyRoster";
import { useTeams } from "@/hooks/useTeams";
import { useTradeEvaluate } from "@/hooks/useTrade";
import { cn } from "@/lib/cn";
import { useLeagueOverride } from "@/state/LeagueContext";

interface PickedPlayer {
  player_id: string;
  name: string;
}

function TeamSelect({
  teams,
  value,
  onChange,
  exclude,
}: {
  teams: Team[];
  value: string;
  onChange: (ownerUserId: string) => void;
  exclude?: string;
}) {
  return (
    <select className="input" value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="">Select a team...</option>
      {teams
        .filter((t) => t.owner_user_id !== exclude)
        .map((t) => (
          <option key={t.owner_user_id} value={t.owner_user_id}>
            {t.team_name}
          </option>
        ))}
    </select>
  );
}

/** Once a team is picked, trading away a player only ever makes sense if
 * that team actually owns it (the backend validates exactly this), so the
 * roster itself -- not a free-text search across every NFL player -- is the
 * picker: load that team's players automatically and let the user tap the
 * ones changing hands. */
function RosterPicker({
  leagueId,
  ownerUserId,
  picked,
  onToggle,
}: {
  leagueId?: string;
  ownerUserId: string;
  picked: PickedPlayer[];
  onToggle: (player: PickedPlayer) => void;
}) {
  const roster = useMyRoster({ leagueId, ownerUserId });

  return (
    <div>
      {picked.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {picked.map((p) => (
            <span
              key={p.player_id}
              className="inline-flex items-center gap-1 rounded-full bg-celadon-light px-2 py-0.5 text-xs text-hunter-dark dark:bg-hunter-dark dark:text-celadon-light"
            >
              {p.name}
              <button
                className="font-bold"
                onClick={() => onToggle(p)}
                aria-label={`Remove ${p.name}`}
              >
                &times;
              </button>
            </span>
          ))}
        </div>
      )}

      <QueryBoundary
        query={roster}
        loading={
          <div className="space-y-1">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        }
        emptyMessage="No roster found for this team."
      >
        {(data) => (
          <div className="max-h-64 divide-y divide-neutral-100 overflow-y-auto rounded-md border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-700">
            {data.players.map((player) => {
              const isPicked = picked.some((p) => p.player_id === player.player_id);
              return (
                <button
                  key={player.player_id}
                  className={cn(
                    "flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-neutral-100 dark:hover:bg-neutral-800",
                    isPicked && "bg-celadon-light dark:bg-hunter-dark",
                  )}
                  onClick={() => onToggle({ player_id: player.player_id, name: player.name })}
                >
                  <PlayerAvatar playerId={player.player_id} name={player.name} size={24} />
                  <span className="flex-1 truncate">{player.name}</span>
                  <span className="shrink-0 text-xs text-neutral-500">
                    {[player.slot ?? player.position, player.team].filter(Boolean).join(" · ")}
                  </span>
                  {isPicked && <span className="shrink-0 text-hunter dark:text-celadon">✓</span>}
                </button>
              );
            })}
          </div>
        )}
      </QueryBoundary>
    </div>
  );
}

function InjuryList({ label, notes }: { label: string; notes: InjuryNote[] }) {
  if (notes.length === 0) return null;
  return (
    <div className="mt-2 space-y-1">
      <p className="text-xs font-medium text-neutral-500">{label}</p>
      {notes.map((note) => (
        <div key={note.player_id} className="flex items-center gap-1.5 text-sm">
          <InjuryTag status={note.injury_status} />
          <span className="font-medium">{note.name}</span>
          <span className="text-xs text-neutral-500">{note.reason}</span>
        </div>
      ))}
    </div>
  );
}

function SideResult({ result }: { result: TradeSideResult }) {
  return (
    <div className="card">
      <p className="text-sm font-semibold">{result.team_name}</p>
      <p className="mt-1 text-xs text-neutral-500">
        Gives up {result.value_given.toFixed(0)}, receives {result.value_received.toFixed(0)} (net{" "}
        {result.net_value >= 0 ? "+" : ""}
        {result.net_value.toFixed(0)})
      </p>
      <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-300">{result.reasoning}</p>
      <InjuryList label="Injured, giving up" notes={result.injured_players_given} />
      <InjuryList label="Injured, receiving" notes={result.injured_players_received} />
    </div>
  );
}

function togglePlayer(prev: PickedPlayer[], player: PickedPlayer): PickedPlayer[] {
  return prev.some((p) => p.player_id === player.player_id)
    ? prev.filter((p) => p.player_id !== player.player_id)
    : [...prev, player];
}

export function TradeAnalyzerPage() {
  const { override } = useLeagueOverride();
  const teams = useTeams(override?.leagueId);
  const [ownerA, setOwnerA] = useState("");
  const [ownerB, setOwnerB] = useState("");
  const [playersA, setPlayersA] = useState<PickedPlayer[]>([]);
  const [playersB, setPlayersB] = useState<PickedPlayer[]>([]);
  const evaluate = useTradeEvaluate();

  const canSubmit = ownerA && ownerB && ownerA !== ownerB && (playersA.length > 0 || playersB.length > 0);

  function handleEvaluate() {
    if (!canSubmit) return;
    evaluate.mutate({
      side_a_owner: ownerA,
      side_a_gives: playersA.map((p) => p.player_id),
      side_b_owner: ownerB,
      side_b_gives: playersB.map((p) => p.player_id),
      league_id: override?.leagueId,
    });
  }

  return (
    <div>
      <h1 className="page-title">Trade Analyzer</h1>

      <div className="mt-4">
        <QueryBoundary
          query={teams}
          loading={<Skeleton className="h-10 w-full" />}
          emptyMessage="No teams yet. Run a sync first."
        >
          {(teamList) => (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="card space-y-3">
                <TeamSelect
                  teams={teamList}
                  value={ownerA}
                  onChange={(next) => {
                    setOwnerA(next);
                    setPlayersA([]);
                  }}
                  exclude={ownerB}
                />
                {ownerA ? (
                  <RosterPicker
                    leagueId={override?.leagueId}
                    ownerUserId={ownerA}
                    picked={playersA}
                    onToggle={(p) => setPlayersA((prev) => togglePlayer(prev, p))}
                  />
                ) : (
                  <p className="text-sm text-neutral-500">Select a team to see its roster.</p>
                )}
              </div>
              <div className="card space-y-3">
                <TeamSelect
                  teams={teamList}
                  value={ownerB}
                  onChange={(next) => {
                    setOwnerB(next);
                    setPlayersB([]);
                  }}
                  exclude={ownerA}
                />
                {ownerB ? (
                  <RosterPicker
                    leagueId={override?.leagueId}
                    ownerUserId={ownerB}
                    picked={playersB}
                    onToggle={(p) => setPlayersB((prev) => togglePlayer(prev, p))}
                  />
                ) : (
                  <p className="text-sm text-neutral-500">Select a team to see its roster.</p>
                )}
              </div>
            </div>
          )}
        </QueryBoundary>
      </div>

      <button className="btn-primary mt-4" disabled={!canSubmit || evaluate.isPending} onClick={handleEvaluate}>
        {evaluate.isPending ? "Evaluating..." : "Evaluate trade"}
      </button>

      {evaluate.isError && (
        <p className="mt-3 text-sm text-rose-600 dark:text-rose-400">{evaluate.error.message}</p>
      )}

      {evaluate.data && (
        <div className="mt-4 space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <SideResult result={evaluate.data.side_a} />
            <SideResult result={evaluate.data.side_b} />
          </div>
          <div className="card bg-celadon-light text-sm font-medium text-hunter-dark dark:bg-hunter-dark dark:text-celadon-light">
            {evaluate.data.verdict}
          </div>
        </div>
      )}
    </div>
  );
}
