"""Small deterministic owner-command interface; no LLM can select arbitrary actions."""
import re

from .manager import report, swap_body


def interpret(model, text):
    text = text.strip()
    if re.fullmatch(r"(?:show |my )?(?:roster|team)", text, re.I):
        return {"answer": model.roster()}
    if re.fullmatch(r"(?:show |my )?(?:report|lineup|status)", text, re.I):
        return {"answer": report(model)}
    approved = re.fullmatch(r"(?:yes|approve)\s+(B[0-9a-f]{8})", text, re.I)
    if approved:
        plan = report(model)
        candidate = next((m for m in plan["moves"] if m["proposal"].casefold() == approved[1].casefold()), None)
        if not candidate:
            raise ValueError("That proposal is no longer recommended/available; read a fresh report")
        return {"body": swap_body(model, candidate["add"], candidate["drop"], approved=True), "proposal": candidate["proposal"]}
    directed = re.fullmatch(r"add\s+(.+?)\s*(?:,|\band\b)?\s+drop\s+(.+)", text, re.I)
    if directed:
        return {"body": swap_body(model, directed[1].strip(), directed[2].strip(), approved=True)}
    best = re.fullmatch(r"drop\s+(.+?)\s*,?\s+add\s+(?:the\s+)?best\s+(PG|SG|SF|PF|C|G|F|UTIL)(?:\s+if better)?", text, re.I)
    if best:
        drop = model.find(best[1].strip().rstrip(","), model.roster())
        candidates = sorted((p for p in model.available() if p["ranked"] and p["status"] not in {"OUT", "INJURY_RESERVE", "SUSPENSION"}
                             and best[2].upper() in p["eligible"]), key=lambda p: -p["value"] * p["remaining_games"])
        for add in candidates:
            if text.lower().endswith("if better") and add["value"] * add["remaining_games"] <= drop["value"] * drop["remaining_games"]:
                return {"answer": "Kept the player: no better eligible free agent"}
            try:
                body = swap_body(model, add["id"], drop["id"], approved=True)
            except ValueError:
                continue
            return {"body": body, "add_name": add["name"], "drop_name": drop["name"]}
        raise ValueError("No legal eligible free agent was found")
    raise ValueError('Supported commands: roster; report; yes B<proposal>; add NAME drop NAME; drop NAME, add best PG [if better]')
