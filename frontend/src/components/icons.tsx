/** Minimal hand-rolled stroke icons (24x24, currentColor) -- no icon-library
 * dependency, and every one inherits text color so retheming nav links
 * (CLAUDE.md section 6.3) is just a Tailwind class, not a prop per icon. */
import type { SVGProps } from "react";

function Icon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    />
  );
}

export function ChatIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M4 5h16v11H8l-4 4V5Z" />
    </Icon>
  );
}

export function RosterIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <circle cx={12} cy={8} r={3.25} />
      <path d="M5 20c0-3.5 3.1-6 7-6s7 2.5 7 6" />
    </Icon>
  );
}

export function RankingsIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M4 20V11M10 20V4M16 20v-7M20 20H4" />
    </Icon>
  );
}

export function KeepersIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M12 3.5l2.4 4.9 5.4.8-3.9 3.8.9 5.4-4.8-2.6-4.8 2.6.9-5.4-3.9-3.8 5.4-.8L12 3.5Z" />
    </Icon>
  );
}

export function TradeIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M4 8h13M13 4l4 4-4 4M20 16H7M11 20l-4-4 4-4" />
    </Icon>
  );
}

export function DraftIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <rect x={5} y={4} width={14} height={17} rx={1.5} />
      <path d="M9 4V3h6v1M8 10h8M8 14h8M8 18h5" />
    </Icon>
  );
}

export function SettingsIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <circle cx={12} cy={12} r={3} />
      <path d="M12 4v2.2M12 17.8V20M4 12h2.2M17.8 12H20M6.3 6.3l1.6 1.6M16.1 16.1l1.6 1.6M6.3 17.7l1.6-1.6M16.1 7.9l1.6-1.6" />
    </Icon>
  );
}

export function CloseIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M6 6l12 12M18 6L6 18" />
    </Icon>
  );
}
