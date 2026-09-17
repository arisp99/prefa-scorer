"""Terminal app for scoring Prefa.

Run it with:

    python3 prefa_cli.py
"""

from __future__ import annotations

from prefa_rules import (
    SUITS,
    DefenderInput,
    HandInput,
    contract_label,
    contract_value,
    create_game,
    defender_scores_for_hand,
    record_ta_grafo_decline,
    score_hand,
)


def main() -> None:
    print("Prefa Scorer")
    state = create_game(ask_player_names())

    while True:
        print_scoreboard(state)
        print("1. Record hand")
        print("2. Undo last hand")
        print("3. Show history")
        print("4. Quit")

        choice = input("Choose: ").strip()
        if choice == "1":
            try:
                state, entry = record_next_event(state)
                print()
                print(f"Saved: {entry.declarer_name} {entry.contract} ({entry.result})")
                for note in entry.notes:
                    print(f"  - {note}")
            except Exception as error:
                print(f"Could not score hand: {error}")
        elif choice == "2":
            state = undo_last_hand(state)
        elif choice == "3":
            print_history(state)
        elif choice == "4":
            return
        else:
            print("Please choose a number from 1 to 4.")


def ask_player_names() -> list[str]:
    names = []
    for index in range(3):
        name = input(f"Player {index + 1} name: ").strip()
        names.append(name or f"Player {index + 1}")
    return names


def print_scoreboard(state) -> None:
    print()
    print("=" * 56)
    print("Scoreboard")
    for index, player in enumerate(state.players, start=1):
        chips = f"+{player.chips}" if player.chips > 0 else str(player.chips)
        print(f"{index}. {player.name:<16} kasa: {player.kasa:<3} chips: {chips}")
    print("=" * 56)


def record_next_event(state):
    if ask_yes_no("Was Ta grafo declared?", default=False):
        declarer = choose_player(state, "Ta grafo player")
        if not ask_yes_no(f"Will {declarer.name} play the contract?", default=True):
            if not ask_yes_no("Record the decline and add 2 kasa?", default=True):
                raise RuntimeError("Event cancelled")
            return record_ta_grafo_decline(state, declarer.id)
        return score_hand(state, ask_hand(state, declarer))
    return score_hand(state, ask_hand(state))


def ask_hand(state, declarer=None) -> HandInput:
    if declarer is None:
        declarer = choose_player(state, "Declarer")
    level = ask_choice("Level", ["6", "7", "8", "9"], default="6")
    suit = ask_choice(
        "Suit",
        ["spades", "clubs", "diamonds", "hearts", "no_trump"],
        default="spades",
    )
    declarer_tricks = ask_int("Declarer tricks", default=int(level), minimum=0, maximum=10)

    defenders = []
    for player in state.players:
        if player.id == declarer.id:
            continue

        active = ask_yes_no(f"Did {player.name} play as defender?", default=True)
        tricks = 0
        if active:
            tricks = ask_int(f"{player.name} tricks", default=0, minimum=0, maximum=10)
        defenders.append(
            DefenderInput(
                player_id=player.id,
                active=active,
                tricks=tricks,
            )
        )

    hand = HandInput(
        declarer_id=declarer.id,
        level=int(level),
        suit=suit,
        declarer_tricks=declarer_tricks,
        defenders=defenders,
    )

    print_preview(hand, state)
    trick_total = declarer_tricks + sum(defender.tricks for defender in defenders)
    if trick_total != 10:
        print(f"Warning: entered tricks total {trick_total}, not 10.")
    if not ask_yes_no("Save this hand?", default=True):
        raise RuntimeError("Hand cancelled")
    return hand

def print_preview(hand: HandInput, state) -> None:
    print()
    print("Preview")
    if hand.declarer_tricks < hand.level:
        result = "short"
    elif hand.declarer_tricks > hand.level:
        result = "overmade"
    else:
        result = "made"

    print(
        f"{contract_label(hand.level, hand.suit)} | "
        f"value {contract_value(hand.level, hand.suit)} | {result}"
    )
    for defender in defender_scores_for_hand(hand, state):
        name = next(player.name for player in state.players if player.id == defender.player_id)
        status = "active" if defender.active else "out"
        print(f"  - {name}: {status}, tricks {defender.tricks}, obligation {defender.obligation}")


def choose_player(state, label: str):
    while True:
        for index, player in enumerate(state.players, start=1):
            print(f"{index}. {player.name}")
        choice = ask_int(label, default=1, minimum=1, maximum=len(state.players))
        return state.players[choice - 1]


def ask_choice(label: str, choices: list[str], default: str) -> str:
    while True:
        prompt = f"{label} ({'/'.join(choices)}) [{default}]: "
        value = input(prompt).strip() or default
        if value in choices:
            return value
        print(f"Choose one of: {', '.join(choices)}")


def ask_int(label: str, default: int, minimum: int, maximum: int) -> int:
    while True:
        raw = input(f"{label} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("Enter a whole number.")
            continue
        if minimum <= value <= maximum:
            return value
        print(f"Enter a number from {minimum} to {maximum}.")


def ask_yes_no(label: str, default: bool) -> bool:
    default_text = "Y/n" if default else "y/N"
    while True:
        value = input(f"{label} [{default_text}]: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer y or n.")


def undo_last_hand(state):
    if not state.history:
        print("No hands to undo.")
        return state
    if len(state.history) == 1:
        names = [player.name for player in state.players]
        return create_game(names, state.starting_kasa)

    previous_entry = state.history[1]
    state.players = previous_entry.players
    state.history.pop(0)
    return state


def print_history(state) -> None:
    print()
    if not state.history:
        print("No hands recorded yet.")
        return
    for entry in state.history:
        print(
            f"{entry.declarer_name}: {entry.contract}, "
            f"{entry.result}, {entry.declarer_tricks} tricks"
        )
        for note in entry.notes:
            print(f"  - {note}")
        print()


if __name__ == "__main__":
    main()
