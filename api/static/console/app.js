/* Console Sentinel : page web qui appelle l'API.
 *
 * - Aucun calcul ici : la validation, le score et les raisons viennent de l'API.
 * - Sécurité : le texte est toujours inséré avec textContent (jamais innerHTML), donc un
 *   fichier importé ne peut pas injecter de code dans la page (protection XSS).
 * - La clé d'API reste en mémoire dans sessionStorage, oubliée à la fermeture de l'onglet.
 */
"use strict";

const NUMBER_COLUMNS = new Set([
  "accuracy", "headshot_rate", "kd_ratio", "kills_per_min", "damage_per_round", "avg_reaction_ms",
  "kills_through_smoke_ratio", "rank_tier", "account_age_days", "hours_played_total", "reports_received",
]);
const PRIORITY = { haute: "▲ Haute", moyenne: "◆ Moyenne", basse: "▽ Basse" }; // pas que la couleur
const state = { key: null, records: new Map(), current: null };
const $ = (id) => document.getElementById(id);

function cell(row, text) {
  const td = document.createElement("td");
  td.textContent = text;
  row.append(td);
  return td;
}

function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.add("is-visible");
  setTimeout(() => $("toast").classList.remove("is-visible"), 4000);
}

/* ---------- Appels à l'API ---------- */

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", "X-API-Key": state.key || "" },
  });
  const body = await response.json().catch(() => ({}));
  if (response.status === 401) throw new Error("Clé d'API refusée.");
  if (!response.ok) {
    const error = new Error(typeof body.detail === "string" ? body.detail : `Erreur ${response.status}`);
    error.details = Array.isArray(body.detail) ? body.detail : [];
    throw error;
  }
  return body;
}

/* ---------- Connexion et navigation ---------- */

async function login(key) {
  state.key = key;
  const info = await api("/model-info");
  try { sessionStorage.setItem("sentinel-key", key); } catch (_) { /* navigation privée */ }
  $("model-version").textContent = info.version;
  $("login").hidden = true;
  $("session").hidden = false;
  $("tabs").hidden = false;
  show("queue");
}

function show(view) {
  for (const id of ["queue", "fiche"]) $(id).hidden = id !== view;
  document.querySelectorAll(".tab").forEach((tab) => {
    if (tab.dataset.target === view) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });
  $("main").focus();
}

/* ---------- Import et analyse ---------- */

function parseCsv(text) {
  const [header, ...lines] = text.trim().split(/\r?\n/);
  const columns = header.split(",").map((c) => c.trim());
  return lines.filter((l) => l.trim()).map((line) => {
    const values = line.split(",");
    const fiche = {};
    columns.forEach((column, i) => {
      const raw = (values[i] ?? "").trim();
      fiche[column] = raw === "" ? null : NUMBER_COLUMNS.has(column) ? Number(raw) : raw;
    });
    return fiche;
  });
}

async function analyze(fiches) {
  // L'API refuse un lot entier si une ligne est invalide : on écarte les lignes signalées
  // (leur numéro est dans l'erreur 422) puis on relance l'analyse des lignes valides.
  const rejected = [];
  let result;
  try {
    result = await api("/predict", { method: "POST", body: JSON.stringify({ fiches }) });
  } catch (error) {
    if (!error.details.length) throw error;
    const bad = new Set(error.details.map((d) => d.loc[2]));
    error.details.forEach((d) => rejected.push(`Ligne ${d.loc[2] + 1} — ${d.message}`));
    const valid = fiches.filter((_, i) => !bad.has(i));
    result = await api("/predict", { method: "POST", body: JSON.stringify({ fiches: valid }) });
  }
  fiches.forEach((f) => state.records.set(f.match_id, f));
  render(result.predictions, rejected);
}

function render(predictions, rejected) {
  $("summary").hidden = false;
  $("n-ok").textContent = predictions.length;
  $("n-flagged").textContent = predictions.filter((p) => p.flagged).length;
  $("n-rejected").textContent = rejected.length;
  $("rejected-block").hidden = rejected.length === 0;
  $("rejected-list").replaceChildren(...rejected.map((text) => {
    const li = document.createElement("li");
    li.textContent = text;
    return li;
  }));

  const rows = predictions.map((p) => {
    const tr = document.createElement("tr");
    cell(tr, PRIORITY[p.priority]).className = `priority-${p.priority}`;
    cell(tr, p.suspicion_score.toFixed(3));
    cell(tr, `${p.player_id.slice(0, 8)}…`);
    cell(tr, p.reasons[0]?.text ?? "");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-ghost";
    button.textContent = "Voir la fiche";
    button.addEventListener("click", () => openFiche(p));
    tr.append(document.createElement("td"));
    tr.lastChild.append(button);
    return tr;
  });
  $("queue-rows").replaceChildren(...rows);
}

/* ---------- Fiche détaillée et décision ---------- */

function openFiche(prediction) {
  state.current = prediction;
  $("fiche-empty").hidden = true;
  $("fiche-content").hidden = false;
  $("f-score").textContent = prediction.suspicion_score.toFixed(3);
  $("f-priority").textContent = PRIORITY[prediction.priority];
  $("f-reasons").replaceChildren(...prediction.reasons.map((r) => {
    const li = document.createElement("li");
    li.textContent = r.text;
    return li;
  }));
  const fiche = state.records.get(prediction.match_id) ?? {};
  $("f-stats").replaceChildren(...Object.entries(fiche).map(([name, value]) => {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.scope = "row";
    th.textContent = name;
    tr.append(th);
    cell(tr, value ?? "non mesuré");
    return tr;
  }));
  show("fiche");
}

async function saveDecision(event) {
  event.preventDefault();
  const p = state.current;
  await api(`/players/${encodeURIComponent(p.player_id)}/decisions`, {
    method: "POST",
    body: JSON.stringify({
      match_id: p.match_id,
      decision: $("d-decision").value,
      moderator: $("d-moderator").value.trim(),
      comment: $("d-comment").value.trim(),
    }),
  });
  toast("Décision enregistrée.");
}

/* ---------- Branchements ---------- */

$("login-form").addEventListener("submit", (event) => {
  event.preventDefault();
  login($("api-key").value.trim()).catch((error) => { $("login-error").textContent = error.message; });
});
$("logout").addEventListener("click", () => {
  try { sessionStorage.removeItem("sentinel-key"); } catch (_) { /* rien */ }
  location.reload();
});
document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => show(tab.dataset.target)));
$("file-input").addEventListener("change", async () => {
  const file = $("file-input").files[0];
  if (file) analyze(parseCsv(await file.text())).catch((error) => toast(error.message));
});
$("load-sample").addEventListener("click", async () => {
  const text = await (await fetch("exemple_profils.csv")).text();
  analyze(parseCsv(text)).catch((error) => toast(error.message));
});
$("decision-form").addEventListener("submit", (event) => saveDecision(event).catch((e) => toast(e.message)));

try {
  const saved = sessionStorage.getItem("sentinel-key");
  if (saved) login(saved).catch(() => sessionStorage.removeItem("sentinel-key"));
} catch (_) { /* navigation privée */ }
