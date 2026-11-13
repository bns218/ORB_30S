const statusEl = document.getElementById("status");
const countdownEl = document.getElementById("countdown");
const gainersBody = document.getElementById("gainers-body");
const losersBody = document.getElementById("losers-body");
const gainerCount = document.getElementById("gainer-count");
const loserCount = document.getElementById("loser-count");

function fmt(n, digits = 2) {
  return n === null || n === undefined ? "-" : Number(n).toFixed(digits);
}

// Mini candlestick for one 30s candle. The body and wick are scaled to the
// candle's own high-low range so shape (not size) shows. Used for both the
// last completed candle and the one still forming.
function liveCandle(c) {
  if (!c) return `<span class="muted">waiting…</span>`;
  const W = 16, H = 28, PAD = 2;
  const rng = c.high - c.low;
  const y = (v) => (rng > 0 ? PAD + ((c.high - v) / rng) * (H - 2 * PAD) : H / 2);
  const dir = c.close > c.open ? "green" : c.close < c.open ? "red" : "neutral";
  const top = Math.min(y(c.open), y(c.close));
  const bodyH = Math.max(Math.abs(y(c.open) - y(c.close)), 1.5);
  const move = c.open ? ((c.close - c.open) / c.open) * 100 : 0;
  const sign = move > 0 ? "+" : "";
  const tip = `O ${fmt(c.open)}  H ${fmt(c.high)}  L ${fmt(c.low)}  C ${fmt(c.close)}  (${c.ticks} ticks)`;
  return `<span class="live" title="${tip}">
    <svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" class="c-${dir}">
      <line x1="${W / 2}" x2="${W / 2}" y1="${y(c.high)}" y2="${y(c.low)}" />
      <rect x="3" width="${W - 6}" y="${top}" height="${bodyH}" />
    </svg>
    <span class="live-move c-${dir}-text">${sign}${move.toFixed(2)}%</span>
  </span>`;
}

// Most recent fully closed 30s candle (the server sends the last few).
function lastCompleted(row) {
  const c = row.last_candles || [];
  return c.length ? c[c.length - 1] : null;
}

function rowHtml(row) {
  const pctClass = row.pct_change >= 0 ? "pct-up" : "pct-down";
  const sign = row.pct_change > 0 ? "+" : "";
  return `<tr>
    <td>${row.symbol}</td>
    <td>${fmt(row.ltp)}</td>
    <td>${fmt(row.prev_close)}</td>
    <td class="${pctClass}">${sign}${fmt(row.pct_change)}%</td>
    <td class="live-cell">${liveCandle(lastCompleted(row))}</td>
    <td class="live-cell">${liveCandle(row.live)}</td>
  </tr>`;
}

function render(msg) {
  statusEl.textContent = msg.connected ? "live" : "disconnected";
  statusEl.className = "status " + (msg.connected ? "connected" : "disconnected");

  // Seconds until the forming 30s candle closes (candles are aligned to :00/:30).
  const left = 30 - (Math.floor(msg.server_time) % 30);
  countdownEl.textContent = `30s candle closes in ${left}s`;

  // Today's gainers/losers: up/down versus the previous close.
  const gainers = msg.data
    .filter((r) => r.pct_change > 0)
    .sort((a, b) => b.pct_change - a.pct_change);
  const losers = msg.data
    .filter((r) => r.pct_change < 0)
    .sort((a, b) => a.pct_change - b.pct_change);

  gainerCount.textContent = gainers.length;
  loserCount.textContent = losers.length;
  gainersBody.innerHTML = gainers.map(rowHtml).join("") || `<tr><td colspan="6" style="color:#666">none yet</td></tr>`;
  losersBody.innerHTML = losers.map(rowHtml).join("") || `<tr><td colspan="6" style="color:#666">none yet</td></tr>`;
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    if (msg.type === "snapshot") render(msg);
  };
  ws.onclose = () => {
    statusEl.textContent = "reconnecting…";
    statusEl.className = "status disconnected";
    setTimeout(connect, 1500);
  };
  ws.onerror = () => ws.close();
}

connect();
