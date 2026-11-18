import { expect, test, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { MockState, PoolPlayer } from "@/api/mockTypes";

import { DraftGrid } from "./DraftGrid";
import { assignLineup, picksUntil } from "./mockUtils";

function player(id: string, position: PoolPlayer["position"], adp: number): PoolPlayer {
  return { player_id: id, name: `Player ${id}`, position, team: "DAL", adp, pos_rank: null, is_rookie: false, college: null, years_exp: 2 };
}

const slots = { QB: 1, RB: 2, WR: 3, TE: 1, FLEX: 1, SUPER_FLEX: 1, K: 1, DEF: 0, BN: 6 };

function makeState(): MockState {
  const teams = [1, 2, 3].map((id) => ({
    team_id: id,
    name: `Team ${id}`,
    participant_id: id === 1 ? "me" : null,
    participant_name: id === 1 ? "Me" : null,
    autopick: false,
    is_cpu: id !== 1,
    online: id === 1,
  }));
  // 3 teams, 2 rounds, snake; Team 3 owns Team 1's 2nd-rounder.
  const picks = [
    { overall: 1, round: 1, slot: 1, original_team_id: 1, owner_team_id: 1, player_id: "a", is_keeper: false, auto: false },
    { overall: 2, round: 1, slot: 2, original_team_id: 2, owner_team_id: 2, player_id: null, is_keeper: false, auto: false },
    { overall: 3, round: 1, slot: 3, original_team_id: 3, owner_team_id: 3, player_id: null, is_keeper: false, auto: false },
    { overall: 4, round: 2, slot: 1, original_team_id: 3, owner_team_id: 3, player_id: null, is_keeper: false, auto: false },
    { overall: 5, round: 2, slot: 2, original_team_id: 2, owner_team_id: 2, player_id: null, is_keeper: false, auto: false },
    { overall: 6, round: 2, slot: 3, original_team_id: 1, owner_team_id: 3, player_id: null, is_keeper: false, auto: false },
  ];
  return {
    draft_id: "d",
    name: "Test",
    invite_code: "abc",
    status: "drafting",
    version: 1,
    settings: {
      num_teams: 3, rounds: 2, draft_type: "snake", roster_slots: slots, scoring: "ppr", pick_seconds: 60,
      cpu_pick_seconds: 1.5, adp_mode: "2027", include_rookies: true, cpu_randomness: 1, season: "2027",
    },
    teams,
    participants: [{ participant_id: "me", name: "Me", is_host: true, online: true, team_id: 1 }],
    picks,
    traded_picks: [{ round: 2, original_team_id: 1, owner_team_id: 3 }],
    keepers: [],
    current_overall: 2,
    deadline: null,
    paused_remaining: null,
    server_time: 0,
    chat: [],
    problems: [],
    me: { participant_id: "me", name: "Me", is_host: true, team_id: 1, queue: [] },
  };
}

test("board shows the drafted player and marks a traded pick with its new owner", () => {
  const state = makeState();
  const pool = new Map([["a", player("a", "QB", 1)]]);
  render(<DraftGrid state={state} poolById={pool} />);
  expect(screen.getByText("P. a")).toBeInTheDocument();
  // Team 1's column, round 2: owned by Team 3 now.
  expect(screen.getByTitle("Traded pick")).toHaveTextContent("→ Team 3");
  expect(screen.getByText("on the clock")).toBeInTheDocument();
});

test("host can click an open pick to edit it", () => {
  const state = makeState();
  const onPickClick = vi.fn();
  render(<DraftGrid state={state} poolById={new Map()} onPickClick={onPickClick} />);
  fireEvent.click(screen.getByTitle("Traded pick").closest("button")!);
  expect(onPickClick).toHaveBeenCalledWith(expect.objectContaining({ round: 2, original_team_id: 1, owner_team_id: 3 }));
});

test("assignLineup fills SUPER_FLEX with a second QB and FLEX with a third RB", () => {
  const roster = [player("q1", "QB", 1), player("r1", "RB", 2), player("q2", "QB", 3), player("r2", "RB", 4), player("r3", "RB", 5)];
  const lineup = assignLineup(roster, slots);
  const bySlot = (s: string) => lineup.filter((l) => l.slot === s).map((l) => l.player?.player_id ?? null);
  expect(bySlot("QB")).toEqual(["q1"]);
  expect(bySlot("SUPER_FLEX")).toEqual(["q2"]);
  expect(bySlot("FLEX")).toEqual(["r3"]);
  expect(bySlot("WR")).toEqual([null, null, null]);
});

test("picksUntil counts to the next pick a team owns, including acquired ones", () => {
  const state = makeState();
  expect(picksUntil(state, 3)).toBe(1);
  expect(picksUntil(state, 1)).toBe(null); // Team 1 traded away its only remaining pick
});
