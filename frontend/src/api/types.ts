/**
 * Hand-written mirror of backend/app/schemas.py.
 *
 * CLAUDE.md section 6.4 calls for generating these from the backend's
 * OpenAPI schema (`npm run gen:types`, wired below to write
 * src/api/schema.ts via openapi-typescript); open question #4 in that doc
 * leaves committed-vs-generated undecided. Plain hand-written interfaces
 * are what every hook and component actually imports here, since they're
 * far easier to read and edit than the deeply-nested generated path types --
 * regenerate schema.ts against a running backend if you want to diff the
 * two, but update this file by hand when a response model changes shape.
 */

export interface League {
  league_id: string;
  name: string;
  season: string;
  total_rosters: number;
  roster_positions: string[];
  scoring_settings: Record<string, number>;
  settings: Record<string, unknown>;
}

export interface Team {
  owner_user_id: string;
  team_name: string;
  roster_id: number;
}

export interface RosterPlayer {
  player_id: string;
  name: string;
  position: string | null;
  team: string | null;
  rank_ecr: number | null;
  pos_rank: string | null;
  group: "starter" | "bench" | "ir" | "taxi";
  slot: string | null;
}

export interface MyRoster {
  team_name: string;
  owner_user_id: string;
  players: RosterPlayer[];
}

// Mirrors backend InjuryNoteOut -- shared by power rankings and trade
// results, same injury-adjusted-value detail in both.
export interface InjuryNote {
  player_id: string;
  name: string;
  injury_status: string;
  multiplier: number;
  reason: string;
}

export interface StarterSlot {
  slot: string;
  player_id: string | null;
  name: string | null;
  position: string | null;
  rank_ecr: number | null;
  value: number;
  injury_status: string | null;
}

export interface TeamPowerRanking {
  rank: number;
  team_name: string;
  owner_user_id: string;
  starting_lineup_value: number;
  average_starter_rank: number | null;
  starters: StarterSlot[];
  positional_value: Record<string, number>;
  positional_rank: Record<string, number>;
  injured_players: InjuryNote[];
}

export interface KeeperCandidate {
  player_id: string;
  name: string;
  position: string;
  team: string | null;
  rank_ecr: number | null;
  pos_rank: string | null;
  drafted_round: number;
  was_drafted: boolean;
  cost_round: number;
  replacement_rank: number;
  value_surplus: number | null;
  reasoning: string;
}

export interface Ranking {
  rank_ecr: number;
  name: string;
  position: string;
  team: string | null;
  pos_rank: string | null;
  sleeper_player_id: string | null;
}

export interface PlayerSearchResult {
  player_id: string;
  full_name: string | null;
  position: string | null;
  team: string | null;
}

export interface SyncStatusEntry {
  resource: string;
  last_synced_at: string;
}

export interface BestAvailablePlayer {
  player_id: string;
  name: string;
  position: string;
  team: string | null;
  rank_ecr: number;
  pos_rank: string | null;
  reasoning: string;
}

export interface GameLine {
  week: number;
  points_ppr: number | null;
  stat_line: string;
}

export interface PlayerAnalysis {
  player_id: string;
  season: string;
  games: GameLine[];
  avg_points: number | null;
  blurb: string;
}

export interface TradeEvaluateRequest {
  side_a_owner: string;
  side_a_gives: string[];
  side_b_owner: string;
  side_b_gives: string[];
  league_id?: string;
}

export interface TradeSideResult {
  owner_user_id: string;
  team_name: string;
  gives: string[];
  receives: string[];
  value_given: number;
  value_received: number;
  net_value: number;
  position_counts_before: Record<string, number>;
  position_counts_after: Record<string, number>;
  reasoning: string;
  injured_players_given: InjuryNote[];
  injured_players_received: InjuryNote[];
}

export interface TradeEvaluation {
  side_a: TradeSideResult;
  side_b: TradeSideResult;
  verdict: string;
}

export interface JobStatus {
  job_id: string;
  status: "pending" | "running" | "done" | "failed";
  error: string | null;
}

export interface AgentHistoryTurn {
  role: "user" | "assistant";
  content: string;
}

export interface AgentAskRequest {
  question: string;
  history: AgentHistoryTurn[];
}

export interface AgentStep {
  tool_name: string;
  arguments: Record<string, unknown>;
  output_preview: string;
  error: boolean;
}

export interface AgentUsage {
  input_tokens: number;
  cached_tokens: number;
  output_tokens: number;
}

export interface AgentResult {
  answer: string;
  steps: AgentStep[];
  usage: AgentUsage;
}

export interface Account {
  id: number;
  email: string;
  display_name: string | null;
  default_league_id: string | null;
  default_owner_user_id: string | null;
}

export interface AuthResponse {
  token: string;
  account: Account;
}

export interface SignupRequest {
  email: string;
  password: string;
  display_name?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface AccountUpdateRequest {
  default_league_id: string | null;
  default_owner_user_id: string | null;
}
