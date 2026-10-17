"""Two-pick expert quality / public market timing, without outcome data."""
import hashlib
import math


class Hybrid:
    """Ordinal utilities and scenario counts are heuristics, not point forecasts."""

    def __init__(self, quality, market):
        self.order = list(quality)
        if not self.order or len(set(quality)) != len(quality) or len(set(market)) != len(market) or set(quality) != set(market):
            raise ValueError("Quality and market must be unique orders of the same nonempty pool")
        self.rank = {pid: i+1 for i, pid in enumerate(quality)}
        m = {pid: i+1 for i, pid in enumerate(market)}
        self.scenarios = {"espn": list(market), "expert": self.order}
        for weight in (.25, .5):
            self.scenarios[f"expert_weight_{weight}"] = sorted(quality, key=lambda p: ((1-weight)*m[p]+weight*self.rank[p], m[p], p))
        for seed in (0, 1):
            def jitter(pid):
                value = int.from_bytes(hashlib.sha256(f"hybrid:{seed}:{pid}".encode()).digest()[:8], "big") / 2**64
                return 24*(value-.5)
            self.scenarios[f"espn_jitter_{seed}"] = sorted(market, key=lambda p: (m[p]+jitter(p), m[p], p))

    def choose(self, gone, roster, gap, legal, final=False, excluded=()):
        """legal(roster IDs, candidate ID) checks our roster, never future outcomes.

        Forecast removals approximate market demand; opponent position caps are
        deliberately not inferred. Exclusions affect our choices, not opponents.
        """
        if not isinstance(gap, int) or gap < 0:
            raise ValueError("Intervening picks must be a nonnegative integer")
        excluded = set(excluded)
        available = [p for p in self.order if p not in gone and p not in excluded]
        best = next((p for p in available if legal(roster, p)), None)
        if best is None:
            raise ValueError("No legal expert-board choice remains")
        candidates = [p for p in available if self.rank[p] <= self.rank[best]+7 and legal(roster, p)]
        if final or gap == 0:
            return {"id": best, "best_expert": best, "deferred": False, "gap": gap,
                    "reason": "Final pick" if final else "Consecutive picks: take best expert first", "alternatives": []}
        rows = []
        for pid in candidates:
            futures, survives = {}, 0
            for name, market in self.scenarios.items():
                removed = set(gone) | {pid}
                forecast = [p for p in market if p not in removed][:gap]
                removed.update(forecast)
                survives += best not in removed
                future = next((p for p in available if p not in removed and legal(roster+[pid], p)), None)
                futures[name] = future
            feasible = all(p is not None for p in futures.values())
            score = sum(-math.log(self.rank[pid])-math.log(self.rank[p]) for p in futures.values())/len(futures) if feasible else None
            rows.append({"id": pid, "quality_order": self.rank[pid], "pair_utility": score,
                         "best_expert_survives_scenarios": survives, "scenario_count": len(futures), "next_choices": futures})
        feasible = [r for r in rows if r["pair_utility"] is not None]
        # If market approximations exhaust every legal future, preserve greedy
        # expert behavior rather than inventing an attainable second selection.
        selected = max(feasible, key=lambda r: (round(r["pair_utility"], 12), -r["quality_order"]))["id"] if feasible else best
        return {"id": selected, "best_expert": best, "deferred": selected != best, "gap": gap,
                "reason": "Better two-pick expert combination" if selected != best else "Take best expert now",
                "alternatives": rows}
