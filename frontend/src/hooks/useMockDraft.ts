import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "@/api/client";
import { mockApi, socketUrl } from "@/api/mockClient";
import type { MockAction, MockState, PoolPlayer } from "@/api/mockTypes";

export type ConnectionStatus = "connecting" | "open" | "reconnecting" | "closed";

/**
 * One live mock draft: the server pushes a full state snapshot over a
 * websocket after every change (picks, joins, chat, clock), and actions go
 * out over plain REST so errors come back as normal responses. Reconnects
 * with backoff; while disconnected it falls back to polling so a flaky
 * phone connection never shows a frozen board.
 */
export function useMockDraft(draftId: string, token: string | null) {
  const [state, setState] = useState<MockState | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [connection, setConnection] = useState<ConnectionStatus>("connecting");
  // Server clock minus local clock, in seconds -- keeps every viewer's pick
  // timer in sync even when device clocks disagree.
  const [clockOffset, setClockOffset] = useState(0);
  const versionRef = useRef(-1);

  const accept = useCallback((next: MockState) => {
    // Out-of-order guard: a REST response can land after a newer push.
    if (next.version < versionRef.current) return;
    versionRef.current = next.version;
    setClockOffset(next.server_time - Date.now() / 1000);
    setState(next);
  }, []);

  useEffect(() => {
    if (!token) return;
    let socket: WebSocket | null = null;
    let closedByUs = false;
    let attempt = 0;
    let retryTimer: number | undefined;
    let pollTimer: number | undefined;

    const poll = () => {
      mockApi
        .state(draftId, token)
        .then(accept)
        .catch((e: unknown) => {
          if (e instanceof ApiError && (e.status === 401 || e.status === 404)) setError(e);
        });
    };

    const connect = () => {
      setConnection(attempt === 0 ? "connecting" : "reconnecting");
      socket = new WebSocket(socketUrl(draftId, token));
      socket.onopen = () => {
        attempt = 0;
        setConnection("open");
        window.clearInterval(pollTimer);
        pollTimer = undefined;
      };
      socket.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "state") accept(msg.state as MockState);
      };
      socket.onclose = (event) => {
        if (closedByUs) return;
        if (event.code === 4401 || event.code === 4404 || event.code === 4403) {
          setConnection("closed");
          setError(
            new ApiError(
              event.code === 4404 ? 404 : 401,
              event.code === 4403
                ? "The host removed you from this draft."
                : event.code === 4404
                  ? "This draft no longer exists."
                  : "You're not in this draft. Use the invite link to join.",
            ),
          );
          return;
        }
        attempt += 1;
        setConnection("reconnecting");
        if (pollTimer === undefined) pollTimer = window.setInterval(poll, 3000);
        retryTimer = window.setTimeout(connect, Math.min(10_000, 500 * 2 ** attempt));
      };
    };

    poll();
    connect();
    const ping = window.setInterval(() => {
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "ping" }));
    }, 25_000);

    return () => {
      closedByUs = true;
      window.clearTimeout(retryTimer);
      window.clearInterval(pollTimer);
      window.clearInterval(ping);
      socket?.close();
    };
  }, [draftId, token, accept]);

  const settings = state?.settings;
  const pool = useQuery({
    queryKey: ["mock-pool", draftId, settings?.adp_mode, settings?.include_rookies, state?.keepers.length],
    queryFn: () => mockApi.pool(draftId, token!),
    enabled: !!token && !!state,
    staleTime: Infinity,
  });

  const [pending, setPending] = useState(false);
  const act = useCallback(
    async (action: MockAction) => {
      if (!token) return;
      setPending(true);
      try {
        accept(await mockApi.act(draftId, token, action));
      } finally {
        setPending(false);
      }
    },
    [draftId, token, accept],
  );

  const poolById = useMemo(() => {
    const map = new Map<string, PoolPlayer>();
    for (const p of pool.data ?? []) map.set(p.player_id, p);
    return map;
  }, [pool.data]);

  return { state, error, connection, clockOffset, pool, poolById, act, pending };
}

/** Seconds left on the pick clock, ticking locally between server pushes. */
export function useCountdown(deadline: number | null, clockOffset: number): number | null {
  const [now, setNow] = useState(() => Date.now() / 1000 + clockOffset);
  useEffect(() => {
    if (deadline == null) return;
    const id = window.setInterval(() => setNow(Date.now() / 1000 + clockOffset), 250);
    return () => window.clearInterval(id);
  }, [deadline, clockOffset]);
  if (deadline == null) return null;
  return Math.max(0, deadline - now);
}
