# NHL Scoreboard Sign

Simple web-based scoreboard for NHL games involving the team configured in the `NHL_TEAM` environment variable.

The app connects to an NHL websocket feed, subscribes to the configured team by its 3-letter abbreviation, and renders a live scoreboard in the browser. When a game is active, the page shows:

- Away and home teams
- Current score
- Shots on goal
- Penalty counts
- Period and clock status
- Most recent scoring or penalty event

## Configuration

Create or update `.env` with your team abbreviation:

```env
NHL_TEAM=PHI
```

`NHL_TEAM` must be a 3-letter NHL team code.

Optional variables:

- `WEB_PORT` - web app port, defaults to `5000`
- `NHL_PORT` - websocket service port, defaults to `8080`
- `NHL_WS_FEED` - websocket feed URL used by the web app

## Run With Docker Compose

Start the stack:

```sh
docker compose up -d
```

Open the scoreboard at:

```text
http://localhost:5000
```

If `WEB_PORT` is set, use that port instead.

## Run Locally

Install dependencies:

```sh
pip install -r requirements.txt
```

Start the websocket backend separately, or point `NHL_WS_FEED` at an existing feed. Then run the web app:

```sh
cd src
python web.py
```

By default the app expects the websocket feed at `ws://localhost:8080`.

## Notes

- If no live or scheduled game is available for the configured team, the page shows `No Game Available`.
- The Docker Compose setup runs two services: the websocket feed and the Flask web frontend.
