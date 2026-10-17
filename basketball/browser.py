"""Optional visible ESPN draft-room control through Playwright.

No private draft write endpoint is guessed. Exact player identity, room turn,
clock and configured UI controls must all match before an action is clicked.
"""
import re
import time

from .config import credentials
from .drafting import auction, board, state
from .espn import Client


def draft_action(model, action, name, execute=False, bid=None):
    p = model.find(name)
    if p["id"] in {x["player"] for x in state(model)["picks"]}:
        raise ValueError("Player is already drafted")
    cfg = model.cfg
    ui = cfg.get("draft_ui", {})
    url = f"https://fantasy.espn.com/basketball/draft?leagueId={cfg['league_id']}&teamId={cfg['team_id']}&seasonId={cfg['season']}"
    if action == "bid":
        quote = auction(model, p["id"], (bid or 1) - 1)
        if bid is None or bid < cfg["draft"].get("minimum_bid", 1) or bid > quote["maximum_bid"]:
            raise ValueError("Bid exceeds the model's maximum or is below the minimum")
    if action == "pick" and p["id"] not in {r["id"] for r in board(model, count=len(model.players))["players"]}:
        raise ValueError("This player cannot fit the remaining draft roster requirements")
    if not execute:
        return {"preview": True, "action": action, "player": p["name"], "id": p["id"], "bid": bid,
                "url": url, "requirements": "Exact player row, your turn/nomination and at least 25 seconds on the clock"}
    if action != "queue" and not ui.get("clock_selector"):
        raise ValueError("Set draft_ui.clock_selector from the actual draft room before executing picks/bids")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError("Install requirements-basketball.txt and run `python -m playwright install chromium`") from exc
    auth = credentials(cfg)
    if not auth["espn_s2"] or not auth["SWID"]:
        raise ValueError("Run basketball login first")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        context.add_cookies([{"name": k, "value": v, "domain": ".espn.com", "path": "/", "secure": True} for k, v in auth.items()])
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        row = page.locator(ui.get("row_selector", "tr")).filter(has=page.get_by_text(p["name"], exact=True))
        if row.count() != 1:
            raise ValueError("Cannot identify exactly one draft row; inspect the visible room and configure draft_ui.row_selector")
        attribute = row.get_attribute(ui.get("player_id_attribute", "data-playerid"))
        image_ids = [image.get_attribute("src") or "" for image in row.get_by_role("img").all()]
        if attribute != str(p["id"]) and not any(re.search(rf"[=/]{p['id']}[.?/]", src) for src in image_ids):
            raise ValueError("The row's ESPN player ID is not verified; configure the actual player ID attribute")
        # Prefer ESPN player IDs when the current UI exposes them; exact-name
        # collisions require an explicit selector containing the player ID.
        duplicates = [q for q in model.players if q["name"] == p["name"]]
        if len(duplicates) > 1 and str(p["id"]) not in ui.get("row_selector", ""):
            raise ValueError("Duplicate player name: configure an ID-specific row selector")
        if action != "queue":
            marker = page.locator(ui.get("turn_selector", "body"))
            if not re.search(ui.get("turn_pattern", r"\byour turn\b"), marker.inner_text(), re.I):
                raise ValueError("Your turn/auction eligibility is not visibly confirmed")
            clock = page.locator(ui["clock_selector"]).inner_text().strip()
            match = re.fullmatch(r"(?:(\d+):)?(\d{1,2})", clock)
            seconds = int(match[1] or 0) * 60 + int(match[2]) if match else 0
            if seconds < 25:
                raise ValueError(f"Only {seconds} seconds left; make the pick/bid manually")
        label = ui.get(action + "_button", {"pick": "Draft", "queue": "Queue", "bid": "Bid"}[action])
        button = row.get_by_role("button", name=label, exact=True)
        if action == "bid":
            if not ui.get("bid_input_selector"):
                raise ValueError("Configure the actual draft room bid input selector")
            page.locator(ui["bid_input_selector"]).fill(str(bid))
        if button.count() != 1 or not button.is_enabled():
            raise ValueError("The verified player row has no unique enabled action button")
        button.click()
        if action == "queue":
            if not ui.get("queue_selector") or not page.locator(ui["queue_selector"]).get_by_text(p["name"], exact=True).is_visible():
                raise ValueError("Queue action clicked, but queue membership was not verified; inspect the room")
            result = {"verified": True, "action": "queue", "player": p["name"]}
        elif action == "bid":
            if not ui.get("bid_status_selector") or not re.search(rf"\b{bid}\b", page.locator(ui["bid_status_selector"]).inner_text()):
                raise ValueError("Bid clicked but not verified; inspect the room before bidding again")
            result = {"verified": True, "action": "bid", "player": p["name"], "bid": bid}
        else:
            result = None
            for _ in range(3):
                picks = Client(cfg).settings().get("draftDetail", {}).get("picks", [])
                if any(x.get("playerId") == p["id"] and x.get("teamId") == cfg["team_id"] for x in picks):
                    result = {"verified": True, "action": "pick", "player": p["name"]}
                    break
                time.sleep(2)
            if result is None:
                raise ValueError("Draft clicked but pick not confirmed by ESPN; inspect the room before retrying")
        browser.close()
        return result
