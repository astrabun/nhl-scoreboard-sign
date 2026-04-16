# NHL Scoreboard Sign

Two web apps for following NHL hockey:

- **Scoreboard** - live game scoreboard for a configured team
- **Playoff Bracket** - live-updating NHL playoff bracket for the current season

---

## Scoreboard

Simple web-based scoreboard for NHL games involving the team configured in the `NHL_TEAM` environment variable.

The app connects to an NHL websocket feed, subscribes to the configured team by its 3-letter abbreviation, and renders a live scoreboard in the browser. When a game is active, the page shows:

- Away and home teams
- Current score
- Shots on goal
- Penalty counts
- Period and clock status
- Most recent scoring or penalty event

## Playoff Bracket

Displays the full NHL playoff bracket fetched from the NHL API. Data refreshes every 5 minutes in the background and pushes updates to connected browsers via WebSocket - no page reload required.

---

## Configuration

Create or update `.env`:

```env
NHL_TEAM=PHI
```

`NHL_TEAM` must be a 3-letter NHL team code (required for the scoreboard).

Optional variables:

- `WEB_PORT` - scoreboard port, defaults to `5000`
- `NHL_PORT` - websocket service port, defaults to `8080`
- `NHL_WS_FEED` - websocket feed URL used by the scoreboard
- `BRACKET_PORT` - playoff bracket port, defaults to `8090`

## Run With Docker Compose

Start the stack:

```sh
docker compose up -d
```

| App | Default URL |
|---|---|
| Scoreboard | http://localhost:5000 |
| Playoff Bracket | http://localhost:8090 |

Use `WEB_PORT` or `BRACKET_PORT` to override the defaults.

## Run Locally

### Scoreboard

Install dependencies:

```sh
pip install -r requirements.txt
```

Start the websocket backend separately, or point `NHL_WS_FEED` at an existing feed. Then run:

```sh
cd src
python web.py
```

By default the app expects the websocket feed at `ws://localhost:8080`.

### Playoff Bracket

```sh
pip install aiohttp
cd src
python web_bracket.py
```

Open `http://localhost:8090`.

## Notes

- If no live or scheduled game is available for the configured team, the scoreboard shows `No Game Available`.
- The Docker Compose setup runs three services: the websocket feed, the scoreboard, and the playoff bracket.
