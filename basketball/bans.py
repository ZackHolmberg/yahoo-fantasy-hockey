"""Persistent live-draft exclusions; historical ranking experiments stay unchanged."""
from .config import path, read_json, write_json

TEAM_ALIASES = {"gsw": "gs", "nyk": "ny", "nop": "no", "sas": "sa", "uta": "utah", "pho": "phx"}


class BannedPlayer(ValueError):
    pass


def listing(cfg):
    policy = read_json(path(cfg, "draft-bans.json"), {"version": 1, "players": [], "teams": []})
    if not isinstance(policy, dict) or policy.get("version") != 1:
        raise ValueError("Invalid draft ban list; repair draft-bans.json before drafting")
    for kind in ("players", "teams"):
        rows = policy.get(kind)
        if not isinstance(rows, list) or any(not isinstance(r, dict) or type(r.get("id")) is not int or r["id"] <= 0
                                             or not isinstance(r.get("name"), str) or not r["name"].strip() for r in rows):
            raise ValueError("Invalid draft ban list; repair draft-bans.json before drafting")
        if len({r["id"] for r in rows}) != len(rows):
            raise ValueError("Duplicate identities in draft ban list")
    return policy


def reason(cfg, player, current_team=None, policy=None):
    policy = listing(cfg) if policy is None else policy
    if any(r["id"] == int(player["id"]) for r in policy["players"]):
        return f"Player ban: {player.get('name', player['id'])}"
    teams = {str(player.get("team", "")), str(current_team or "")}
    match = next((r for r in policy["teams"] if str(r["id"]) in teams), None)
    return f"NBA team ban: {match['name']}" if match else None


def require(cfg, player, current_team=None):
    blocked = reason(cfg, player, current_team)
    if blocked:
        raise BannedPlayer(blocked + "; explicitly unban before drafting")


def team(cfg, value):
    from .availability import SITE, Sources
    from .drafting import normalize_name
    # The public catalog supplies stable ESPN team IDs; no account cookies.
    raw = Sources(cfg).get(SITE + "teams?limit=100")
    rows = [r["team"] for sport in raw["sports"] for league in sport["leagues"] for r in league["teams"]]
    query = normalize_name(str(value).strip())
    query = TEAM_ALIASES.get(query, query)
    matches = [r for r in rows if query in {normalize_name(str(r.get(k, ""))) for k in
                                          ("id", "displayName", "shortDisplayName", "name", "abbreviation", "location")}]
    if len(matches) != 1:
        raise ValueError("Identify exactly one NBA team by full name, abbreviation or ESPN team ID")
    row = matches[0]
    return {"id": int(row["id"]), "name": row["displayName"], "abbreviation": row["abbreviation"]}


def edit(cfg, kind, entry, remove=False):
    policy = listing(cfg)
    rows = policy[kind]
    policy[kind] = sorted([r for r in rows if r["id"] != entry["id"]] + ([] if remove else [entry]), key=lambda r: r["id"])
    write_json(path(cfg, "draft-bans.json"), policy)
    return policy


def remove(cfg, kind, value):
    # Removal works offline even if the player disappeared from the snapshot.
    rows = listing(cfg)[kind]
    query = str(value).strip().casefold()
    if kind == "teams":
        query = TEAM_ALIASES.get(query, query)
    matches = [r for r in rows if query in {str(r["id"]), r["name"].casefold(), r.get("abbreviation", "").casefold()}]
    if len(matches) != 1:
        raise ValueError("Identify one existing ban by its listed name, ID or team abbreviation")
    return edit(cfg, kind, matches[0], remove=True)


def board(model, count=20, current=None, slot=None):
    from .drafting import board as ranked_board
    policy = listing(model.cfg)
    result = ranked_board(model, len(model.players), current, slot)
    rows = [r for r in result["players"] if not reason(model.cfg, model.by_id[r["id"]], policy=policy)]
    return {**result, "players": rows[:count] if count > 0 else rows,
            "ban_list": policy, "excluded_by_ban": len(result["players"])-len(rows)}


def auction(model, name, current_bid=0):
    from .drafting import auction as quote
    require(model.cfg, model.find(name))
    return quote(model, name, current_bid)
