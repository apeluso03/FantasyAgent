import { Link } from "react-router-dom";

import { useLeague } from "@/hooks/useLeague";
import { useLeagueOverride } from "@/state/LeagueContext";

/** Shown on every page while a league override is active (Settings page),
 * so it's never ambiguous which league -- the server's configured default,
 * or a different one being tried out -- is on screen. */
export function LeagueBanner() {
  const { override } = useLeagueOverride();
  const league = useLeague(override?.leagueId);

  if (!override) return null;

  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-md bg-celadon-light px-3 py-2 text-sm text-hunter-dark dark:bg-hunter-dark dark:text-celadon-light">
      <span>
        Viewing a different league: <strong>{league.data?.name ?? override.leagueId}</strong>
        {!override.ownerUserId && " -- pick your team in Settings to see My Roster/Keepers/Draft Board"}
      </span>
      <Link to="/settings" className="font-medium underline underline-offset-2">
        Settings
      </Link>
    </div>
  );
}
