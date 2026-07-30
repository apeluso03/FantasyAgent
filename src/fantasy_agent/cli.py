"""CLI for the data layer: sync Sleeper data into the local cache and inspect it.

Usage:
    fantasy-agent sync
    fantasy-agent league
    fantasy-agent rosters
    fantasy-agent players --search "mahomes"
    fantasy-agent rankings-sync
    fantasy-agent rankings-show --search "mahomes"
    fantasy-agent rankings-unmatched
    fantasy-agent rankings-alias 12345 4046
    fantasy-agent keepers
    fantasy-agent trade --side-a-owner <id> --side-a-gives p1,p2 --side-b-owner <id> --side-b-gives p3
    fantasy-agent ask "should I keep Bijan Robinson or draft fresh?"
    fantasy-agent best-available
"""

from __future__ import annotations

import logging

import typer

from .agent.core import run_agent
from .agent.tools import ToolError, resolve_owner
from .config import settings
from .db.models import LeagueRecord, PlayerAlias, PlayerRecord, RankingRecord, RosterRecord, UserRecord
from .db.session import get_session
from .draft import get_best_available
from .keeper import compute_keeper_candidates
from .sync import sync_all, sync_rankings_all
from .trade import evaluate_trade

app = typer.Typer(add_completion=False, no_args_is_help=True)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@app.command()
def sync(
    league_id: str = typer.Option(settings.sleeper_league_id, help="Sleeper league ID to sync."),
    force_players: bool = typer.Option(
        False, "--force-players", help="Re-pull the full players/nfl dump even if the cache is fresh."
    ),
) -> None:
    """Pull league, users, rosters, and (if stale) the player database into the local cache."""
    sync_all(league_id, force_players=force_players)
    typer.echo("Sync complete.")


@app.command()
def league() -> None:
    """Show cached league settings."""
    with get_session() as session:
        record = session.get(LeagueRecord, settings.sleeper_league_id)
        if record is None:
            typer.echo("No cached league data — run `fantasy-agent sync` first.")
            raise typer.Exit(code=1)
        typer.echo(f"{record.name} (season {record.season}, {record.total_rosters} teams)")
        typer.echo(f"Roster positions: {', '.join(record.roster_positions)}")
        typer.echo(f"Last synced: {record.synced_at}")


@app.command()
def rosters() -> None:
    """Show each roster's owner and player count."""
    with get_session() as session:
        league_record = session.get(LeagueRecord, settings.sleeper_league_id)
        if league_record is None:
            typer.echo("No cached league data — run `fantasy-agent sync` first.")
            raise typer.Exit(code=1)

        users_by_id = {
            u.user_id: u
            for u in session.query(UserRecord).filter_by(league_id=settings.sleeper_league_id).all()
        }
        roster_records = (
            session.query(RosterRecord)
            .filter_by(league_id=settings.sleeper_league_id)
            .order_by(RosterRecord.roster_id)
            .all()
        )
        for roster in roster_records:
            owner = users_by_id.get(roster.owner_id)
            owner_label = owner.team_name if owner else "(no owner)"
            typer.echo(f"#{roster.roster_id:>2}  {owner_label:<25} players={len(roster.players)}")


@app.command()
def players(
    search: str = typer.Option(..., "--search", help="Case-insensitive substring to match against player names."),
    limit: int = typer.Option(20, help="Max results to show."),
) -> None:
    """Look up cached players by (partial) name — sanity check for the player cache."""
    needle = search.lower()
    with get_session() as session:
        matches = [
            p
            for p in session.query(PlayerRecord).all()
            if p.full_name and needle in p.full_name.lower()
        ][:limit]
        if not matches:
            typer.echo("No matches. Have you run `fantasy-agent sync`?")
            return
        for p in matches:
            typer.echo(f"{p.full_name:<25} {p.position or '-':<4} {p.team or 'FA':<4} id={p.player_id}")


@app.command()
def rankings_sync(
    page: str = typer.Option(settings.fantasypros_ranking_page, help="FantasyPros rankings page slug."),
    force: bool = typer.Option(False, "--force", help="Re-scrape even if the cache is fresh."),
) -> None:
    """Scrape FantasyPros rankings and match players to cached Sleeper IDs."""
    try:
        result = sync_rankings_all(page, force=force)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if result is None:
        typer.echo("Rankings cache is still fresh — nothing to do (use --force to override).")
        return

    typer.echo(f"Synced {result.total} ranked players from '{result.page}': {result.matched} matched.")
    if result.unmatched:
        typer.echo(f"{len(result.unmatched)} unmatched - run `fantasy-agent rankings-unmatched` to review:")
        for fp_id, name, position in result.unmatched[:10]:
            typer.echo(f"  fp_id={fp_id:<8} {name:<25} {position}")
        if len(result.unmatched) > 10:
            typer.echo(f"  ... and {len(result.unmatched) - 10} more")


@app.command()
def rankings_show(
    search: str = typer.Option(None, "--search", help="Case-insensitive substring to match against player names."),
    page: str = typer.Option(settings.fantasypros_ranking_page, help="FantasyPros rankings page slug."),
    limit: int = typer.Option(25, help="Max results to show."),
) -> None:
    """Show cached FantasyPros rankings, optionally filtered by name."""
    with get_session() as session:
        query = session.query(RankingRecord).filter_by(source="fantasypros", page=page)
        if search:
            needle = search.lower()
            rows = [r for r in query.all() if needle in r.name.lower()]
        else:
            rows = query.order_by(RankingRecord.rank_ecr).all()
        rows = rows[:limit]
        if not rows:
            typer.echo("No cached rankings. Have you run `fantasy-agent rankings-sync`?")
            return
        for r in rows:
            sleeper_id = r.sleeper_player_id or "UNMATCHED"
            typer.echo(
                f"#{r.rank_ecr:<4} {r.name:<25} {r.position:<4} {r.team or 'FA':<4} "
                f"{r.pos_rank or '':<6} sleeper_id={sleeper_id}"
            )


@app.command()
def rankings_unmatched(page: str = typer.Option(settings.fantasypros_ranking_page)) -> None:
    """List cached rankings that couldn't be matched to a Sleeper player."""
    with get_session() as session:
        rows = (
            session.query(RankingRecord)
            .filter_by(source="fantasypros", page=page, sleeper_player_id=None)
            .order_by(RankingRecord.rank_ecr)
            .all()
        )
        if not rows:
            typer.echo("No unmatched players.")
            return
        for r in rows:
            typer.echo(f"fp_id={r.fp_player_id:<8} {r.name:<25} {r.position:<4} {r.team or 'FA'}")
        typer.echo(f"\n{len(rows)} unmatched. Add an override with: fantasy-agent rankings-alias <fp_id> <sleeper_id>")


@app.command()
def rankings_alias(
    fp_player_id: int = typer.Argument(..., help="FantasyPros player ID (from rankings-unmatched)."),
    sleeper_player_id: str = typer.Argument(..., help="Sleeper player ID to map it to."),
    note: str = typer.Option(None, help="Optional note explaining the override."),
) -> None:
    """Manually map a FantasyPros player ID to a Sleeper player ID, overriding automatic matching."""
    with get_session() as session:
        sleeper_player = session.get(PlayerRecord, sleeper_player_id)
        if sleeper_player is None:
            typer.echo(f"No cached Sleeper player with id={sleeper_player_id}. Run `fantasy-agent sync` first?")
            raise typer.Exit(code=1)

        alias = session.get(PlayerAlias, fp_player_id)
        if alias is None:
            alias = PlayerAlias(fp_player_id=fp_player_id)
            session.add(alias)
        alias.sleeper_player_id = sleeper_player_id
        alias.note = note

        # Apply immediately to any cached ranking rows for this fp_player_id.
        for ranking in session.query(RankingRecord).filter_by(fp_player_id=fp_player_id).all():
            ranking.sleeper_player_id = sleeper_player_id
            ranking.match_method = "alias"

    typer.echo(f"Aliased fp_id={fp_player_id} -> sleeper_id={sleeper_player_id} ({sleeper_player.full_name}).")


@app.command()
def keepers(
    owner_user_id: str = typer.Option(settings.sleeper_owner_user_id, help="Sleeper user_id whose roster to evaluate."),
    penalty: int = typer.Option(settings.keeper_round_penalty, help="Rounds subtracted from draft round for keeper cost."),
) -> None:
    """Rank your roster's keeper candidates by value surplus, with reasoning."""
    with get_session() as session:
        try:
            candidates = compute_keeper_candidates(session, owner_user_id=owner_user_id, penalty=penalty)
        except RuntimeError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc

        for c in candidates:
            rank_label = f"#{c.rank_ecr}" if c.rank_ecr is not None else "unranked"
            typer.echo(f"{c.name:<25} {c.position:<4} {c.team or 'FA':<4} {rank_label:<9} cost=R{c.cost_round}")
            typer.echo(f"    {c.reasoning}")


@app.command()
def trade(
    side_a_owner: str = typer.Option(..., help="Sleeper user_id for side A."),
    side_a_gives: str = typer.Option(..., help="Comma-separated Sleeper player IDs side A trades away."),
    side_b_owner: str = typer.Option(..., help="Sleeper user_id for side B."),
    side_b_gives: str = typer.Option(..., help="Comma-separated Sleeper player IDs side B trades away."),
) -> None:
    """Evaluate a proposed trade for both sides: value swing + roster-need impact."""
    a_gives = [p.strip() for p in side_a_gives.split(",") if p.strip()]
    b_gives = [p.strip() for p in side_b_gives.split(",") if p.strip()]
    with get_session() as session:
        try:
            result = evaluate_trade(session, side_a_owner, a_gives, side_b_owner, b_gives)
        except (RuntimeError, ValueError) as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc

        typer.echo(f"{result.side_a.team_name}: {result.side_a.reasoning}")
        typer.echo("")
        typer.echo(f"{result.side_b.team_name}: {result.side_b.reasoning}")
        typer.echo("")
        typer.echo(f"Verdict: {result.verdict}")


@app.command()
def ask(
    question: str = typer.Argument(..., help="A keeper/trade/roster question in plain English."),
    model: str = typer.Option(None, help="Override the default Claude model."),
) -> None:
    """Ask the Claude tool-calling agent a question, grounded in the local cache.

    Tool calls and their results are logged as they happen (root logger is INFO
    by default) -- this is the "here's how it thinks" trace, not just the answer.
    """
    with get_session() as session:
        try:
            answer = run_agent(question, session, model=model)
        except RuntimeError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
    typer.echo(answer)


@app.command("best-available")
def best_available(
    team: str = typer.Option(None, help="Team to evaluate needs for (defaults to your team)."),
    limit: int = typer.Option(15, help="Max players to show."),
) -> None:
    """Live draft board: best available players (polled fresh from Sleeper), ranked with roster-need context."""
    with get_session() as session:
        try:
            owner_user_id = settings.sleeper_owner_user_id
            if team:
                owner_user_id = resolve_owner(session, team).user_id
            players = get_best_available(session, owner_user_id=owner_user_id, limit=limit)
        except (RuntimeError, ToolError) as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc

        for p in players:
            typer.echo(f"#{p.rank_ecr:<4} {p.name:<25} {p.position:<4} {p.team or 'FA':<4} {p.pos_rank or '':<6}")
            typer.echo(f"    {p.reasoning}")


if __name__ == "__main__":
    app()
