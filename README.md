# Prefa Scorer

A local scorer for the three-player Prefa.

## Running the Web App (Recommended)

The app is now a modern web-based interface using Flask backend and HTML/CSS/JavaScript frontend:

```bash
# Set up virtual environment (first time only)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start the Flask server
python3 app.py
```

Then open **http://localhost:8000** in your browser.

### Features

- **Player Score Display** - Real-time kasa and chips for each player
- **Ta Grafo Decision** - Mark the selected declarer as Ta grafo, then record
  whether they play normally or decline and add 2 kasa
- **Contract Recording** - Full contract details with dynamic defender selection
- **Hand History** - Complete history of all recorded hands
- **Automatic Saving** - The current game survives server restarts
- **New Game** - Start fresh game with custom player names and starting kasa
- **Undo** - Undo the last recorded hand

## Terminal Interface

Run the terminal CLI scorer with:

```bash
python3 prefa_cli.py
```

## Project Structure

- `prefa_rules.py` - Core game scoring logic and rules engine
- `app.py` - Flask backend server
- `templates/index.html` - Web interface HTML
- `static/style.css` - Web interface styling
- `static/script.js` - Web interface JavaScript and API integration
- `prefa_cli.py` - Terminal interface
- `test_prefa_rules.py` - Unit tests for scoring rules
- `test_app.py` - Flask API, validation, persistence, and undo tests

## Running Tests

```bash
python3 -m unittest
```

## Implemented rules

- Three players with a starting kasa of 20.
- Contract values for 6 suit/no-trump, 7, 8, and 9 contracts.
- Defender obligations, including one-defender-alone adjustments.
- Optional defender participation.
- Exact contracts reduce the declarer's kasa, then lick from the opponent with
  the largest kasa once the declarer's kasa is zero.
- Overmade contracts do not reduce kasa or lick.
- Short declarer contracts add kasa penalties.
- Active defenders receive chip payments for tricks unless the hand is overmade.
- Short defenders pay chip penalties to the declarer.
- Only one player may say `Ta grafo`, and that player is the only possible
  declarer for the round.
- If the Ta grafo player elects to play, the contract is scored normally with
  no special penalty.
- If the Ta grafo player declines to play, the round ends and their kasa
  increases by 2; the decline is recorded in history and can be undone.
- Overmade contracts do not reduce kasa or lick, but all defender chip
  settlements still occur.
- Inactive defenders have zero scoring tricks and no chip settlement.
- Trick totals other than 10 show a warning but may still be recorded.
- The current game is saved to `prefa_game.json` after every change.
- A defender short by `n` pays `contract value * n`, doubled when `n >= 2`.
- Defender trick payments are paid from declarer to active defenders.
- A declarer short by two or more doubles defender trick payments.
- Both defenders may opt out; the declarer's result is still recorded.
