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
    try {
      const b = await r.json();
      if (typeof b.detail === "string") detail = b.detail;
      else if (b.nws?.error || b.open_meteo?.error) {
        // 502 weather bundle: surface per-source reasons instead of "Bad Gateway".
        detail = [b.nws?.error && "NWS: " + b.nws.error,
                  b.open_meteo?.error && "Open-Meteo: " + b.open_meteo.error]
                 .filter(Boolean).join("; ") || detail;
      }
    } catch {}
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
    try {
      const id = t.dataset.delcatch;
      const tripId = t.closest(".trip").dataset.trip;
      await api(`/api/catches/${id}`, { method: "DELETE" });
      await renderCatches(tripId);
    } catch (err) { alert("Failed: " + err.message); }
  } else if (t.dataset.deltrip) {
    if (confirm("Delete this trip and all its catches?")) {
      try {
        await api(`/api/trips/${t.dataset.deltrip}`, { method: "DELETE" });
        await loadTrips();
      } catch (err) { alert("Failed: " + err.message); }
    }
  } else if (t.dataset.edittrip) {
    try {
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
    } catch (err) { alert("Failed: " + err.message); }
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
          <h3>${i + 1}. ${esc(s.species)} <span class="chip planned">${esc(s.activity)}</span>${s.winter_focus ? ' <span class="chip planned">winter focus</span>' : ""}</h3>
          <div class="meta">${esc(s.rod || "")}</div>
          <ul>
            ${s.limits ? `<li><strong>Limits:</strong> ${esc(s.limits)}${s.limits_authority ? ` <span class="meta">(${esc(s.limits_authority)})</span>` : ""}</li>` : ""}
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
      </div>
      ${planContextHtml(p)}`;
  } catch (err) {
    box.innerHTML = `<div class="card err">Planning failed: ${esc(err.message)}</div>`;
  }
});

// ---------- plan: dossier-sourced context blocks ----------
function planContextHtml(p) {
  let html = "";
  // Standing reminders (e.g. Loon Lake road-status check) — always visible.
  if (p.reminders && p.reminders.length) {
    html += `<div class="card" style="border-left:4px solid #e0a13c">
      <h3 style="margin-top:0">⚠ Reminders — ${esc(p.date || p.month_name || "")}</h3>
      <ul style="color:var(--dim);font-size:.9rem;padding-left:20px;margin:6px 0">
        ${p.reminders.map((r) => `<li>${esc(r)}</li>`).join("")}
      </ul>
    </div>`;
  }
  if (p.winter_targeting) {
    html += `<div class="card">
      <h3 style="margin-top:0">Winter targeting (Nov–Feb)</h3>
      <div><strong>Focus:</strong> ${esc(p.winter_targeting.focus)}</div>
      <div class="meta" style="margin-top:4px">${esc(p.winter_targeting.why)}</div>
      ${p.winter_targeting.source ? `<div class="meta">${esc(p.winter_targeting.source)}</div>` : ""}
    </div>`;
  }
  if (p.regs) {
    const rows = (p.regs.species || []).map((r) => {
      const lim = [];
      if (r.daily_bag != null) lim.push(`${r.daily_bag}/day`);
      if (r.possession != null) lim.push(`${r.possession} possession`);
      if (r.size_limit) lim.push(r.size_limit);
      if (r.conditions) lim.push(r.conditions);
      return `<tr>
        <td><strong>${esc(r.species)}</strong><div class="meta">${esc(r.season || "")}</div></td>
        <td>${lim.length ? esc(lim.join("; ")) : "—"}</td>
        <td class="meta">${esc(r.authority || "")}</td>
      </tr>`;
    }).join("");
    html += `<div class="card">
      <h3 style="margin-top:0">Regulations ${p.regs.zone ? `— ${esc(p.regs.zone)}` : ""}</h3>
      <table style="width:100%;border-collapse:collapse;font-size:.9rem">
        <tr><th style="text-align:left">Species</th><th style="text-align:left">Limits</th><th style="text-align:left">Authority</th></tr>
        ${rows}
      </table>
      ${p.regs.special_regs ? `<div class="meta" style="margin-top:6px">${esc(p.regs.special_regs)}</div>` : ""}
      ${p.regs.health_advisory ? `<div class="meta" style="margin-top:4px">Health advisory: ${esc(p.regs.health_advisory)}</div>` : ""}
      <div class="meta" style="margin-top:4px">Source: ${esc(p.regs.booklet || "")}</div>
    </div>`;
  }
  if (p.stocking) {
    const progs = (p.stocking.programs || []).map((pg) =>
      `<li><strong>${esc(pg.program)}:</strong> ${esc(pg.detail)} <span class="meta">(${esc(pg.source || "")})</span></li>`).join("");
    html += `<div class="card">
      <h3 style="margin-top:0">Stocking</h3>
      ${progs ? `<ul style="color:var(--dim);font-size:.9rem;padding-left:20px;margin:6px 0">${progs}</ul>` : ""}
      <div class="meta" style="margin-top:4px">${esc(p.stocking.advice || "")}${p.stocking.source ? ` <span class="meta">(${esc(p.stocking.source)})</span>` : ""}</div>
    </div>`;
  }
  if (p.water_context && p.water_context.length) {
    html += `<div class="card">
      <h3 style="margin-top:0">Water conditions (static context)</h3>
      <ul style="color:var(--dim);font-size:.9rem;padding-left:20px;margin:6px 0">
        ${p.water_context.map((f) => `<li>${esc(f.fact)} <span class="meta">(as of ${esc(f.as_of)} — ${esc(f.source)})</span></li>`).join("")}
      </ul>
    </div>`;
  }
  return html;
}

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
      const stale = nws.stale ? ` <span class="stale">(cached ${fmtTs(nws.fetched_at) || "?"}, stale)</span>` : "";
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
      const omStale = om.stale ? ` <span class="stale">(cached ${fmtTs(om.fetched_at) || "?"}, stale)</span>` : "";
      omHtml = `
        <div class="card">
          <h3 style="margin-top:0">Hourly (next 24h) <span class="meta">temp °C · wind km/h</span>${omStale}</h3>
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
      usgsHtml = `<div class="card"><h3 style="margin-top:0">USGS gauges</h3><div class="err">${esc(usgs.error)}</div></div>`;
    } else if (!(usgs.gauges || []).length) {
      usgsHtml = `<div class="card meta">${esc(usgs.note || "No USGS gauge configured for this water.")}</div>`;
    } else {
      const gs = usgs.gauges;
      usgsHtml = `<div class="card">
        <h3 style="margin-top:0">USGS gauges <span class="meta">fetched ${esc(fmtTs(usgs.fetched_at))}</span></h3>
        ${gs.map((g) => {
          const badge = g.status && g.status !== "live" ? ` <span class="stale">[${esc(g.status)}]</span>` : "";
          const val = g.value != null
            ? `<strong>${Number(g.value).toLocaleString()} ${esc(g.unit || "")}</strong>`
            : "<strong>—</strong>";
          return `<div style="margin:8px 0;padding-bottom:8px;border-bottom:1px solid rgba(255,255,255,.08)">
            <div><strong>${esc(g.label || g.site)}</strong> <span class="meta">USGS ${esc(g.site)} · ${esc(g.parameter || "")}${badge}</span></div>
            <div>${val} <span class="meta">as of ${esc(fmtTs(g.as_of))} · via ${esc(g.source || "?")}</span></div>
            ${g.spec_note ? `<div class="meta">${esc(g.spec_note)}</div>` : ""}
            ${g.note ? `<div class="meta" style="color:#e0a13c">${esc(g.note)}</div>` : ""}
          </div>`;
        }).join("")}
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
      ${g.rods.map((r) => `<div class="catch-row"><span class="cnt">▸</span><span><strong>${esc(r.name)}</strong> — ${esc(r.use)}</span></div>`).join("")}
    </div>
    <div class="card"><h3>Reels</h3>
      ${g.reels.map((r) => `<div class="catch-row"><span class="cnt">▸</span><span><strong>${esc(r.name)}</strong> + ${esc(r.pairing)} — ${esc(r.line)}</span></div>`).join("")}
    </div>
    <div class="card"><h3>Lures</h3>
      ${g.lures.map((l) => `<div class="catch-row"><span class="cnt">▸</span><span>${esc(l)}</span></div>`).join("")}
    </div>
    <div class="card"><h3>Extras</h3>
      ${g.extras.map((l) => `<div class="catch-row"><span class="cnt">▸</span><span>${esc(l)}</span></div>`).join("")}
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
