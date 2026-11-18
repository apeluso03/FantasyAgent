/** Hand-written mirror of the mock draft API (backend/app/routers/mock.py
 * and backend/app/mock/views.py). Kept separate from types.ts since the mock
 * draft is its own feature with its own auth (per-draft participant tokens). */

export type Position = "QB" | "RB" | "WR" | "TE" | "K" | "DEF";
export type SlotName = Position | "FLEX" | "SUPER_FLEX" | "BN";
export type DraftType = "snake" | "linear" | "3rr";
export type AdpMode = "2027" | "dynasty" | "redraft";
export type DraftStatus = "lobby" | "drafting" | "paused" | "complete";

export interface MockSettings {
  num_teams: number;
  rounds: number;
  draft_type: DraftType;
  roster_slots: Record<SlotName, number>;
  scoring: string;
  pick_seconds: number;
  cpu_pick_seconds: number;
  adp_mode: AdpMode;
  include_rookies: boolean;
  cpu_randomness: number;
  season: string;
}

export interface MockTeam {
  team_id: number;
  name: string;
  participant_id: string | null;
  participant_name: string | null;
  autopick: boolean;
  is_cpu: boolean;
  online: boolean;
}

export interface MockParticipant {
  participant_id: string;
  name: string;
  is_host: boolean;
  online: boolean;
  team_id: number | null;
}

export interface MockPick {
  overall: number;
  round: number;
  slot: number;
  original_team_id: number;
  owner_team_id: number;
  player_id: string | null;
  is_keeper: boolean;
  auto: boolean;
}

export interface TradedPick {
  round: number;
  original_team_id: number;
  owner_team_id: number | null;
}

export interface MockKeeper {
  team_id: number;
  player_id: string;
  round: number;
}

export interface ChatMessage {
  participant_id: string | null;
  name: string;
  text: string;
  ts: number;
}

export interface MockState {
  draft_id: string;
  name: string;
  invite_code: string;
  status: DraftStatus;
  version: number;
  settings: MockSettings;
  teams: MockTeam[];
  participants: MockParticipant[];
  picks: MockPick[];
  traded_picks: TradedPick[];
  keepers: MockKeeper[];
  current_overall: number | null;
  deadline: number | null;
  paused_remaining: number | null;
  server_time: number;
  chat: ChatMessage[];
  problems: string[];
  me: {
    participant_id: string | null;
    name: string | null;
    is_host: boolean;
    team_id: number | null;
    queue: string[];
  };
}

export interface PoolPlayer {
  player_id: string;
  name: string;
  position: Position;
  team: string | null;
  adp: number;
  pos_rank: string | null;
  is_rookie: boolean;
  college: string | null;
  years_exp: number | null;
}

export interface DraftCredentials {
  draft_id: string;
  invite_code: string;
  participant_id: string;
  token: string;
}

export interface DraftSummary {
  draft_id: string;
  name: string;
  invite_code: string;
  status: DraftStatus;
  num_teams: number;
  open_seats: number;
  teams: { team_id: number; name: string; claimed_by: string | null }[];
}

export type MockAction =
  | { type: "pick"; player_id: string }
  | { type: "queue"; player_ids: string[] }
  | { type: "autopick"; enabled: boolean }
  | { type: "chat"; text: string }
  | { type: "claim_seat"; team_id: number }
  | { type: "leave_seat" }
  | { type: "update_settings"; settings: Omit<MockSettings, "scoring" | "season"> }
  | { type: "rename_team"; team_id: number; name: string }
  | { type: "rename_draft"; name: string }
  | { type: "set_order"; team_ids: number[] }
  | { type: "randomize_order" }
  | { type: "set_pick_owner"; round: number; original_team_id: number; owner_team_id: number | null }
  | { type: "set_keepers"; keepers: MockKeeper[] }
  | { type: "assign_seat"; team_id: number; participant_id: string | null }
  | { type: "kick"; participant_id: string }
  | { type: "import_sleeper"; league_id: string; season?: string }
  | { type: "start" }
  | { type: "pause" }
  | { type: "resume" }
  | { type: "undo" }
  | { type: "force_pick" }
  | { type: "reset" };
