"""Render data/rankings.csv into DRAFT_SHEET.md grouped by draft round (12 teams)."""
import csv

TEAMS = 12
rows = list(csv.DictReader(open("data/rankings.csv")))[:216]
out = ["# Draft sheet: league 23491 (12-team H2H points)",
       "",
       "Ranked by value over replacement (VOR) using this league's scoring. Round bands assume players go in this order;",
       "real drafts won't follow it, so treat bands as 'this is fair value around here'. Check Yahoo eligibility in the draft room:",
       "a player listed C here who is also LW/RW-eligible on Yahoo is worth MORE (wing slots run thin faster).",
       ""]
for i in range(0, len(rows), TEAMS):
    out.append(f"## Round {i // TEAMS + 1} (picks {i + 1}-{i + TEAMS})")
    out.append("| # | Player | Pos | Team | Proj FP | VOR | Note |")
    out.append("|---|---|---|---|---|---|---|")
    for r in rows[i:i + TEAMS]:
        out.append(f"| {r['rank']} | {r['name']} | {r['pos_rank']} | {r['team']} | {float(r['proj_fp']):.0f} | {float(r['vor']):.0f} | {r['note']} |")
    out.append("")
out += ["## Rookies (no NHL history, so the model can't project them)",
        "Consider them only in the late rounds (about round 12 on) unless the value is clear:",
        "- **Porter Martone** (PHI): 1st-line power winger, so hits help here. Yahoo ADP around 68.",
        "- **Gavin McKenna** (TOR): with Tavares and Nylander. ADP around 94. Scoring-only profile.",
        "- **Anton Frondell** (CHI): 1C and PP1 while Bedard is out. Faceoffs help. ADP around 138.",
        "- **Roman Kantserov** (CHI): top line and PP1 with Kane. Usually undrafted.",
        "- **Ivar Stenberg** (SJS): ADP around 133.",
        "- **Ilya Protas** (WSH): top line. Usually undrafted.",
        "",
        "## Rules of thumb for this league",
        "- Blocks (0.75) and hits (0.5) are worth a lot. Prefer the physical player when projections are close.",
        "- Only one goalie starts per day. Aim for 1 strong starter, then a 2nd by the middle rounds and a 3rd late.",
        "- Centers are plentiful because faceoffs are worth points. Don't reach for a C; wingers run out first.",
        "- Avoid unsettled goalie situations: EDM, NJD, PIT, VAN, WPG (Hellebuyck), TOR's 1A/1B."]
open("DRAFT_SHEET.md", "w").write("\n".join(out) + "\n")
print("wrote DRAFT_SHEET.md")
