import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module
from prefa_rules import create_game


class PrefaApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "game.json"
        app_module.app.config.update(TESTING=True, STATE_FILE=self.state_file)
        app_module.game_state = create_game(["A", "B", "C"])
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def valid_hand(self, **changes):
        a, b, c = [player.id for player in app_module.game_state.players]
        payload = {
            "declarer_id": a,
            "level": 6,
            "suit": "spades",
            "declarer_tricks": 6,
            "defenders": [
                {"player_id": b, "active": True, "tricks": 2},
                {"player_id": c, "active": True, "tricks": 2},
            ],
        }
        payload.update(changes)
        return payload

    def test_score_hand_returns_warning_for_non_ten_total(self):
        response = self.client.post(
            "/api/score-hand",
            json=self.valid_hand(declarer_tricks=5),
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["warnings"], ["Entered tricks total 9, not 10."])
        self.assertTrue(self.state_file.exists())

    def test_valid_hand_returns_no_warnings(self):
        response = self.client.post("/api/score-hand", json=self.valid_hand())
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["warnings"], [])
        self.assertEqual(data["game"]["players"][0]["kasa"], 18)
        self.assertEqual(len(data["game"]["history"]), 1)

    def test_ta_grafo_decline_adds_kasa_and_persists(self):
        player_id = app_module.game_state.players[1].id
        response = self.client.post(
            "/api/ta-grafo/decline",
            json={"player_id": player_id},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["game"]["players"][1]["kasa"], 22)
        self.assertEqual(data["entry"]["result"], "declined")
        restored = app_module.load_game(self.state_file)
        self.assertEqual(restored.players[1].kasa, 22)

    def test_ta_grafo_decline_rejects_unknown_player(self):
        response = self.client.post(
            "/api/ta-grafo/decline",
            json={"player_id": "missing"},
        )
        self.assertEqual(response.status_code, 400)

    def test_ta_grafo_decline_can_be_undone_after_reload(self):
        player_id = app_module.game_state.players[0].id
        response = self.client.post(
            "/api/ta-grafo/decline",
            json={"player_id": player_id},
        )
        self.assertEqual(response.status_code, 200)
        app_module.game_state = app_module.load_game(self.state_file)
        response = self.client.post("/api/undo")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["game"]["players"][0]["kasa"], 20)

    def test_inactive_defender_tricks_are_forced_to_zero(self):
        payload = self.valid_hand()
        payload["defenders"][1].update(active=False, tricks=9)
        response = self.client.post("/api/score-hand", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["warnings"], ["Entered tricks total 8, not 10."])
        self.assertEqual(data["game"]["players"][2]["chips"], 0)

    def test_rejects_invalid_player_and_duplicate_defenders(self):
        payload = self.valid_hand(declarer_id="missing")
        response = self.client.post("/api/score-hand", json=payload)
        self.assertEqual(response.status_code, 400)

        payload = self.valid_hand()
        payload["defenders"][1]["player_id"] = payload["defenders"][0]["player_id"]
        response = self.client.post("/api/score-hand", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("unique", response.get_json()["error"])

    def test_rejects_invalid_contract_and_tricks(self):
        response = self.client.post(
            "/api/score-hand",
            json=self.valid_hand(suit="stars"),
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/api/score-hand",
            json=self.valid_hand(declarer_tricks=11),
        )
        self.assertEqual(response.status_code, 400)

    def test_new_game_validates_and_persists(self):
        response = self.client.post(
            "/api/new-game",
            json={
                "player1": "<A>",
                "player2": "B",
                "player3": "C",
                "starting_kasa": 30,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["game"]["players"][0]["name"], "<A>")
        restored = app_module.load_game(self.state_file)
        self.assertEqual(restored.players[0].name, "<A>")
        self.assertEqual(restored.starting_kasa, 30)

    def test_persistence_reload_and_undo(self):
        response = self.client.post("/api/score-hand", json=self.valid_hand())
        self.assertEqual(response.status_code, 200)
        app_module.game_state = app_module.load_game(self.state_file)
        self.assertEqual(app_module.game_state.players[0].kasa, 18)

        response = self.client.post("/api/undo")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["game"]["players"][0]["kasa"], 20)
        restored = app_module.load_game(self.state_file)
        self.assertEqual(restored.players[0].kasa, 20)

    def test_corrupt_save_falls_back_to_fresh_game(self):
        self.state_file.write_text("not json", encoding="utf-8")
        state = app_module.load_game(self.state_file)
        self.assertEqual(len(state.players), 3)
        self.assertEqual([player.kasa for player in state.players], [20, 20, 20])

    def test_failed_save_does_not_advance_in_memory_state(self):
        with patch.object(app_module, "save_game", side_effect=OSError):
            response = self.client.post("/api/score-hand", json=self.valid_hand())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(app_module.game_state.players[0].kasa, 20)
        self.assertEqual(app_module.game_state.history, [])


if __name__ == "__main__":
    unittest.main()
