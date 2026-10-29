import { useState } from "react";

import { cn } from "@/lib/cn";

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
  return (first + last).toUpperCase() || "?";
}

/** Sleeper's CDN headshots (CLAUDE.md section 6.3) with a circular
 * initials fallback on load error -- no disk cache needed, the browser
 * handles that. */
export function PlayerAvatar({
  playerId,
  name,
  size = 36,
}: {
  playerId: string;
  name: string;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);
  const style = { width: size, height: size };

  if (failed) {
    return (
      <div
        className="flex shrink-0 items-center justify-center rounded-full bg-celadon text-xs font-semibold text-hunter-dark dark:bg-hunter dark:text-celadon-light"
        style={style}
      >
        {initialsOf(name)}
      </div>
    );
  }

  return (
    <img
      src={`https://sleepercdn.com/content/nfl/players/thumb/${playerId}.jpg`}
      alt={name}
      className={cn("shrink-0 rounded-full bg-neutral-200 object-cover dark:bg-neutral-800")}
      style={style}
      onError={() => setFailed(true)}
    />
  );
}
