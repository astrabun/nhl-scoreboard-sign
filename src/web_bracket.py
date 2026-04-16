#!/usr/bin/env python3
"""NHL Playoff Bracket — live-updating web server.

Requires: pip install aiohttp
Run:      python web_bracket.py
Open:     http://localhost:8080
"""

import asyncio
import json
import logging
import os
from datetime import datetime

import aiohttp
from aiohttp import web

NHL_API_URL = "https://api-web.nhle.com/v1/playoff-bracket/2026"
REFRESH_INTERVAL = 300  # 5 minutes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

bracket_data: dict | None = None
clients: set[web.WebSocketResponse] = set()


async def fetch_bracket() -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            NHL_API_URL, timeout=aiohttp.ClientTimeout(total=10)
        ) as r:
            r.raise_for_status()
            return await r.json(content_type=None)


async def broadcast(payload: str) -> None:
    gone: set[web.WebSocketResponse] = set()
    for ws in clients:
        try:
            await ws.send_str(payload)
        except Exception:
            gone.add(ws)
    clients.difference_update(gone)


async def poller(app: web.Application) -> None:
    global bracket_data
    while True:
        try:
            data = await fetch_bracket()
            bracket_data = data
            log.info(
                "Bracket refreshed at %s — broadcasting to %d client(s)",
                datetime.now().strftime("%H:%M:%S"),
                len(clients),
            )
            await broadcast(json.dumps({"type": "update", "data": data}))
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.warning("Bracket fetch failed: %s", exc)
        await asyncio.sleep(REFRESH_INTERVAL)


async def start_poller(app: web.Application) -> None:
    app["poller"] = asyncio.create_task(poller(app))


async def stop_poller(app: web.Application) -> None:
    app["poller"].cancel()
    await asyncio.gather(app["poller"], return_exceptions=True)


async def index(req: web.Request) -> web.Response:
    return web.Response(text=PAGE, content_type="text/html")


async def websocket_handler(req: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(req)
    clients.add(ws)
    log.info("Client connected (%d total)", len(clients))
    if bracket_data is not None:
        await ws.send_str(json.dumps({"type": "update", "data": bracket_data}))
    try:
        async for _ in ws:
            pass
    finally:
        clients.discard(ws)
        log.info("Client disconnected (%d remaining)", len(clients))
    return ws


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NHL Playoffs 2026</title>
<style>
:root {
  --bg: #06070f;
  --surface: #0d0f1e;
  --border: #1c1e38;
  --border-hi: #3a3d6a;
  --gold: #c8a84b;
  --text: #d8dae8;
  --muted: #50527a;
  --win-bg: rgba(200,168,75,0.13);
  --elim: 0.32;
  --cw: 172px;
  --ch: 88px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body {
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
}
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  padding: 14px 16px 8px;
  display: flex;
  flex-direction: column;
}
header { text-align: center; flex-shrink: 0; margin-bottom: 8px; }
#logo { max-height: 48px; display: none; }
#bracket-title {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--gold);
  margin-top: 6px;
  letter-spacing: 0.3px;
}
#bracket-subtitle { font-size: 0.72rem; color: var(--muted); margin-top: 3px; }
#status {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  font-size: 0.68rem;
  color: var(--muted);
  margin-bottom: 10px;
  flex-shrink: 0;
}
#dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: #2a2a45;
  transition: background 0.4s;
  flex-shrink: 0;
}
#dot.live { background: #4caf50; }
#dot.err  { background: #e53935; }
#bracket {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.bracket {
  display: flex;
  align-items: stretch;
  justify-content: center;
  transform-origin: center center;
  flex-shrink: 0;
}
.conf { display: flex; align-items: flex-start; }
.conf.west { flex-direction: row; }
.conf.east { flex-direction: row-reverse; }
.rcol { display: flex; flex-direction: column; align-items: stretch; flex-shrink: 0; width: var(--cw); }
.rhdr {
  font-size: 0.62rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--muted);
  text-align: center;
  padding-bottom: 10px;
  white-space: nowrap;
}
.sc {
  width: var(--cw);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 7px;
  padding: 7px 9px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  transition: border-color 0.2s;
}
.sc:hover { border-color: var(--border-hi); }
.sc.scf {
  border-color: rgba(200,168,75,0.45);
  box-shadow: 0 0 18px rgba(200,168,75,0.1);
}
.sc-lbl {
  font-size: 0.58rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 2px;
}
.sc-tbd {
  font-size: 0.72rem;
  color: var(--muted);
  font-style: italic;
  padding: 15px 0;
  text-align: center;
}
.team {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 5px;
  border-radius: 4px;
  font-size: 0.77rem;
}
.team.win { background: var(--win-bg); }
.team.out { opacity: var(--elim); }
.team img { width: 26px; height: 26px; object-fit: contain; flex-shrink: 0; }
.team-abbr { flex: 1; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.team-w { font-weight: 700; color: var(--gold); font-size: 0.88rem; min-width: 14px; text-align: right; }
.scf-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 0 20px;
  flex-shrink: 0;
  gap: 10px;
}
#cup-logo { max-height: 56px; object-fit: contain; }
</style>
</head>
<body>
<header>
  <img id="logo" alt="NHL Playoffs">
  <div id="bracket-title">NHL Playoffs 2026</div>
  <div id="bracket-subtitle">Loading\u2026</div>
</header>
<div id="status">
  <span id="dot"></span>
  <span id="status-txt">Connecting\u2026</span>
</div>
<div id="bracket"></div>

<script>
const W = 4;

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(proto + '://' + location.host + '/ws');
  const dot = document.getElementById('dot');
  const txt = document.getElementById('status-txt');
  ws.onopen  = () => { dot.className = 'live'; txt.textContent = 'Live'; };
  ws.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'update') {
      render(msg.data);
      txt.textContent = 'Updated ' + new Date().toLocaleTimeString();
    }
  };
  ws.onclose = () => {
    dot.className = 'err';
    txt.textContent = 'Reconnecting\u2026';
    setTimeout(connect, 3000);
  };
  ws.onerror = () => ws.close();
}

function byLetter(data) {
  const m = {};
  for (const s of (data.series || [])) if (s.seriesLetter) m[s.seriesLetter] = s;
  return m;
}

function teamRow(team, wins, state) {
  if (!team) return '';
  const cls = state === 'win' ? 'win' : state === 'out' ? 'out' : '';
  const logo = team.darkLogo || team.logo || '';
  const img = logo
    ? '<img src="' + logo + '" alt="' + team.abbrev + '" loading="lazy" onerror="this.remove()">'
    : '<span style="width:26px;flex-shrink:0"></span>';
  return '<div class="team ' + cls + '">' + img
    + '<span class="team-abbr">' + team.abbrev + '</span>'
    + '<span class="team-w">' + wins + '</span></div>';
}

function card(s, label, extraClass) {
  const cx = extraClass || '';
  if (!s) return '<div class="sc ' + cx + '"><div class="sc-lbl">' + (label||'') + '</div><div class="sc-tbd">TBD</div></div>';
  const topW = s.topSeedWins === W, botW = s.bottomSeedWins === W;
  const lbl = label || (s.seriesTitle + ' \u00b7 ' + s.seriesLetter);
  let body;
  if (s.topSeedTeam || s.bottomSeedTeam) {
    body = teamRow(s.topSeedTeam,    s.topSeedWins,    topW ? 'win' : botW ? 'out' : '')
         + teamRow(s.bottomSeedTeam, s.bottomSeedWins, botW ? 'win' : topW ? 'out' : '');
  } else {
    body = '<div class="sc-tbd">TBD</div>';
  }
  return '<div class="sc ' + cx + '"><div class="sc-lbl">' + lbl + '</div>' + body + '</div>';
}

function sp(px) { return '<div style="height:' + px + 'px;flex-shrink:0"></div>'; }
function gp(px) { return '<div style="width:' + px + 'px;flex-shrink:0"></div>'; }

function render(data) {
  const logo = document.getElementById('logo');
  if (data.bracketLogo) { logo.src = data.bracketLogo; logo.style.display = ''; }
  document.getElementById('bracket-title').textContent = (data.bracketTitle && data.bracketTitle.default) || 'NHL Playoffs 2026';
  document.getElementById('bracket-subtitle').textContent = (data.bracketSubTitle && data.bracketSubTitle.default) || '';

  const s = byLetter(data);

  // Layout math (CH must match CSS --ch: 88px)
  const CH = 88, PG = 10, GG = 28;
  const R1H = 2 * (2 * CH + PG) + GG;          // 400
  const mid1 = CH + PG / 2;                      // 93  — pair-1 center
  const mid2 = 2 * CH + PG + GG + CH + PG / 2;  // 307 — pair-2 center
  const r2t1 = Math.round(mid1 - CH / 2);        // 49
  const r2t2 = Math.round(mid2 - CH / 2);        // 263
  const cfT  = Math.round((mid1 + mid2) / 2 - CH / 2);  // 156

  function r1Col(a, b, c, d, hdr) {
    return '<div class="rcol">'
      + '<div class="rhdr">' + hdr + '</div>'
      + '<div style="height:' + R1H + 'px;display:flex;flex-direction:column;">'
      + card(s[a], 'R1 \u00b7 ' + a)
      + sp(PG)
      + card(s[b], 'R1 \u00b7 ' + b)
      + sp(GG)
      + card(s[c], 'R1 \u00b7 ' + c)
      + sp(PG)
      + card(s[d], 'R1 \u00b7 ' + d)
      + '</div></div>';
  }

  function r2Col(i, j, hdr) {
    return '<div class="rcol">'
      + '<div class="rhdr">' + hdr + '</div>'
      + '<div style="height:' + R1H + 'px;position:relative;">'
      + '<div style="position:absolute;top:' + r2t1 + 'px;left:0;right:0;">' + card(s[i], 'R2 \u00b7 ' + i) + '</div>'
      + '<div style="position:absolute;top:' + r2t2 + 'px;left:0;right:0;">' + card(s[j], 'R2 \u00b7 ' + j) + '</div>'
      + '</div></div>';
  }

  function cfCol(m, hdr) {
    return '<div class="rcol">'
      + '<div class="rhdr">' + hdr + '</div>'
      + '<div style="height:' + R1H + 'px;position:relative;">'
      + '<div style="position:absolute;top:' + cfT + 'px;left:0;right:0;">' + card(s[m], hdr + ' \u00b7 ' + m) + '</div>'
      + '</div></div>';
  }

  const cupLogo = (s['O'] && s['O'].seriesLogo) || '';
  const scfHtml = '<div class="scf-col">'
    + (cupLogo ? '<img id="cup-logo" src="' + cupLogo + '" alt="Stanley Cup Final">' : '')
    + '<div style="padding-top:22px;">' + card(s['O'], 'Stanley Cup Final', 'scf') + '</div>'
    + '</div>';

  document.getElementById('bracket').innerHTML =
    '<div class="bracket">'
    + '<div class="conf west">'
    + r1Col('E','F','G','H','Round 1') + gp(12)
    + r2Col('K','L','Round 2')         + gp(12)
    + cfCol('N','Conf. Finals')        + gp(18)
    + '</div>'
    + scfHtml
    + '<div class="conf east">'
    + r1Col('A','B','C','D','Round 1') + gp(12)
    + r2Col('I','J','Round 2')         + gp(12)
    + cfCol('M','Conf. Finals')        + gp(18)
    + '</div>'
    + '</div>';
  scaleToFit();
}

function scaleToFit() {
  const b = document.querySelector('.bracket');
  if (!b) return;
  b.style.transform = '';
  const container = document.getElementById('bracket');
  const scale = Math.min(
    container.clientWidth  / b.scrollWidth,
    container.clientHeight / b.scrollHeight
  );
  b.style.transform = 'scale(' + scale + ')';
}

window.addEventListener('resize', scaleToFit);
connect();
</script>
</body>
</html>"""


app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/ws", websocket_handler)
app.on_startup.append(start_poller)
app.on_cleanup.append(stop_poller)

if __name__ == "__main__":
    port = int(os.environ.get("BRACKET_PORT", 8090))
    web.run_app(app, host="0.0.0.0", port=port)
