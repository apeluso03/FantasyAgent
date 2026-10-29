import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { LeagueBanner } from "@/components/LeagueBanner";
import { PlayerPanel } from "@/components/PlayerPanel";
import { cn } from "@/lib/cn";

import {
  ChatIcon,
  DraftIcon,
  KeepersIcon,
  RankingsIcon,
  RosterIcon,
  SettingsIcon,
  TradeIcon,
} from "../icons";

const NAV_ITEMS = [
  { to: "/", label: "Chat", Icon: ChatIcon },
  { to: "/roster", label: "My Roster", Icon: RosterIcon },
  { to: "/rankings", label: "Power Rankings", Icon: RankingsIcon },
  { to: "/keepers", label: "Keepers", Icon: KeepersIcon },
  { to: "/trade", label: "Trade", Icon: TradeIcon },
  { to: "/draft", label: "Draft Board", Icon: DraftIcon },
  { to: "/settings", label: "Settings", Icon: SettingsIcon },
] as const;

function NavItem({ to, label, Icon, variant }: (typeof NAV_ITEMS)[number] & { variant: "sidebar" | "tabbar" }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 rounded-md text-sm font-medium transition-colors",
          variant === "sidebar" ? "px-3 py-2" : "flex-1 flex-col gap-0.5 py-1.5 text-[11px]",
          isActive
            ? "bg-celadon-light text-hunter-dark dark:bg-hunter-dark dark:text-celadon-light"
            : "text-neutral-600 hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800",
        )
      }
    >
      <Icon className={variant === "sidebar" ? "h-5 w-5" : "h-5 w-5"} />
      <span>{label}</span>
    </NavLink>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <nav className="hidden w-56 flex-col gap-1 border-r border-neutral-200 p-3 md:flex dark:border-neutral-800">
        <div className="page-title px-3 py-2">FantasyAgent</div>
        {NAV_ITEMS.map((item) => (
          <NavItem key={item.to} {...item} variant="sidebar" />
        ))}
      </nav>

      <main className="flex-1 pb-20 md:pb-0">
        <div className="mx-auto max-w-4xl px-4 py-6">
          <LeagueBanner />
          {children}
        </div>
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-30 flex border-t border-neutral-200 bg-white md:hidden dark:border-neutral-800 dark:bg-neutral-900">
        {NAV_ITEMS.map((item) => (
          <NavItem key={item.to} {...item} variant="tabbar" />
        ))}
      </nav>

      <PlayerPanel />
    </div>
  );
}
