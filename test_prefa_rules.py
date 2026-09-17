import unittest

from prefa_rules import (
    DefenderInput,
    HandInput,
    apply_successful_kasa_change,
    contract_value,
    create_game,
    defender_scores_for_hand,
    game_state_from_dict,
    game_state_to_dict,
    record_ta_grafo_decline,
    score_hand,
)


class PrefaRulesTest(unittest.TestCase):
    def setUp(self):
        self.state = create_game(["A", "B", "C"])
        self.a, self.b, self.c = [player.id for player in self.state.players]

    def hand(
        self,
        *,
        level=6,
        suit="spades",
        declarer_tricks=6,
        b_active=True,
        b_tricks=2,
        c_active=True,
        c_tricks=2,
    ):
        return HandInput(
            declarer_id=self.a,
            level=level,
            suit=suit,
            declarer_tricks=declarer_tricks,
            defenders=[
                DefenderInput(self.b, b_active, b_tricks),
                DefenderInput(self.c, c_active, c_tricks),
            ],
        )

    def scores(self, state):
        return [(player.name, player.kasa, player.chips) for player in state.players]

    def test_contract_values(self):
        self.assertEqual(contract_value(6, "spades"), 2)
        self.assertEqual(contract_value(6, "hearts"), 5)
        self.assertEqual(contract_value(6, "no_trump"), 6)
        self.assertEqual(contract_value(7, "no_trump"), 8)
        self.assertEqual(contract_value(8, "no_trump"), 9)
        self.assertEqual(contract_value(9, "hearts"), 9)
        self.assertEqual(contract_value(9, "no_trump"), 10)

    def test_exact_contract_reduces_kasa_and_pays_defenders(self):
        state, _entry = score_hand(self.state, self.hand())
        self.assertEqual(self.scores(state), [
            ("A", 18, -8),
            ("B", 20, 4),
            ("C", 20, 4),
        ])

    def test_ta_grafo_decline_adds_two_kasa_and_history(self):
        state, entry = record_ta_grafo_decline(self.state, self.a)
        self.assertEqual([player.kasa for player in state.players], [22, 20, 20])
        self.assertEqual(entry.contract, "Ta Grafo")
        self.assertEqual(entry.result, "declined")
        self.assertEqual(entry.defenders, [])
        self.assertEqual(len(state.history), 1)

    def test_ta_grafo_player_who_plays_scores_as_normal_declarer(self):
        state, entry = score_hand(self.state, self.hand())
        self.assertEqual(entry.result, "made")
        self.assertEqual([player.kasa for player in state.players], [18, 20, 20])
        self.assertFalse(any("Ta grafo" in note for note in entry.notes))

    def test_overmade_contract_keeps_kasa_and_settles_all_chips(self):
        state, _entry = score_hand(
            self.state,
            self.hand(declarer_tricks=7, b_tricks=1, c_tricks=2),
        )
        self.assertEqual(self.scores(state), [
            ("A", 20, -2),
            ("B", 20, -2),
            ("C", 20, 4),
        ])

    def test_short_by_two_doubles_kasa_and_defender_payment(self):
        state, _entry = score_hand(
            self.state,
            self.hand(
                level=8,
                suit="hearts",
                declarer_tricks=6,
                b_tricks=1,
                c_active=False,
                c_tricks=9,
            ),
        )
        self.assertEqual(self.scores(state), [
            ("A", 36, -16),
            ("B", 20, 16),
            ("C", 20, 0),
        ])

    def test_defender_short_by_two_pays_doubled_total_shortage(self):
        state, _entry = score_hand(
            self.state,
            self.hand(b_tricks=0, c_tricks=2),
        )
        self.assertEqual(self.scores(state), [
            ("A", 18, 4),
            ("B", 20, -8),
            ("C", 20, 4),
        ])

    def test_one_active_defender_gets_lone_obligation(self):
        scores = defender_scores_for_hand(
            self.hand(level=7, b_active=True, b_tricks=2, c_active=False, c_tricks=8),
            self.state,
        )
        self.assertEqual([(score.active, score.tricks, score.obligation) for score in scores], [
            (True, 2, 2),
            (False, 0, 0),
        ])

    def test_both_defenders_out_still_records_declarer_result(self):
        state, entry = score_hand(
            self.state,
            self.hand(b_active=False, b_tricks=7, c_active=False, c_tricks=3),
        )
        self.assertEqual(entry.result, "made")
        self.assertEqual(self.scores(state), [
            ("A", 18, 0),
            ("B", 20, 0),
            ("C", 20, 0),
        ])

    def test_licking_uses_largest_opponent_kasa(self):
        self.state.players[0].kasa = 1
        self.state.players[1].kasa = 8
        self.state.players[2].kasa = 5
        state, _entry = score_hand(self.state, self.hand())
        self.assertEqual([player.kasa for player in state.players], [0, 7, 5])

    def test_excess_licking_becomes_declarer_chips(self):
        self.state.players[0].kasa = 0
        self.state.players[1].kasa = 0
        self.state.players[2].kasa = 0
        notes = apply_successful_kasa_change(self.state.players, self.a, 3)
        self.assertEqual(self.state.players[0].chips, 3)
        self.assertIn("excess licking", notes[0])

    def test_serialization_round_trip_preserves_history_snapshots(self):
        state, _entry = score_hand(self.state, self.hand())
        restored = game_state_from_dict(game_state_to_dict(state))
        self.assertEqual(self.scores(restored), self.scores(state))
        self.assertEqual(len(restored.history), 1)
        self.assertEqual(restored.history[0].players[0].kasa, 18)


if __name__ == "__main__":
    unittest.main()
