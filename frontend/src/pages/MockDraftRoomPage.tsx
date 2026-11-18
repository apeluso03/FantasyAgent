import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, getAuthToken } from "@/api/client";
import { clearCredentials, loadCredentials, mockApi, saveCredentials } from "@/api/mockClient";
import type { DraftCredentials, MockAction, MockPick, MockState, PoolPlayer } from "@/api/mockTypes";
import { DraftGrid } from "@/components/mock/DraftGrid";
import { HostSetup, PickOwnerDialog } from "@/components/mock/HostSetup";
import { picksUntil } from "@/components/mock/mockUtils";
import { PickTicker } from "@/components/mock/PickTicker";
import { PlayerList } from "@/components/mock/PlayerList";
import { ResultsView } from "@/components/mock/ResultsView";
import { ChatPanel, QueuePanel, RosterPanel } from "@/components/mock/SidePanels";
import { useMockDraft } from "@/hooks/useMockDraft";
import { cn } from "@/lib/cn";

type Tab = "board" | "players" | "queue" | "rosters" | "chat" | "setup" | "results";
const MAIN_TABS: Tab[] = ["board", "setup", "results"];

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const mql = window.matchMedia?.(query);
    if (!mql) return;
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

/**
 * The live draft room, laid out like Sleeper's: the on-the-clock strip and
 * pick ticker across the top, the board filling the main area, and a tabbed
 * panel (players / queue / rosters / chat) beside it -- or, on a phone, every
 * one of those as its own tab.
 */
export function MockDraftRoomPage() {
  const { draftId = "" } = useParams();
  const [creds, setCreds] = useState<DraftCredentials | null>(() => loadCredentials(draftId));
  const [reclaimFailed, setReclaimFailed] = useState(false);

  // A host on a new device: if they're signed in, the server re-issues their seat token.
  useEffect(() => {
    if (creds || !getAuthToken()) {
      if (!creds) setReclaimFailed(true);
      return;
    }
    api
      .post<DraftCredentials>(`/api/mock/drafts/${draftId}/host-token`)
      .then((c) => {
        saveCredentials(c);
        setCreds(c);
      })
      .catch(() => setReclaimFailed(true));
  }, [creds, draftId]);

  if (!creds) {
    if (!reclaimFailed) return <FullScreenMessage title="Loading draft..." />;
    return (
      <FullScreenMessage
        title="You're not in this draft"
        body="Ask the host for the invite link to join."
        action={<Link to="/mock" className="btn-primary">Go to mock drafts</Link>}
      />
    );
  }
  return <Room draftId={draftId} token={creds.token} />;
}

function Room({ draftId, token }: { draftId: string; token: string }) {
  const navigate = useNavigate();
  const { state, error, connection, clockOffset, pool, poolById, act: rawAct, pending } = useMockDraft(draftId, token);
  const [tab, setTab] = useState<Tab | null>(null); // phone: the one visible panel
  const [mainSel, setMainSel] = useState<Tab | null>(null); // desktop: left panel
  const [sideSel, setSideSel] = useState<Tab | null>(null); // desktop: right panel
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  const [actionError, setActionError] = useState<string | null>(null);
  const [editPick, setEditPick] = useState<MockPick | null>(null);
  const [copied, setCopied] = useState(false);

  const act = async (a: MockAction) => {
    setActionError(null);
    try {
      await rawAct(a);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
      throw e;
    }
  };
  const safeAct = (a: MockAction) => act(a).catch(() => undefined);

  const drafted = useMemo(
    () => new Set((state?.picks ?? []).filter((p) => p.player_id).map((p) => p.player_id!)),
    [state?.picks],
  );

  const current = state?.picks.find((p) => p.overall === state.current_overall);
  const myTurn = !!state && state.status === "drafting" && current?.owner_team_id === state.me.team_id;

  // Flash the tab title when it's your pick -- easy to miss in another tab.
  useEffect(() => {
    if (!myTurn) {
      document.title = state ? `${state.name} · Mock Draft` : "Mock Draft";
      return;
    }
    let on = true;
    const id = window.setInterval(() => {
      document.title = on ? "⏰ Your pick!" : `${state?.name} · Mock Draft`;
      on = !on;
    }, 1000);
    return () => window.clearInterval(id);
  }, [myTurn, state?.name, state]);

  if (error) {
    if (error.status === 401 || error.status === 404) clearCredentials(draftId);
    return (
      <FullScreenMessage
        title={error.status === 404 ? "Draft not found" : "Can't open this draft"}
        body={error.message}
        action={<Link to="/mock" className="btn-primary">Go to mock drafts</Link>}
      />
    );
  }
  if (!state) return <FullScreenMessage title="Connecting to draft..." />;

  const isHost = state.me.is_host;
  const lobby = state.status === "lobby";
  const done = state.status === "complete";
  const canPick = state.status === "drafting" && (myTurn || isHost);
  const defaultTab: Tab = done ? "results" : lobby ? (isHost ? "setup" : "rosters") : "players";
  const inviteUrl = `${window.location.origin}/mock/join/${state.invite_code}`;
  const until = picksUntil(state, state.me.team_id);
  const myTeam = state.teams.find((t) => t.team_id === state.me.team_id);

  const onPick = (p: PoolPlayer) => {
    if (!myTurn && isHost && current) {
      const owner = state.teams.find((t) => t.team_id === current.owner_team_id)?.name;
      if (!window.confirm(`Draft ${p.name} for ${owner}?`)) return;
    }
    void safeAct({ type: "pick", player_id: p.player_id });
  };
  const toggleQueue = (p: PoolPlayer) => {
    const q = state.me.queue;
    void safeAct({
      type: "queue",
      player_ids: q.includes(p.player_id) ? q.filter((x) => x !== p.player_id) : [...q, p.player_id],
    });
  };
  const exportCsv = async () => {
    const blob = await mockApi.exportCsv(draftId, token);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${state.name.replace(/[^a-z0-9]+/gi, "-")}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const tabs: { id: Tab; label: string; show: boolean }[] = [
    { id: "board", label: "Board", show: true },
    { id: "results", label: "Results", show: done },
    { id: "setup", label: "Setup", show: lobby && isHost },
    { id: "players", label: "Players", show: true },
    { id: "queue", label: `Queue${state.me.queue.length ? ` (${state.me.queue.length})` : ""}`, show: !!state.me.participant_id },
    { id: "rosters", label: "Rosters", show: true },
    { id: "chat", label: "Chat", show: true },
  ];

  const activeTab: Tab = tabs.some((x) => x.id === tab && x.show) ? tab! : defaultTab;

  const panel = (t: Tab) => {
    switch (t) {
      case "board":
        return (
          <DraftGrid
            state={state}
            poolById={poolById}
            onPickClick={isHost && !done ? (p) => (p.player_id ? undefined : setEditPick(p)) : undefined}
          />
        );
      case "results":
        return <ResultsView state={state} poolById={poolById} />;
      case "setup":
        return <HostSetup state={state} pool={pool.data ?? []} act={act} />;
      case "players":
        return pool.isPending ? (
          <p className="p-6 text-center text-sm text-neutral-500">Loading players...</p>
        ) : (
          <PlayerList
            state={state}
            pool={pool.data ?? []}
            drafted={drafted}
            canPick={canPick}
            busy={pending}
            onPick={onPick}
            onToggleQueue={toggleQueue}
          />
        );
      case "queue":
        return (
          <QueuePanel
            state={state}
            poolById={poolById}
            drafted={drafted}
            canPick={canPick}
            onPick={onPick}
            onChange={(ids) => void safeAct({ type: "queue", player_ids: ids })}
          />
        );
      case "rosters":
        return lobby && !isHost ? <SeatPicker state={state} act={safeAct} /> : <RosterPanel state={state} poolById={poolById} />;
      case "chat":
        return <ChatPanel state={state} onSend={(text) => act({ type: "chat", text })} />;
    }
  };

  // A remembered tab can stop existing (Setup once the draft starts); fall back to the default then.
  const visible = (t: Tab | null): t is Tab => t != null && tabs.some((x) => x.id === t && x.show);
  const mainTab: Tab = visible(mainSel) ? mainSel : done ? "results" : lobby && isHost ? "setup" : "board";
  const sideTab: Tab = visible(sideSel) ? sideSel : lobby ? (isHost ? "chat" : "rosters") : "players";

  return (
    <div className="flex h-[100dvh] flex-col bg-neutral-50 text-neutral-900 dark:bg-neutral-950 dark:text-neutral-100">
      {/* Top bar */}
      <header className="flex flex-wrap items-center gap-2 border-b border-neutral-200 bg-white px-3 py-2 dark:border-neutral-800 dark:bg-neutral-900">
        <button onClick={() => navigate("/mock")} className="text-sm text-neutral-500 hover:text-neutral-800" aria-label="Back">
          ←
        </button>
        <div className="min-w-0">
          <div className="truncate font-semibold">{state.name}</div>
          <div className="text-[11px] text-neutral-500">
            {state.settings.num_teams} teams · {state.settings.rounds} rds · {state.settings.draft_type === "3rr" ? "3RR" : state.settings.draft_type} ·
            Superflex PPR · {state.settings.adp_mode === "2027" ? "2027 ADP" : state.settings.adp_mode === "dynasty" ? "Dynasty ADP" : "Redraft ADP"}
            {connection !== "open" && <span className="ml-2 text-amber-600">● {connection}</span>}
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {state.status === "drafting" && until != null && until > 0 && (
            <span className="text-xs text-neutral-500">Your pick in {until}</span>
          )}
          {myTeam && !lobby && !done && (
            <label className="flex items-center gap-1.5 text-xs">
              <input
                type="checkbox"
                checked={myTeam.autopick}
                onChange={(e) => void safeAct({ type: "autopick", enabled: e.target.checked })}
              />
              Autopick
            </label>
          )}
          {lobby && (
            <button
              className="btn-secondary py-1.5 text-xs"
              onClick={() => {
                void navigator.clipboard?.writeText(inviteUrl);
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1500);
              }}
              title={inviteUrl}
            >
              {copied ? "Copied!" : "Copy invite link"}
            </button>
          )}
          {isHost && <HostControls status={state.status} act={safeAct} problems={state.problems} />}
          {done && (
            <button className="btn-secondary py-1.5 text-xs" onClick={() => void exportCsv()}>
              Export CSV
            </button>
          )}
        </div>
      </header>

      {actionError && (
        <div className="flex items-center justify-between bg-rose-50 px-3 py-1.5 text-sm text-rose-700 dark:bg-rose-900/30 dark:text-rose-300">
          {actionError}
          <button onClick={() => setActionError(null)}>✕</button>
        </div>
      )}
      {lobby && state.problems.length > 0 && (
        <div className="bg-amber-50 px-3 py-1.5 text-xs text-amber-800 dark:bg-amber-900/30 dark:text-amber-300">
          {state.problems.join(" ")}
        </div>
      )}

      {!lobby && <PickTicker state={state} poolById={poolById} clockOffset={clockOffset} />}

      {isDesktop ? (
        // Desktop: board/setup/results on the left, players/queue/rosters/chat on the right.
        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">
            <nav className="flex border-b border-neutral-200 bg-white text-sm dark:border-neutral-800 dark:bg-neutral-900">
              {tabs
                .filter((t) => t.show && MAIN_TABS.includes(t.id))
                .map((t) => (
                  <TabButton key={t.id} active={mainTab === t.id} onClick={() => setMainSel(t.id)}>
                    {t.label}
                  </TabButton>
                ))}
            </nav>
            <div className="min-h-0 flex-1 overflow-auto p-1">{panel(mainTab)}</div>
          </div>
          <aside className="flex w-[440px] shrink-0 flex-col border-l border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
            <nav className="flex border-b border-neutral-200 text-sm dark:border-neutral-800">
              {tabs
                .filter((t) => t.show && !MAIN_TABS.includes(t.id))
                .map((t) => (
                  <TabButton key={t.id} active={sideTab === t.id} onClick={() => setSideSel(t.id)}>
                    {t.label}
                  </TabButton>
                ))}
            </nav>
            <div className="min-h-0 flex-1 overflow-auto">{panel(sideTab)}</div>
          </aside>
        </div>
      ) : (
        // Phone: every panel is its own tab.
        <>
          <nav className="flex overflow-x-auto border-b border-neutral-200 bg-white text-sm dark:border-neutral-800 dark:bg-neutral-900">
            {tabs
              .filter((t) => t.show)
              .map((t) => (
                <TabButton key={t.id} active={activeTab === t.id} onClick={() => setTab(t.id)}>
                  {t.label}
                </TabButton>
              ))}
          </nav>
          <main className="min-h-0 flex-1 overflow-auto">{panel(activeTab)}</main>
        </>
      )}

      {editPick && <PickOwnerDialog state={state} pick={editPick} act={act} onClose={() => setEditPick(null)} />}
    </div>
  );
}

function HostControls({
  status,
  act,
  problems,
}: {
  status: string;
  act: (a: MockAction) => Promise<unknown>;
  problems: string[];
}) {
  if (status === "lobby") {
    return (
      <button className="btn-primary py-1.5 text-xs" disabled={problems.length > 0} onClick={() => void act({ type: "start" })}>
        Start draft
      </button>
    );
  }
  return (
    <div className="flex gap-1">
      {status === "drafting" && (
        <>
          <button className="btn-secondary py-1.5 text-xs" onClick={() => void act({ type: "pause" })}>
            Pause
          </button>
          <button className="btn-secondary py-1.5 text-xs" onClick={() => void act({ type: "force_pick" })} title="Make the CPU pick now for whoever is on the clock">
            Autopick now
          </button>
        </>
      )}
      {status === "paused" && (
        <button className="btn-primary py-1.5 text-xs" onClick={() => void act({ type: "resume" })}>
          Resume
        </button>
      )}
      <button className="btn-secondary py-1.5 text-xs" onClick={() => void act({ type: "undo" })}>
        Undo pick
      </button>
      <button
        className="btn-secondary py-1.5 text-xs"
        onClick={() => {
          if (window.confirm("Reset the draft? Every pick (except keepers) is cleared and you're back in the lobby.")) void act({ type: "reset" });
        }}
      >
        Reset
      </button>
    </div>
  );
}

function SeatPicker({ state, act }: { state: MockState; act: (a: MockAction) => Promise<unknown> }) {
  return (
    <div className="space-y-2 p-3">
      <p className="text-sm text-neutral-500">
        Waiting for the host to start. Pick an open team, or stay where you are. Teams nobody claims are drafted by the CPU.
      </p>
      <ul className="space-y-1">
        {state.teams.map((t, i) => {
          const mine = t.team_id === state.me.team_id;
          return (
            <li key={t.team_id} className={cn("flex items-center gap-2 rounded-md border px-3 py-2 text-sm dark:border-neutral-800", mine && "border-hunter")}>
              <span className="w-5 text-xs text-neutral-400">{i + 1}</span>
              <span className="flex-1 font-medium">{t.name}</span>
              <span className="text-xs text-neutral-500">{t.participant_name ?? "CPU"}</span>
              {mine ? (
                <button className="text-xs text-neutral-500 hover:underline" onClick={() => void act({ type: "leave_seat" })}>
                  Leave
                </button>
              ) : t.is_cpu ? (
                <button className="btn-secondary py-1 text-xs" onClick={() => void act({ type: "claim_seat", team_id: t.team_id })}>
                  Take
                </button>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "shrink-0 border-b-2 px-3 py-2 font-medium",
        active ? "border-hunter text-hunter dark:border-celadon dark:text-celadon" : "border-transparent text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200",
      )}
    >
      {children}
    </button>
  );
}

function FullScreenMessage({ title, body, action }: { title: string; body?: string; action?: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50 p-6 dark:bg-neutral-950">
      <div className="card max-w-sm space-y-3 text-center">
        <h1 className="page-title">{title}</h1>
        {body && <p className="text-sm text-neutral-500">{body}</p>}
        {action}
      </div>
    </div>
  );
}
