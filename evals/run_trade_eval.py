"""Trade eval: ask the agent each question in trade_cases.toml and score it.

A case passes only if all three checks pass (see trade_cases.toml):
tool used, correct inputs, correct verdict. Runs against eval_snapshot.db,
never your live database, so scores stay comparable between runs.

    python evals/run_trade_eval.py                  # all cases, default model
    python evals/run_trade_eval.py --case fair_wr_swap --case multi_3_for_2
    python evals/run_trade_eval.py --repeat 3       # agent output varies; check consistency
    python evals/run_trade_eval.py --model gpt-5.6-luna
    python evals/run_trade_eval.py --check-cases    # no model calls: re-verify expectations

Calls the real OpenAI API (needs OPENAI_API_KEY in .env). Not part of pytest
on purpose: it costs money and isn't deterministic.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import statistics
import sys
import time
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parent

# config.py reads .env relative to the working directory, so run from the repo
# root no matter where this script was launched from (picks up OPENAI_API_KEY).
os.chdir(REPO_ROOT)

from fantasy_agent.agent.core import run_agent_with_trace  # noqa: E402
from fantasy_agent.agent.tools import TOOL_HANDLERS, ToolError, resolve_owner  # noqa: E402
from fantasy_agent.config import settings  # noqa: E402
from fantasy_agent.db.session import get_session, init_db, reset_engine  # noqa: E402
from fantasy_agent.rankings.matching import normalize_name  # noqa: E402

# Appended to every eval question (never to real chat) so the verdict can be
# graded with a regex instead of a second "judge" model.
VERDICT_INSTRUCTION = (
    "\n\nEnd your answer with exactly one final line in one of these formats:\n"
    "VERDICT: FAIR   (values are roughly even -- neither side clearly comes out ahead)\n"
    "VERDICT: FAVORS <team name>   (that team clearly comes out ahead by value)\n"
    "VERDICT: INVALID   (the trade can't be evaluated as described)"
)

_VERDICT_RE = re.compile(r"VERDICT:\s*\**\s*(FAIR|INVALID|FAVORS\s+(.+?))\s*\**\s*$", re.IGNORECASE | re.MULTILINE)


@dataclass
class Verdict:
    kind: str  # "FAIR" | "FAVORS" | "INVALID" | "UNPARSEABLE"
    team: str | None = None  # as written, for FAVORS

    def __str__(self) -> str:
        return f"FAVORS {self.team}" if self.kind == "FAVORS" else self.kind


@dataclass
class CaseRun:
    case_id: str
    kind: str
    attempt: int
    tool_used: bool = False
    inputs_ok: bool = False
    verdict_ok: bool = False
    expected: str = ""
    got: str = ""
    trade_args: dict | None = None
    seconds: float = 0.0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    tool_calls: list[str] = field(default_factory=list)
    answer: str = ""
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.tool_used and self.inputs_ok and self.verdict_ok


# --- setup -----------------------------------------------------------------


def load_cases(path: Path) -> tuple[dict, list[dict]]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data["snapshot"], data["cases"]


def point_at_snapshot(snapshot: dict, cases_path: Path) -> None:
    """Swap the global settings over to the snapshot DB/league before anything
    touches the database. Safe here: this is a single-threaded script, not the
    server (see CLAUDE.md section 9)."""
    db_path = (cases_path.parent / snapshot["db"]).resolve()
    if not db_path.exists():
        sys.exit(f"Snapshot not found: {db_path}")
    settings.database_url = f"sqlite:///{db_path.as_posix()}"
    settings.sleeper_league_id = snapshot["league_id"]
    settings.sleeper_owner_user_id = snapshot["owner_user_id"]
    reset_engine()
    init_db()


# --- grading ---------------------------------------------------------------


def parse_verdict(text: str) -> Verdict:
    matches = _VERDICT_RE.findall(text or "")
    if not matches:
        return Verdict("UNPARSEABLE")
    word, team = matches[-1]
    word = word.split()[0].upper()
    return Verdict(word, team.strip(" *.\"'`") or None) if word == "FAVORS" else Verdict(word)


def _owner_id(session, team: str | None) -> str | None:
    if not team:
        return None
    try:
        return resolve_owner(session, team).user_id
    except ToolError:
        return None


def verdict_matches(session, expected: str, got: Verdict) -> bool:
    want = parse_verdict(f"VERDICT: {expected}")
    if want.kind != got.kind:
        return False
    if want.kind != "FAVORS":
        return True
    # Compare by team identity, not spelling: "Run JT Run" == "Run JT Run!!!!".
    want_owner = _owner_id(session, want.team)
    return want_owner is not None and want_owner == _owner_id(session, got.team)


def _same_players(expected: list[str], given: list[str]) -> bool:
    """Same count, and each expected name matches one given name (either may be
    partial: "Kincaid" vs "Dalton Kincaid", "Kenneth Walker" vs "... III")."""
    if len(expected) != len(given):
        return False
    remaining = [normalize_name(g) for g in given]
    for name in map(normalize_name, expected):
        hit = next((g for g in remaining if g and (name in g or g in name)), None)
        if hit is None:
            return False
        remaining.remove(hit)
    return True


def accepted_horizons(case: dict) -> list[str]:
    """A case's `horizon` is one value or a list (any is correct -- only allowed
    when the verdict is the same under each, which --check-cases enforces)."""
    horizon = case.get("horizon", "win_now")
    return [horizon] if isinstance(horizon, str) else list(horizon)


def inputs_match(session, case: dict, args: dict | None) -> bool:
    if not args:
        return False
    if args.get("horizon", "win_now") not in accepted_horizons(case):
        return False
    exp_a, exp_b = _owner_id(session, case["team_a"]), _owner_id(session, case["team_b"])
    got_a, got_b = _owner_id(session, args.get("team_a")), _owner_id(session, args.get("team_b"))
    a_gives, b_gives = args.get("team_a_gives") or [], args.get("team_b_gives") or []

    as_written = (got_a, got_b) == (exp_a, exp_b) and _same_players(case["team_a_gives"], a_gives) and _same_players(case["team_b_gives"], b_gives)
    swapped = (got_a, got_b) == (exp_b, exp_a) and _same_players(case["team_a_gives"], b_gives) and _same_players(case["team_b_gives"], a_gives)
    return as_written or swapped


def pipeline_verdict(session, case: dict, horizon: str) -> str:
    """What evaluate_trade itself says about the case's trade, in eval terms."""
    try:
        result = TOOL_HANDLERS["evaluate_trade"](
            session,
            team_a=case["team_a"],
            team_a_gives=case["team_a_gives"],
            team_b=case["team_b"],
            team_b_gives=case["team_b_gives"],
            horizon=horizon,
        )
    except ToolError:
        return "INVALID"
    text = result["verdict"]
    if text.startswith("Roughly fair"):
        return "FAIR"
    favored = re.search(r"favors (.+?) by value", text)
    return f"FAVORS {favored.group(1)}" if favored else f"UNASSESSABLE ({text})"


# --- running ---------------------------------------------------------------


def run_case(case: dict, attempt: int, model: str | None) -> CaseRun:
    run = CaseRun(case_id=case["id"], kind=case["kind"], attempt=attempt, expected=case["expected"])
    with get_session() as session:
        start = time.perf_counter()
        try:
            result = run_agent_with_trace(case["question"] + VERDICT_INSTRUCTION, session, model=model)
        except Exception as exc:  # API errors etc.: count as a failed case, keep going
            run.seconds = time.perf_counter() - start
            run.error = f"{type(exc).__name__}: {exc}"
            run.got = "ERROR"
            return run
        run.seconds = time.perf_counter() - start

        run.answer = result.answer
        run.tool_calls = [s.tool_name for s in result.steps]
        run.input_tokens = result.usage.input_tokens
        run.cached_tokens = result.usage.cached_tokens
        run.output_tokens = result.usage.output_tokens

        trade_calls = [s for s in result.steps if s.tool_name == "evaluate_trade"]
        run.tool_used = bool(trade_calls)
        # The last call is what the answer is based on; earlier ones may be
        # the agent correcting itself after a ToolError, which is fine.
        run.trade_args = trade_calls[-1].arguments if trade_calls else None
        run.inputs_ok = inputs_match(session, case, run.trade_args)

        got = parse_verdict(result.answer)
        run.got = str(got)
        run.verdict_ok = verdict_matches(session, case["expected"], got)
    return run


def check_cases(cases: list[dict]) -> int:
    """Re-verify each case's `expected` against the pipeline. No model calls."""
    bad = 0
    with get_session() as session:
        for case in cases:
            # Every accepted horizon must give the expected verdict -- otherwise
            # "either horizon is fine" would be a lie for this case.
            for horizon in accepted_horizons(case):
                actual = pipeline_verdict(session, case, horizon)
                ok = verdict_matches(session, case["expected"], parse_verdict(f"VERDICT: {actual}"))
                bad += not ok
                print(
                    f"  {'ok ' if ok else 'BAD'}  {case['id']:<30} {horizon:<9} "
                    f"expected {case['expected']!r:<34} pipeline says {actual!r}"
                )
    checks = sum(len(accepted_horizons(c)) for c in cases)
    print(f"\n{checks - bad}/{checks} case expectations (per accepted horizon) match the pipeline.")
    return 1 if bad else 0


# --- reporting -------------------------------------------------------------


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _pct(n: int, d: int) -> str:
    return f"{n / d:.0%}" if d else "n/a"


def report(runs: list[CaseRun], model: str, repeat: int) -> None:
    n = len(runs)
    passed = sum(r.passed for r in runs)
    print(f"\nTrade eval: {passed}/{n} correct ({_pct(passed, n)})   model={model}" + (f"   repeat={repeat}" if repeat > 1 else ""))
    print(f"  tool used        {sum(r.tool_used for r in runs)}/{n}")
    print(f"  correct inputs   {sum(r.inputs_ok for r in runs)}/{n}")
    print(f"  correct verdict  {sum(r.verdict_ok for r in runs)}/{n}")

    by_kind: dict[str, list[CaseRun]] = {}
    for r in runs:
        by_kind.setdefault(r.kind, []).append(r)
    print("  by kind:  " + "  ".join(f"{k} {sum(r.passed for r in rs)}/{len(rs)}" for k, rs in by_kind.items()))

    secs = [r.seconds for r in runs]
    slowest = max(runs, key=lambda r: r.seconds)
    print(f"\nSpeed:  avg {statistics.mean(secs):.1f}s | p95 {_p95(secs):.1f}s | slowest {slowest.seconds:.1f}s ({slowest.case_id})")

    inp, cached, out = (sum(getattr(r, f) for r in runs) for f in ("input_tokens", "cached_tokens", "output_tokens"))
    calls = sum(len(r.tool_calls) for r in runs)
    print(f"Tokens: {inp:,} in ({_pct(cached, inp)} cached) | {out:,} out | {(inp + out) / n:,.0f} per question | {calls / n:.1f} tool calls per question")

    failures = [r for r in runs if not r.passed]
    if failures:
        print("\nFailures:")
        for r in failures:
            if r.error:
                print(f"  {r.case_id} #{r.attempt}: {r.error}")
                continue
            missed = [name for name, ok in (("tool", r.tool_used), ("inputs", r.inputs_ok), ("verdict", r.verdict_ok)) if not ok]
            print(f"  {r.case_id} #{r.attempt}: failed {', '.join(missed)}")
            print(f"      expected {r.expected!r}, got {r.got!r}")
            if r.tool_used and not r.inputs_ok:
                print(f"      evaluate_trade args: {json.dumps(r.trade_args)}")
            if not r.tool_used:
                print(f"      tools called: {r.tool_calls or 'none'}")


def save(runs: list[CaseRun], model: str) -> Path:
    out_dir = EVALS_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"trade_{stamp}_{model}.json"
    payload = {"model": model, "run_at": stamp, "runs": [asdict(r) | {"passed": r.passed} for r in runs]}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=Path, default=EVALS_DIR / "trade_cases.toml")
    parser.add_argument("--model", default=None, help="Override the agent's model (default: settings.openai_model).")
    parser.add_argument("--case", action="append", dest="case_ids", help="Run only this case id (repeatable).")
    parser.add_argument("--repeat", type=int, default=1, help="Run each case N times.")
    parser.add_argument("--check-cases", action="store_true", help="Verify expectations against the pipeline; no model calls.")
    args = parser.parse_args()

    snapshot, cases = load_cases(args.cases)
    if args.case_ids:
        unknown = set(args.case_ids) - {c["id"] for c in cases}
        if unknown:
            sys.exit(f"Unknown case id(s): {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c["id"] in args.case_ids]
    point_at_snapshot(snapshot, args.cases)

    if args.check_cases:
        return check_cases(cases)

    if not settings.openai_api_key:
        sys.exit("OPENAI_API_KEY is not set -- add it to .env.")
    model = args.model or settings.openai_model

    runs: list[CaseRun] = []
    total = len(cases) * args.repeat
    for attempt in range(1, args.repeat + 1):
        for case in cases:
            run = run_case(case, attempt, args.model)
            runs.append(run)
            mark = "PASS" if run.passed else "FAIL"
            print(f"[{len(runs):>2}/{total}] {mark}  {case['id']:<30} {run.seconds:5.1f}s  got {run.got}", flush=True)

    report(runs, model, args.repeat)
    print(f"\nFull results: {save(runs, model).relative_to(REPO_ROOT)}")
    return 0 if all(r.passed for r in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
