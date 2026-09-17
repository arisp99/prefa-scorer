"""Flask server for the Prefa scorer."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from threading import Lock

from flask import Flask, jsonify, render_template, request

from prefa_rules import (
    SUITS,
    DefenderInput,
    GameState,
    HandInput,
    create_game,
    game_state_from_dict,
    game_state_to_dict,
    record_ta_grafo_decline,
    score_hand,
)


app = Flask(__name__)
app.config["STATE_FILE"] = Path(
    os.environ.get("PREFA_STATE_FILE", Path(__file__).with_name("prefa_game.json"))
)
state_lock = Lock()


def public_game_dict(state: GameState) -> dict:
    """Return the browser-facing representation of a game."""
    return {
        "players": [
            {"id": player.id, "name": player.name, "kasa": player.kasa, "chips": player.chips}
            for player in state.players
        ],
        "history": [
            {
                "id": entry.id,
                "timestamp": entry.timestamp,
                "declarer_name": entry.declarer_name,
                "contract": entry.contract,
                "value": entry.value,
                "result": entry.result,
                "declarer_tricks": entry.declarer_tricks,
                "notes": entry.notes,
            }
            for entry in state.history
        ],
        "starting_kasa": state.starting_kasa,
    }


def load_game(path: Path | None = None) -> GameState:
    """Load persisted state, falling back safely to a fresh game."""
    state_file = path or app.config["STATE_FILE"]
    try:
        with state_file.open(encoding="utf-8") as saved:
            return game_state_from_dict(json.load(saved))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return create_game()


def save_game(state: GameState, path: Path | None = None) -> None:
    """Atomically persist the full game, including undo snapshots."""
    state_file = path or app.config["STATE_FILE"]
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_file.with_suffix(f"{state_file.suffix}.tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(game_state_to_dict(state), output, indent=2)
        output.write("\n")
    temporary.replace(state_file)


game_state = load_game()


def error_response(message: str, status: int = 400):
    return jsonify({"success": False, "error": message}), status


def require_json_object() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object")
    return data


def require_int(data: dict, key: str, minimum: int, maximum: int) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be a whole number")
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


def parse_hand(data: dict, state: GameState) -> tuple[HandInput, list[str]]:
    """Validate API input and return a hand plus non-blocking warnings."""
    player_ids = {player.id for player in state.players}
    declarer_id = data.get("declarer_id")
    if declarer_id not in player_ids:
        raise ValueError("declarer_id must identify a current player")

    level = require_int(data, "level", 6, 9)
    suit = data.get("suit")
    if suit not in SUITS:
        raise ValueError("suit is not valid")
    declarer_tricks = require_int(data, "declarer_tricks", 0, 10)

    raw_defenders = data.get("defenders")
    if not isinstance(raw_defenders, list) or len(raw_defenders) != 2:
        raise ValueError("Exactly two defenders are required")

    expected_defenders = player_ids - {declarer_id}
    seen_ids = set()
    defenders = []
    for raw_defender in raw_defenders:
        if not isinstance(raw_defender, dict):
            raise ValueError("Each defender must be an object")
        player_id = raw_defender.get("player_id")
        if player_id not in expected_defenders or player_id in seen_ids:
            raise ValueError("Defenders must be the two unique non-declarers")
        seen_ids.add(player_id)

        active = raw_defender.get("active", True)
        if not isinstance(active, bool):
            raise ValueError("Defender active values must be true or false")
        tricks = raw_defender.get("tricks", 0)
        if isinstance(tricks, bool) or not isinstance(tricks, int) or not 0 <= tricks <= 10:
            raise ValueError("Defender tricks must be a whole number from 0 to 10")
        if not active:
            tricks = 0
        defenders.append(DefenderInput(player_id=player_id, active=active, tricks=tricks))

    if seen_ids != expected_defenders:
        raise ValueError("Defenders must be the two unique non-declarers")

    trick_total = declarer_tricks + sum(defender.tricks for defender in defenders)
    warnings = []
    if trick_total != 10:
        warnings.append(f"Entered tricks total {trick_total}, not 10.")

    hand = HandInput(
        declarer_id=declarer_id,
        level=level,
        suit=suit,
        declarer_tricks=declarer_tricks,
        defenders=defenders,
    )
    return hand, warnings


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/game")
def get_game():
    with state_lock:
        return jsonify(public_game_dict(game_state))


@app.post("/api/new-game")
def new_game():
    global game_state
    try:
        data = require_json_object()
        names = []
        name_fields = (("player1", "Player 1"), ("player2", "Player 2"), ("player3", "Player 3"))
        for key, fallback in name_fields:
            value = data.get(key, fallback)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Every player needs a name")
            if len(value.strip()) > 60:
                raise ValueError("Player names must be 60 characters or fewer")
            names.append(value.strip())
        starting_kasa = require_int(data, "starting_kasa", 1, 999)

        with state_lock:
            next_state = create_game(names, starting_kasa)
            save_game(next_state)
            game_state = next_state
            return jsonify({"success": True, "game": public_game_dict(game_state)})
    except ValueError as error:
        return error_response(str(error))
    except OSError:
        return error_response("The game could not be saved", 500)


@app.post("/api/score-hand")
def score_hand_endpoint():
    global game_state
    try:
        data = require_json_object()
        with state_lock:
            hand, warnings = parse_hand(data, game_state)
            next_state, entry = score_hand(game_state, hand)
            save_game(next_state)
            game_state = next_state
            return jsonify(
                {
                    "success": True,
                    "warnings": warnings,
                    "game": public_game_dict(game_state),
                    "entry": {
                        "declarer_name": entry.declarer_name,
                        "contract": entry.contract,
                        "result": entry.result,
                        "notes": entry.notes,
                    },
                }
            )
    except ValueError as error:
        return error_response(str(error))
    except OSError:
        return error_response("The game could not be saved", 500)


@app.post("/api/ta-grafo/decline")
def ta_grafo_decline_endpoint():
    """Record the forced declarer declining a Ta grafo hand."""
    global game_state
    try:
        data = require_json_object()
        player_id = data.get("player_id")
        with state_lock:
            if player_id not in {player.id for player in game_state.players}:
                raise ValueError("player_id must identify a current player")
            next_state, entry = record_ta_grafo_decline(game_state, player_id)
            save_game(next_state)
            game_state = next_state
            return jsonify(
                {
                    "success": True,
                    "game": public_game_dict(game_state),
                    "entry": {
                        "declarer_name": entry.declarer_name,
                        "contract": entry.contract,
                        "result": entry.result,
                        "notes": entry.notes,
                    },
                }
            )
    except ValueError as error:
        return error_response(str(error))
    except OSError:
        return error_response("The game could not be saved", 500)


@app.post("/api/undo")
def undo_endpoint():
    global game_state
    with state_lock:
        if not game_state.history:
            return error_response("No hands to undo")
        try:
            if len(game_state.history) == 1:
                names = [player.name for player in game_state.players]
                next_state = create_game(names, game_state.starting_kasa)
            else:
                next_state = deepcopy(game_state)
                previous_entry = next_state.history[1]
                next_state.players = previous_entry.players
                next_state.history.pop(0)
            save_game(next_state)
            game_state = next_state
            return jsonify({"success": True, "game": public_game_dict(game_state)})
        except OSError:
            return error_response("The game could not be saved", 500)


if __name__ == "__main__":
    app.run(port=8000)
