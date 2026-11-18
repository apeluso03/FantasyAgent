import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";

import { loadCredentials, mockApi, saveCredentials } from "@/api/mockClient";

/** Public landing for an invite link -- no account needed, just a name. */
export function MockJoinPage() {
  const { code = "" } = useParams();
  const navigate = useNavigate();
  const [name, setName] = useState(() => {
    try {
      return localStorage.getItem("mock-draft-name") ?? "";
    } catch {
      return "";
    }
  });

  const info = useQuery({ queryKey: ["mock-invite", code], queryFn: () => mockApi.inviteInfo(code), retry: false });
  const join = useMutation({
    mutationFn: () => mockApi.join(code, name.trim()),
    onSuccess: (creds) => {
      saveCredentials(creds);
      try {
        localStorage.setItem("mock-draft-name", name.trim());
      } catch {
        // ignore
      }
      navigate(`/mock/draft/${creds.draft_id}`, { replace: true });
    },
  });

  useEffect(() => {
    document.title = info.data ? `Join ${info.data.name}` : "Join mock draft";
  }, [info.data]);

  // Already in this draft on this device -- go straight in.
  if (info.data && loadCredentials(info.data.draft_id)) {
    return <Navigate to={`/mock/draft/${info.data.draft_id}`} replace />;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50 p-4 dark:bg-neutral-950">
      <div className="card w-full max-w-sm space-y-4">
        {info.isPending && <p className="text-sm text-neutral-500">Loading invite...</p>}
        {info.isError && (
          <>
            <h1 className="page-title">Invite not found</h1>
            <p className="text-sm text-neutral-500">{info.error.message}</p>
          </>
        )}
        {info.data && (
          <>
            <div>
              <div className="text-xs uppercase tracking-wide text-neutral-400">You're invited to a mock draft</div>
              <h1 className="page-title">{info.data.name}</h1>
              <p className="text-sm text-neutral-500">
                {info.data.num_teams} teams · superflex PPR ·{" "}
                {info.data.status === "lobby"
                  ? `${info.data.open_seats} open seat${info.data.open_seats === 1 ? "" : "s"}`
                  : info.data.status === "complete"
                    ? "finished"
                    : "in progress"}
              </p>
            </div>
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                if (name.trim()) join.mutate();
              }}
            >
              <label className="block space-y-1 text-sm">
                <span className="text-xs text-neutral-500">Your name</span>
                <input className="input" autoFocus maxLength={30} value={name} onChange={(e) => setName(e.target.value)} required />
              </label>
              {join.isError && <p className="text-sm text-rose-600">{join.error.message}</p>}
              <button className="btn-primary w-full" disabled={join.isPending || !name.trim()}>
                {info.data.open_seats > 0 && info.data.status !== "complete" ? "Join draft" : "Join as spectator"}
              </button>
            </form>
            <p className="text-xs text-neutral-500">No account needed. You'll take the first open team, and can switch before the draft starts.</p>
          </>
        )}
      </div>
    </div>
  );
}
