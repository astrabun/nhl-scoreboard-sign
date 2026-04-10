import asyncio
import json
import os
import queue
import sys
import threading
from dotenv import load_dotenv
from flask import Flask, Response, stream_with_context

load_dotenv()

NHL_TEAM = os.environ.get("NHL_TEAM")
if not NHL_TEAM:
    print("Error: NHL_TEAM environment variable must be set.", file=sys.stderr)
    sys.exit(1)

NHL_WS_FEED = os.environ.get("NHL_WS_FEED", "ws://localhost:8080")

app = Flask(__name__)

# Latest message received from websocket; None = not yet connected
_latest: dict | None = None
_latest_lock = threading.Lock()

# One queue per connected SSE client
_clients: list[queue.Queue] = []
_clients_lock = threading.Lock()


def _broadcast(payload: dict):
    global _latest
    with _latest_lock:
        _latest = payload
    data = json.dumps(payload)
    with _clients_lock:
        dead = []
        for q in _clients:
            try:
                q.put_nowait(data)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _clients.remove(q)


async def _ws_listener():
    import websockets

    while True:
        try:
            async with websockets.connect(NHL_WS_FEED) as ws:
                await ws.send(json.dumps({"type": "subscribe", "team": NHL_TEAM}))
                async for raw in ws:
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    _broadcast(payload)
        except Exception:
            await asyncio.sleep(5)


def _start_ws_thread():
    def run():
        asyncio.run(_ws_listener())

    t = threading.Thread(target=run, daemon=True)
    t.start()


PERIOD_LABELS = {1: "1st", 2: "2nd", 3: "3rd"}


def _format_period(descriptor):
    ptype = descriptor.get("periodType", "REG")
    num = descriptor.get("number", 1)
    if ptype == "OT":
        return "OT"
    if ptype == "SO":
        return "SO"
    return PERIOD_LABELS.get(num, f"P{num}")


def _time_to_seconds(t):
    try:
        m, s = t.split(":")
        return int(m) * 60 + int(s)
    except Exception:
        return 0


def _get_last_event(summary):
    events = []
    for period_block in summary.get("scoring", []):
        period_num = period_block["periodDescriptor"]["number"]
        for goal in period_block.get("goals", []):
            t = goal.get("timeInPeriod", "0:00")
            name = goal.get("name", {}).get("default", "Unknown")
            team = goal.get("teamAbbrev", {}).get("default", "")
            strength = goal.get("strength", "ev").upper()
            label = f"GOAL: {name} ({team}) &mdash; P{period_num} {t} [{strength}]"
            events.append((period_num, _time_to_seconds(t), label))

    for period_block in summary.get("penalties", []):
        period_num = period_block["periodDescriptor"]["number"]
        for pen in period_block.get("penalties", []):
            t = pen.get("timeInPeriod", "0:00")
            player = pen.get("committedByPlayer", {})
            first = player.get("firstName", {}).get("default", "")
            last = player.get("lastName", {}).get("default", "Unknown")
            team = pen.get("teamAbbrev", {}).get("default", "")
            desc = pen.get("descKey", "penalty").replace("-", " ")
            dur = pen.get("duration", 2)
            label = f"PENALTY: {first[0]+'. ' if first else ''}{last} ({team}) &mdash; P{period_num} {t} {desc} ({dur} min)"
            events.append((period_num, _time_to_seconds(t), label))

    if not events:
        return "No events yet"
    events.sort(key=lambda e: (e[0], e[1]), reverse=True)
    return events[0][2]


def _count_penalties(summary, team_abbrev):
    count = 0
    for period_block in summary.get("penalties", []):
        for pen in period_block.get("penalties", []):
            if pen.get("teamAbbrev", {}).get("default", "") == team_abbrev:
                count += 1
    return count


def _build_view(payload: dict) -> dict:
    """Distil a raw payload into only what the template needs."""
    msg_type = payload.get("type")
    if msg_type == "error":
        return {"type": "error"}

    data = payload.get("data", {})
    away = data.get("awayTeam", {})
    home = data.get("homeTeam", {})
    away_abbrev = away.get("abbrev", "AWAY")
    home_abbrev = home.get("abbrev", "HOME")

    game_state = data.get("gameState", "")
    period_desc = data.get("periodDescriptor", {})
    period_label = _format_period(period_desc)
    clock = data.get("clock", {})

    in_intermission = clock.get("inIntermission", False)
    clock_running = clock.get("running", False)

    if game_state == "FINAL":
        clock_text = f"{period_label} &bull; FINAL"
        indicator_text, indicator_color = "", ""
    elif game_state in ("PRE", "PREGAME", "PREVIEW"):
        clock_text = "Pre-Game"
        indicator_text, indicator_color = "", ""
    elif in_intermission:
        clock_text = f"End of {period_label} &bull; Intermission"
        indicator_text, indicator_color = "⏱ Intermission", "#5599ff"
    elif clock_running:
        clock_text = (
            f"{period_label} &bull; {clock.get('timeRemaining', '20:00')} remaining"
        )
        indicator_text, indicator_color = "▶ In Play", "#44cc44"
    else:
        clock_text = (
            f"{period_label} &bull; {clock.get('timeRemaining', '20:00')} remaining"
        )
        indicator_text, indicator_color = "⏸ Stopped", "#ffaa00"

    summary = data.get("summary", {})
    header_state = ""
    if game_state == "FINAL":
        header_state = "FINAL"
    elif game_state in ("LIVE", "CRIT"):
        header_state = "LIVE"

    return {
        "type": "update",
        "away_abbrev": away_abbrev,
        "home_abbrev": home_abbrev,
        "away_name": away.get("commonName", {}).get("default", away_abbrev),
        "home_name": home.get("commonName", {}).get("default", home_abbrev),
        "away_score": away.get("score", 0),
        "home_score": home.get("score", 0),
        "away_sog": away.get("sog", 0),
        "home_sog": home.get("sog", 0),
        "away_pen": _count_penalties(summary, away_abbrev),
        "home_pen": _count_penalties(summary, home_abbrev),
        "clock": clock_text,
        "clock_running": clock_running,
        "seconds_remaining": clock.get("secondsRemaining", 0),
        "period_prefix": period_label,
        "indicator_text": indicator_text,
        "indicator_color": indicator_color,
        "header": f"{away_abbrev} @ {home_abbrev}"
        + (f" &bull; {header_state}" if header_state else ""),
        "last_event": _get_last_event(summary),
    }


HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NHL Scoreboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0a0a0a;
    color: #fff;
    font-family: Helvetica, Arial, sans-serif;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
  }
  #board {
    width: 100%;
    max-width: 700px;
    padding: 24px 16px;
  }
  .hidden { display: none !important; }

  /* status (connecting / no game) */
  #status {
    text-align: center;
    font-size: 1.5rem;
    font-weight: bold;
    color: #888;
    padding: 60px 0;
  }
  #status.error { color: #ff4444; }

  /* scoreboard */
  #scoreboard { display: none; }

  #header {
    text-align: center;
    font-size: 1.2rem;
    font-weight: bold;
    color: #FFD700;
    margin-bottom: 12px;
    letter-spacing: 0.04em;
  }

  .score-row {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    margin-bottom: 10px;
  }
  .team-name {
    font-size: 1.5rem;
    font-weight: bold;
    width: 200px;
    overflow-wrap: break-word;
  }
  .team-name.away { text-align: right; }
  .team-name.home { text-align: left; }
  .score {
    font-size: 4rem;
    font-weight: bold;
    color: #FFD700;
    width: 72px;
    text-align: center;
    line-height: 1;
  }
  .dash {
    font-size: 2.5rem;
    color: #888;
    user-select: none;
  }

  #clock-row {
    text-align: center;
    font-size: 1.2rem;
    color: #ddd;
    margin-bottom: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
  }
  #play-indicator {
    font-size: 0.95rem;
    font-weight: bold;
  }

  hr { border: none; border-top: 1px solid #333; margin: 10px 0; }

  .stats-row {
    display: flex;
    justify-content: space-between;
    padding: 6px 16px;
    font-size: 1rem;
    color: #ccc;
  }
  .stat-block { display: flex; flex-direction: column; gap: 4px; }
  .stat-block.away { text-align: left; }
  .stat-block.home { text-align: right; }

  #last-event {
    text-align: center;
    font-size: 0.9rem;
    color: #888;
    margin-top: 14px;
    line-height: 1.4;
    word-break: break-word;
  }
</style>
</head>
<body>
<div id="board">
  <div id="status">Connecting&hellip;</div>

  <div id="scoreboard">
    <div id="header"></div>

    <div class="score-row">
      <div class="team-name away" id="away-name"></div>
      <div class="score" id="away-score"></div>
      <div class="dash">&ndash;</div>
      <div class="score" id="home-score"></div>
      <div class="team-name home" id="home-name"></div>
    </div>

    <div id="clock-row">
      <span id="clock"></span>
      <span id="play-indicator"></span>
    </div>
    <hr>

    <div class="stats-row">
      <div class="stat-block away">
        <span>SOG: <strong id="away-sog"></strong></span>
        <span>PEN: <strong id="away-pen"></strong></span>
      </div>
      <div class="stat-block home">
        <span>SOG: <strong id="home-sog"></strong></span>
        <span>PEN: <strong id="home-pen"></strong></span>
      </div>
    </div>

    <hr>
    <div id="last-event"></div>
  </div>
</div>

<script>
const status = document.getElementById('status');
const scoreboard = document.getElementById('scoreboard');

function show(view) {
  if (view === 'status') {
    scoreboard.style.display = 'none';
    status.style.display = '';
  } else {
    status.style.display = 'none';
    scoreboard.style.display = 'block';
  }
}

function set(id, html) {
  document.getElementById(id).innerHTML = html;
}

let countdownInterval = null;
let secondsRemaining = 0;
let periodPrefix = '';

function renderClock() {
  const m = Math.floor(secondsRemaining / 60);
  const s = secondsRemaining % 60;
  set('clock', `${periodPrefix} &bull; ${m}:${s.toString().padStart(2, '0')} remaining`);
}

const es = new EventSource('/events');

es.addEventListener('update', e => {
  const d = JSON.parse(e.data);
  set('header', d.header);
  set('away-name', d.away_name);
  set('home-name', d.home_name);
  set('away-score', d.away_score);
  set('home-score', d.home_score);
  set('away-sog', d.away_sog);
  set('home-sog', d.home_sog);
  set('away-pen', d.away_pen);
  set('home-pen', d.home_pen);
  set('last-event', 'Last: ' + d.last_event);
  const ind = document.getElementById('play-indicator');
  ind.textContent = d.indicator_text;
  ind.style.color = d.indicator_color;

  if (d.clock_running) {
    if (countdownInterval === null) {
      // Transition to running: seed from server and start ticking
      secondsRemaining = d.seconds_remaining;
      periodPrefix = d.period_prefix;
      renderClock();
      countdownInterval = setInterval(() => {
        secondsRemaining = Math.max(0, secondsRemaining - 1);
        renderClock();
      }, 1000);
    }
    // Already running: leave the interval alone
  } else {
    clearInterval(countdownInterval);
    countdownInterval = null;
    set('clock', d.clock);
  }

  show('scoreboard');
});

es.addEventListener('error_payload', e => {
  status.classList.add('error');
  set('status', 'No Game Available');
  show('status');
});

es.addEventListener('connecting', e => {
  status.classList.remove('error');
  set('status', JSON.parse(e.data).message);
  show('status');
});

es.onerror = () => {
  status.classList.remove('error');
  set('status', 'Reconnecting&hellip;');
  show('status');
};
</script>
</body>
</html>"""


@app.route("/")
def index():
    return HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/events")
def events():
    q: queue.Queue = queue.Queue(maxsize=20)
    with _clients_lock:
        _clients.append(q)

    # Send the latest cached payload immediately so the page isn't blank
    with _latest_lock:
        cached = _latest

    def generate():
        try:
            if cached is not None:
                view = _build_view(cached)
                event_name = "error_payload" if view["type"] == "error" else "update"
                yield f"event: {event_name}\ndata: {json.dumps(view)}\n\n"
            else:
                yield f"event: connecting\ndata: {json.dumps({'message': 'Connecting\u2026'})}\n\n"

            while True:
                try:
                    raw = q.get(timeout=25)
                except queue.Empty:
                    # heartbeat to keep the connection alive
                    yield ": heartbeat\n\n"
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                view = _build_view(payload)
                event_name = "error_payload" if view["type"] == "error" else "update"
                yield f"event: {event_name}\ndata: {json.dumps(view)}\n\n"
        finally:
            with _clients_lock:
                try:
                    _clients.remove(q)
                except ValueError:
                    pass

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    _start_ws_thread()
    app.run(host="0.0.0.0", port=5000, threaded=True)
