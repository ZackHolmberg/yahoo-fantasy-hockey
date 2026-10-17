// Run in the browser developer console on a signed-in fantasy.espn.com page.
// Read-only: exports league/player/schedule data, never cookies or credentials.
// Import with: python -m basketball import <downloaded basketball-export.json>
(async () => {
  if (location.hostname !== 'fantasy.espn.com') throw new Error('Open your ESPN fantasy league first');
  const query = new URL(location.href).searchParams;
  const leagueId = query.get('leagueId');
  const seasonId = query.get('seasonId');
  if (!leagueId || !seasonId) throw new Error('Include leagueId and seasonId in the page URL');
  const base = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/${encodeURIComponent(seasonId)}`;
  const url = `${base}/segments/0/leagues/${encodeURIComponent(leagueId)}`;
  const get = async (u, filter) => {
    const r = await fetch(u, {credentials: 'include', cache: 'no-store',
      headers: filter ? {'x-fantasy-filter': JSON.stringify(filter)} : {}});
    if (!r.ok) throw new Error(`ESPN read failed: HTTP ${r.status}`);
    return r.json();
  };
  const league = await get(url + '?view=mSettings&view=mStatus&view=mTeam&view=mRoster&view=mMatchup&view=mDraftDetail&view=mPendingTransactions');
  const players = [];
  for (let offset = 0; ; offset += 500) {
    if (offset >= 10000) throw new Error('Player pagination did not finish');
    const page = await get(url + '?view=kona_player_info', {players: {offset, limit: 500,
      sortPercOwned: {sortPriority: 1, sortAsc: false},
      filterStatsForExternalIds: {value: [+seasonId, +seasonId - 1, +seasonId - 2]},
      filterStatsForSourceIds: {value: [0, 1]}, filterStatsForSplitTypeIds: {value: [0]}}});
    if (!Array.isArray(page.players)) throw new Error('Missing player data');
    players.push(...page.players);
    if (page.players.length < 500 || players.length >= (page.totalPlayerCount ?? Infinity)) break;
  }
  if (new Set(players.map(p => p.player.id)).size !== players.length) throw new Error('Repeated player page');
  const periods = league.settings?.scheduleSettings?.matchupPeriods?.[league.status?.currentMatchupPeriod]
    ?.filter(p => +p <= league.scoringPeriodId);
  if (periods?.length) {
    const transactions = new Map();
    for (const period of periods) {
      const history = await get(url + `?view=mTransactions2&scoringPeriodId=${period}`,
        {transactions: {filterType: {value: ['FREEAGENT', 'WAIVER', 'TRADE_PROPOSAL', 'TRADE_ACCEPT', 'TRADE_DECLINE']}}});
      if (!Array.isArray(history.transactions)) throw new Error('Missing acquisition history');
      if ((history.totalTransactionCount ?? history.transactions.length) > history.transactions.length)
        throw new Error('Truncated acquisition history');
      history.transactions.forEach(t => transactions.set(t.id, t));
    }
    league.basketballTransactions = [...transactions.values()];
  }
  const season = await get(base + '?view=proTeamSchedules_wl');
  const blob = new Blob([JSON.stringify({league, players, season})], {type: 'application/json'});
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = 'basketball-export.json';
  a.click();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  console.info(`Exported ${players.length} basketball players. No credentials exported.`);
})();
