"""Scoring rules for the three-player Prefa house rules.

This module is the "truth" for scoring. The Flask app and CLI should only
collect input and display results; the actual scoring decisions should live
here.

Vocabulary used in this file:

- ``kasa`` is the long-term pouch/score each player is trying to reduce to 0.
- ``chips`` are side payments between players during a hand.
- ``declarer`` is the player who won the bidding and plays the contract.
- ``defenders`` are the two non-declarers.
- ``contract value`` is the scoring value of the bid. It is used for both kasa
  movement and chip payments.
- ``licking`` starts after a declarer's own kasa reaches 0. Successful contract
  value then comes out of opponents' kasas, starting with the largest kasa.
- ``Ta grafo`` makes that player the only possible declarer. They either play
  a normal contract or decline the hand and add 2 kasa.

High-level scoring flow:

1. ``score_hand`` records a played contract:
   - normalize the hand so each defender has the correct obligation
   - apply declarer kasa movement
   - exact contract: reduce kasa / lick
   - overmade contract: no kasa movement
   - short contract: add kasa penalty
   - apply chip settlements for defenders
   - defenders who are short pay the declarer
   - defenders who meet their obligation get paid for tricks
   - store a history snapshot so undo can work
2. ``record_ta_grafo_decline`` records the +2 kasa outcome when that player
   elects not to play.

This file is intentionally plain Python. If a scoring rule needs to change,
start here before looking at any user interface code.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Iterable
from uuid import uuid4


SUITS = {
    "spades": {"label": "Spades", "order": 0},
    "clubs": {"label": "Clubs", "order": 1},
    "diamonds": {"label": "Diamonds", "order": 2},
    "hearts": {"label": "Hearts", "order": 3},
    "no_trump": {"label": "No Trump", "order": 4},
}
"""Suit names and suit ordering.

The order matters only for 6-level suit contracts:

- 6 Spades = 2
- 6 Clubs = 3
- 6 Diamonds = 4
- 6 Hearts = 5
- 6 No Trump = 6

For 7, 8, and 9 contracts, suit contracts all share the same value, while
No Trump is one value higher.
"""

DEFENDER_OBLIGATIONS = {
    6: [2, 2],
    7: [2, 1],
    8: [1, 1],
    9: [1, 0],
}
"""Default defender trick obligations by contract level.

The first number belongs to the first defender in table/player order after
removing the declarer; the second number belongs to the other defender.

If only one defender stays active, this table is overridden:

- against 6 or 7: the lone active defender owes 2 tricks
- against 8 or 9: the lone active defender owes 1 trick
"""


@dataclass
class Player:
    """A player's current score.

    ``id`` is used internally because names can be edited. For example, if two
    people are both named Nick, their ids still keep the scoring unambiguous.
    """

    name: str
    kasa: int = 20
    chips: int = 0
    id: str = field(default_factory=lambda: str(uuid4()))


@dataclass
class DefenderInput:
    """Raw defender information entered for a hand.

    ``active`` means the defender accepted responsibility for defending.

    ``tricks`` is the number of tricks credited to this defender for scoring.
    """

    player_id: str
    active: bool = True
    tricks: int = 0


@dataclass
class DefenderScore:
    """Defender information after obligations have been calculated."""

    player_id: str
    active: bool
    tricks: int
    obligation: int


@dataclass
class HandInput:
    """All information needed to score one played contract."""

    declarer_id: str
    level: int
    suit: str
    declarer_tricks: int
    defenders: list[DefenderInput]


@dataclass
class HistoryEntry:
    """A played contract plus the game snapshot after that hand.

    The ``players`` snapshot is what makes undo simple: to undo the latest
    hand, the app restores the snapshot from the previous history entry.
    """

    id: str
    timestamp: str
    contract: str
    value: int
    result: str
    declarer_id: str
    declarer_name: str
    declarer_tricks: int
    defenders: list[DefenderScore]
    notes: list[str]
    players: list[Player]


@dataclass
class GameState:
    """The complete current game state."""

    players: list[Player]
    history: list[HistoryEntry] = field(default_factory=list)
    starting_kasa: int = 20


def create_game(names: Iterable[str] | None = None, starting_kasa: int = 20) -> GameState:
    """Create a fresh game with three players."""
    if names is None:
        names = ["Player 1", "Player 2", "Player 3"]

    return GameState(
        players=[Player(name=str(name), kasa=starting_kasa) for name in names],
        starting_kasa=starting_kasa,
    )


def contract_value(level: int, suit: str) -> int:
    """Return the kasa/chip value for a contract."""
    level = int(level)
    if level == 6:
        if suit == "no_trump":
            return 6
        return SUITS[suit]["order"] + 2
    if level == 7:
        return 8 if suit == "no_trump" else 7
    if level == 8:
        return 9 if suit == "no_trump" else 8
    if level == 9:
        return 10 if suit == "no_trump" else 9
    raise ValueError(f"Unsupported contract level: {level}")


def contract_label(level: int, suit: str) -> str:
    """Return a human-readable contract name, such as ``6 Spades``."""
    return f"{level} {SUITS[suit]['label']}"


def player_by_id(players: list[Player], player_id: str) -> Player:
    """Find a player by id or raise a helpful error."""
    for player in players:
        if player.id == player_id:
            return player
    raise ValueError(f"Unknown player id: {player_id}")


def settle(players: list[Player], from_id: str, to_id: str, amount: int) -> None:
    """Move chip value from one player to another.

    Kasa is not affected here. This is only for side payments:

    - declarer paying defenders for tricks
    - short defenders paying the declarer
    - excess licking value that has become chips
    """
    if amount == 0:
        return
    player_by_id(players, from_id).chips -= amount
    player_by_id(players, to_id).chips += amount


def largest_kasa_opponent(players: list[Player], declarer_id: str) -> Player | None:
    """Return the opponent who should be licked next.

    The house rule says to lick from the player with the largest kasa first.
    If both opponents are tied, this code chooses alphabetically by name so the
    result is deterministic.
    """
    opponents = [
        player for player in players
        if player.id != declarer_id and player.kasa > 0
    ]
    if not opponents:
        return None
    return sorted(opponents, key=lambda player: (-player.kasa, player.name))[0]


def apply_successful_kasa_change(players: list[Player], declarer_id: str, value: int) -> list[str]:
    """Reduce declarer's kasa first, then lick opponents' kasas.

    Example:
    - Declarer has kasa 3 and makes a value-5 contract.
    - First, declarer reduces own kasa by 3, reaching 0.
    - The remaining 2 is licked from the opponent with the largest kasa.
    """
    declarer = player_by_id(players, declarer_id)
    remaining = value
    notes: list[str] = []

    if declarer.kasa > 0:
        own_reduction = min(declarer.kasa, remaining)
        declarer.kasa -= own_reduction
        remaining -= own_reduction
        notes.append(f"{declarer.name} reduced kasa by {own_reduction}")

    while remaining > 0:
        target = largest_kasa_opponent(players, declarer_id)
        if target is None:
            declarer.chips += remaining
            notes.append(f"{declarer.name} received {remaining} chips as excess licking value")
            break

        lick = min(target.kasa, remaining)
        target.kasa -= lick
        remaining -= lick
        notes.append(f"{declarer.name} licked {lick} from {target.name}")

    return notes


def normalize_hand(hand: HandInput, state: GameState) -> HandInput:
    """Fill in defender obligations based on player order and participation.

    The user interface supplies raw defender input. This function makes it
    consistent with the rules:

    - defenders are ordered according to the game state's player order
    - each defender gets the default obligation for the contract level
    - if only one defender is active, the special lone-defender obligation is
      applied and the inactive defender owes 0

    It returns a new ``HandInput`` so later code can safely use normalized
    values without mutating the object passed in by the UI.
    """
    defenders_by_id = {defender.player_id: defender for defender in hand.defenders}
    defender_scores: list[DefenderScore] = []

    defender_index = 0
    for player in state.players:
        if player.id == hand.declarer_id:
            continue

        input_defender = defenders_by_id.get(player.id, DefenderInput(player.id))
        defender_scores.append(
            DefenderScore(
                player_id=player.id,
                active=input_defender.active,
                tricks=int(input_defender.tricks) if input_defender.active else 0,
                obligation=DEFENDER_OBLIGATIONS[int(hand.level)][defender_index],
            )
        )
        defender_index += 1

    active_defenders = [defender for defender in defender_scores if defender.active]
    if len(active_defenders) == 1:
        # Lone defender rule:
        # 6/7 contracts require 2 tricks; 8/9 contracts require 1 trick.
        active_defenders[0].obligation = 2 if int(hand.level) < 8 else 1
        for defender in defender_scores:
            if not defender.active:
                defender.obligation = 0

    return HandInput(
        declarer_id=hand.declarer_id,
        level=int(hand.level),
        suit=hand.suit,
        declarer_tricks=int(hand.declarer_tricks),
        defenders=[
            DefenderInput(
                player_id=defender.player_id,
                active=defender.active,
                tricks=defender.tricks,
            )
            for defender in defender_scores
        ],
    )


def defender_scores_for_hand(hand: HandInput, state: GameState) -> list[DefenderScore]:
    """Return defenders with obligations included.

    This is used by both the UI preview and ``score_hand``. It intentionally
    does not change kasa or chips; it only answers the question: "Who owed how
    many tricks for this hand?"
    """
    normalized = normalize_hand(hand, state)
    scores: list[DefenderScore] = []
    defender_index = 0

    for player in state.players:
        if player.id == normalized.declarer_id:
            continue
        defender = normalized.defenders[defender_index]
        scores.append(
            DefenderScore(
                player_id=defender.player_id,
                active=defender.active,
                tricks=defender.tricks,
                obligation=DEFENDER_OBLIGATIONS[normalized.level][defender_index],
            )
        )
        defender_index += 1

    active_defenders = [defender for defender in scores if defender.active]
    if len(active_defenders) == 1:
        active_defenders[0].obligation = 2 if normalized.level < 8 else 1
        for defender in scores:
            if not defender.active:
                defender.obligation = 0

    return scores


def score_hand(state: GameState, hand: HandInput) -> tuple[GameState, HistoryEntry]:
    """Score one played contract and return the updated state plus history.

    This function does not mutate the incoming ``state``. It deep-copies the
    game first, applies scoring to the copy, and returns the updated copy.

    Result categories:

    - ``made``: declarer took exactly the contracted number of tricks
    - ``overmade``: declarer took more than the contract
    - ``short``: declarer took fewer than the contract

    Current house-rule assumptions:

    - A defender short by 1 pays ``contract value`` chips to the declarer.
    - A defender short by 2 or more pays double the total shortage:
      ``contract value * shortage * 2``.
    - If declarer is short by 2 or more, defender trick payments are doubled.
    - Overmade hands do not reduce kasa or lick, but defender chip settlements
      still occur.
    """
    next_state = deepcopy(state)
    normalized = normalize_hand(hand, next_state)
    defender_scores = defender_scores_for_hand(normalized, next_state)
    declarer = player_by_id(next_state.players, normalized.declarer_id)
    value = contract_value(normalized.level, normalized.suit)

    if normalized.declarer_tricks < normalized.level:
        result = "short"
    elif normalized.declarer_tricks > normalized.level:
        result = "overmade"
    else:
        result = "made"

    notes: list[str] = []

    if result == "made":
        # Exact contracts are the only successful hands that reduce kasa.
        notes.extend(
            apply_successful_kasa_change(
                next_state.players,
                normalized.declarer_id,
                value,
            )
        )

    if result == "short":
        # Declarer short by 1 adds CV to kasa; short by 2+ adds double CV.
        deficit = normalized.level - normalized.declarer_tricks
        kasa_penalty = value * 2 if deficit >= 2 else value
        declarer.kasa += kasa_penalty
        notes.append(f"{declarer.name} was short by {deficit} and added {kasa_penalty} kasa")

    declarer_short_multiplier = 1
    if result == "short" and normalized.level - normalized.declarer_tricks >= 2:
        declarer_short_multiplier = 2

    for defender in defender_scores:
        if not defender.active:
            continue

        defender_player = player_by_id(next_state.players, defender.player_id)
        deficit = max(0, defender.obligation - defender.tricks)

        if deficit > 0:
            # A defender who misses obligation pays the declarer.
            # Missing by 2+ doubles the whole shortage penalty.
            penalty = value * deficit
            if deficit >= 2:
                penalty *= 2
            settle(next_state.players, defender.player_id, normalized.declarer_id, penalty)
            notes.append(f"{defender_player.name} was short by {deficit} and paid {penalty} chips")
            continue

        # Normal defender payment for tricks taken. If declarer was short by
        # 2+, the payment is doubled. Overmade hands still settle chips.
        payment = value * defender.tricks * declarer_short_multiplier
        settle(next_state.players, normalized.declarer_id, defender.player_id, payment)
        notes.append(
            f"{defender_player.name} received {payment} chips "
            f"for {defender.tricks} tricks"
        )

    entry = HistoryEntry(
        id=str(uuid4()),
        timestamp=datetime.now().isoformat(timespec="seconds"),
        contract=contract_label(normalized.level, normalized.suit),
        value=value,
        result=result,
        declarer_id=normalized.declarer_id,
        declarer_name=declarer.name,
        declarer_tricks=normalized.declarer_tricks,
        defenders=defender_scores,
        notes=notes,
        players=deepcopy(next_state.players),
    )

    next_state.history.insert(0, entry)
    return next_state, entry


def record_ta_grafo_decline(
    state: GameState,
    player_id: str,
) -> tuple[GameState, HistoryEntry]:
    """Record a Ta grafo player declining to play the contract.

    Declining ends the bidding round without a played contract and adds 2 to
    that player's kasa. It remains a full history event so persistence and
    undo behave exactly as they do for played hands.
    """
    next_state = deepcopy(state)
    player = player_by_id(next_state.players, player_id)
    player.kasa += 2
    notes = [f"{player.name} declined Ta grafo and added 2 kasa"]

    entry = HistoryEntry(
        id=str(uuid4()),
        timestamp=datetime.now().isoformat(timespec="seconds"),
        contract="Ta Grafo",
        value=2,
        result="declined",
        declarer_id=player.id,
        declarer_name=player.name,
        declarer_tricks=0,
        defenders=[],
        notes=notes,
        players=deepcopy(next_state.players),
    )
    next_state.history.insert(0, entry)
    return next_state, entry


def game_state_to_dict(state: GameState) -> dict:
    """Convert a complete game, including undo snapshots, to plain data."""
    return asdict(state)


def game_state_from_dict(data: dict) -> GameState:
    """Restore a game produced by ``game_state_to_dict``.

    Invalid or incomplete data raises ``ValueError`` so callers can safely
    fall back to a fresh game.
    """
    try:
        players = [Player(**player) for player in data["players"]]
        history = []
        for raw_entry in data.get("history", []):
            history.append(
                HistoryEntry(
                    id=raw_entry["id"],
                    timestamp=raw_entry["timestamp"],
                    contract=raw_entry["contract"],
                    value=int(raw_entry["value"]),
                    result=raw_entry["result"],
                    declarer_id=raw_entry["declarer_id"],
                    declarer_name=raw_entry["declarer_name"],
                    declarer_tricks=int(raw_entry["declarer_tricks"]),
                    defenders=[
                        DefenderScore(**defender)
                        for defender in raw_entry.get("defenders", [])
                    ],
                    notes=list(raw_entry.get("notes", [])),
                    players=[Player(**player) for player in raw_entry["players"]],
                )
            )
        state = GameState(
            players=players,
            history=history,
            starting_kasa=int(data.get("starting_kasa", 20)),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Invalid saved game data") from error

    if len(state.players) != 3:
        raise ValueError("A saved game must contain exactly three players")
    return state
