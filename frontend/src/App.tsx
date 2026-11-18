import { Navigate, Route, Routes } from "react-router-dom";

import { api } from "@/api/client";

import { AppShell } from "@/components/layout/AppShell";
import { ChatPage } from "@/pages/ChatPage";
import { DraftBoardPage } from "@/pages/DraftBoardPage";
import { KeepersPage } from "@/pages/KeepersPage";
import { LandingPage } from "@/pages/LandingPage";
import { MockDraftRoomPage } from "@/pages/MockDraftRoomPage";
import { MockJoinPage } from "@/pages/MockJoinPage";
import { MockLobbyPage } from "@/pages/MockLobbyPage";
import { MyRosterPage } from "@/pages/MyRosterPage";
import { PowerRankingsPage } from "@/pages/PowerRankingsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { TradeAnalyzerPage } from "@/pages/TradeAnalyzerPage";
import { MOCK_ONLY } from "@/lib/appMode";
import { useAuth } from "@/state/AuthContext";
import { LeagueProvider } from "@/state/LeagueContext";
import { PlayerPanelProvider } from "@/state/PlayerPanelContext";

function AuthenticatedApp() {
  return (
    <LeagueProvider>
      <PlayerPanelProvider>
        <AppShell>
          <Routes>
            <Route path="/" element={<ChatPage />} />
            <Route path="/roster" element={<MyRosterPage />} />
            <Route path="/rankings" element={<PowerRankingsPage />} />
            <Route path="/keepers" element={<KeepersPage />} />
            <Route path="/trade" element={<TradeAnalyzerPage />} />
            <Route path="/draft" element={<DraftBoardPage />} />
            <Route path="/mock" element={<MockLobbyPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AppShell>
      </PlayerPanelProvider>
    </LeagueProvider>
  );
}

/** The whole signed-in site when deployed with VITE_APP_MODE=mock: just the
 * mock draft lobby under a slim header. */
function MockOnlyApp() {
  const { account, logout } = useAuth();
  return (
    <div className="min-h-screen bg-neutral-50 dark:bg-neutral-950">
      <header className="border-b border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-4 py-3">
          <span className="page-title">2027 Mock Draft</span>
          <div className="flex items-center gap-3 text-sm">
            <span className="hidden text-neutral-500 sm:inline">{account?.email}</span>
            <button
              className="btn-secondary py-1.5"
              onClick={() => {
                // Revoke server-side too; sign out locally regardless.
                void api.post("/api/auth/logout").catch(() => undefined).finally(logout);
              }}
            >
              Log out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-6">
        <Routes>
          <Route path="/mock" element={<MockLobbyPage />} />
          <Route path="*" element={<Navigate to="/mock" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function GatedApp() {
  const { account, isLoading } = useAuth();

  if (isLoading) {
    // Validating a stored token -- avoid flashing the landing page for an
    // already-signed-in visitor while that round trip is in flight.
    return <div className="min-h-screen bg-neutral-50 dark:bg-neutral-950" />;
  }

  if (!account) return <LandingPage />;
  return MOCK_ONLY ? <MockOnlyApp /> : <AuthenticatedApp />;
}

export default function App() {
  // The mock draft room and its invite links are reachable signed out:
  // invited friends join with just a name (a per-draft token, not an
  // account). Creating a draft still needs an account -- that's /mock,
  // inside the gated app.
  return (
    <Routes>
      <Route path="/mock/join/:code" element={<MockJoinPage />} />
      <Route path="/mock/draft/:draftId" element={<MockDraftRoomPage />} />
      <Route path="*" element={<GatedApp />} />
    </Routes>
  );
}
