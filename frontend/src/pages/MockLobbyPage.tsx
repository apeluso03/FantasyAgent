import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "@/api/client";
import { saveCredentials } from "@/api/mockClient";
import type { AdpMode, DraftCredentials, DraftSummary, Position } from "@/api/mockTypes";
import { POSITION_STYLES } from "@/components/mock/mockUtils";
import { Badge } from "@/components/ui/Badge";
import { PlayerAvatar } from "@/components/ui/PlayerAvatar";
import { QueryBoundary } from "@/components/ui/QueryBoundary";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/cn";
import { useAuth } from "@/state/AuthContext";

interface AdpRow {
  player_id: string;
  name: string;
  position: Position;
  team: string | null;
  college: string | null;
  is_rookie: boolean;
  adp: number;
}

export function MockLobbyPage() {
  const navigate = useNavigate();
  const { account } = useAuth();
  const [name, setName] = useState("2027 Mock Draft");
  const [hostName, setHostName] = useState(account?.display_name ?? "");
  const [numTeams, setNumTeams] = useState(12);
  const [pickSeconds, setPickSeconds] = useState(60);

  const drafts = useQuery({
    queryKey: ["mock-drafts"],
    queryFn: () => api.get<DraftSummary[]>("/api/mock/drafts"),
  });

  const create = useMutation({
    mutationFn: () =>
      api.post<DraftCredentials>("/api/mock/drafts", {
        name,
        host_name: hostName || undefined,
        settings: { num_teams: numTeams, pick_seconds: pickSeconds },
      }),
    onSuccess: (creds) => {
      saveCredentials(creds);
      navigate(`/mock/draft/${creds.draft_id}`);
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="page-title">Mock Draft</h1>
        <p className="text-sm text-neutral-500">
          Draft live with up to 12 people for the 2027 season — superflex PPR by default, 2027 ADP with the incoming rookie
          class, traded picks and keepers. Empty seats are drafted by the CPU.
        </p>
      </div>

      <form
        className="card space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <h2 className="font-semibold">New mock draft</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span className="text-xs text-neutral-500">Draft name</span>
            <input className="input" maxLength={60} value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-xs text-neutral-500">Your name in the draft</span>
            <input className="input" maxLength={30} value={hostName} onChange={(e) => setHostName(e.target.value)} placeholder={account?.email.split("@")[0]} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-xs text-neutral-500">Teams</span>
            <select className="input" value={numTeams} onChange={(e) => setNumTeams(Number(e.target.value))}>
              {Array.from({ length: 11 }, (_, i) => i + 2).map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-xs text-neutral-500">Pick timer</span>
            <select className="input" value={pickSeconds} onChange={(e) => setPickSeconds(Number(e.target.value))}>
              <option value={0}>No limit</option>
              <option value={30}>30 seconds</option>
              <option value={60}>1 minute</option>
              <option value={90}>90 seconds</option>
              <option value={180}>3 minutes</option>
            </select>
          </label>
        </div>
        <p className="text-xs text-neutral-500">
          Everything else (roster slots, rounds, draft type, traded picks, keepers, importing your Sleeper league) is set up
          in the draft room before you start.
        </p>
        {create.isError && <p className="text-sm text-rose-600">{create.error.message}</p>}
        <button className="btn-primary" disabled={create.isPending}>
          {create.isPending ? "Creating (first one builds the ADP board)..." : "Create draft room"}
        </button>
      </form>

      <section className="space-y-2">
        <h2 className="font-semibold">Your drafts</h2>
        <QueryBoundary query={drafts} loading={<Skeleton className="h-16" />}>
          {(list) =>
            list.length === 0 ? (
              <p className="text-sm text-neutral-500">None yet.</p>
            ) : (
              <ul className="space-y-2">
                {list.map((d) => (
                  <li key={d.draft_id}>
                    <Link to={`/mock/draft/${d.draft_id}`} className="card flex items-center justify-between hover:border-hunter">
                      <div>
                        <div className="font-medium">{d.name}</div>
                        <div className="text-xs text-neutral-500">
                          {d.num_teams} teams · {d.num_teams - d.open_seats} people
                        </div>
                      </div>
                      <Badge tone={d.status === "complete" ? "neutral" : d.status === "lobby" ? "brand" : "good"}>
                        {d.status === "lobby" ? "Lobby" : d.status === "complete" ? "Complete" : d.status === "paused" ? "Paused" : "Drafting"}
                      </Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            )
          }
        </QueryBoundary>
      </section>

      <AdpPreview />
    </div>
  );
}

function AdpPreview() {
  const [mode, setMode] = useState<AdpMode>("2027");
  const [rookiesOnly, setRookiesOnly] = useState(false);
  const adp = useQuery({
    queryKey: ["mock-adp", mode, rookiesOnly],
    queryFn: () =>
      api.get<{ built_at: string | null; players: AdpRow[] }>("/api/mock/adp", { mode, rookies_only: rookiesOnly, limit: 60 }),
  });

  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-semibold">ADP board</h2>
        <select className="input ml-auto w-auto py-1 text-xs" value={mode} onChange={(e) => setMode(e.target.value as AdpMode)}>
          <option value="2027">2027 projection</option>
          <option value="dynasty">Dynasty</option>
          <option value="redraft">Redraft</option>
        </select>
        <label className="flex items-center gap-1 text-xs">
          <input type="checkbox" checked={rookiesOnly} onChange={(e) => setRookiesOnly(e.target.checked)} /> 2027 rookies only
        </label>
      </div>
      <p className="text-xs text-neutral-500">
        Superflex blend of Sleeper redraft + dynasty ADP and FantasyPros dynasty superflex rankings, with the 2027 rookie class
        slotted in from a consensus of early prospect rankings.
      </p>
      <QueryBoundary query={adp} loading={<Skeleton className="h-40" />}>
        {(data) =>
          data.players.length === 0 ? (
            <p className="text-sm text-neutral-500">The board builds automatically when you create your first draft.</p>
          ) : (
            <div className="card divide-y divide-neutral-100 p-0 dark:divide-neutral-800">
              {data.players.map((p) => (
                <div key={p.player_id} className="flex items-center gap-3 px-3 py-1.5 text-sm">
                  <span className="w-8 tabular-nums text-neutral-400">{p.adp.toFixed(0)}</span>
                  <PlayerAvatar playerId={p.player_id} name={p.name} size={26} />
                  <span className="flex-1 truncate font-medium">{p.name}</span>
                  <span className={cn("rounded px-1.5 text-[11px] font-semibold", POSITION_STYLES[p.position].chip)}>{p.position}</span>
                  <span className="w-28 truncate text-right text-xs text-neutral-500">
                    {p.is_rookie ? `${p.college} (R)` : p.team ?? "FA"}
                  </span>
                </div>
              ))}
            </div>
          )
        }
      </QueryBoundary>
    </section>
  );
}
