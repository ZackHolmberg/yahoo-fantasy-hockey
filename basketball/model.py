"""A single projection and scoring model for drafting, moves, lineups and trades."""
import math
import statistics

RATIOS = {"FG%": ("FGM", "FGA"), "FT%": ("FTM", "FTA"), "3PT%": ("3PM", "3PA")}


def rates(split):
    totals = split.get("stats", {})
    gp = totals.get("GP", 0)
    if gp <= 0:
        return None
    return {k: v / gp for k, v in totals.items() if k not in RATIOS and k != "GP"}


def projection(p, cfg, snapshot):
    """ESPN projection or a two-season prior, updated by current-season games."""
    splits = p.get("splits", [])
    actual = next((s for s in splits if s["season"] == cfg["season"] and s["source"] == 0 and rates(s)), None)
    projected = next((s for s in splits if s["season"] == cfg["season"] and s["source"] == 1 and rates(s)), None)
    history = [(s, 0.65 if s["season"] == cfg["season"] - 1 else 0.35) for s in splits
               if s["source"] == 0 and s["season"] in {cfg["season"] - 1, cfg["season"] - 2} and rates(s)]
    prior, gp, source = {}, 0, "unranked"
    if projected:
        prior, gp, source = rates(projected), projected["stats"]["GP"], "espn_projection"
    elif history:
        weight = sum(w * s["stats"]["GP"] for s, w in history)
        keys = {k for s, _ in history for k in rates(s)}
        prior = {k: sum(w * s["stats"]["GP"] * rates(s).get(k, 0) for s, w in history) / weight for k in keys}
        gp = sum(w * s["stats"]["GP"] for s, w in history) / sum(w for _, w in history)
        source = "history_blend"
    current_gp = actual["stats"]["GP"] if actual else 0
    if actual:
        recent = rates(actual)
        alpha = current_gp / (current_gp + cfg.get("projection_prior_games", 20)) if prior else 1
        prior = {k: recent.get(k, 0) * alpha + prior.get(k, 0) * (1 - alpha) for k in prior.keys() | recent.keys()}
        gp = gp or 65
        source = "current_plus_" + source
    override = cfg.get("adjustments", {}).get(str(p["id"]), {})
    prior.update(override.get("per_game", {}))
    if override.get("per_game"):
        source = "manual_override"
    gp = override.get("games", gp)
    multiplier = override.get("multiplier", 1)
    prior = {k: float(v) * multiplier for k, v in prior.items()}
    today = snapshot["fetched_at"][:10]
    team_games = snapshot.get("games", {}).get(p["team"], [])
    remaining = sum(g["date"] >= today and not g.get("cancelled") for g in team_games)
    # Dates from the actual NBA schedule, rather than an elapsed-calendar fraction.
    team_played = sum(g["date"] < today and not g.get("cancelled") for g in team_games)
    availability = min(1, gp / max(1, remaining + team_played))
    games_left = max(0, remaining * availability) if team_games else max(0, gp - current_gp)
    p = dict(p, per_game=prior, projected_games=gp, current_games=current_gp,
             remaining_games=round(games_left, 1), projection_source=source, ranked=bool(prior))
    p["fpg"] = sum(prior.get(k, 0) * w for k, w in cfg.get("scoring", {}).items())
    p["ros"] = p["fpg"] * p["remaining_games"]
    return p


def totals(players, games=None):
    out = {}
    for p in players:
        count = games.get(p["id"], 0) if games is not None else p["remaining_games"]
        for k, v in p["per_game"].items():
            out[k] = out.get(k, 0) + v * count
    for key, (made, attempted) in RATIOS.items():
        out[key] = out.get(made, 0) / out[attempted] if out.get(attempted) else 0
    return out


class Model:
    def __init__(self, cfg, snapshot):
        self.cfg, self.snapshot = cfg, snapshot
        self.players = [projection(p, cfg, snapshot) for p in snapshot["players"]]
        self.by_id = {p["id"]: p for p in self.players}
        self.categories = [c for c in cfg.get("categories", []) if c not in cfg.get("punts", [])]
        # Estimate distribution from a roster-sized pool, not thousands of non-NBA players.
        from .config import roster_size
        reference = sorted((p for p in self.players if p["ranked"]), key=lambda p: -sum(p["per_game"].get(k, 0) for k in ("PTS", "REB", "AST")))[:cfg["teams"] * roster_size(cfg)]
        self.baselines, self.means, self.scales = {}, {}, {}
        for cat in self.categories:
            if cat in RATIOS:
                made, att = RATIOS[cat]
                denom = sum(p["per_game"].get(att, 0) for p in reference)
                self.baselines[cat] = sum(p["per_game"].get(made, 0) for p in reference) / denom if denom else 0
            values = [self.component(p, cat) for p in reference]
            self.means[cat] = statistics.mean(values) if values else 0
            self.scales[cat] = statistics.pstdev(values) if len(values) > 1 else 1
        for p in self.players:
            p["value"] = self.score(p)

    def component(self, p, cat):
        if cat in RATIOS:
            made, att = RATIOS[cat]
            return p["per_game"].get(made, 0) - self.baselines[cat] * p["per_game"].get(att, 0)
        return p["per_game"].get(cat, 0) * (-1 if cat in self.cfg.get("lower_is_better", []) else 1)

    def score(self, p, weights=None):
        if self.cfg["format"] == "points":
            return p["fpg"]
        return sum((self.component(p, c) - self.means[c]) / (self.scales[c] or 1) * (weights or {}).get(c, 1)
                   for c in self.categories)

    def roster(self, team=None):
        return [p for p in self.players if p["owner"] == (team or self.cfg["team_id"])]

    def available(self):
        return [p for p in self.players if not p["owner"] and p["availability"] in {"FREEAGENT", "WAIVERS"}]

    def find(self, name, pool=None):
        pool = self.players if pool is None else pool
        exact = [p for p in pool if str(p["id"]) == str(name) or p["name"].casefold() == str(name).casefold()]
        matches = exact or [p for p in pool if str(name).casefold() in p["name"].casefold()]
        if len(matches) != 1:
            raise ValueError(f"Identify one player by name or ESPN ID: {name!r}")
        return matches[0]

    def compare(self, ours, theirs):
        """Attempt-weighted percentages, category direction and punt-aware H2H odds."""
        if self.cfg["format"] == "points":
            a = sum(ours.get(k, 0) * w for k, w in self.cfg["scoring"].items())
            b = sum(theirs.get(k, 0) * w for k, w in self.cfg["scoring"].items())
            return {"ours": round(a, 2), "theirs": round(b, 2), "margin": round(a - b, 2)}
        result = {}
        for c in self.cfg["categories"]:
            a, b = ours.get(c, 0), theirs.get(c, 0)
            diff = (a - b) * (-1 if c in self.cfg.get("lower_is_better", []) else 1)
            result[c] = {"ours": round(a, 4), "theirs": round(b, 4),
                         "winner": "tie" if abs(diff) < 1e-9 else ("ours" if diff > 0 else "theirs"),
                         "punted": c in self.cfg.get("punts", [])}
        return result

    def target_weights(self, ours, theirs):
        """Emphasize close H2H categories; this is a heuristic, not calibrated odds."""
        weights = {}
        for cat in self.categories:
            scale = self.scales[cat] or 1
            if cat in RATIOS:
                _, att = RATIOS[cat]
                scale /= max(1, (ours.get(att, 0) + theirs.get(att, 0)) / 2)
            margin = abs(ours.get(cat, 0) - theirs.get(cat, 0)) / scale
            weights[cat] = 0.25 + math.exp(-0.5 * (margin / 5) ** 2)
        return weights
