const statusEl = document.getElementById("status");
const gainersBody = document.getElementById("gainers-body");
const losersBody = document.getElementById("losers-body");
const gainerCount = document.getElementById("gainer-count");
const loserCount = document.getElementById("loser-count");

function fmt(n, digits = 2) {
  return n === null || n === undefined ? "-" : Number(n).toFixed(digits);
}

function candleDots(colors) {
  return (colors || [])
    .map((c) => `<span class="candle-dot ${c}" title="${c}"></span>`)
    .join("");
}

function rowHtml(row) {
  const pctClass = row.pct_change >= 0 ? "pct-up" : "pct-down";
  return `<tr>
    <td>${row.symbol}</td>
    <td>${fmt(row.ltp)}</td>
    <td class="${pctClass}">${fmt(row.pct_change)}%</td>
    <td>${candleDots(row.last_two_colors)}</td>
  </tr>`;
}

function render(msg) {
  statusEl.textContent = msg.connected ? "live" : "disconnected";
  statusEl.className = "status " + (msg.connected ? "connected" : "disconnected");

  const gainers = msg.data
    .filter((r) => r.signal === "GAINER")
    .sort((a, b) => (b.pct_change ?? -999) - (a.pct_change ?? -999));
  const losers = msg.data
    .filter((r) => r.signal === "LOSER")
    .sort((a, b) => (a.pct_change ?? 999) - (b.pct_change ?? 999));

  gainerCount.textContent = gainers.length;
  loserCount.textContent = losers.length;
  gainersBody.innerHTML = gainers.map(rowHtml).join("") || `<tr><td colspan="4" style="color:#666">none yet</td></tr>`;
  losersBody.innerHTML = losers.map(rowHtml).join("") || `<tr><td colspan="4" style="color:#666">none yet</td></tr>`;
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
