import { Badge } from "@/components/ui/Badge";

// Mirrors the CLI's _INJURY_TAGS mapping and Settings.unavailable_injury_statuses
// -- short label plus a severity tone (can't play vs. discounted but starting).
const LABELS: Record<string, string> = {
  questionable: "Q",
  doubtful: "D",
  out: "O",
  ir: "IR",
  pup: "PUP",
  sus: "SUS",
};

const UNAVAILABLE = new Set(["out", "ir", "pup", "sus"]);

export function InjuryTag({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  const key = status.toLowerCase();
  const label = LABELS[key] ?? status.toUpperCase();
  return <Badge tone={UNAVAILABLE.has(key) ? "bad" : "warning"}>{label}</Badge>;
}
