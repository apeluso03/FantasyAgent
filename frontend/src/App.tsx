import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { ChatPage } from "@/pages/ChatPage";
import { DraftBoardPage } from "@/pages/DraftBoardPage";
import { KeepersPage } from "@/pages/KeepersPage";
import { LandingPage } from "@/pages/LandingPage";
import { MyRosterPage } from "@/pages/MyRosterPage";
import { PowerRankingsPage } from "@/pages/PowerRankingsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { TradeAnalyzerPage } from "@/pages/TradeAnalyzerPage";
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
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AppShell>
      </PlayerPanelProvider>
    </LeagueProvider>
  );
}

export default function App() {
  const { account, isLoading } = useAuth();

  if (isLoading) {
    // Validating a stored token -- avoid flashing the landing page for an
    // already-signed-in visitor while that round trip is in flight.
    return <div className="min-h-screen bg-neutral-50 dark:bg-neutral-950" />;
  }

  return account ? <AuthenticatedApp /> : <LandingPage />;
}
