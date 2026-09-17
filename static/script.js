let currentGame = null;
let selectedDefenders = {};

const obligations = {
  6: [2, 2],
  7: [2, 1],
  8: [1, 1],
  9: [1, 0],
};

document.addEventListener("DOMContentLoaded", () => {
  attachEventListeners();
  loadGame();
});

async function apiRequest(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("The server returned an unreadable response.");
  }
  if (!response.ok || data.success === false) {
    throw new Error(data.error || "The request could not be completed.");
  }
  return data;
}

async function loadGame() {
  setBusy(true, "Loading game...");
  try {
    currentGame = await apiRequest("/api/game");
    render();
    clearNotice();
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    setBusy(false);
  }
}

function render() {
  renderScores();
  renderDeclarerOptions();
  renderHistory();
  updateContractValue();
  updateTrickCounter();
  updateTaGrafoMode();
  document.getElementById("undoBtn").disabled = currentGame.history.length === 0;
  document.getElementById("gameStatus").textContent =
    `${currentGame.players.map((player) => player.name).join(" · ")} · kasa ${currentGame.starting_kasa}`;
}

function renderScores() {
  const grid = document.getElementById("scoreGrid");
  grid.replaceChildren();
  currentGame.players.forEach((player, index) => {
    const card = element("article", "score-card");
    const marker = element("span", "player-marker", String(index + 1));
    const name = element("h3", "score-name", player.name);
    const values = element("div", "score-values");
    values.append(scoreMetric("Kasa", player.kasa), scoreMetric("Chips", formatSigned(player.chips)));
    card.append(marker, name, values);
    grid.append(card);
  });
}

function scoreMetric(label, value) {
  const metric = element("div", "score-value");
  metric.append(element("span", "score-label", label), element("strong", "score-number", String(value)));
  return metric;
}

function renderDeclarerOptions() {
  const select = document.getElementById("declarer");
  const previous = select.value;
  select.replaceChildren(new Option("Select player", ""));
  currentGame.players.forEach((player) => select.add(new Option(player.name, player.id)));
  if (currentGame.players.some((player) => player.id === previous)) {
    select.value = previous;
  }
  updateDefenders();
}

function updateDefenders() {
  const declarerId = document.getElementById("declarer").value;
  const container = document.getElementById("defendersContainer");
  container.replaceChildren();
  selectedDefenders = {};

  if (!declarerId) {
    container.append(element("p", "empty-state", "Select a declarer first."));
    document.getElementById("declarerTricksLabel").textContent = "Declarer tricks";
    updateTrickCounter();
    return;
  }

  const declarer = currentGame.players.find((player) => player.id === declarerId);
  document.getElementById("declarerTricksLabel").textContent = `${declarer.name} tricks`;
  const defenders = currentGame.players.filter((player) => player.id !== declarerId);
  defenders.forEach((defender, index) => {
    selectedDefenders[defender.id] = { active: true, tricks: 0, index };

    const row = element("div", "defender-row");
    row.dataset.playerId = defender.id;
    const identity = element("div", "defender-identity");
    identity.append(
      element("strong", "", defender.name),
      element("span", "obligation", obligationText(index)),
    );

    const toggleLabel = element("label", "switch-label");
    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.checked = true;
    toggle.className = "defender-active";
    toggleLabel.append(toggle, document.createTextNode("Plays"));

    const tricksLabel = element("label", "tricks-input");
    tricksLabel.append(document.createTextNode("Tricks"));
    const tricks = document.createElement("input");
    tricks.type = "number";
    tricks.min = "0";
    tricks.max = "10";
    tricks.value = "0";
    tricks.inputMode = "numeric";
    tricksLabel.append(tricks);

    toggle.addEventListener("change", () => {
      selectedDefenders[defender.id].active = toggle.checked;
      if (!toggle.checked) {
        tricks.value = "0";
        selectedDefenders[defender.id].tricks = 0;
      }
      tricks.disabled = !toggle.checked;
      updateObligations();
      updateTrickCounter();
    });
    tricks.addEventListener("input", () => {
      selectedDefenders[defender.id].tricks = clampTricks(tricks.value);
      updateTrickCounter();
    });

    row.append(identity, toggleLabel, tricksLabel);
    container.append(row);
  });
  updateObligations();
  updateTrickCounter();
}

function updateObligations() {
  const active = Object.values(selectedDefenders).filter((defender) => defender.active);
  document.querySelectorAll(".defender-row").forEach((row) => {
    const defender = selectedDefenders[row.dataset.playerId];
    let obligation = 0;
    if (defender.active && active.length === 1) {
      obligation = Number(document.getElementById("level").value) < 8 ? 2 : 1;
    } else if (defender.active) {
      obligation = obligations[Number(document.getElementById("level").value)][defender.index];
    }
    row.querySelector(".obligation").textContent = defender.active
      ? `Owes ${obligation} trick${obligation === 1 ? "" : "s"}`
      : "Not participating";
  });
}

function obligationText(index) {
  const obligation = obligations[Number(document.getElementById("level").value)][index];
  return `Owes ${obligation} trick${obligation === 1 ? "" : "s"}`;
}

function updateContractValue() {
  const level = Number(document.getElementById("level").value);
  const suit = document.getElementById("suit").value;
  let value;
  if (level === 6) {
    value = { spades: 2, clubs: 3, diamonds: 4, hearts: 5, no_trump: 6 }[suit];
  } else {
    value = level + (suit === "no_trump" ? 1 : 0);
  }
  document.getElementById("contractValue").textContent = `Value ${value}`;
}

function updateTrickCounter() {
  const declarerTricks = clampTricks(document.getElementById("declarerTricks").value);
  const defenderTricks = Object.values(selectedDefenders)
    .filter((defender) => defender.active)
    .reduce((total, defender) => total + defender.tricks, 0);
  const total = declarerTricks + defenderTricks;
  const counter = document.getElementById("trickCounter");
  counter.classList.toggle("warning", total !== 10);
  counter.classList.toggle("complete", total === 10);
  counter.querySelector("strong").textContent = `${total} / 10`;
  const difference = 10 - total;
  counter.querySelector("span").textContent = difference === 0
    ? "All tricks assigned"
    : difference > 0
      ? `${difference} trick${difference === 1 ? "" : "s"} unassigned`
      : `${Math.abs(difference)} too many tricks`;
}

function renderHistory() {
  const list = document.getElementById("historyList");
  list.replaceChildren();
  const count = currentGame.history.length;
  document.getElementById("handCount").textContent = `${count} event${count === 1 ? "" : "s"}`;
  if (count === 0) {
    list.append(element("li", "empty-state", "No hands recorded yet."));
    return;
  }

  currentGame.history.forEach((entry, index) => {
    const item = element("li", "history-item");
    const heading = element("div", "history-heading");
    const isDeclinedTaGrafo = entry.contract === "Ta Grafo" && entry.result === "declined";
    heading.append(
      element("strong", "", `${isDeclinedTaGrafo ? "Bidding" : "Hand"} ${count - index}`),
      element("span", `result result-${entry.result}`, entry.result),
    );
    const titleText = isDeclinedTaGrafo
      ? `${entry.declarer_name} · Ta grafo · +2 kasa`
      : `${entry.declarer_name} · ${entry.contract} · ${entry.declarer_tricks} tricks`;
    const title = element("p", "history-title", titleText);
    const notes = element("ul", "history-notes");
    entry.notes.forEach((note) => notes.append(element("li", "", note)));
    item.append(heading, title, notes);
    list.append(item);
  });
}

async function recordHand(event) {
  event.preventDefault();
  const declarerId = document.getElementById("declarer").value;
  if (!declarerId) {
    showNotice("Select a declarer before recording the hand.", "error");
    return;
  }

  if (isTaGrafoDecline()) {
    await recordTaGrafoDecline(declarerId);
    return;
  }

  const defenders = Object.entries(selectedDefenders).map(([playerId, defender]) => ({
    player_id: playerId,
    active: defender.active,
    tricks: defender.active ? defender.tricks : 0,
  }));
  setBusy(true, "Recording hand...");
  try {
    const data = await apiRequest("/api/score-hand", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        declarer_id: declarerId,
        level: Number(document.getElementById("level").value),
        suit: document.getElementById("suit").value,
        declarer_tricks: clampTricks(document.getElementById("declarerTricks").value),
        defenders,
      }),
    });
    currentGame = data.game;
    resetHandForm();
    render();
    if (data.warnings.length) {
      showNotice(`Hand saved. ${data.warnings.join(" ")}`, "warning");
    } else {
      showNotice("Hand saved.", "success");
    }
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function recordTaGrafoDecline(playerId) {
  setBusy(true, "Recording Ta grafo decline...");
  try {
    const data = await apiRequest("/api/ta-grafo/decline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ player_id: playerId }),
    });
    currentGame = data.game;
    resetHandForm();
    render();
    showNotice("Ta grafo decline saved: +2 kasa.", "success");
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function undoLastHand() {
  setBusy(true, "Undoing last hand...");
  try {
    const data = await apiRequest("/api/undo", { method: "POST" });
    currentGame = data.game;
    resetHandForm();
    render();
    showNotice("Last hand undone.", "success");
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function startNewGame(event) {
  event.preventDefault();
  setBusy(true, "Starting new game...");
  try {
    const data = await apiRequest("/api/new-game", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        player1: document.getElementById("player1Name").value,
        player2: document.getElementById("player2Name").value,
        player3: document.getElementById("player3Name").value,
        starting_kasa: Number(document.getElementById("startingKasa").value),
      }),
    });
    currentGame = data.game;
    document.getElementById("newGameDialog").close();
    resetHandForm();
    render();
    showNotice("New game started.", "success");
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    setBusy(false);
  }
}

function resetHandForm() {
  document.getElementById("contractForm").reset();
  document.getElementById("level").value = "6";
  document.getElementById("suit").value = "spades";
  document.getElementById("declarerTricks").value = "6";
  document.getElementById("taGrafoToggle").checked = false;
  document.querySelector('input[name="taGrafoOutcome"][value="play"]').checked = true;
  selectedDefenders = {};
  updateTaGrafoMode();
}

function isTaGrafoDecline() {
  return document.getElementById("taGrafoToggle").checked
    && document.querySelector('input[name="taGrafoOutcome"]:checked').value === "decline";
}

function updateTaGrafoMode() {
  const enabled = document.getElementById("taGrafoToggle").checked;
  const decline = enabled && isTaGrafoDecline();
  document.getElementById("taGrafoOutcome").classList.toggle("hidden", !enabled);
  document.getElementById("levelField").classList.toggle("hidden", decline);
  document.getElementById("suitField").classList.toggle("hidden", decline);
  document.getElementById("participationFieldset").classList.toggle("hidden", decline);
  document.getElementById("tricksFieldset").classList.toggle("hidden", decline);
  document.getElementById("contractValue").classList.toggle("hidden", decline);
  document.getElementById("recordBtn").textContent = decline
    ? "Record decline (+2 kasa)"
    : "Record hand";
}

function showNewGameDialog() {
  currentGame.players.forEach((player, index) => {
    document.getElementById(`player${index + 1}Name`).value = player.name;
  });
  document.getElementById("startingKasa").value = currentGame.starting_kasa;
  document.getElementById("newGameDialog").showModal();
}

function attachEventListeners() {
  document.getElementById("contractForm").addEventListener("submit", recordHand);
  document.getElementById("declarer").addEventListener("change", updateDefenders);
  document.getElementById("taGrafoToggle").addEventListener("change", updateTaGrafoMode);
  document.querySelectorAll('input[name="taGrafoOutcome"]').forEach((input) => {
    input.addEventListener("change", updateTaGrafoMode);
  });
  document.getElementById("level").addEventListener("change", () => {
    updateContractValue();
    updateObligations();
  });
  document.getElementById("suit").addEventListener("change", updateContractValue);
  document.getElementById("declarerTricks").addEventListener("input", updateTrickCounter);
  document.getElementById("undoBtn").addEventListener("click", undoLastHand);
  document.getElementById("newGameBtn").addEventListener("click", showNewGameDialog);
  document.getElementById("cancelGameBtn").addEventListener("click", () => {
    document.getElementById("newGameDialog").close();
  });
  document.getElementById("newGameForm").addEventListener("submit", startNewGame);
}

function setBusy(busy, message = "") {
  document.body.classList.toggle("busy", busy);
  document.querySelectorAll("button").forEach((button) => {
    if (button.id !== "undoBtn" || busy) button.disabled = busy;
  });
  if (busy && message) document.getElementById("gameStatus").textContent = message;
  if (!busy && currentGame) {
    document.getElementById("undoBtn").disabled = currentGame.history.length === 0;
    document.getElementById("gameStatus").textContent =
      `${currentGame.players.map((player) => player.name).join(" · ")} · kasa ${currentGame.starting_kasa}`;
  }
}

function showNotice(message, kind) {
  const notice = document.getElementById("notice");
  notice.textContent = message;
  notice.className = `notice ${kind}`;
  notice.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function clearNotice() {
  const notice = document.getElementById("notice");
  notice.textContent = "";
  notice.className = "notice hidden";
}

function clampTricks(value) {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) return 0;
  return Math.min(10, Math.max(0, parsed));
}

function formatSigned(value) {
  return value > 0 ? `+${value}` : String(value);
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}
