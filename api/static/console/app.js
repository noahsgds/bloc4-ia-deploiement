/* Console Sentinel : interface de modération branchée sur l'API.
 *
 * Principes :
 * - aucune logique métier ici : tout calcul (validation, score, raisons) est fait par l'API ;
 * - sécurité : le contenu est toujours inséré avec textContent (jamais innerHTML), ce qui
 *   empêche l'injection de code via un fichier importé (XSS) ;
 * - la clé d'API est gardée dans sessionStorage (oubliée à la fermeture de l'onglet).
 */
"use strict";

const COLUMNS = [
  "player_id", "match_id", "accuracy", "headshot_rate", "kd_ratio", "kills_per_min",
  "damage_per_round", "avg_reaction_ms", "kills_through_smoke_ratio", "rank_tier",
  "account_age_days", "hours_played_total", "reports_received", "input_device", "platform",
];
const TEXT_COLUMNS = new Set(["player_id", "match_id", "input_device", "platform"]);
const MAX_BATCH = 1000;
const PRIORITY_LABEL = { haute: "Haute", moyenne: "Moyenne", basse: "Basse" };
const PRIORITY_ICON = { haute: "▲", moyenne: "◆", basse: "▽" };
const DECISION_LABEL = { triche_confirmee: "Triche confirmée", innocente: "Innocenté", a_approfondir: "À approfondir" };
const METRIC_LABELS = {
  pr_auc: "PR-AUC",
  roc_auc: "ROC-AUC",
  precision_top: "Précision top 1 %",
  recall: "Rappel",
  false_positive_rate: "Taux de faux positifs",
};
const GROUP_LABELS = { input_device: "Périphérique", platform: "Plateforme", accessibility_mode: "Mode accessibilité", age_band: "Tranche d'âge" };

const state = { apiKey: null, model: null, rows: [], validRows: [], predictions: [], records: new Map(), decisions: new Map(), current: null };
const $ = (id) => document.getElementById(id);

/* ---------- Utilitaires ---------- */

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

function svg(tag, attrs = {}, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

const pct = (x, digits = 0) => `${(x * 100).toFixed(digits)} %`;
const shortId = (id) => `${String(id).slice(0, 8)}…`;

let toastTimer;
function toast(message, isError = false) {
  const box = $("toast");
  box.textContent = message;
  box.classList.toggle("is-error", isError);
  box.classList.add("is-visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.remove("is-visible"), 4500);
}

function storage(action, value) {
  // sessionStorage peut être indisponible (navigation privée stricte) : on ne bloque jamais.
  try {
    if (action === "get") return sessionStorage.getItem("sentinel-key");
    if (action === "set") sessionStorage.setItem("sentinel-key", value);
    if (action === "clear") sessionStorage.removeItem("sentinel-key");
  } catch (_) { /* fonctionnement sans mémorisation */ }
  return null;
}

/* ---------- Appels à l'API ---------- */

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", "X-API-Key": state.apiKey || "", ...(options.headers || {}) },
  }).catch(() => null);

  setStatus(Boolean(response));
  if (!response) throw new Error("L'API ne répond pas. Vérifiez que le service est démarré.");
  if (response.status === 401) {
    logout();
    throw new Error("Clé d'API refusée. Reconnectez-vous.");
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join(" ; ") : body.detail;
    throw new Error(detail || `Erreur ${response.status}`);
  }
  return body;
}

function setStatus(up) {
  $("status-pill").classList.toggle("is-down", !up);
  $("status-text").textContent = up ? "API connectée" : "API injoignable";
}

/* ---------- Connexion ---------- */

async function login(key) {
  state.apiKey = key;
  state.model = await api("/model-info");
  storage("set", key);
  $("login").hidden = true;
  $("session").hidden = false;
  $("tabs").hidden = false;
  $("model-version").textContent = state.model.version;
  renderHealth();
  show("import");
}

function logout() {
  state.apiKey = null;
  storage("clear");
  $("session").hidden = true;
  $("tabs").hidden = true;
  document.querySelectorAll(".view").forEach((v) => (v.hidden = true));
  $("login").hidden = false;
  $("api-key").value = "";
}

/* ---------- Navigation ---------- */

function show(viewId) {
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== viewId));
  document.querySelectorAll(".tab").forEach((t) => {
    if (t.dataset.target === viewId) t.setAttribute("aria-current", "page");
    else t.removeAttribute("aria-current");
  });
  $("main").focus();
}

/* ---------- Import et validation ---------- */

function parseCsv(text) {
  // Lecteur CSV simple : virgules, guillemets doubles, retours à la ligne Windows ou Unix.
  const rows = [];
  let row = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field); field = "";
      if (row.some((v) => v !== "")) rows.push(row);
      row = [];
    } else field += c;
  }
  row.push(field);
  if (row.some((v) => v !== "")) rows.push(row);
  if (rows.length < 2) throw new Error("Le fichier ne contient aucune ligne de données.");
  const header = rows[0].map((h) => h.trim());
  return rows.slice(1).map((values) => Object.fromEntries(header.map((h, i) => [h, (values[i] ?? "").trim()])));
}

function toRecord(raw) {
  // Conversion des textes du CSV en nombres ; cellule vide -> null (valeur absente).
  const record = {};
  for (const [key, value] of Object.entries(raw)) {
    if (value === "") record[key] = null;
    else if (TEXT_COLUMNS.has(key) || Number.isNaN(Number(value))) record[key] = value;
    else record[key] = Number(value);
  }
  return record;
}

async function handleFile(file) {
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) return toast("Fichier trop volumineux (5 Mo maximum).", true);
  try {
    state.rows = parseCsv(await file.text());
    if (state.rows.length > MAX_BATCH) {
      toast(`Seules les ${MAX_BATCH} premières lignes sont analysées.`);
      state.rows = state.rows.slice(0, MAX_BATCH);
    }
    const report = await api("/profiles/validate", { method: "POST", body: JSON.stringify({ rows: state.rows }) });
    renderValidation(report, file.name);
  } catch (error) {
    toast(error.message, true);
  }
}

function renderValidation(report, fileName) {
  $("validation").hidden = false;
  $("v-total").textContent = report.total;
  $("v-valid").textContent = report.valid_count;
  $("v-invalid").textContent = report.invalid_count;

  const tbody = $("invalid-rows");
  tbody.replaceChildren();
  for (const row of report.rows.filter((r) => !r.valid)) {
    const list = el("ul");
    row.errors.forEach((message) => list.append(el("li", { text: message })));
    tbody.append(el("tr", {}, el("td", { class: "num", text: String(row.row) }), el("td", {}, list)));
  }
  $("invalid-block").hidden = report.invalid_count === 0;

  state.validRows = report.rows.filter((r) => r.valid).map((r) => toRecord(state.rows[r.row - 1]));
  const button = $("analyze");
  button.disabled = state.validRows.length === 0;
  button.textContent = `Analyser les ${state.validRows.length} profils conformes`;
  toast(`${fileName} : ${report.valid_count} ligne(s) conforme(s), ${report.invalid_count} rejetée(s).`);
}

async function analyze() {
  const button = $("analyze");
  button.disabled = true;
  button.textContent = "Analyse en cours…";
  try {
    const results = [];
    for (let i = 0; i < state.validRows.length; i += MAX_BATCH) {
      const items = state.validRows.slice(i, i + MAX_BATCH);
      const batch = await api("/predict/batch", { method: "POST", body: JSON.stringify({ items }) });
      results.push(...batch.predictions);
    }
    results.sort((a, b) => b.suspicion_score - a.suspicion_score);
    state.predictions = results;
    state.records = new Map(state.validRows.map((r) => [`${r.player_id}|${r.match_id}`, r]));
    renderQueue();
    show("queue");
    toast(`${results.length} fiches analysées.`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = `Analyser les ${state.validRows.length} profils conformes`;
  }
}

/* ---------- File de revue ---------- */

function priorityBadge(priority) {
  return el("span", { class: `badge badge-${priority}` },
    el("span", { "aria-hidden": "true", text: PRIORITY_ICON[priority] }), PRIORITY_LABEL[priority]);
}

function scoreBar(prediction) {
  const fill = el("span", { class: "score-fill" });
  fill.style.width = pct(prediction.suspicion_score);
  return el("div", { class: `score prio-${prediction.priority}` },
    el("span", { class: "score-track", "aria-hidden": "true" }, fill),
    el("span", { class: "score-value", text: prediction.suspicion_score.toFixed(2) }));
}

function renderQueue() {
  const hasData = state.predictions.length > 0;
  $("queue-empty").hidden = hasData;
  $("queue-content").hidden = !hasData;
  if (!hasData) return;

  $("q-total").textContent = state.predictions.length;
  $("q-flagged").textContent = state.predictions.filter((p) => p.flagged).length;
  $("q-decided").textContent = state.decisions.size;
  renderHistogram();
  renderQueueRows();
}

function renderQueueRows() {
  const priority = $("filter-priority").value;
  const search = $("filter-search").value.trim().toLowerCase();
  const visible = state.predictions.filter((p) =>
    (!priority || p.priority === priority) && (!search || String(p.player_id).toLowerCase().startsWith(search)));

  const tbody = $("queue-rows");
  tbody.replaceChildren();
  visible.forEach((p, index) => {
    const key = `${p.player_id}|${p.match_id}`;
    const decision = state.decisions.get(key);
    const button = el("button", { type: "button", class: "btn btn-ghost", text: "Examiner" });
    button.setAttribute("aria-label", `Examiner le joueur ${shortId(p.player_id)}`);
    button.addEventListener("click", () => openPlayer(p));
    tbody.append(el("tr", {},
      el("td", { text: String(index + 1) }),
      el("td", { class: "mono", title: p.player_id }, shortId(p.player_id), el("span", { class: "match-id", text: `match ${shortId(p.match_id)}` })),
      el("td", {}, scoreBar(p)),
      el("td", {}, priorityBadge(p.priority)),
      el("td", { class: "reason-cell", text: p.reasons[0] ? p.reasons[0].text : "—" }),
      el("td", {}, decision ? el("span", { class: `decision-tag ${decision}`, text: DECISION_LABEL[decision] }) : el("span", { class: "muted", text: "En attente" })),
      el("td", {}, button)));
  });
  $("filter-count").textContent = `${visible.length} fiche(s) affichée(s)`;
}

function renderHistogram() {
  const bins = 20;
  const counts = new Array(bins).fill(0);
  state.predictions.forEach((p) => counts[Math.min(bins - 1, Math.floor(p.suspicion_score * bins))]++);
  const width = 760, height = 170, left = 36, bottom = 26, top = 10;
  const max = Math.max(...counts, 1);
  const barW = (width - left) / bins;
  const chart = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img",
    "aria-label": `Histogramme des scores : ${state.predictions.length} fiches, seuil de décision à ${state.model.threshold.toFixed(2)}` });

  [0, 0.5, 1].forEach((f) => {
    const y = top + (1 - f) * (height - top - bottom);
    chart.append(svg("line", { x1: left, x2: width, y1: y, y2: y, class: "grid" }));
    chart.append(svg("text", { x: left - 6, y: y + 4, "text-anchor": "end" }, String(Math.round(f * max))));
  });
  counts.forEach((count, i) => {
    const h = (count / max) * (height - top - bottom);
    const lower = i / bins;
    const fill = lower >= state.model.threshold ? "var(--high)" : lower >= state.model.threshold / 2 ? "var(--medium)" : "var(--series-1)";
    const rect = svg("rect", { x: left + i * barW + 1, y: height - bottom - h, width: barW - 2, height: Math.max(h, 0), rx: 2, fill });
    rect.append(svg("title", {}, `Scores ${lower.toFixed(2)} – ${(lower + 1 / bins).toFixed(2)} : ${count} fiche(s)`));
    chart.append(rect);
  });
  const tx = left + state.model.threshold * (width - left);
  chart.append(svg("line", { x1: tx, x2: tx, y1: top, y2: height - bottom, stroke: "var(--text)", "stroke-width": 2, "stroke-dasharray": "4 3" }));
  chart.append(svg("text", { x: tx + 6, y: top + 12, class: "value-label" }, `seuil ${state.model.threshold.toFixed(2)}`));
  [0, 0.25, 0.5, 0.75, 1].forEach((f) => chart.append(svg("text", { x: left + f * (width - left), y: height - 6, "text-anchor": f === 1 ? "end" : "middle" }, f.toFixed(2))));
  $("score-histogram").replaceChildren(chart);
}

/* ---------- Fiche joueur ---------- */

function openPlayer(prediction) {
  state.current = prediction;
  const key = `${prediction.player_id}|${prediction.match_id}`;
  const record = state.records.get(key) || {};
  $("dlg-title").textContent = prediction.player_id;
  $("dlg-summary").replaceChildren(
    "Score de suspicion ", el("strong", { class: "mono", text: prediction.suspicion_score.toFixed(2) }),
    " · priorité ", priorityBadge(prediction.priority),
    prediction.flagged ? " · au-dessus du seuil de décision" : " · sous le seuil de décision");

  const reasons = $("dlg-reasons");
  reasons.replaceChildren();
  prediction.reasons.forEach((r) => {
    const up = r.direction === "hausse";
    reasons.append(el("li", { class: up ? "up" : "down" },
      el("div", {}, r.text.split(" — ")[0],
        el("span", { class: "reason-dir", text: up ? "▲ augmente le risque" : "▼ diminue le risque" }))));
  });

  const reasonFeatures = new Set(prediction.reasons.map((r) => r.feature));
  const stats = $("dlg-stats");
  stats.replaceChildren();
  for (const [feature, label] of Object.entries(state.model.feature_labels)) {
    const value = record[feature];
    const row = el("tr", { class: reasonFeatures.has(feature) ? "is-reason" : "" },
      el("th", { scope: "row", text: label }),
      el("td", { class: "num", text: value === null || value === undefined ? "non mesuré" : String(value) }));
    stats.append(row);
  }

  $("decision-form").reset();
  $("decision-error").textContent = "";
  $("player-dialog").showModal();
}

async function submitDecision(event) {
  event.preventDefault();
  const form = event.target;
  const data = new FormData(form);
  if (!data.get("decision") || !data.get("moderator")) {
    $("decision-error").textContent = "Choisissez une décision et indiquez votre identifiant.";
    return;
  }
  const p = state.current;
  try {
    await api(`/players/${encodeURIComponent(p.player_id)}/decisions`, {
      method: "POST",
      body: JSON.stringify({ match_id: p.match_id, decision: data.get("decision"), moderator: data.get("moderator"), comment: data.get("comment") || "" }),
    });
    state.decisions.set(`${p.player_id}|${p.match_id}`, data.get("decision"));
    $("player-dialog").close();
    renderQueue();
    toast(`Décision enregistrée : ${DECISION_LABEL[data.get("decision")]}.`);
  } catch (error) {
    $("decision-error").textContent = error.message;
  }
}

/* ---------- Santé du modèle ---------- */

function renderHealth() {
  const m = state.model;
  const card = $("model-card");
  card.replaceChildren();
  [
    ["Version", m.version],
    ["Algorithme", m.model_name.replaceAll("_", " ")],
    ["Entraîné le", new Date(m.created_at).toLocaleString("fr-FR")],
    ["Commit du code", m.git_commit],
    ["Seuil de décision", m.threshold.toFixed(3)],
    ["Empreinte des données", m.data.fingerprint],
  ].forEach(([label, value]) => card.append(el("div", {}, el("dt", { text: label }), el("dd", { text: String(value) }))));

  renderMetricsChart(m);
  renderFairnessChart(m);

  const list = $("acceptance");
  list.replaceChildren();
  const labels = { ...METRIC_LABELS, fairness: "Équité entre groupes" };
  for (const [name, passed] of Object.entries(m.acceptance.details)) {
    list.append(el("li", {},
      el("span", { class: passed ? "check-ok" : "check-ko", text: passed ? "✓ Atteint" : "✗ Non atteint" }),
      el("span", { text: labels[name] || name })));
  }
}

function legend(items) {
  const box = el("div", { class: "legend" });
  items.forEach(([label, color]) => {
    const span = el("span", { text: label });
    span.style.setProperty("--swatch", color);
    box.append(span);
  });
  return box;
}

function renderMetricsChart(m) {
  const metrics = ["pr_auc", "roc_auc", "precision_top", "recall"];
  const width = 520, rowH = 54, left = 140, right = 60, top = 6;
  const height = top + metrics.length * rowH;
  const scale = (v) => left + v * (width - left - right);
  const chart = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img",
    "aria-label": "Comparaison des métriques de Sentinel et de la règle des signalements ; données détaillées dans le tableau associé" });
  [0, 0.5, 1].forEach((f) => chart.append(svg("line", { x1: scale(f), x2: scale(f), y1: 0, y2: height, class: "grid" })));
  metrics.forEach((name, i) => {
    const y = top + i * rowH;
    chart.append(svg("text", { x: 0, y: y + 22 }, METRIC_LABELS[name]));
    [[m.test_metrics[name], "var(--series-1)", 6], [m.baseline_test_metrics[name], "var(--series-2)", 26]].forEach(([value, color, dy]) => {
      chart.append(svg("rect", { x: left, y: y + dy, width: Math.max(scale(value) - left, 2), height: 16, rx: 2, fill: color }));
      chart.append(svg("text", { x: scale(value) + 6, y: y + dy + 13, class: "value-label" }, pct(value)));
    });
  });
  $("metrics-chart").replaceChildren(legend([["Sentinel", "var(--series-1)"], ["Règle des signalements", "var(--series-2)"]]), chart);

  const table = $("metrics-table");
  table.replaceChildren(el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "Métrique" }), el("th", { scope: "col", class: "num", text: "Sentinel" }), el("th", { scope: "col", class: "num", text: "Signalements" }))));
  const body = el("tbody");
  Object.keys(METRIC_LABELS).forEach((name) => body.append(el("tr", {},
    el("th", { scope: "row", text: METRIC_LABELS[name] }),
    el("td", { class: "num", text: pct(m.test_metrics[name], 1) }),
    el("td", { class: "num", text: pct(m.baseline_test_metrics[name], 1) }))));
  table.append(body);
}

function renderFairnessChart(m) {
  const groups = Object.entries(m.fairness_fpr_gaps);
  const width = 520, rowH = 40, left = 150, right = 70, top = 6, limit = 2, maxPts = 3;
  const height = top + groups.length * rowH + 10;
  const scale = (pts) => left + (pts / maxPts) * (width - left - right);
  const chart = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img",
    "aria-label": "Écart de taux de faux positifs par groupe audité, comparé à la limite de 2 points ; données détaillées dans le tableau associé" });
  groups.forEach(([group, gap], i) => {
    const y = top + i * rowH;
    const pts = gap * 100;
    chart.append(svg("text", { x: 0, y: y + 17 }, GROUP_LABELS[group] || group));
    chart.append(svg("rect", { x: left, y: y + 4, width: Math.max(scale(pts) - left, 2), height: 18, rx: 2, fill: pts < limit ? "var(--series-1)" : "var(--high)" }));
    chart.append(svg("text", { x: scale(pts) + 6, y: y + 17, class: "value-label" }, `${pts.toFixed(1)} pt`));
  });
  chart.append(svg("line", { x1: scale(limit), x2: scale(limit), y1: 0, y2: height, stroke: "var(--medium)", "stroke-width": 2 }));
  chart.append(svg("text", { x: scale(limit) + 4, y: height - 2, class: "value-label" }, "limite 2 pt"));
  $("fairness-chart").replaceChildren(chart);

  const table = $("fairness-table");
  table.replaceChildren(el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "Groupe" }), el("th", { scope: "col", class: "num", text: "Écart (points)" }), el("th", { scope: "col", text: "Verdict" }))));
  const body = el("tbody");
  groups.forEach(([group, gap]) => body.append(el("tr", {},
    el("th", { scope: "row", text: GROUP_LABELS[group] || group }),
    el("td", { class: "num", text: (gap * 100).toFixed(2) }),
    el("td", { text: gap * 100 < limit ? "Conforme" : "Non conforme" }))));
  table.append(body);
}

/* ---------- Démarrage ---------- */

document.addEventListener("DOMContentLoaded", () => {
  $("expected-columns").textContent = COLUMNS.join(", ");

  $("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const key = $("api-key").value.trim();
    $("login-error").textContent = "";
    if (!key) { $("login-error").textContent = "Saisissez la clé d'API."; return; }
    try { await login(key); } catch (error) { $("login-error").textContent = error.message; }
  });
  $("logout").addEventListener("click", logout);
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => show(tab.dataset.target)));
  document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => show(b.dataset.goto)));

  const drop = $("dropzone");
  $("file-input").addEventListener("change", (e) => handleFile(e.target.files[0]));
  ["dragenter", "dragover"].forEach((type) => drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.add("is-over"); }));
  ["dragleave", "drop"].forEach((type) => drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.remove("is-over"); }));
  drop.addEventListener("drop", (e) => handleFile(e.dataTransfer.files[0]));
  $("load-sample").addEventListener("click", async () => {
    const response = await fetch("exemple_profils.csv");
    const blob = await response.blob();
    handleFile(new File([blob], "exemple_profils.csv", { type: "text/csv" }));
  });
  $("analyze").addEventListener("click", analyze);
  $("filter-priority").addEventListener("change", renderQueueRows);
  $("filter-search").addEventListener("input", renderQueueRows);
  $("decision-form").addEventListener("submit", submitDecision);

  const saved = storage("get");
  if (saved) login(saved).catch(() => logout());
});
