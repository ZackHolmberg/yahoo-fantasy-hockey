"""Replace league team names with aliases (T1..T12, the Yahoo team number in /hockey/23491/<n>).

Some opponents' team names trip content filters, so everything Claude writes (season log,
run logs, texts, show_run.py output) goes through scrub(). The mapping lives in the gitignored
data/team_aliases.json: {"T1": "exact Yahoo team name", "T2": ["full name", "short form"], ...}.
The owner fills it in once; list short forms the bot might use too.

  python3 team_alias.py < file       # scrub stdin to stdout
  python3 team_alias.py --file PATH  # scrub a file in place
"""
import json
import re
import sys
from pathlib import Path

MAP = Path(__file__).resolve().parent / "data/team_aliases.json"


def load():
    try:
        raw = json.loads(MAP.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    pairs = []
    for alias, names in raw.items():
        if not alias.startswith("_"):
            pairs += [(alias, n) for n in ([names] if isinstance(names, str) else names) if n.strip()]
    return pairs


def scrub(text, aliases=None):
    aliases = load() if aliases is None else aliases
    # longest names first, case-insensitive, tolerant of straight/curly apostrophes and extra spaces
    for alias, name in sorted(aliases, key=lambda an: -len(an[1])):
        pat = re.escape(name.strip()).replace("'", "['’]").replace(r"\ ", r"\s+")
        text = re.sub(r"\b" + pat + r"\b", alias, text, flags=re.IGNORECASE)
    return text


if __name__ == "__main__":
    if sys.argv[1:2] == ["--file"]:
        p = Path(sys.argv[2])
        p.write_text(scrub(p.read_text()))
    else:
        sys.stdout.write(scrub(sys.stdin.read()))
