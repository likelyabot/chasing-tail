/* fishing-app UI — vanilla JS, no build step. Talks to /api/*. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

let USERS = [];
let WATERS = [];

// ---------- tabs ----------
$$("#tabs button").forEach((btn) =>
  btn.addEventListener("click", () => {
    $$("#tabs button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    $$(".tab").forEach((t) => t.classList.add("hidden"));
    $("#tab-" + btn.dataset.tab).classList.remove("hidden");
    if (btn.dataset.tab === "weather") loadWeather();
    if (btn.dataset.tab === "gear") loadGear();
    if (btn.dataset.tab === "chat") loadChatBadge();
  })
);

// ---------- api helpers ----------
async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return r.status === 204 ? null : r.json();
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

function fmtTs(iso) {
  if (!iso) return "";
  try { return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }); }
  catch { return iso; }
}

// ---------- boot ----------
async function boot() {
  [USERS, WATERS] = await Promise.all([api("/api/users"), api("/api/waters")]);
  fillSelect("#tf-user", USERS.map((u) => [u.id, u.name]));
  fillSelect("#pf-water", WATERS.map((w) => [w.slug, w.name]));
  fillSelect("#tf-water", WATERS.map((w) => [w.id, w.name]));
  fillSelect("#wf-water", WATERS.map((w) => [w.slug, w.name]));
  const today = new Date().toISOString().slice(0, 10);
  $("#tf-date").value = today;
  $("#pf-date").value = today;
  await loadTrips();
}

function fillSelect(sel, pairs) {
  $(sel).innerHTML = pairs.map(([v, l]) => `<option value="${esc(String(v))}">${esc(l)}</option>`).join("");
}

// ---------- trips ----------
async function loadTrips() {
  const trips = await api("/api/trips");
  const el = $("#trip-list");
  if (!trips.length) {
    el.innerHTML = `<div class="card meta">No trips yet — plan one above.</div>`;
    return;
  }
  el.innerHTML = trips.map((t) => `
    <div class="card trip" data-trip="${t.id}">
      <h3>${esc(t.water_name)} <span class="chip ${esc(t.status)}">${esc(t.status)}</span></h3>
      <div class="when">${esc(t.date)} · ${esc(t.user_name)}${t.target_species ? " · targeting " + esc(t.target_species) : ""}</div>
      ${t.notes ? `<div class="meta">${esc(t.notes)}</div>` : ""}
      <div class="catches" data-catches="${t.id}"></div>
      <div class="inline-form" hidden data-addform="${t.id}">
        <input placeholder="species" data-f="species" required>
        <input placeholder="count" data-f="count" type="number" min="1" value="1">
        <input placeholder="lure / method" data-f="lure_or_method">
        <input placeholder="spot" data-f="spot">
        <button class="ghost" data-savecatch="${t.id}">Log catch</button>
      </div>
      <div class="row" style="margin-top:10px">
        <button class="ghost" data-togglecatch="${t.id}">+ catch</button>
        <button class="ghost" data-edittrip="${t.id}">edit</button>
        <button class="danger" data-deltrip="${t.id}">delete</button>
      </div>
    </div>`).join("");
  for (const t of trips) renderCatches(t.id);
}

async function renderCatches(tripId) {
  const box = $(`[data-catches="${tripId}"]`);
  const catches = await api(`/api/catches?trip_id=${tripId}`);
  box.innerHTML = catches.length
    ? catches.map((c) => `
      <div class="catch-row" data-catch="${c.id}">
        <span class="cnt">${c.count}×</span>
        <span><strong>${esc(c.species)}</strong>${c.lure_or_method ? " · " + esc(c.lure_or_method) : ""}${c.spot ? " · " + esc(c.spot) : ""}</span>
        <span class="meta" style="flex:1"></span>
        <button class="danger" data-delcatch="${c.id}" style="padding:2px 8px">✕</button>
      </div>`).join("")
    : `<div class="meta" style="margin-top:8px">No catches logged yet.</div>`;
}

$("#trip-list").addEventListener("click", async (e) => {
  const t = e.target.closest("button");
  if (!t) return;
  if (t.dataset.togglecatch) {
    $(`[data-addform="${t.dataset.togglecatch}"]`).toggleAttribute("hidden");
  } else if (t.dataset.savecatch) {
    const form = $(`[data-addform="${t.dataset.savecatch}"]`);
    const body = {};
    form.querySelectorAll("[data-f]").forEach((i) => (body[i.dataset.f] = i.value));
    body.count = parseInt(body.count || "1", 10);
    body.trip_id = parseInt(t.dataset.savecatch, 10);
    try {
      await api("/api/catches", { method: "POST", body: JSON.stringify(body) });
      form.setAttribute("hidden", "");
      form.querySelectorAll("input").forEach((i) => (i.value = i.type === "number" ? "1" : ""));
      await renderCatches(body.trip_id);
    } catch (err) { alert("Failed: " + err.message); }
  } else if (t.dataset.delcatch) {
    const id = t.dataset.delcatch;
    const tripId = t.closest(".trip").dataset.trip;
    await api(`/api/catches/${id}`, { method: "DELETE" });
    await renderCatches(tripId);
  } else if (t.dataset.deltrip) {
    if (confirm("Delete this trip and all its catches?")) {
      await api(`/api/trips/${t.dataset.deltrip}`, { method: "DELETE" });
      await loadTrips();
    }
  } else if (t.dataset.edittrip) {
    const trip = (await api(`/api/trips/${t.dataset.edittrip}`));
    const water = WATERS.find((w) => String(w.id) === String(trip.water_id));
    const user = USERS.find((u) => String(u.id) === String(trip.user_id));
    const name = prompt("Water name:", water?.name || "");
    if (name === null) return;
    const date = prompt("Date (YYYY-MM-DD):", trip.date);
    if (date === null) return;
    const species = prompt("Target species:", trip.target_species || "");
    const notes = prompt("Notes:", trip.notes || "");
    const status = prompt("Status (planned/completed/cancelled):", trip.status);
    await api(`/api/trips/${trip.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        water_id: WATERS.find((w) => w.name === name)?.id,
        date, target_species: species || null, notes: notes || null,
        status: ["planned", "completed", "cancelled"].includes(status) ? status : trip.status,
      }),
    });
    await loadTrips();
  }
});

$("#trip-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {
    user_id: parseInt($("#tf-user").value, 10),
    water_id: parseInt($("#tf-water").value, 10),
    date: $("#tf-date").value,
    target_species: $("#tf-species").value.trim() || null,
    notes: $("#tf-notes").value.trim() || null,
    status: $("#tf-status").value,
  };
  try {
    await api("/api/trips", { method: "POST", body: JSON.stringify(body) });
    $("#tf-species").value = ""; $("#tf-notes").value = "";
    await loadTrips();
  } catch (err) { alert("Failed: " + err.message); }
});

// ---------- plan ----------
let planGeneration = 0;

$("#plan-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const gen = ++planGeneration;
  const q = new URLSearchParams({
    water_slug: $("#pf-water").value,
    live_weather: $("#pf-live").checked ? "true" : "false",
  });
  if ($("#pf-date").value) q.set("date", $("#pf-date").value);
  if ($("#pf-species").value.trim()) q.set("species", $("#pf-species").value.trim());
  const box = $("#plan-result");
  box.innerHTML = `<div class="card meta">Thinking…</div>`;
  try {
    const p = await api("/api/recommend?" + q.toString());
    if (gen !== planGeneration) return;
    box.innerHTML = `
      <div class="kayak ${esc(p.kayak.level)}">
        <span class="flag">${esc(p.kayak.flag)}</span> — ${esc(p.kayak.reason)}
      </div>
      ${p.suggestions.map((s, i) => `
        <div class="card sugg">
          <h3>${i + 1}. ${esc(s.species)} <span class="chip planned">${esc(s.activity)}</span></h3>
          <div class="meta">${esc(s.rod || "")}</div>
          <ul>
            ${(s.lures || []).map((l) => `<li><strong>Lure:</strong> ${esc(l)}</li>`).join("")}
            ${s.lines ? `<li><strong>Line:</strong> ${esc(s.lines)}</li>` : ""}
            ${(s.tips || []).map((t) => `<li>${esc(t)}</li>`).join("")}
          </ul>
        </div>`).join("")}
      <div class="card">
        <h3 style="margin-top:0">Conditions</h3>
        <ul style="color:var(--dim);font-size:.9rem;padding-left:20px;margin:6px 0">
          ${p.weather_notes.map((n) => `<li>${esc(n)}</li>`).join("")}
        </ul>
        <div class="meta">Engine: ${esc(p.engine)} · live weather: ${p.weather_live ? "yes" : "no"}</div>
      </div>`;
  } catch (err) {
    box.innerHTML = `<div class="card err">Planning failed: ${esc(err.message)}</div>`;
  }
});

// ---------- weather ----------
let wfGeneration = 0;

async function loadWeather() {
  const slug = $("#wf-water").value;
  const box = $("#weather-result");
  const gen = ++wfGeneration;
  const goBtn = $("#wf-go");
  goBtn.disabled = true;
  box.innerHTML = `<div class="card meta">Fetching NWS + Open-Meteo + USGS…</div>`;
  try {
    const w = await api(`/api/weather/${slug}`);
    if (gen !== wfGeneration) return;  // superseded by a newer request
    $("#wf-meta").textContent = "generated " + fmtTs(w.generated_at);
    const nws = w.nws, om = w.open_meteo, usgs = w.usgs;

    let nwsHtml = "";
    if (nws.error) {
      nwsHtml = `<div class="err">NWS: ${esc(nws.error)}</div>`;
    } else {
      const stale = nws.stale ? ` <span class="stale">(cached ${fmtTs(nws.fetched_at)}, stale)</span>` : "";
      nwsHtml = `
        <div class="card">
          <h3 style="margin-top:0">NWS forecast <span class="meta">(${esc(nws.office)} grid ${esc(nws.grid)},${esc(nws.gridY)})</span>${stale}</h3>
          <div class="meta" style="margin-bottom:8px">${esc(nws.headline || "")}</div>
          ${(nws.periods || []).slice(0, 8).map((p) => `
            <div class="period">
              <span class="nm">${esc(p.name)}<br><span class="meta">${fmtTs(p.startTime)}</span></span>
              <span>${p.temperature}°${esc(p.temperatureUnit)}</span>
              <span class="tx">${esc(p.shortForecast)}</span>
            </div>`).join("")}
        </div>`;
    }

    let omHtml = "";
    if (om.error) {
      omHtml = `<div class="err">Open-Meteo: ${esc(om.error)}</div>`;
    } else {
      const h = om.hourly || {};
      const temps = (h.temperature_2m || []).slice(0, 24);
      const winds = (h.wind_speed_10m || []).slice(0, 24);
      const tMin = Math.min(...temps), tMax = Math.max(...temps);
      const wMax = Math.max(...winds, 0.1);
      omHtml = `
        <div class="card">
          <h3 style="margin-top:0">Hourly (next 24h) <span class="meta">temp °C · wind km/h</span></h3>
          <div class="hourbar">${temps.map((t, i) =>
            `<div class="bar" title="${esc(h.time[i])} ${t}°C wind ${winds[i]} km/h"
              style="height:${Math.round(((t - tMin) / Math.max(tMax - tMin, 0.1)) * 100)}%"></div>`).join("")}</div>
          <div class="hourbar">${winds.map((wd, i) =>
            `<div class="bar wind" title="wind ${wd} km/h"
              style="height:${Math.round((wd / wMax) * 100)}%"></div>`).join("")}</div>
          <div class="meta">range ${tMin}–${tMax} °C · peak wind ${Math.max(...winds)} km/h ·
            precip up to ${Math.max(...(h.precipitation_probability || [0]).slice(0, 24))}%</div>
        </div>`;
    }

    let usgsHtml = "";
    if (usgs === null) {
      usgsHtml = `<div class="card meta">No USGS gauge configured for this water.</div>`;
    } else if (usgs.error) {
      usgsHtml = `<div class="card"><h3 style="margin-top:0">USGS gauge ${esc(usgs.site || "")}</h3><div class="err">${esc(usgs.error)}</div></div>`;
    } else {
      const stale = usgs.stale ? ` <span class="stale">(cached ${fmtTs(usgs.fetched_at)}${usgs.note ? ", " + esc(usgs.note) : ""})</span>` : "";
      usgsHtml = `
        <div class="card">
          <h3 style="margin-top:0">USGS gauge ${esc(usgs.site)} <span class="meta">via ${esc(usgs.source)}</span>${stale}</h3>
          <div>Stage: <strong>${usgs.stage_ft != null ? usgs.stage_ft.toFixed(2) + " ft" : "—"}</strong>
            ${usgs.storage_acft != null ? ` · Storage: <strong>${Math.round(usgs.storage_acft).toLocaleString()} ac-ft</strong>` : ""}
            <span class="meta">as of ${esc(fmtTs(usgs.as_of))}</span></div>
        </div>`;
    }

    box.innerHTML = nwsHtml + omHtml + usgsHtml;
  } catch (err) {
    if (gen !== wfGeneration) return;
    box.innerHTML = `<div class="card err">Weather failed: ${esc(err.message)}</div>`;
  } finally {
    if (gen === wfGeneration) goBtn.disabled = false;
  }
}
$("#wf-go").addEventListener("click", loadWeather);

// ---------- gear ----------
async function loadGear() {
  const g = await api("/api/gear");
  $("#gear-result").innerHTML = `
    <div class="card"><h3>Rods</h3>
      ${g.rods.map((r) => `<div class="catch-row"><span class="cnt">▸</span><span><strong>${esc(r.name)}</strong> + ${esc(r.pairing)} — ${esc(r.role)}</span></div>`).join("")}
    </div>
    <div class="card"><h3>Lures</h3>
      ${g.lures.map((l) => `<div class="catch-row"><span class="cnt">▸</span><span>${esc(l)}</span></div>`).join("")}
    </div>
    <div class="card"><h3>Boats</h3>
      ${g.boats.map((b) => `<div class="catch-row"><span class="cnt">▸</span><span><strong>${esc(b.name)}</strong> (${esc(b.experience)}) — ${esc(b.note)}</span></div>`).join("")}
    </div>`;
}

// ---------- chat (stub) ----------
async function loadChatBadge() {
  const hz = await api("/healthz");
  $("#chat-badge").textContent = hz.chat_enabled ? "enabled" : "disabled (phase 2)";
}

$("#chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#chat-input");
  const msg = input.value.trim();
  if (!msg) return;
  input.value = "";
  const log = $("#chat-log");
  log.insertAdjacentHTML("beforeend", `<div class="msg me">${esc(msg)}</div>`);
  log.scrollTop = log.scrollHeight;
  let reply;
  try {
    const out = await api("/api/chat", { method: "POST", body: JSON.stringify({ message: msg }) });
    reply = `${out.reply}${out.enabled ? "" : "\n(set HERMES_CHAT_ENDPOINT to enable)"}`;
  } catch (err) {
    reply = "Chat error: " + err.message;
  }
  log.insertAdjacentHTML("beforeend", `<div class="msg bot">${esc(reply)}</div>`);
  log.scrollTop = log.scrollHeight;
});

boot().catch((e) => {
  document.body.insertAdjacentHTML("afterbegin",
    `<div style="background:#3a1512;color:#ffb4a8;padding:10px 16px">Boot error: ${esc(e.message)}</div>`);
});
