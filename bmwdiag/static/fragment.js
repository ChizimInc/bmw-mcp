// Fragmentul global al paginii „Sesiuni”: un interval [de, pana] (secunde de la start) ales cu un slider dublu.
// Toate filele (Rezumat, Grafice, Evenimente, Tabel, Erori) respectă intervalul; el stă în hash
// (#<id>/<tab>?de=120&pana=185) și se poate salva cu nume (bmw-data\fragmente\<id>.json). Doar citire pe mașină.
// Se încarcă după sesiuni_date.js și înaintea lui sesiuni.js; folosește funcțiile lor la apel.
"use strict";

const MIN_FRAGMENT_S = 0.5;
let frUi = null; // referințe DOM ale barei pentru sesiunea deschisă
let frTragere = null; // tragerea în curs: {mod, start, ancora, pointerId, schimbat}
let frPending = null; // valoarea de pe tastatură, neconfirmată încă
let frTimerTasta = null;
let frObs = null;

// ---------- hash și stare ----------
function frDinQuery(qs) {
  if (!qs) return null;
  const p = new URLSearchParams(qs);
  if (!p.has("de") || !p.has("pana")) return null;
  const de = Number(p.get("de")), pana = Number(p.get("pana"));
  if (!isFinite(de) || !isFinite(pana) || de < 0 || pana <= de) return null;
  return { de, pana };
}

function hashSesiune(tab) {
  const fr = detaliu.fr;
  return `#${detaliu.id}/${tab}` + (fr ? `?de=${fr.de}&pana=${fr.pana}` : "");
}

// limitele sesiunii: din minigraficul încărcat (primul moment) + durata din rezumat
function limiteSesiune() {
  const m = detaliu.mini, durataS = ((detaliu.date || {}).rezumat || {}).durata_s || 0;
  const t0 = m && m.t.length ? m.t[0] : 0;
  const t1 = durataS > 0 ? t0 + durataS : (m && m.t.length ? m.t[m.t.length - 1] : t0 + 1);
  return [t0, t1];
}

function frNormalizat(x) { // null = toată sesiunea
  const [T0, T1] = limiteSesiune();
  const rot = (v) => Math.round(v * 10) / 10;
  let de = Math.max(T0, Math.min(x.de, x.pana)), pana = Math.min(T1, Math.max(x.de, x.pana));
  if (de <= T0 + 0.05 && pana >= T1 - 0.05) return null;
  de = rot(de); pana = rot(pana);
  if (pana - de < MIN_FRAGMENT_S) { pana = rot(Math.min(T1, de + MIN_FRAGMENT_S)); de = rot(Math.max(0, pana - MIN_FRAGMENT_S)); }
  return { de, pana };
}

function frCurent() {
  const [T0, T1] = limiteSesiune();
  return detaliu.fr || { de: T0, pana: T1 };
}

function seteazaFragment(fr) {
  const vechi = detaliu.fr;
  if ((!fr && !vechi) || (fr && vechi && fr.de === vechi.de && fr.pana === vechi.pana)) { actualizeazaFragment(); return; }
  detaliu.fr = fr;
  detaliu.rezFr = null;
  if (sg && sg.id === detaliu.id) { sg.cache.clear(); sg.x = null; sg.t0 = sg.t1 = null; sg.fereastra = null; }
  history.replaceState(null, "", hashSesiune(tabCurent));
  actualizeazaFragment();
  deseneazaTab(); // bara rămâne (și focusul pe mâner); conținutul filei se refă pe fragment
}

async function frPost(cale, corp) {
  const r = await fetch(cale, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corp || {}) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.eroare || `Eroare ${r.status}`);
  return d;
}

// ---------- bara ----------
function curataFragment() {
  clearTimeout(frTimerTasta);
  frPending = frTragere = null;
  if (frObs) { frObs.disconnect(); frObs = null; }
  frUi = null;
  const b = document.getElementById("bara-fragment");
  if (b) { b.hidden = true; b.innerHTML = ""; }
}

function initFragment() {
  curataFragment();
  const id = detaliu.id, enc = encodeURIComponent(id);
  construiesteBara(document.getElementById("bara-fragment"));
  api(`/api/sesiuni/${enc}/fragmente`).then((r) => r.json()).then((l) => {
    if (detaliu && detaliu.id === id) { detaliu.fragmente = l; desenSalvate(); }
  }).catch(() => { /* fără fragmente salvate */ });
  const col = ["rpm", "viteza", "tmot"].find((c) => colDisponibile(detaliu.date).has(c));
  if (!col) { detaliu.mini = { col: null, t: [], y: [] }; actualizeazaFragment(); return; }
  api(urlDate(id, [col], null, null, 600)).then((r) => r.json()).then((d) => {
    if (!detaliu || detaliu.id !== id) return;
    detaliu.mini = { col, t: d.t, y: d[col] };
    if (detaliu.fr) { // un fragment din link, în afara sesiunii, se aduce în limite
      const n = frNormalizat(detaliu.fr);
      if (!n || n.de !== detaliu.fr.de || n.pana !== detaliu.fr.pana) { seteazaFragment(n); }
    }
    actualizeazaFragment();
    desenMini();
  }).catch(() => { detaliu.mini = { col: null, t: [], y: [] }; actualizeazaFragment(); });
}

function construiesteBara(bara) {
  bara.hidden = false;
  bara.innerHTML = "";
  const ui = {};
  ui.text = el("span", { class: "fr-text", id: "fr-text", role: "status" });
  const btnTot = el("button", { type: "button", id: "fr-tot", text: "Toată sesiunea", onclick: () => seteazaFragment(null) });

  ui.canvas = el("canvas", { class: "fr-mini", "aria-hidden": "true" });
  ui.umbraSt = el("div", { class: "fr-umbra st" });
  ui.umbraDr = el("div", { class: "fr-umbra dr" });
  ui.zona = el("div", { class: "fr-zona" });
  const mane = (capat, text) => el("div", { class: "fr-mane", role: "slider", tabindex: "0", "aria-label": text,
    "aria-orientation": "horizontal", "data-capat": capat, onkeydown: (ev) => tastaMane(ev, capat) });
  ui.mDe = mane("de", "Începutul fragmentului");
  ui.mPana = mane("pana", "Sfârșitul fragmentului");
  ui.pista = el("div", { class: "fr-pista", id: "fr-pista", title: "Trage pe grafic ca să alegi un fragment nou, trage mânerele sau zona ca să o ajustezi; dublu-click = toată sesiunea" },
    ui.canvas, ui.umbraSt, ui.umbraDr, ui.zona, ui.mDe, ui.mPana);
  ui.pista.addEventListener("pointerdown", pornesteTragere);
  ui.pista.addEventListener("pointermove", mutaTragere);
  ui.pista.addEventListener("pointerup", terminaTragere);
  ui.pista.addEventListener("pointercancel", terminaTragere);
  ui.pista.addEventListener("dblclick", () => seteazaFragment(null));
  ui.slider = el("div", { class: "fr-slider" }, ui.pista);

  ui.inDe = el("input", { type: "text", id: "fr-de", size: "8", inputmode: "decimal", "aria-label": "Începutul fragmentului (secunde sau m:ss)",
    onchange: aplicaCampuri, onkeydown: (ev) => { if (ev.key === "Enter") aplicaCampuri(); } });
  ui.inPana = el("input", { type: "text", id: "fr-pana", size: "8", inputmode: "decimal", "aria-label": "Sfârșitul fragmentului (secunde sau m:ss)",
    onchange: aplicaCampuri, onkeydown: (ev) => { if (ev.key === "Enter") aplicaCampuri(); } });

  const ev = (detaliu.date.evenimente || []).filter((e) => typeof e.t_rel_s === "number");
  ui.selEv = el("select", { id: "fr-ev", "aria-label": "Fragment în jurul unui eveniment", onchange: (e) => {
    const i = e.target.value;
    e.target.value = "";
    if (i === "") return;
    const x = ev[Number(i)];
    seteazaFragment(frNormalizat({ de: x.t_rel_s - FEREASTRA_EV_S, pana: x.t_rel_s + FEREASTRA_EV_S }));
  } }, el("option", { value: "", text: `În jurul unui eveniment (±${FEREASTRA_EV_S} s)…` }),
  ev.map((x, i) => el("option", { value: String(i), text: `${minSec(x.t_rel_s)} · ${x.tip}: ${String(x.detalii || "").slice(0, 50)}` })));
  if (!ev.length) ui.selEv.disabled = true;

  ui.nume = el("input", { type: "text", id: "fr-nume", maxlength: "60", placeholder: "nume (ex. Cuplare 2)", "aria-label": "Numele fragmentului de salvat",
    onkeydown: (e) => { if (e.key === "Enter") salveazaFragment(); } });
  ui.btnSalv = el("button", { type: "button", id: "fr-salveaza", text: "Salvează fragmentul", onclick: salveazaFragment });
  ui.mesaj = el("span", { class: "mic", id: "fr-mesaj", role: "status" });
  ui.salvate = el("div", { class: "fr-salvate", id: "fr-salvate" });

  bara.append(
    el("div", { class: "fr-sus" }, el("strong", { text: "Fragment" }), ui.text, btnTot),
    ui.slider,
    el("div", { class: "fr-jos" },
      el("label", {}, "De la", ui.inDe), el("label", {}, "Până la", ui.inPana), ui.selEv,
      el("label", {}, "Nume", ui.nume), ui.btnSalv, ui.mesaj),
    ui.salvate);
  frUi = ui;
  if (window.ResizeObserver) { frObs = new ResizeObserver(() => desenMini()); frObs.observe(ui.pista); }
  actualizeazaFragment();
  desenSalvate();
}

function actualizeazaFragment() {
  if (!frUi || !detaliu) return;
  afiseazaFragment(frCurent());
  desenSalvate();
}

function textDurata(s) {
  return s < 60 ? `${fmtVal(s)} s` : durata(s);
}

function afiseazaFragment(cur) {
  if (!frUi) return;
  const [T0, T1] = limiteSesiune(), w = (T1 - T0) || 1;
  const a = ((cur.de - T0) / w) * 100, b = ((cur.pana - T0) / w) * 100;
  const u = frUi;
  u.zona.style.left = a + "%"; u.zona.style.width = Math.max(0, b - a) + "%";
  u.umbraSt.style.width = a + "%";
  u.umbraDr.style.left = b + "%"; u.umbraDr.style.width = Math.max(0, 100 - b) + "%";
  u.mDe.style.left = a + "%"; u.mPana.style.left = b + "%";
  for (const [m, v, mn, mx] of [[u.mDe, cur.de, T0, cur.pana - MIN_FRAGMENT_S], [u.mPana, cur.pana, cur.de + MIN_FRAGMENT_S, T1]]) {
    m.setAttribute("aria-valuemin", String(+mn.toFixed(1)));
    m.setAttribute("aria-valuemax", String(+mx.toFixed(1)));
    m.setAttribute("aria-valuenow", String(+v.toFixed(1)));
    m.setAttribute("aria-valuetext", fmtRel(v, 1) + " de la start");
  }
  const intreaga = !detaliu.fr && !frTragere && !frPending;
  u.text.textContent = `${intreaga ? "toată sesiunea" : "fragment"}: ${fmtRel(cur.de, 1)} – ${fmtRel(cur.pana, 1)} (${textDurata(cur.pana - cur.de)})`;
  u.slider.classList.toggle("activ", !intreaga);
  document.getElementById("fr-tot").disabled = intreaga;
  u.btnSalv.disabled = !detaliu.fr;
  if (document.activeElement !== u.inDe) u.inDe.value = fmtRel(cur.de, 1);
  if (document.activeElement !== u.inPana) u.inPana.value = fmtRel(cur.pana, 1);
}

function aplicaCampuri() {
  const de = parseTimp(frUi.inDe.value), pana = parseTimp(frUi.inPana.value);
  if (de === null || pana === null || de === pana) { afiseazaFragment(frCurent()); return; }
  seteazaFragment(frNormalizat({ de, pana }));
  afiseazaFragment(frCurent());
}

// ---------- tragere cu mouse / deget ----------
function tDinX(clientX) {
  const r = frUi.pista.getBoundingClientRect(), [T0, T1] = limiteSesiune();
  return T0 + Math.min(1, Math.max(0, (clientX - r.left) / (r.width || 1))) * (T1 - T0);
}

function pornesteTragere(ev) {
  if (!frUi || (ev.pointerType === "mouse" && ev.button !== 0)) return;
  const [T0, T1] = limiteSesiune();
  if (T1 - T0 < 2 * MIN_FRAGMENT_S) return;
  const start = { ...frCurent() }, t = tDinX(ev.clientX);
  let mod;
  if (ev.target === frUi.mDe) mod = "de";
  else if (ev.target === frUi.mPana) mod = "pana";
  else if (detaliu.fr && t >= start.de && t <= start.pana) mod = "mut";
  else mod = "nou";
  frTragere = { mod, start, ancora: mod === "mut" ? t - start.de : t, pointerId: ev.pointerId, schimbat: false, cur: start };
  frUi.pista.setPointerCapture(ev.pointerId);
  frUi.slider.classList.add("trage");
  ev.preventDefault();
}

function mutaTragere(ev) {
  const d = frTragere;
  if (!d || ev.pointerId !== d.pointerId) return;
  const t = tDinX(ev.clientX), [T0, T1] = limiteSesiune(), c = d.start;
  let n;
  if (d.mod === "de") n = { de: Math.min(Math.max(t, T0), c.pana - MIN_FRAGMENT_S), pana: c.pana };
  else if (d.mod === "pana") n = { de: c.de, pana: Math.max(Math.min(t, T1), c.de + MIN_FRAGMENT_S) };
  else if (d.mod === "mut") {
    const lat = c.pana - c.de, de = Math.min(Math.max(t - d.ancora, T0), T1 - lat);
    n = { de, pana: de + lat };
  } else n = { de: Math.min(d.ancora, t), pana: Math.max(d.ancora, t) };
  d.schimbat = true;
  d.cur = n;
  afiseazaFragment(n);
}

function terminaTragere(ev) {
  const d = frTragere;
  if (!d || ev.pointerId !== d.pointerId) return;
  frTragere = null;
  frUi.slider.classList.remove("trage");
  if (ev.type === "pointercancel" || !d.schimbat || d.cur.pana - d.cur.de < MIN_FRAGMENT_S) { afiseazaFragment(frCurent()); return; }
  seteazaFragment(frNormalizat(d.cur));
}

// ---------- tastatură pe mânere ----------
function tastaMane(ev, capat) {
  const [T0, T1] = limiteSesiune();
  const pas = ev.ctrlKey ? 0.1 : ev.shiftKey ? 10 : 1;
  let delta = 0, abs = null;
  if (ev.key === "ArrowLeft" || ev.key === "ArrowDown") delta = -pas;
  else if (ev.key === "ArrowRight" || ev.key === "ArrowUp") delta = pas;
  else if (ev.key === "Home") abs = T0;
  else if (ev.key === "End") abs = T1;
  else return;
  ev.preventDefault();
  const c = frPending || { ...frCurent() };
  const n = { ...c };
  if (capat === "de") n.de = Math.max(T0, Math.min(abs !== null ? abs : c.de + delta, c.pana - MIN_FRAGMENT_S));
  else n.pana = Math.min(T1, Math.max(abs !== null ? abs : c.pana + delta, c.de + MIN_FRAGMENT_S));
  frPending = n;
  afiseazaFragment(n);
  clearTimeout(frTimerTasta);
  frTimerTasta = setTimeout(() => {
    const v = frPending;
    frPending = null;
    if (v) seteazaFragment(frNormalizat(v));
  }, 400);
}

// ---------- minigraficul ----------
function desenMini() {
  if (!frUi || !detaliu) return;
  const cv = frUi.canvas, w = cv.clientWidth, h = cv.clientHeight;
  if (!w || !h) return;
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(w * dpr);
  cv.height = Math.round(h * dpr);
  const ctx = cv.getContext("2d"), c = culori(), [T0, T1] = limiteSesiune(), lat = (T1 - T0) || 1;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  const m = detaliu.mini;
  if (m && m.t.length) {
    const v = m.y.filter((x) => x !== null && x !== undefined);
    if (v.length) {
      let mn = Math.min(...v), mx = Math.max(...v);
      if (mx === mn) { mx = mn + 1; }
      ctx.strokeStyle = c.serii[0]; ctx.lineWidth = 1.2; ctx.beginPath();
      let pus = false;
      m.t.forEach((t, i) => {
        if (m.y[i] === null || m.y[i] === undefined) return;
        const x = ((t - T0) / lat) * w, y = h - 4 - ((m.y[i] - mn) / (mx - mn)) * (h - 12);
        if (pus) ctx.lineTo(x, y); else { ctx.moveTo(x, y); pus = true; }
      });
      ctx.stroke();
    }
  }
  ctx.lineWidth = 1;
  for (const e of detaliu.date.evenimente || []) {
    if (typeof e.t_rel_s !== "number") continue;
    const x = Math.round(((e.t_rel_s - T0) / lat) * w) + 0.5;
    ctx.strokeStyle = c.ev[e.tip] || c.axa; ctx.globalAlpha = 0.7;
    ctx.beginPath(); ctx.moveTo(x, h - 9); ctx.lineTo(x, h); ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

if (window.matchMedia) {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => desenMini());
}

// ---------- fragmente salvate ----------
async function salveazaFragment() {
  const fr = detaliu && detaliu.fr, u = frUi;
  if (!fr || !u) { if (u) u.mesaj.textContent = "Alege întâi un fragment (trage pe grafic)."; return; }
  const nume = u.nume.value.trim() || `Fragment ${minSec(fr.de)}–${minSec(fr.pana)}`;
  const id = detaliu.id;
  try {
    const l = await frPost(`/api/sesiuni/${encodeURIComponent(id)}/fragmente`, { nume, de_la: fr.de, pana_la: fr.pana });
    if (!detaliu || detaliu.id !== id) return;
    detaliu.fragmente = l;
    u.nume.value = "";
    u.mesaj.textContent = `Salvat: „${nume}”.`;
    desenSalvate();
  } catch (e) { u.mesaj.textContent = "Nu pot salva: " + e.message; }
}

async function stergeFragment(f) {
  if (!window.confirm(`Ștergi fragmentul „${f.nume}”? (Datele sesiunii nu se modifică.)`)) return;
  const id = detaliu.id;
  try {
    const l = await frPost(`/api/sesiuni/${encodeURIComponent(id)}/fragmente/${encodeURIComponent(f.id)}/sterge`);
    if (!detaliu || detaliu.id !== id) return;
    detaliu.fragmente = l;
    if (frUi) frUi.mesaj.textContent = `Șters: „${f.nume}”.`;
    desenSalvate();
  } catch (e) { if (frUi) frUi.mesaj.textContent = "Nu pot șterge: " + e.message; }
}

function desenSalvate() {
  if (!frUi || !detaliu) return;
  const z = frUi.salvate, fr = detaliu.fr;
  z.innerHTML = "";
  const l = detaliu.fragmente || [];
  if (!l.length) { z.append(el("span", { class: "mic", text: "Niciun fragment salvat pentru această sesiune." })); return; }
  z.append(el("span", { class: "mic", text: "Fragmente salvate:" }));
  for (const f of l) {
    const activ = !!fr && Math.abs(f.de_la - fr.de) < 0.06 && Math.abs(f.pana_la - fr.pana) < 0.06;
    z.append(el("span", { class: "fr-chip" + (activ ? " activ" : "") },
      el("button", { type: "button", "aria-pressed": String(activ), title: "Aplică acest fragment",
        text: `${f.nume} · ${minSec(f.de_la)}–${minSec(f.pana_la)}`, onclick: () => seteazaFragment(frNormalizat({ de: f.de_la, pana: f.pana_la })) }),
      el("button", { type: "button", class: "fr-sterge", "aria-label": `Șterge fragmentul ${f.nume}`, title: "Șterge", text: "×", onclick: () => stergeFragment(f) })));
  }
}
