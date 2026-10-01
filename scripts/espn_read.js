// Paste into the Claude in Chrome javascript tool on any fantasy.espn.com tab (uses the owner's login).
// Read-only. Builds the compact payload `python3 manage.py --league espn report` takes: our roster with slots and the
// top 40 free agents/waiver players as "Name|POS|STATUS|TEAM" specs. See docs/MANAGER_ESPN.md.
const B = 'https://lm-api-reads.fantasy.espn.com/apis/v3/games/fhl/seasons/2027';
const L = B + '/segments/0/leagues/1034056432';
const MY_TEAM = 5;  // Suzuki For Hart
const get = (u, h) => fetch(u + (u.includes('?') ? '&' : '?') + '_=' + Date.now(),
  {credentials: 'include', cache: 'no-store', headers: h || {}}).then(r => r.json());
const teams = Object.fromEntries((await get(B + '?view=proTeamSchedules_wl')).settings.proTeams
  .map(t => [t.id, t.abbrev.toUpperCase()]));
const POS = {1: 'F', 2: 'F', 3: 'F', 4: 'D', 5: 'G'};
const SLOT = {3: 'F', 4: 'D', 5: 'G', 7: 'BE', 8: 'IR'};
const fmt = p => `${p.fullName.replace(/'/g, '\u2019')}|${POS[p.defaultPositionId]}|${p.injuryStatus && p.injuryStatus !== 'ACTIVE' ? p.injuryStatus : ''}|${teams[p.proTeamId] || ''}`;
const league = await get(L + '?view=mRoster&view=mTeam&view=mPendingTransactions&view=mStatus');
const mine = league.teams.find(t => t.id === MY_TEAM);
const roster = mine.roster.entries.map(e => ({spec: fmt(e.playerPoolEntry.player), slot: SLOT[e.lineupSlotId] || e.lineupSlotId}));
const filter = {players: {filterStatus: {value: ['FREEAGENT', 'WAIVERS']}, limit: 40, sortPercOwned: {sortPriority: 1, sortAsc: false}}};
const fa = (await get(L + '?view=kona_player_info', {'x-fantasy-filter': JSON.stringify(filter)})).players
  .map(x => fmt(x.player) + (x.status === 'WAIVERS' ? ' (waivers)' : ''));
const today = new Date().toLocaleDateString('en-CA');
const payload = [`D ${today}`, ...roster.map(r => `R ${r.slot}:${r.spec}`), ...fa.map(f => `F ${f}`)].join(' ~ ');
// Hand-off: tool results are cut at ~1000 chars, so keep the payload in the page and return it in chunks.
// Pass every chunk, in order, as separate arguments: python3 manage.py [--league espn] report '<chunk0>' '<chunk1>' ...
window.__fh = payload;
window.__fhChunk = i => window.__fh.slice(i * 900, (i + 1) * 900);
payload.length <= 900 ? payload
  : `${Math.ceil(payload.length / 900)} chunks: run window.__fhChunk(0), window.__fhChunk(1), ... and pass each verbatim`
