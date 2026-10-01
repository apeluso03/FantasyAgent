import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

export interface PlayerPanelTarget {
  playerId: string;
  name: string;
  position?: string | null;
  team?: string | null;
  rankEcr?: number | null;
  posRank?: string | null;
}

interface PlayerPanelContextValue {
  target: PlayerPanelTarget | null;
  openPlayer: (target: PlayerPanelTarget) => void;
  closePlayer: () => void;
}

const PlayerPanelContext = createContext<PlayerPanelContextValue | null>(null);

export function PlayerPanelProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<PlayerPanelTarget | null>(null);

  const value = useMemo<PlayerPanelContextValue>(
    () => ({ target, openPlayer: setTarget, closePlayer: () => setTarget(null) }),
    [target],
  );

  return <PlayerPanelContext.Provider value={value}>{children}</PlayerPanelContext.Provider>;
}

export function usePlayerPanel(): PlayerPanelContextValue {
  const ctx = useContext(PlayerPanelContext);
  if (!ctx) throw new Error("usePlayerPanel must be used within a PlayerPanelProvider");
  return ctx;
}
