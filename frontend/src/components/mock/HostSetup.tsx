import { useEffect, useMemo, useState } from "react";

import type { MockAction, MockKeeper, MockSettings, MockState, PoolPlayer, SlotName } from "@/api/mockTypes";
import { cn } from "@/lib/cn";

import { SLOT_LABELS, SLOT_ORDER, pickLabel, teamName } from "./mockUtils";

type Act = (a: MockAction) => Promise<void>;

function Section({ title, children, hint }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="card space-y-3">
      <div>
        <h3 className="font-semibold text-hunter-dark dark:text-celadon">{title}</h3>
        {hint && <p className="text-xs text-neutral-500">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

export function HostSetup({ state, pool, act }: { state: MockState; pool: PoolPlayer[]; act: Act }) {
  return (
    <div className="grid gap-3 p-2 lg:grid-cols-2">
      <SettingsForm state={state} act={act} />
      <TeamsEditor state={state} act={act} />
      <TradedPicksEditor state={state} act={act} />
      <KeepersEditor state={state} pool={pool} act={act} />
      <SleeperImport state={state} act={act} />
    </div>
  );
}

const TIMERS = [0, 30, 45, 60, 90, 120, 180, 300];

function SettingsForm({ state, act }: { state: MockState; act: Act }) {
  const [s, setS] = useState<MockSettings>(state.settings);
  useEffect(() => {
    setS(state.settings);
  }, [state.settings]);
  const dirty = JSON.stringify(s) !== JSON.stringify(state.settings);
  const set = <K extends keyof MockSettings>(k: K, v: MockSettings[K]) => setS((prev) => ({ ...prev, [k]: v }));
  const setSlot = (slot: SlotName, v: number) =>
    setS((prev) => {
      const roster_slots = { ...prev.roster_slots, [slot]: Math.max(0, Math.min(10, v)) };
      // Keep rounds in step with roster size unless the host changed rounds on their own.
      const oldTotal = Object.values(prev.roster_slots).reduce((a, b) => a + b, 0);
      const newTotal = Object.values(roster_slots).reduce((a, b) => a + b, 0);
      return { ...prev, roster_slots, rounds: prev.rounds === oldTotal ? newTotal : prev.rounds };
    });

  return (
    <Section title="Draft settings" hint="Defaults: 12-team superflex PPR, 1QB/2RB/3WR/1TE/1FLEX/1SF/1K + 6 bench.">
      <div className="grid grid-cols-2 gap-2 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-neutral-500">Teams</span>
          <select className="input" value={s.num_teams} onChange={(e) => set("num_teams", Number(e.target.value))}>
            {Array.from({ length: 11 }, (_, i) => i + 2).map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-neutral-500">Rounds</span>
          <input
            className="input"
            type="number"
            min={1}
            max={30}
            value={s.rounds}
            onChange={(e) => set("rounds", Number(e.target.value))}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-neutral-500">Draft type</span>
          <select className="input" value={s.draft_type} onChange={(e) => set("draft_type", e.target.value as MockSettings["draft_type"])}>
            <option value="snake">Snake</option>
            <option value="3rr">Snake, 3rd-round reversal</option>
            <option value="linear">Linear</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-neutral-500">Pick timer</span>
          <select className="input" value={s.pick_seconds} onChange={(e) => set("pick_seconds", Number(e.target.value))}>
            {TIMERS.map((t) => (
              <option key={t} value={t}>
                {t === 0 ? "No limit" : t < 60 ? `${t}s` : `${t / 60} min`}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-neutral-500">ADP source</span>
          <select className="input" value={s.adp_mode} onChange={(e) => set("adp_mode", e.target.value as MockSettings["adp_mode"])}>
            <option value="2027">2027 projection (default)</option>
            <option value="dynasty">Dynasty / startup</option>
            <option value="redraft">Redraft (current season)</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-neutral-500">CPU speed</span>
          <select className="input" value={s.cpu_pick_seconds} onChange={(e) => set("cpu_pick_seconds", Number(e.target.value))}>
            <option value={0}>Instant</option>
            <option value={1.5}>Fast</option>
            <option value={3}>Normal</option>
            <option value={6}>Slow</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-neutral-500">CPU style</span>
          <select className="input" value={s.cpu_randomness} onChange={(e) => set("cpu_randomness", Number(e.target.value))}>
            <option value={0}>Strict ADP</option>
            <option value={1}>Realistic</option>
            <option value={2.5}>Chaotic</option>
          </select>
        </label>
        <label className="flex items-end gap-2 pb-2">
          <input type="checkbox" checked={s.include_rookies} onChange={(e) => set("include_rookies", e.target.checked)} />
          <span className="text-sm">Include 2027 rookies</span>
        </label>
      </div>

      <div>
        <div className="mb-1 text-xs text-neutral-500">Roster slots</div>
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
          {SLOT_ORDER.map((slot) => (
            <div key={slot} className="flex items-center justify-between rounded-md border border-neutral-200 px-2 py-1 dark:border-neutral-700">
              <span className="text-xs font-semibold">{SLOT_LABELS[slot]}</span>
              <div className="flex items-center gap-1">
                <button className="px-1 text-neutral-400" onClick={() => setSlot(slot, (s.roster_slots[slot] ?? 0) - 1)}>
                  −
                </button>
                <span className="w-4 text-center text-sm tabular-nums">{s.roster_slots[slot] ?? 0}</span>
                <button className="px-1 text-neutral-400" onClick={() => setSlot(slot, (s.roster_slots[slot] ?? 0) + 1)}>
                  +
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="flex gap-2">
        <button
          className="btn-primary"
          disabled={!dirty}
          onClick={() => {
            const { scoring: _scoring, season: _season, ...rest } = s;
            void act({ type: "update_settings", settings: rest });
          }}
        >
          Save settings
        </button>
        {dirty && (
          <button className="btn-secondary" onClick={() => setS(state.settings)}>
            Discard
          </button>
        )}
      </div>
    </Section>
  );
}

function TeamsEditor({ state, act }: { state: MockState; act: Act }) {
  const [editing, setEditing] = useState<number | null>(null);
  const [name, setName] = useState("");
  const move = (i: number, d: number) => {
    const ids = state.teams.map((t) => t.team_id);
    const j = i + d;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    void act({ type: "set_order", team_ids: ids });
  };

  return (
    <Section title="Teams & draft order" hint="Unclaimed teams are drafted by the CPU. Moving a team moves its original picks with it.">
      <div className="flex gap-2">
        <button className="btn-secondary" onClick={() => void act({ type: "randomize_order" })}>
          Randomize order
        </button>
      </div>
      <ol className="space-y-1">
        {state.teams.map((t, i) => (
          <li key={t.team_id} className="flex items-center gap-2 text-sm">
            <span className="w-5 text-right text-xs text-neutral-400">{i + 1}</span>
            {editing === t.team_id ? (
              <form
                className="flex flex-1 gap-1"
                onSubmit={(e) => {
                  e.preventDefault();
                  void act({ type: "rename_team", team_id: t.team_id, name }).then(() => setEditing(null));
                }}
              >
                <input className="input py-1" autoFocus maxLength={40} value={name} onChange={(e) => setName(e.target.value)} />
                <button className="btn-primary py-1">Save</button>
              </form>
            ) : (
              <button
                className="flex-1 truncate text-left font-medium hover:underline"
                onClick={() => {
                  setEditing(t.team_id);
                  setName(t.name);
                }}
                title="Rename"
              >
                {t.name}
              </button>
            )}
            <select
              className="input w-36 py-1 text-xs"
              value={t.participant_id ?? ""}
              onChange={(e) => void act({ type: "assign_seat", team_id: t.team_id, participant_id: e.target.value || null })}
            >
              <option value="">CPU</option>
              {state.participants.map((p) => (
                <option key={p.participant_id} value={p.participant_id}>
                  {p.name}
                  {p.is_host ? " (host)" : ""}
                </option>
              ))}
            </select>
            <button className="px-1 text-neutral-400" onClick={() => move(i, -1)} aria-label="Move up">
              ↑
            </button>
            <button className="px-1 text-neutral-400" onClick={() => move(i, 1)} aria-label="Move down">
              ↓
            </button>
          </li>
        ))}
      </ol>
      {state.participants.length > 1 && (
        <div className="space-y-1 border-t border-neutral-200 pt-2 dark:border-neutral-800">
          <div className="text-xs text-neutral-500">People in the room</div>
          {state.participants.map((p) => (
            <div key={p.participant_id} className="flex items-center gap-2 text-sm">
              <span className={cn("h-2 w-2 rounded-full", p.online ? "bg-emerald-500" : "bg-neutral-300")} />
              <span className="flex-1">{p.name}</span>
              <span className="text-xs text-neutral-500">{p.team_id ? teamName(state, p.team_id) : "watching"}</span>
              {!p.is_host && (
                <button className="text-xs text-rose-600 hover:underline" onClick={() => void act({ type: "kick", participant_id: p.participant_id })}>
                  Remove
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

function TradedPicksEditor({ state, act }: { state: MockState; act: Act }) {
  const [round, setRound] = useState(1);
  const [from, setFrom] = useState(state.teams[0].team_id);
  const [to, setTo] = useState<string>(String(state.teams[1]?.team_id ?? ""));

  return (
    <Section
      title="Traded picks"
      hint="Give a team extra picks: each pick moves from its original team to its new owner, so the original team loses it. You can also tap any pick on the board."
    >
      <div className="flex flex-wrap items-end gap-2 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-neutral-500">Round</span>
          <select className="input w-20" value={round} onChange={(e) => setRound(Number(e.target.value))}>
            {Array.from({ length: state.settings.rounds }, (_, i) => i + 1).map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-neutral-500">Original team's pick</span>
          <select className="input w-40" value={from} onChange={(e) => setFrom(Number(e.target.value))}>
            {state.teams.map((t) => (
              <option key={t.team_id} value={t.team_id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-neutral-500">Now owned by</span>
          <select className="input w-40" value={to} onChange={(e) => setTo(e.target.value)}>
            {state.teams.map((t) => (
              <option key={t.team_id} value={t.team_id}>
                {t.name}
              </option>
            ))}
            <option value="none">Nobody (remove pick)</option>
          </select>
        </label>
        <button
          className="btn-primary"
          onClick={() =>
            void act({
              type: "set_pick_owner",
              round,
              original_team_id: from,
              owner_team_id: to === "none" ? null : Number(to),
            })
          }
        >
          Apply
        </button>
      </div>
      {state.traded_picks.length > 0 ? (
        <ul className="space-y-1 text-sm">
          {state.traded_picks.map((tp) => {
            const pick = state.picks.find((p) => p.round === tp.round && p.original_team_id === tp.original_team_id);
            return (
              <li key={`${tp.round}:${tp.original_team_id}`} className="flex items-center gap-2">
                <span className="w-12 text-xs text-neutral-400">{pick ? pickLabel(pick) : `R${tp.round}`}</span>
                <span className="flex-1 truncate">
                  {teamName(state, tp.original_team_id)}'s R{tp.round} →{" "}
                  <b>{tp.owner_team_id == null ? "removed" : teamName(state, tp.owner_team_id)}</b>
                </span>
                <button
                  className="text-xs text-neutral-500 hover:underline"
                  onClick={() =>
                    void act({
                      type: "set_pick_owner",
                      round: tp.round,
                      original_team_id: tp.original_team_id,
                      owner_team_id: tp.original_team_id,
                    })
                  }
                >
                  Undo
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-xs text-neutral-500">No traded picks yet.</p>
      )}
      <PickCounts state={state} />
    </Section>
  );
}

function PickCounts({ state }: { state: MockState }) {
  const counts = new Map<number, number>();
  for (const p of state.picks) counts.set(p.owner_team_id, (counts.get(p.owner_team_id) ?? 0) + 1);
  const uneven = state.teams.some((t) => (counts.get(t.team_id) ?? 0) !== state.settings.rounds);
  if (!uneven) return null;
  return (
    <div className="flex flex-wrap gap-1 text-[11px]">
      {state.teams.map((t) => {
        const n = counts.get(t.team_id) ?? 0;
        return (
          <span
            key={t.team_id}
            className={cn(
              "rounded px-1.5 py-0.5",
              n > state.settings.rounds
                ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-300"
                : n < state.settings.rounds
                  ? "bg-rose-100 text-rose-800 dark:bg-rose-500/20 dark:text-rose-300"
                  : "bg-neutral-100 dark:bg-neutral-800",
            )}
          >
            {t.name}: {n}
          </span>
        );
      })}
    </div>
  );
}

function KeepersEditor({ state, pool, act }: { state: MockState; pool: PoolPlayer[]; act: Act }) {
  const [team, setTeam] = useState(state.teams[0].team_id);
  const [round, setRound] = useState(state.settings.rounds);
  const [query, setQuery] = useState("");
  const byId = useMemo(() => new Map(pool.map((p) => [p.player_id, p])), [pool]);
  const kept = new Set(state.keepers.map((k) => k.player_id));
  const matches = query.trim()
    ? pool.filter((p) => !kept.has(p.player_id) && p.name.toLowerCase().includes(query.trim().toLowerCase())).slice(0, 6)
    : [];
  const save = (keepers: MockKeeper[]) => act({ type: "set_keepers", keepers });

  return (
    <Section
      title="Keepers"
      hint="A keeper uses that team's earliest pick in the chosen round and comes off the board before the draft starts."
    >
      <div className="flex flex-wrap items-end gap-2 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-neutral-500">Team</span>
          <select className="input w-40" value={team} onChange={(e) => setTeam(Number(e.target.value))}>
            {state.teams.map((t) => (
              <option key={t.team_id} value={t.team_id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-neutral-500">Round</span>
          <select className="input w-20" value={round} onChange={(e) => setRound(Number(e.target.value))}>
            {Array.from({ length: state.settings.rounds }, (_, i) => i + 1).map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <div className="relative flex min-w-[10rem] flex-1 flex-col gap-1">
          <span className="text-xs text-neutral-500">Player</span>
          <input className="input" placeholder="Search to add" value={query} onChange={(e) => setQuery(e.target.value)} />
          {matches.length > 0 && (
            <ul className="absolute z-20 mt-1 w-full rounded-md border border-neutral-200 bg-white shadow-lg dark:border-neutral-700 dark:bg-neutral-900">
              {matches.map((p) => (
                <li key={p.player_id}>
                  <button
                    className="w-full px-3 py-1.5 text-left text-sm hover:bg-neutral-100 dark:hover:bg-neutral-800"
                    onClick={() => {
                      setQuery("");
                      void save([...state.keepers, { team_id: team, player_id: p.player_id, round }]);
                    }}
                  >
                    {p.name} <span className="text-xs text-neutral-500">{p.pos_rank}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      {state.keepers.length > 0 ? (
        <ul className="space-y-1 text-sm">
          {state.keepers.map((k) => (
            <li key={k.player_id} className="flex items-center gap-2">
              <span className="w-10 text-xs text-neutral-400">R{k.round}</span>
              <span className="flex-1 truncate">
                <b>{byId.get(k.player_id)?.name ?? k.player_id}</b> — {teamName(state, k.team_id)}
              </span>
              <button
                className="text-xs text-neutral-500 hover:underline"
                onClick={() => void save(state.keepers.filter((x) => x.player_id !== k.player_id))}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-neutral-500">No keepers.</p>
      )}
    </Section>
  );
}

function SleeperImport({ state, act }: { state: MockState; act: Act }) {
  const [leagueId, setLeagueId] = useState("");
  const [season, setSeason] = useState(state.settings.season);
  return (
    <Section
      title="Import from a Sleeper league"
      hint="Pulls team names, roster settings, rounds, and every traded pick for the chosen season from your real league. Replaces current teams, trades and keepers."
    >
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (leagueId.trim()) void act({ type: "import_sleeper", league_id: leagueId.trim(), season });
        }}
      >
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-xs text-neutral-500">Sleeper league ID (this season's league)</span>
          <input className="input" inputMode="numeric" value={leagueId} onChange={(e) => setLeagueId(e.target.value)} placeholder="e.g. 1180234567890123456" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-neutral-500">Picks for</span>
          <input className="input w-20" value={season} maxLength={4} onChange={(e) => setSeason(e.target.value)} />
        </label>
        <button className="btn-primary" type="submit" disabled={!leagueId.trim()}>
          Import
        </button>
      </form>
    </Section>
  );
}

/** Small dialog opened by tapping a board cell in the lobby: reassign that one pick. */
export function PickOwnerDialog({
  state,
  pick,
  act,
  onClose,
}: {
  state: MockState;
  pick: { round: number; slot: number; original_team_id: number; owner_team_id: number };
  act: Act;
  onClose: () => void;
}) {
  const [owner, setOwner] = useState<string>(String(pick.owner_team_id));
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="card w-full max-w-sm space-y-3" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-semibold">
          Pick {pickLabel(pick)} — {teamName(state, pick.original_team_id)}'s round {pick.round}
        </h3>
        <select className="input" value={owner} onChange={(e) => setOwner(e.target.value)}>
          {state.teams.map((t) => (
            <option key={t.team_id} value={t.team_id}>
              {t.name}
              {t.team_id === pick.original_team_id ? " (original)" : ""}
            </option>
          ))}
          {state.status === "lobby" && <option value="none">Nobody (remove pick)</option>}
        </select>
        <div className="flex justify-end gap-2">
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            onClick={() =>
              void act({
                type: "set_pick_owner",
                round: pick.round,
                original_team_id: pick.original_team_id,
                owner_team_id: owner === "none" ? null : Number(owner),
              }).then(onClose)
            }
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
