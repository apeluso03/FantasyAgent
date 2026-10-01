import { Link } from "react-router-dom";

/** Shown instead of a page's normal content when a league override is
 * active but no "my team" has been picked for it yet -- querying with no
 * owner_user_id would just fall back to the server's own default, which
 * almost certainly isn't a valid owner in a different league. */
export function NeedsTeamPrompt() {
  return (
    <div className="card flex flex-col items-center gap-3 py-10 text-center">
      <p className="text-neutral-600 dark:text-neutral-300">Pick which team is yours in this league first.</p>
      <Link to="/settings" className="btn-primary">
        Pick your team in Settings
      </Link>
    </div>
  );
}
