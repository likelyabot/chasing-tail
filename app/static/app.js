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
    if (btn.dataset.tab === "community") loadCommunity();
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

// Clock part of a local ISO datetime ("2026-11-25T06:42" -> "06:42").
// Open-Meteo sunrise/sunset are already local (timezone param) — slicing
// avoids Date-parsing TZ assumptions. Returns "" for anything unexpected.
function fmtClockLocal(iso) {
  if (typeof iso !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(iso)) return "";
  return iso.slice(11, 16);
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
      <details class="plan">
        <summary>Plan — in season + regs</summary>
        <div class="plan-body" data-planbody="${t.id}" data-water="${esc(t.water_slug || "")}" data-date="${esc(t.date || "")}"></div>
      </details>
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
      purgePlanCache(trip.id);  // water/date may have changed — stale plan is useless
      await loadTrips();
    } catch (err) { alert("Failed: " + err.message); }
  } else if (t.dataset.planretry) {
    const body = t.closest("details.plan")?.querySelector(".plan-body");
    if (body) loadPlanFor(body);
  }
});

// ---------- trip plan panel (lazy "in season + regs" per card) ----------
// Offline-by-design: live_weather=false (future-dated trips have no forecast;
// the Plan tab remains the live-snapshot surface). Plans are fetched only on
// first expand of a card, never in bulk on page load. The cache key includes
// water_slug + date, so an edited trip misses the cache and refetches; the
// edit handler also purges the trip's entries explicitly.
const PLAN_CACHE = new Map();

function planKey(tripId, waterSlug, dateStr) {
  return `${tripId}|${waterSlug}|${dateStr}`;
}

function purgePlanCache(tripId) {
  for (const k of PLAN_CACHE.keys()) {
    if (k.startsWith(tripId + "|")) PLAN_CACHE.delete(k);
  }
}

function renderPlanBody(body, p) {
  const top3 = (p.suggestions || []).slice(0, 3);
  const top = top3[0];
  let html = "";
  if (top3.length) {
    html += `<div class="plan-picks">${top3.map((s, i) =>
      `${i + 1}. <strong>${esc(s.species)}</strong> <span class="meta">(${esc(s.activity)}, score ${s.score})</span>`
    ).join("<br>")}</div>`;
  }
  if (top && top.limits) {
    html += `<div class="plan-reg"><strong>Regs — ${esc(top.species)}:</strong> ${esc(top.limits)}${
      top.limits_authority ? ` <span class="meta">(${esc(top.limits_authority)})</span>` : ""}</div>`;
  }
  const special = (p.regs || {}).special_regs;
  if (special) html += `<div class="plan-reg"><strong>Special:</strong> ${esc(special)}</div>`;
  if (p.winter_targeting) {
    html += `<div class="plan-winter">❄ <strong>Winter focus:</strong> ${esc(p.winter_targeting.focus)} ` +
      `<span class="meta">— ${esc(p.winter_targeting.why)}</span></div>`;
  }
  if (p.stocking) {
    const prog = (p.stocking.programs || [])[0];
    const bits = [];
    if (prog) bits.push(`<strong>${esc(prog.program)}:</strong> ${esc(prog.detail)}`);
    if (p.stocking.advice) bits.push(esc(p.stocking.advice));
    if (bits.length) html += `<div class="plan-stock">🐟 <strong>Stocking:</strong> ${bits.join(" ")}</div>`;
  }
  if (p.kayak) {
    html += `<div class="plan-kayak"><span class="kbadge ${esc(p.kayak.level)}" ` +
      `title="${esc(p.kayak.reason)}">${esc(p.kayak.flag)}</span></div>`;
  }
  if (!html) html = `<div class="meta">No plan data for this water.</div>`;
  body.innerHTML = html;
  body.dataset.state = "done";
}

async function loadPlanFor(body) {
  const key = planKey(body.dataset.planbody, body.dataset.water, body.dataset.date);
  const cached = PLAN_CACHE.get(key);
  if (cached) { renderPlanBody(body, cached); return; }
  body.dataset.state = "loading";
  body.innerHTML = `<div class="meta">Building plan…</div>`;
  try {
    const q = new URLSearchParams({
      water_slug: body.dataset.water,
      date: body.dataset.date,
      live_weather: "false",
    });
    const p = await api("/api/recommend?" + q.toString());
    PLAN_CACHE.set(key, p);
    renderPlanBody(body, p);
  } catch (err) {
    body.dataset.state = "error";
    body.innerHTML = `<div class="err">Plan failed: ${esc(err.message)} ` +
      `<button class="ghost" data-planretry="${body.dataset.planbody}" style="margin-left:8px">Retry</button></div>`;
  }
}

$("#trip-list").addEventListener("toggle", (e) => {
  const det = e.target instanceof Element ? e.target.closest("details.plan") : null;
  if (!det || !det.open) return;
  const body = det.querySelector(".plan-body");
  if (!body || body.dataset.state === "loading" || body.dataset.state === "done") return;
  if (!body.dataset.water) {
    body.dataset.state = "error";
    body.innerHTML = `<div class="err">No water on this trip — set a water to get a plan.</div>`;
    return;
  }
  loadPlanFor(body);
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
      const d = om.daily || {};
      // Sunrise/sunset arrive as LOCAL ISO strings (timezone=America/Los_Angeles)
      // — slice the clock part directly; no Date parsing, no TZ assumptions.
      // Missing fields degrade to a hidden line, never "undefined".
      const sunUp = fmtClockLocal(Array.isArray(d.sunrise) ? d.sunrise[0] : null);
      const sunDown = fmtClockLocal(Array.isArray(d.sunset) ? d.sunset[0] : null);
      const sunBits = [];
      if (sunUp) sunBits.push(`☀️ Sunrise ${sunUp}`);
      if (sunDown) sunBits.push(`🌇 Sunset ${sunDown}`);
      const sunLine = sunBits.length ? `<div class="sunline">${sunBits.join(" · ")}</div>` : "";
      // Lunar line: computed server-side (pure local calc, no external API),
      // same date basis as the rest of the bundle. Renders for every water;
      // missing/invalid fields degrade to a hidden line, never "undefined".
      const PHASE_EMOJI = {
        "new moon": "🌑", "waxing crescent": "🌒", "first quarter": "🌓",
        "waxing gibbous": "🌔", "full moon": "🌕", "waning gibbous": "🌖",
        "last quarter": "🌗", "waning crescent": "🌘",
      };
      const ln = (w && typeof w.lunar === "object" && w.lunar) ? w.lunar : null;
      const lunarBits = [];
      if (ln && PHASE_EMOJI[ln.phase] && Number.isFinite(ln.illumination_pct)) {
        const pct = Math.max(0, Math.min(100, Math.round(ln.illumination_pct)));
        const pretty = ln.phase.split(" ").map((x) => x.charAt(0).toUpperCase() + x.slice(1)).join(" ");
        lunarBits.push(`${PHASE_EMOJI[ln.phase]} ${pretty} · ${pct}% lit`);
        if (Number.isInteger(ln.next_full_moon_in_days)) {
          lunarBits.push(ln.next_full_moon_in_days === 0 ? "full tonight" : `full in ${ln.next_full_moon_in_days}d`);
        }
        if (Number.isInteger(ln.next_new_moon_in_days)) {
          lunarBits.push(ln.next_new_moon_in_days === 0 ? "new tonight" : `new in ${ln.next_new_moon_in_days}d`);
        }
      }
      const lunarLine = lunarBits.length ? `<div class="sunline">${lunarBits.join(" · ")}</div>` : "";
      omHtml = `
        <div class="card">
          <h3 style="margin-top:0">Hourly (next 24h) <span class="meta">temp °F · wind mph</span>${omStale}</h3>
          ${sunLine}
          ${lunarLine}
          <div class="hourbar">${temps.map((t, i) =>
            `<div class="bar" title="${esc(h.time[i])} ${t}°F wind ${winds[i]} mph"
              style="height:${Math.round(((t - tMin) / Math.max(tMax - tMin, 0.1)) * 100)}%"></div>`).join("")}</div>
          <div class="hourbar">${winds.map((wd, i) =>
            `<div class="bar wind" title="wind ${wd} mph"
              style="height:${Math.round((wd / wMax) * 100)}%"></div>`).join("")}</div>
          <div class="meta">range ${tMin}–${tMax} °F · peak wind ${Math.max(...winds)} mph ·
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
let gearEditing = false;
let gearMsgTimer = null;

async function loadGear() {
  if (gearEditing) return;  // don't clobber unsaved edits when switching tabs
  try {
    renderGearView(await api("/api/gear"));
  } catch (err) {
    gearShowError("Could not load gear: " + err.message);
  }
}

// Shape guard: the backend guarantees this (get_gear falls back to static
// defaults on corrupt rows; PUT echoes the validated payload), but the view
// must never blank the tab on bad input — surface the error instead.
function isGearPayload(g) {
  return !!g && typeof g === "object" &&
    ["rods", "reels", "lures", "extras"].every((k) => Array.isArray(g[k]));
}

function renderGearView(g) {
  if (!isGearPayload(g)) {
    gearShowError("Unexpected gear data — please refresh.");
    return;  // leave whatever is currently rendered in place
  }
  gearEditing = false;
  const editBtn = $("#gear-edit");
  editBtn.hidden = false;
  editBtn.disabled = false;
  $("#gear-editor").setAttribute("hidden", "");
  // renderGearEditor hid #gear-result when entering edit mode; it must be
  // un-hidden here or the tab stays blank after Save/Cancel/Reset (the
  // reported blank-page bug — the list was rendered into a hidden container).
  $("#gear-result").removeAttribute("hidden");
  $("#gear-result").innerHTML = `
    <div class="card"><h3>Rods</h3>
      ${g.rods.map((r) => `<div class="catch-row"><span class="cnt">▸</span><span><strong>${esc(r.name)}</strong> — ${esc(r.use)}</span></div>`).join("") || `<div class="meta">None listed.</div>`}
    </div>
    <div class="card"><h3>Reels</h3>
      ${g.reels.map((r) => `<div class="catch-row"><span class="cnt">▸</span><span><strong>${esc(r.name)}</strong> + ${esc(r.pairing)} — ${esc(r.line)}</span></div>`).join("") || `<div class="meta">None listed.</div>`}
    </div>
    <div class="card"><h3>Lures</h3>
      ${g.lures.map((l) => `<div class="catch-row"><span class="cnt">▸</span><span>${esc(l)}</span></div>`).join("") || `<div class="meta">None listed.</div>`}
    </div>
    <div class="card"><h3>Extras</h3>
      ${g.extras.map((l) => `<div class="catch-row"><span class="cnt">▸</span><span>${esc(l)}</span></div>`).join("") || `<div class="meta">None listed.</div>`}
    </div>`;
}

function gearFlash(msg) {
  $("#gear-msg").textContent = msg;
  clearTimeout(gearMsgTimer);
  gearMsgTimer = setTimeout(() => ($("#gear-msg").textContent = ""), 2500);
}

const rodRowHtml = (r) => `<div class="gear-row">
  <input data-f="name" maxlength="100" placeholder="rod name" value="${esc(r.name)}">
  <input data-f="use" maxlength="200" placeholder="used for…" value="${esc(r.use)}">
  <button class="danger" data-delrow="rods" style="padding:4px 10px">✕</button>
</div>`;
const reelRowHtml = (r) => `<div class="gear-row">
  <input data-f="name" maxlength="100" placeholder="reel name" value="${esc(r.name)}">
  <input data-f="pairing" maxlength="100" placeholder="pairs with" value="${esc(r.pairing)}">
  <input data-f="line" maxlength="200" placeholder="line" value="${esc(r.line)}">
  <button class="danger" data-delrow="reels" style="padding:4px 10px">✕</button>
</div>`;

function renderGearEditor(g) {
  gearEditing = true;
  $("#gear-edit").hidden = true;
  $("#gear-result").setAttribute("hidden", "");
  const ed = $("#gear-editor");
  ed.removeAttribute("hidden");
  ed.innerHTML = `
    <div class="card"><h3>Rods</h3>
      <div id="gear-rods">${g.rods.map(rodRowHtml).join("")}</div>
      <button class="ghost" data-addrow="rods" style="margin-top:8px">+ add rod</button>
    </div>
    <div class="card"><h3>Reels</h3>
      <div id="gear-reels">${g.reels.map(reelRowHtml).join("")}</div>
      <button class="ghost" data-addrow="reels" style="margin-top:8px">+ add reel</button>
    </div>
    <div class="card"><h3>Lures <span class="meta">one per line</span></h3>
      <textarea id="gear-lures" rows="6">${esc(g.lures.join("\n"))}</textarea>
    </div>
    <div class="card"><h3>Extras <span class="meta">one per line</span></h3>
      <textarea id="gear-extras" rows="3">${esc(g.extras.join("\n"))}</textarea>
    </div>
    <div id="gear-error" class="err" hidden></div>
    <div class="card gear-actions">
      <button id="gear-save">Save</button>
      <button id="gear-cancel" class="ghost">Cancel</button>
      <button id="gear-reset" class="danger">Reset to defaults</button>
      <span class="spacer"></span>
      <span class="meta">Saves replace the whole list.</span>
    </div>`;
  ed.onclick = (e) => {
    const t = e.target.closest("button");
    if (!t) return;
    if (t.dataset.addrow === "rods") $("#gear-rods").insertAdjacentHTML("beforeend", rodRowHtml({ name: "", use: "" }));
    else if (t.dataset.addrow === "reels") $("#gear-reels").insertAdjacentHTML("beforeend", reelRowHtml({ name: "", pairing: "", line: "" }));
    else if (t.dataset.delrow) t.closest(".gear-row").remove();
  };
  $("#gear-save").onclick = saveGear;
  $("#gear-cancel").onclick = cancelGear;
  $("#gear-reset").onclick = resetGear;
}

function collectGear() {
  const pick = (row, f) => row.querySelector(`[data-f="${f}"]`).value.trim();
  return {
    rods: $$("#gear-rods .gear-row").map((r) => ({ name: pick(r, "name"), use: pick(r, "use") })),
    reels: $$("#gear-reels .gear-row").map((r) => ({
      name: pick(r, "name"), pairing: pick(r, "pairing"), line: pick(r, "line"),
    })),
    lures: $("#gear-lures").value.split("\n").map((s) => s.trim()).filter(Boolean),
    extras: $("#gear-extras").value.split("\n").map((s) => s.trim()).filter(Boolean),
  };
}

function gearShowError(msg) {
  const el = $("#gear-error");
  if (el) {
    el.textContent = msg;
    el.hidden = false;
  } else {
    gearFlash(msg);  // editor not mounted (e.g. GET failed) — use the toolbar slot
  }
}

async function saveGear() {
  try {
    const saved = await gearApi("PUT");
    renderGearView(saved);
    gearFlash("Saved");
  } catch (err) {
    gearShowError("Save failed: " + err.message);
  }
}

async function cancelGear() {
  try {
    renderGearView(await api("/api/gear"));
  } catch (err) {
    gearShowError("Cancel failed: " + err.message);
  }
}

async function resetGear() {
  if (!confirm("Reset gear to the repo defaults? Your edits will be lost.")) return;
  try {
    await gearApi("DELETE");
    renderGearView(await api("/api/gear"));
    gearFlash("Reset to defaults");
  } catch (err) {
    gearShowError("Reset failed: " + err.message);
  }
}

// PUT/DELETE with readable 422 detail (field + message) instead of bare status text.
async function gearApi(method) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (method === "PUT") opts.body = JSON.stringify(collectGear());
  const res = await fetch("/api/gear", opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      const errs = (Array.isArray(j.detail) ? j.detail : []).map(
        (e) => `${e.msg || ""}${e.loc ? " [" + e.loc.slice(-2).join(".") + "]" : ""}`);
      if (errs.length) detail = errs.join("; ");
    } catch (_) { /* non-JSON error body — keep statusText */ }
    throw new Error(detail);
  }
  // 2xx handling: DELETE is 204 (null); PUT echoes the saved payload. If a
  // 2xx ever arrives with an empty/non-JSON body, refetch instead of letting
  // res.json() throw — callers must always receive a renderable payload.
  if (res.status === 204) return null;
  try {
    return await res.json();
  } catch (_) {
    if (method === "PUT") {
      const r2 = await fetch("/api/gear");
      if (!r2.ok) throw new Error("saved, but refetch failed: " + r2.statusText);
      return r2.json();
    }
    throw new Error("empty response from server");
  }
}

$("#gear-edit").addEventListener("click", async () => {
  if (gearEditing) return;
  try {
    renderGearEditor(await api("/api/gear"));
  } catch (err) {
    gearShowError("Could not load gear: " + err.message);
  }
});

// ---------- community (FishBrain imports + Reddit feed) ----------
let cmWater = "";
let cmDays = 7;
let cmGen = 0;

// Chip labels for water slugs (shorter than the full WATERS names).
const CM_WATER_NAMES = {
  "collins-lake": "Collins Lake",
  "new-bullards-bar": "New Bullards Bar",
  "loon-lake": "Loon Lake",
  "sacramento-river-westport": "Sacramento River",
};

$("#cm-filter").addEventListener("click", (e) => {
  const t = e.target.closest("button");
  if (!t) return;
  if (t.classList.contains("cm-water")) {
    cmWater = t.dataset.water;
    $$("#cm-filter .cm-water").forEach((b) => b.classList.toggle("active", b === t));
  } else if (t.classList.contains("cm-days")) {
    cmDays = parseInt(t.dataset.days, 10);
    $$("#cm-filter .cm-days").forEach((b) => b.classList.toggle("active", b === t));
  } else {
    return;
  }
  loadCommunity();
});

function cmWaterLabel(slug) {
  if (!slug) return "Other";
  return CM_WATER_NAMES[slug] || slug;
}

async function loadCommunity() {
  const gen = ++cmGen;
  const q = new URLSearchParams();
  if (cmWater) q.set("water_slug", cmWater);
  q.set("days", String(cmDays));
  const fbBox = $("#cm-fb-rows");
  const rdBox = $("#cm-rd-posts");
  fbBox.innerHTML = `<div class="meta">Loading…</div>`;
  rdBox.innerHTML = `<div class="meta">Loading…</div>`;
  try {
    const d = await api("/api/community?" + q.toString());
    if (gen !== cmGen) return;  // superseded by a newer filter click
    renderFbSection(d.fishbrain || {});
    renderRdSection(d.reddit || {});
  } catch (err) {
    if (gen !== cmGen) return;
    fbBox.innerHTML = `<div class="err">Community failed: ${esc(err.message)}</div>`;
    rdBox.innerHTML = "";
  }
}

function renderFbSection(fb) {
  // Import batch list with per-batch Undo.
  const batches = fb.batches || [];
  $("#cm-fb-batches").innerHTML = batches.length
    ? batches.map((b) => `
      <div class="cm-batch">
        <span class="meta">batch ${esc(b.batch_id)} · ${b.row_count} rows · ${esc(fmtTs(b.imported_at))}${b.source_label ? " · " + esc(b.source_label) : ""}</span>
        <button class="danger" data-undobat="${esc(b.batch_id)}" style="padding:3px 10px">Undo</button>
      </div>`).join("")
    : "";

  const rows = fb.rows || [];
  $("#cm-fb-rows").innerHTML = rows.length
    ? rows.map((r) => `
      <div class="cm-entry">
        <div><strong>${esc(r.species || "(unknown species)")}</strong>
          <span class="chip">${esc(cmWaterLabel(r.water))}</span></div>
        <div class="meta">${r.date ? esc(r.date) : "undated"}${r.weight_lb != null ? ` · ${r.weight_lb} lb` : ""}${r.length_in != null ? ` · ${r.length_in} in` : ""}${r.location ? ` · ${esc(r.location)}` : ""}</div>
        ${r.notes ? `<div class="meta">${esc(r.notes)}</div>` : ""}
        ${r.photo_url ? `<div class="meta">📷 <a href="${esc(r.photo_url)}" target="_blank" rel="noopener noreferrer">photo</a></div>` : ""}
      </div>`).join("")
    : `<div class="meta">No imports yet — paste a FishBrain export.</div>`;
}

function renderRdSection(rd) {
  const badge = $("#cm-rd-badge");
  const subs = (rd.subs || []).map((s) => "r/" + s).join(", ");
  $("#cm-rd-subs").textContent = subs ? "(" + subs + ")" : "";
  const box = $("#cm-rd-posts");
  if (!rd.enabled) {
    badge.textContent = "disabled";
    box.innerHTML = `<div class="meta cm-muted">${esc(rd.notice || "Reddit feed: configure REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET in Portainer to enable.")}</div>`;
    return;
  }
  badge.textContent = rd.stale ? "stale" : "live";
  let html = "";
  if (rd.stale) {
    html += `<div class="stale">Feed stale (last fetched ${esc(fmtTs(rd.fetched_at)) || "?"}) — Reddit unreachable.${rd.error ? ` ${esc(rd.error)}` : ""}</div>`;
  }
  const posts = rd.posts || [];
  html += posts.length
    ? posts.map((p) => `
      <a class="cm-entry cm-link" href="${esc(p.permalink)}" target="_blank" rel="noopener noreferrer">
        <div><strong>${esc(p.title)}</strong>
          <span class="chip">r/${esc(p.sub)}</span>
          <span class="chip">${esc(cmWaterLabel(p.matched_water))}</span></div>
        <div class="meta">u/${esc(p.author)} · ${esc(fmtTs(p.created_utc))}</div>
        ${p.selftext_excerpt ? `<div class="meta">${esc(p.selftext_excerpt)}</div>` : ""}
      </a>`).join("")
    : `<div class="meta">No posts in this window.</div>`;
  box.innerHTML = html;
}

$("#cm-fb-import-btn").addEventListener("click", async () => {
  const ta = $("#cm-fb-text");
  const text = ta.value.trim();
  const sum = $("#cm-fb-summary");
  if (!text) { sum.textContent = "Nothing to import."; return; }
  const btn = $("#cm-fb-import-btn");
  btn.disabled = true;
  sum.textContent = "Importing…";
  try {
    const r = await fetch("/api/community/fishbrain/import", {
      method: "POST",
      headers: { "Content-Type": "text/plain" },
      body: text,
    });
    let body = null;
    try { body = await r.json(); } catch { /* non-JSON error body */ }
    if (!r.ok) {
      let detail = r.statusText;
      if (body && typeof body.detail === "string") detail = body.detail;
      throw new Error(detail);
    }
    ta.value = "";
    sum.textContent = `Imported ${body.imported}, skipped ${body.skipped} (batch ${body.batch_id})`;
    await loadCommunity();
  } catch (err) {
    sum.textContent = "Import failed: " + err.message;
  } finally {
    btn.disabled = false;
  }
});

$("#cm-fb-batches").addEventListener("click", async (e) => {
  const t = e.target.closest("[data-undobat]");
  if (!t) return;
  if (!confirm("Remove this import batch?")) return;
  try {
    await api(`/api/community/fishbrain/import/${encodeURIComponent(t.dataset.undobat)}`, { method: "DELETE" });
    $("#cm-fb-summary").textContent = "Batch removed.";
    await loadCommunity();
  } catch (err) {
    alert("Failed: " + err.message);
  }
});

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
