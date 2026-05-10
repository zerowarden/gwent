# gwent_service

`gwent_service` is the stateful HTTP layer around `gwent_engine`.

It owns:
- match creation
- hidden mulligan staging
- player-safe projections
- REST endpoints

It does not own gameplay rules. All rules execution still lives in `gwent_engine`.

## Run the Service

From the repository root:

```bash
uv sync
uv run --package gwent-service uvicorn gwent_service.main:app --reload
```

The app will start on `http://127.0.0.1:8000`.

To run with durable SQLite storage instead of the default in-memory repository:

```bash
GWENT_SERVICE_REPOSITORY=sqlite \
GWENT_SERVICE_SQLITE_PATH=./gwent_service.sqlite3 \
uv run --package gwent-service uvicorn gwent_service.main:app --reload
```

If `GWENT_SERVICE_REPOSITORY` is omitted, the service uses the in-memory repository.

## Try It Out

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Create a match:

```bash
curl -X POST http://127.0.0.1:8000/matches \
  -H "content-type: application/json" \
  -d '{
    "match_id": "demo-match",
    "viewer_player_id": "alice",
    "participants": [
      {
        "service_player_id": "alice",
        "engine_player_id": "p1",
        "deck_id": "monsters_sample_deck"
      },
      {
        "service_player_id": "bob",
        "engine_player_id": "p2",
        "deck_id": "nilfgaard_sample_deck"
      }
    ],
    "rng_seed": 7
  }'
```

Fetch the projected match view for one player:

```bash
curl "http://127.0.0.1:8000/matches/demo-match?viewer_player_id=alice"
```

Submit mulligans:

```bash
curl -X POST http://127.0.0.1:8000/matches/demo-match/mulligan \
  -H "content-type: application/json" \
  -d '{
    "service_player_id": "alice",
    "card_instance_ids": ["p1_card_1"]
  }'
```

```bash
curl -X POST http://127.0.0.1:8000/matches/demo-match/mulligan \
  -H "content-type: application/json" \
  -d '{
    "service_player_id": "bob",
    "card_instance_ids": []
  }'
```

After both mulligans are submitted, the service resolves the engine into `in_round`.

Play a card:

```bash
curl -X POST http://127.0.0.1:8000/matches/demo-match/actions/play-card \
  -H "content-type: application/json" \
  -d '{
    "service_player_id": "alice",
    "card_instance_id": "p1_card_1",
    "target_row": "close"
  }'
```

Pass a turn:

```bash
curl -X POST http://127.0.0.1:8000/matches/demo-match/actions/pass \
  -H "content-type: application/json" \
  -d '{
    "service_player_id": "bob"
  }'
```

Resolve a pending choice:

1. Fetch the match for the acting player.
2. Read `pending_choice.choice_id`.
3. Submit:

```bash
curl -X POST http://127.0.0.1:8000/matches/demo-match/actions/resolve-choice \
  -H "content-type: application/json" \
  -d '{
    "service_player_id": "alice",
    "choice_id": "choice_1",
    "selected_card_instance_ids": ["p1_card_1"],
    "selected_rows": []
  }'
```

## Current Endpoints

- `GET /health`
- `POST /matches`
- `GET /matches/{match_id}?viewer_player_id=...`
- `POST /matches/{match_id}/mulligan`
- `POST /matches/{match_id}/actions/play-card`
- `POST /matches/{match_id}/actions/pass`
- `POST /matches/{match_id}/actions/use-leader`
- `POST /matches/{match_id}/actions/resolve-choice`

## Notes

- Use `viewer_player_id` to choose which player-safe projection you receive.
- Opponent hand contents are intentionally hidden.
- Mulligan selections are staged privately in the service until both players submit.
- Pending choices are exposed only to the player who must resolve them.
- The engine CLI demo lives in the separate workspace package and can be run from the repo root with `uv run --package gwent-engine python -m gwent_engine.cli.main`.
