"""Yahoo league 23491 without Claude: Playwright drives a dedicated browser profile the owner signed into once.

    .venv/bin/python yahoo_bot.py login            # once (and whenever Yahoo logs it out): sign in, then close the window
    .venv/bin/python yahoo_bot.py report           # read the site and print manage.py's report; changes nothing
    .venv/bin/python yahoo_bot.py apply [--dry-run]  # report, set lineup/IR, make AUTO-OK add/drops, re-check
    .venv/bin/python yahoo_bot.py swap "Add" "Drop" [--dry-run]  # one add/drop the OWNER approved (reply pipeline)
    .venv/bin/python yahoo_bot.py team N           # another team's roster specs (for manage.py trade)

`apply` only does what the report marks as ACTIONS (lineup, IR, AUTO-OK swaps within data/manager_rules.json).
Every click is preceded by a check that the player names on the page match the plan; anything that doesn't
match is skipped and reported, never guessed. Prints a final RESULT_JSON line for scripts/daily_auto.sh.
The profile (data/yahoo_profile/) holds the owner's Yahoo session: gitignored, never commit or copy it.
"""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent
PROFILE = REPO / "data/yahoo_profile"
BASE = "https://hockey.fantasysports.yahoo.com"
LEAGUE, TEAM = "/hockey/23491", 11
FA_QUERIES = ["status=A&pos=P&sort=OR&sdir=1&count=0", "status=A&pos=P&sort=OR&sdir=1&count=25",
              "status=A&pos=P&sort=AR&sdir=1&count=0", "status=A&pos=G&sort=OR&sdir=1&count=0"]

# Runs in the page. Same extraction as scripts/yahoo_read.js, plus Yahoo player ids for the actions.
EXTRACT_JS = """async ({league, team, faQueries}) => {
  const STATUS = /^(DTD|O|IR|IR-LT|IR-NR|NA|SUSP|INJ)$/;
  const doc = async p => new DOMParser().parseFromString(
    await (await fetch(p, {credentials: 'include', cache: 'no-store'})).text(), 'text/html');
  const one = cell => {
    const a = cell.querySelector('a[class*="name"]') || cell.querySelector('a[href*="/players/"]');
    if (!a) return null;
    const texts = [...cell.querySelectorAll('span, abbr')].map(s => s.textContent.trim());
    const tp = texts.find(t => /^[A-Z]{2,4} - [A-Z,]+$/.test(t)) ||
      ((cell.textContent.replace(/\\s+/g, ' ').match(/\\b([A-Z]{2,4}) - ([A-Z]{1,2}(?:,[A-Z]{1,2})*)\\b/) || [])[0]) || ' - ';
    const [tm, pos] = tp.split(' - ');
    const pid = ((a.getAttribute('href') || '').match(/players\\/(\\d+)/) || [])[1] || '';
    return {name: a.textContent.trim(), spec: `${a.textContent.trim()}|${pos}|${texts.find(t => STATUS.test(t)) || ''}|${tm}`, pid};
  };
  const today = new Date().toLocaleDateString('en-CA');
  let page = await doc(`${league}/${team}/team?date=${today}`);
  if (!page.querySelector('#statTable0')) page = await doc(`${league}/${team}`);  // other teams' pages
  if (!page.querySelector('#statTable0')) return {loggedOut: true};
  const roster = [...page.querySelectorAll('#statTable0 tbody tr, #statTable1 tbody tr')]
    .map(r => {  // our page has an Edit column, other teams' pages don't: use the cell holding the player link
      const cell = [...r.cells].find(c => c.querySelector('a[href*="/players/"]'));
      return cell && Object.assign({slot: r.cells[0].textContent.trim()}, one(cell));
    }).filter(r => r && r.spec);
  const fas = new Map();
  for (const q of faQueries) {
    const d = await doc(`${league}/players?${q}`);
    const t = [...d.querySelectorAll('table')].find(t => t.querySelector('a[href*="/players/"]') && t.rows.length > 10);
    for (const r of t ? t.tBodies[0].rows : []) { const x = one(r); if (x && !/\\|NA\\|/.test(x.spec)) fas.set(x.name, x); }
  }
  return {today, roster, fas: [...fas.values()]};
}"""

# Runs on the team page: set each listed player's slot in Yahoo's edit-roster form and submit it.
SET_LINEUP_JS = """(moves) => {
  const form = [...document.forms].find(f => /editroster/.test(f.action));
  if (!form) return {error: 'edit-roster form not found'};
  const done = [], skipped = [];
  for (const [pid, name, slot] of moves) {
    const sel = form.querySelector(`select[name="${pid}"]`);
    const row = sel && sel.closest('tr');
    const shown = row && (row.querySelector('a[class*="name"]') || {}).textContent;
    if (!sel || (shown || '').trim() !== name) { skipped.push(`${name}: row/name mismatch`); continue; }
    if (![...sel.options].some(o => o.value === slot)) { skipped.push(`${name}: ${slot} not allowed (${[...sel.options].map(o => o.value)})`); continue; }
    sel.value = slot; done.push(`${name} -> ${slot}`);
  }
  if (done.length) { (form.requestSubmit ? form.requestSubmit() : form.submit()); }
  return {done, skipped};
}"""


def browser(p, headless=True):
    return p.chromium.launch_persistent_context(str(PROFILE), headless=headless, viewport={"width": 1280, "height": 900})


def read(page):
    page.goto(f"{BASE}{LEAGUE}/{TEAM}", wait_until="domcontentloaded")
    data = page.evaluate(EXTRACT_JS, {"league": LEAGUE, "team": TEAM, "faQueries": FA_QUERIES})
    if data.get("loggedOut"):
        sys.exit("yahoo_bot: not signed in. Run `.venv/bin/python yahoo_bot.py login` and sign into Yahoo.")
    return data


def run_report(data):
    items = [f"D {data['today']}"] + [f"R {r['slot']}:{r['spec']}" for r in data["roster"]] + [f"F {f['spec']}" for f in data["fas"]]
    out = subprocess.run([sys.executable, str(REPO / "manage.py"), "report", "--json", "-"], input=" ~ ".join(items),
                         capture_output=True, text=True, cwd=REPO)
    if out.returncode:
        sys.exit(f"yahoo_bot: manage.py report failed:\n{out.stdout}{out.stderr}")
    text, _, plan = out.stdout.partition("\nPLAN_JSON ")
    return text, json.loads(plan)


def apply(page, data, plan, dry, approved=False):
    pids = {r["name"]: r["pid"] for r in data["roster"]} | {f["name"]: f["pid"] for f in data["fas"]}
    slots = {r["name"]: r["slot"] for r in data["roster"]}
    did, skipped = [], []

    # lineup + IR in one edit-roster submit
    moves = [[pids.get(n, ""), n, s] for n, s in plan["lineup"].items()]
    for n in plan["ir"]:
        moves.append([pids.get(n, ""), n, "IR"])  # tried as IR, then IR+ below if Yahoo only allows that
    if moves:
        if dry:
            did += [f"(dry run) {n} -> {s}" for _, n, s in moves]
        else:
            page.goto(f"{BASE}{LEAGUE}/{TEAM}/team?date={data['today']}", wait_until="domcontentloaded")
            res = page.evaluate(SET_LINEUP_JS, moves)
            if res.get("error"):
                skipped.append("lineup: " + res["error"])
            else:
                retry = [[pids.get(n, ""), n, "IR+"] for n in plan["ir"] if any(x.startswith(f"{n}: IR not allowed") for x in res["skipped"])]
                res["skipped"] = [x for x in res["skipped"] if not any(x.startswith(f"{r[1]}: IR not allowed") for r in retry)]
                page.wait_for_load_state("domcontentloaded")
                did += res["done"]; skipped += res["skipped"]
                if retry:
                    page.goto(f"{BASE}{LEAGUE}/{TEAM}/team?date={data['today']}", wait_until="domcontentloaded")
                    r2 = page.evaluate(SET_LINEUP_JS, retry)
                    page.wait_for_load_state("domcontentloaded")
                    did += r2.get("done", []); skipped += r2.get("skipped", []) + ([r2["error"]] if r2.get("error") else [])

    # AUTO-OK add/drops, one at a time, names checked on Yahoo's add page before submitting
    for sw in plan["swaps"]:
        add, drop = sw["add"], sw["drop"]
        apid, dpid = pids.get(add), pids.get(drop)
        if not apid or not dpid or slots.get(drop) is None:
            skipped.append(f"add {add} / drop {drop}: player id not found"); continue
        if dry:
            did.append(f"(dry run) add {add} / drop {drop} (+{sw['gain']})"); continue
        page.goto(f"{BASE}{LEAGUE}/addplayer?apid={apid}", wait_until="domcontentloaded")
        box = page.locator(f'input[name="dpid"][value="{dpid}"]')
        body = page.inner_text("body")
        if add not in body or drop not in body or box.count() != 1:
            skipped.append(f"add {add} / drop {drop}: add page didn't show both players; nothing submitted"); continue
        box.check()
        page.locator('input[name="submit_drop_player"], form[action*="addplayer"] button[type="submit"]').first.click()
        page.wait_for_load_state("domcontentloaded")
        confirm = page.locator('form[action*="addplayer"] input[type="submit"], form[action*="addplayer"] button[type="submit"]')
        if confirm.count():  # Yahoo sometimes shows a confirm step
            confirm.first.click(); page.wait_for_load_state("domcontentloaded")
        waiver = "waiver" in page.inner_text("body").lower()
        subprocess.run([sys.executable, str(REPO / "manage.py"), "acq", add, drop] + ([] if approved else ["--auto"]),
                       cwd=REPO, capture_output=True)
        did.append(f"{'waiver claim' if waiver else 'added'} {add} / dropped {drop} (+{sw['gain']})")
    return did, skipped


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    dry = "--dry-run" in sys.argv
    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        if cmd == "login":
            ctx = browser(p, headless=False)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(f"{BASE}{LEAGUE}/{TEAM}")
            print("Sign into Yahoo in the window that opened (tick 'Stay signed in'), "
                  "check your team page loads, then close the window.")
            page.wait_for_event("close", timeout=0)
            ctx.close()
            return
        ctx = browser(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if cmd == "team":
            page.goto(f"{BASE}{LEAGUE}/{TEAM}", wait_until="domcontentloaded")
            other = page.evaluate(EXTRACT_JS, {"league": LEAGUE, "team": int(sys.argv[2]), "faQueries": []})
            if other.get("loggedOut"):
                sys.exit("yahoo_bot: not signed in. Run `.venv/bin/python yahoo_bot.py login` and sign into Yahoo.")
            print(" ~ ".join(r["spec"] for r in other["roster"]))
            ctx.close()
            return
        data = read(page)
        if cmd == "swap":
            add, drop = sys.argv[2], sys.argv[3]
            plan = {"lineup": {}, "ir": [], "swaps": [{"add": add, "drop": drop, "gain": 0}]}
            did, skipped = apply(page, data, plan, dry, approved=True)
            ctx.close()
            print("\nRESULT_JSON " + json.dumps({"did": did, "skipped": skipped}))
            return
        text, plan = run_report(data)
        print(text)
        result = {"date": data["today"], "did": [], "skipped": [], "plan": plan}
        if cmd == "apply":
            result["did"], result["skipped"] = apply(page, data, plan, dry)
            if result["did"] and not dry:  # re-check: the report should now have nothing left to do
                text2, plan2 = run_report(read(page))
                left = plan2["lineup"] or plan2["ir"] or plan2["swaps"]
                result["left_after"] = plan2 if left else None
            print("\nDID:", *result["did"] or ["nothing"], sep="\n  ")
            if result["skipped"]:
                print("SKIPPED:", *result["skipped"], sep="\n  ")
        ctx.close()
        print("\nRESULT_JSON " + json.dumps(result))


if __name__ == "__main__":
    main()
