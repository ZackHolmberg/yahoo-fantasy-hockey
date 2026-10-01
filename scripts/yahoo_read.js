// Paste into the Claude in Chrome javascript tool on any hockey.fantasysports.yahoo.com tab (uses the owner's login).
// Read-only: fetches our roster page and the available-players pages in the background (no navigation) and prints
// the compact payload `python3 manage.py report` takes (D date ~ R slot:spec ~ ... ~ F spec ~ ...; no '=' or ';', which the tool's privacy filter blocks). See docs/MANAGER.md.
const LEAGUE = '/hockey/23491', MY_TEAM = 11;  // Suzuki For Hart
const STATUS = /^(DTD|O|IR|IR-LT|IR-NR|NA|SUSP|INJ)$/;
const doc = async path => new DOMParser().parseFromString(
  await (await fetch(path, {credentials: 'include', cache: 'no-store'})).text(), 'text/html');
// apostrophes become ’ so the payload survives single-quoting in the shell; manage.py turns them back
const clean = s => s.trim().replace(/'/g, '’');
const spec = cell => {
  const a = cell.querySelector('a[class*="name"]') || cell.querySelector('a[href*="/players/"]');
  if (!a) return null;
  const texts = [...cell.querySelectorAll('span, abbr')].map(s => s.textContent.trim());
  const tp = texts.find(t => /^[A-Z]{2,4} - [A-Z,]+$/.test(t)) || ' - ';
  const [team, pos] = tp.split(' - ');
  return `${clean(a.textContent)}|${pos}|${texts.find(t => STATUS.test(t)) || ''}|${team}`;
};
const today = new Date().toLocaleDateString('en-CA');  // YYYY-MM-DD, local time
const team = await doc(`${LEAGUE}/${MY_TEAM}/team?date=${today}`);
const roster = [...team.querySelectorAll('#statTable0 tbody tr, #statTable1 tbody tr')]
  .map(r => ({slot: r.cells[0]?.textContent.trim(), spec: r.cells[2] && spec(r.cells[2])}))
  .filter(r => r.spec);
const freeAgents = new Set();
// preseason/overall rank (2 pages), current-season rank, goalies
for (const q of ['status=A&pos=P&sort=OR&sdir=1&count=0', 'status=A&pos=P&sort=OR&sdir=1&count=25',
                 'status=A&pos=P&sort=AR&sdir=1&count=0', 'status=A&pos=G&sort=OR&sdir=1&count=0']) {
  const d = await doc(`${LEAGUE}/players?${q}`);
  const t = [...d.querySelectorAll('table')].find(t => t.querySelector('a[href*="/players/"]') && t.rows.length > 10);
  for (const r of t ? t.tBodies[0].rows : []) {
    const s = spec(r);
    if (s) freeAgents.add(s);
  }
}
const payload = [`D ${today}`, ...roster.map(r => `R ${r.slot}:${r.spec}`), ...[...freeAgents].filter(f => !/\|NA\|/.test(f)).map(f => `F ${f}`)].join(' ~ ');
// Hand-off: tool results are cut at ~1000 chars, so keep the payload in the page and return it in chunks.
// Pass every chunk, in order, as separate arguments: python3 manage.py [--league espn] report '<chunk0>' '<chunk1>' ...
window.__fh = payload;
window.__fhChunk = i => window.__fh.slice(i * 900, (i + 1) * 900);
payload.length <= 900 ? payload
  : `${Math.ceil(payload.length / 900)} chunks: run window.__fhChunk(0), window.__fhChunk(1), ... and pass each verbatim`
