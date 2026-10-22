"""Yahoo league 23491 without Claude: Playwright drives a dedicated browser profile the owner signed into once.

    .venv/bin/python yahoo_bot.py login            # once (and whenever Yahoo logs it out): sign in, then close the window
    .venv/bin/python yahoo_bot.py report           # read the site and print manage.py's report; changes nothing
    .venv/bin/python yahoo_bot.py apply [--dry-run]  # report, set lineup/IR, make AUTO-OK add/drops, re-check
    .venv/bin/python yahoo_bot.py week [--dry-run]  # Mondays: pre-set skater lineups for tomorrow..Sunday
    .venv/bin/python yahoo_bot.py add "Name" [--dry-run]  # one pure add into an open spot the OWNER asked for
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
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright

REPO = Path(__file__).resolve().parent
PROFILE = REPO / "data/yahoo_profile"
BASE = "https://hockey.fantasysports.yahoo.com"
LEAGUE, TEAM = "/hockey/23491", 11
FA_QUERIES = ["status=A&pos=P&sort=OR&sdir=1&count=0", "status=A&pos=P&sort=OR&sdir=1&count=25",
              "status=A&pos=P&sort=AR&sdir=1&count=0", "status=A&pos=G&sort=OR&sdir=1&count=0"]

# Runs in the page. Same extraction as scripts/yahoo_read.js, plus Yahoo player ids for the actions.
EXTRACT_JS = """async ({league, team, faQueries, date}) => {
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
  const today = date || new Date().toLocaleDateString('en-CA');
  let page = await doc(`${league}/${team}/team?date=${today}`);
  if (!page.querySelector('#statTable0') && !date) page = await doc(`${league}/${team}`);  // other teams' pages
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
  for (let [pid, name, slot] of moves) {
    const sel = form.querySelector(`select[name="${pid}"]`);
    const row = sel && sel.closest('tr');
    const shown = row && (row.querySelector('a[class*="name"]') || {}).textContent;
    if (!sel || (shown || '').trim() !== name) { skipped.push(`${name}: row/name mismatch`); continue; }
    const has = v => [...sel.options].some(o => o.value === v);
    if (slot === 'IR' && !has('IR') && has('IR+')) slot = 'IR+';  // status O only fits IR+ in this league
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


def run_report(data, *flags):
    items = [f"D {data['today']}"] + [f"R {r['slot']}:{r['spec']}" for r in data["roster"]] + [f"F {f['spec']}" for f in data["fas"]]
    out = subprocess.run([sys.executable, str(REPO / "manage.py"), "report", "--json", *flags, "-"], input=" ~ ".join(items),
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
        moves.append([pids.get(n, ""), n, "IR"])  # SET_LINEUP_JS falls back to IR+ if Yahoo only allows that
    if moves:
        if dry:
            did += [f"(dry run) {n} -> {s}" for _, n, s in moves]
        else:
            page.goto(f"{BASE}{LEAGUE}/{TEAM}/team?date={data['today']}", wait_until="domcontentloaded")
            try:  # wait for the submit's navigation, or the next goto aborts it (net::ERR_ABORTED)
                with page.expect_navigation(wait_until="load", timeout=30000):
                    res = page.evaluate(SET_LINEUP_JS, moves)
            except PlaywrightTimeout:  # nothing was submitted (no move applied, or no form)
                pass
            if res.get("error"):
                skipped.append("lineup: " + res["error"])
            else:
                did += res["done"]; skipped += res["skipped"]

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
        # Yahoo's add page picks the drop with a per-player "—" button that ticks a hidden checkbox, then offers
        # a submit button reading "Add X, Drop Y": only click it if it names exactly our two players
        page.locator(f'button[data-check-box-value^="{dpid}"]').click()
        submit = page.locator('input[name="submit_add_player"]')
        try:  # the button is rendered a moment after the drop is picked
            submit.wait_for(state="attached", timeout=10000)
        except PlaywrightTimeout:
            pass
        label = submit.get_attribute("value") if submit.count() == 1 else ""
        if add not in (label or "") or drop not in (label or ""):
            skipped.append(f"add {add} / drop {drop}: Yahoo's confirm button read {label!r}; nothing submitted"); continue
        submit.click()
        page.wait_for_load_state("domcontentloaded")
        confirm = page.locator('form[action*="addplayer"] input[type="submit"], form[action*="addplayer"] button[type="submit"]')
        if confirm.count():  # Yahoo sometimes shows a confirm step
            confirm.first.click(); page.wait_for_load_state("domcontentloaded")
        waiver = "waiver" in page.inner_text("body").lower()
        subprocess.run([sys.executable, str(REPO / "manage.py"), "acq", add, drop] + ([] if approved else ["--auto"]),
                       cwd=REPO, capture_output=True)
        did.append(f"{'waiver claim' if waiver else 'added'} {add} / dropped {drop} (+{sw['gain']})")
    return did, skipped


def week(page, dry):
    """Monday: set the skater lineup for each remaining day of the week (tomorrow..Sunday). Goalies are left to the
    daily run, which sets them from that day's starter news; the daily run also re-checks everything else."""
    today = date.today()
    did, skipped = [], []
    for i in range(1, 7 - today.weekday()):
        day = (today + timedelta(days=i)).isoformat()
        data = page.evaluate(EXTRACT_JS, {"league": LEAGUE, "team": TEAM, "faQueries": [], "date": day})
        if data.get("loggedOut"):
            skipped.append(f"{day}: couldn't load that day's roster page"); continue
        _, plan = run_report(data, "--skaters-only")
        if not plan["lineup"]:
            continue
        d, s = apply(page, data, {"lineup": plan["lineup"], "ir": [], "swaps": []}, dry)
        did += [f"{day[5:]} {x}" for x in d]; skipped += [f"{day[5:]} {x}" for x in s]
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
        if cmd == "week":
            did, skipped = week(page, dry)
            ctx.close()
            print("\nRESULT_JSON " + json.dumps({"did": did, "skipped": skipped}))
            return
        if cmd == "add":  # a pure add into an open roster spot the OWNER asked for (reply pipeline)
            name = sys.argv[2]
            pid = {f["name"]: f["pid"] for f in data["fas"]}.get(name)
            if not pid:
                ctx.close()
                print("\nRESULT_JSON " + json.dumps({"did": [], "skipped": [f"add {name}: not found among free agents"]}))
                return
            page.goto(f"{BASE}{LEAGUE}/addplayer?apid={pid}", wait_until="domcontentloaded")
            btn = page.locator('input[name="submit_add_drop"]')
            if btn.count() != 1 or name not in (btn.get_attribute("value") or "") or "don't drop" not in (btn.get_attribute("value") or ""):
                ctx.close()
                print("\nRESULT_JSON " + json.dumps({"did": [], "skipped": [f"add {name}: Yahoo didn't offer a no-drop add (roster full?); nothing submitted"]}))
                return
            if dry:
                ctx.close()
                print("\nRESULT_JSON " + json.dumps({"did": [f"(dry run) add {name}"], "skipped": []}))
                return
            btn.click(); page.wait_for_load_state("domcontentloaded")
            confirm = page.locator('form[action*="addplayer"] input[type="submit"], form[action*="addplayer"] button[type="submit"]')
            if confirm.count():
                confirm.first.click(); page.wait_for_load_state("domcontentloaded")
            waiver = "waiver" in page.inner_text("body").lower()
            subprocess.run([sys.executable, str(REPO / "manage.py"), "acq", name, "-"], cwd=REPO, capture_output=True)
            ctx.close()
            print("\nRESULT_JSON " + json.dumps({"did": [f"{'waiver claim' if waiver else 'added'} {name}"], "skipped": []}))
            return
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
