// Pagina „Comparare”: două sesiuni (de regulă rece și cald), aliniate la un eveniment ales din fiecare.
// Doar citire: folosește /api/sesiuni, /api/sesiuni/<id> și /api/sesiuni/<id>/date. Starea e în hash.
"use strict";

const $ = (id) => document.getElementById(id);
const MARIMI = ["rpm", "sarcina", "cuplu", "clapeta", "pedala", "tmot", "viteza", "maf", "avans", "sarcina_tinta", "rpm_tinta"];
const MARIMI_IMPLICIT = ["rpm", "sarcina"];
const COL_TABEL = ["rpm", "sarcina", "cuplu", "clapeta"]; // cădere / înainte / minim / după
const DT_INAINTE = 3, DT_DUPA = 3, TOL = 1.5; // înainte = t−3 s, după = t+3 s, minim în [t−3, t+3]
const CHEIE_SYNC = "comparare";
const CAT_TOATE = "toate";

let dict = { coloane: {}, steaguri: {}, unitati: {} };
let lista = [];
const cache = new Map(); // id → {detaliu, date, ms}
let st = null;           // starea curentă (vezi citesteHash)
let ses = { a: null, b: null }; // sesiunile încărcate: {id, info, evenimente, t, v, disp}
let grafice = [];
let jeton = 0;

// ---------- ajutoare ----------
function el(tag, atribute, ...copii) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(atribute || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of copii.flat()) {
    if (c === null || c === undefined || c === false) continue;
    e.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return e;
}

async function api(cale) {
  const r = await fetch(cale);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.eroare || `Eroare ${r.status}`);
  }
  return r.json();
}

function eroarePagina(t) { const p = $("eroare-pagina"); p.textContent = t || ""; p.hidden = !t; }
function eticheta(a) { const d = dict.coloane[a]; return d && d.eticheta ? d.eticheta : a; }
function unitateCol(a, coloane) {
  const d = dict.coloane[a];
  if (d && d.unitate_afisata) return d.unitate_afisata;
  const u = ((coloane || {})[a] || {}).unitate;
  const brut = u === null || u === undefined ? "" : String(u).trim();
  return dict.unitati[brut] || brut;
}
function pad2(n) { return String(n).padStart(2, "0"); }
function fmtVal(v) {
  if (v === null || v === undefined || !isFinite(v)) return "–";
  if (Math.abs(v) < 1e-9) return "0"; // zgomot de virgulă mobilă
  return String(+Number(v).toPrecision(5)).replace(".", ",");
}
function fmtSemn(v) { // cu semn explicit, pentru diferențe
  if (v === null || v === undefined || !isFinite(v)) return "–";
  const s = fmtVal(Math.abs(v));
  return Math.abs(v) < 1e-9 ? "0" : (v > 0 ? "+" : "−") + s;
}
function fmtRel(sec) {
  const s = Math.max(0, sec), m = Math.floor(s / 60), r = s % 60;
  return `${m}:${r.toFixed(1).padStart(4, "0")}`.replace(".", ",");
}
function oraScurta(iso) { const m = /[T ](\d{2}):(\d{2})/.exec(iso || ""); return m ? `${m[1]}:${m[2]}` : "?"; }
function dataRo(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(iso || "");
  return m ? `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}` : "–";
}
function numeSteag(n) { return dict.steaguri[n] || n; }

function culori() {
  const cs = getComputedStyle(document.documentElement);
  const g = (n) => cs.getPropertyValue(n).trim() || "#888";
  return { a: g("--serie-1"), b: g("--serie-2"), axa: g("--slab"), grila: g("--linie"), accent: g("--accent"), text: g("--text") };
}

// ---------- evenimente ----------
function categorie(e) { // cheia de grupare a unui eveniment (sau null dacă nu se compară)
  if (e.tip === "steag") return "steag:" + String(e.detalii).split(":")[0].trim();
  if (e.tip === "marcaj") return "marcaj:" + String(e.detalii).trim();
  if (e.tip === "eroare") return "eroare";
  return null;
}
function numeCategorie(c) {
  if (c === CAT_TOATE) return "Toate (steaguri, marcaje, erori)";
  if (c.startsWith("steag:")) return "Steag: " + numeSteag(c.slice(6));
  if (c.startsWith("marcaj:")) return "Marcaj: " + c.slice(7);
  return c === "eroare" ? "Erori noi" : c;
}
function evenimenteDin(s, cat) {
  return s.evenimente.filter((e) => { const c = categorie(e); return c && (cat === CAT_TOATE || c === cat); });
}
function textEv(e) {
  const t = fmtRel(e.t_rel_s);
  if (e.tip === "steag") return `${t} · ${String(e.detalii).split(":")[0]}`;
  return `${t} · ${e.tip}: ${String(e.detalii).slice(0, 50)}`;
}
function etichetaSes(s, litera) {
  return `${litera}: ${s.info.conditie || "necunoscut"} ${oraScurta(s.info.start)}`;
}

// ---------- încărcare ----------
async function incarcaSesiune(id) {
  if (cache.has(id)) return cache.get(id);
  const t0 = performance.now();
  const det = await api(`/api/sesiuni/${encodeURIComponent(id)}`);
  const disp = new Set(Object.keys((det.rezumat || {}).coloane || {}));
  const cols = MARIMI.filter((c) => disp.has(c));
  const d = cols.length ? await api(`/api/sesiuni/${encodeURIComponent(id)}/date?coloane=${cols.join(",")}`) : { t: [] };
  const info = lista.find((x) => x.id === id) || { id, start: (det.sesiune || {}).start, conditie: (det.sesiune || {}).conditie };
  const rez = { id, info, evenimente: (det.evenimente || []).filter((e) => typeof e.t_rel_s === "number"),
    t: d.t || [], v: d, disp: cols, coloane: det.coloane || {}, ms: performance.now() - t0 };
  cache.set(id, rez);
  return rez;
}

// ---------- calcule ----------
function indice(t, x) { // primul index cu t[i] >= x
  let lo = 0, hi = t.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (t[m] < x) lo = m + 1; else hi = m; }
  return lo;
}
function valoareLa(t, v, tc, tol) { // valoarea nenulă cea mai apropiată de tc, în ±tol secunde
  const lo = indice(t, tc);
  let cel = null, dist = tol + 1e-9;
  for (let k = lo - 1; k >= 0 && tc - t[k] <= tol; k--) if (v[k] !== null && v[k] !== undefined) { cel = v[k]; dist = tc - t[k]; break; }
  for (let k = lo; k < t.length && t[k] - tc <= tol; k++) {
    if (v[k] !== null && v[k] !== undefined) { if (t[k] - tc < dist) cel = v[k]; break; }
  }
  return cel;
}
function masoara(s, col, te) {
  const v = s.v[col];
  if (!v) return null;
  const t = s.t, a = indice(t, te - DT_INAINTE), b = indice(t, te + DT_DUPA + 1e-9);
  let min = null;
  for (let i = a; i < b; i++) if (v[i] !== null && v[i] !== undefined && (min === null || v[i] < min)) min = v[i];
  const inainte = valoareLa(t, v, te - DT_INAINTE, TOL), dupa = valoareLa(t, v, te + DT_DUPA, TOL);
  return { inainte, min, dupa, cadere: inainte !== null && min !== null ? inainte - min : null };
}
function medie(a) { return a.length ? a.reduce((x, y) => x + y, 0) / a.length : null; }
function mediana(a) {
  if (!a.length) return null;
  const s = [...a].sort((x, y) => x - y), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

// ---------- stare în hash ----------
function citesteHash() {
  const p = new URLSearchParams(location.hash.replace(/^#/, ""));
  const num = (k) => { const x = parseFloat(p.get(k)); return isFinite(x) ? x : null; };
  const marimi = (p.get("m") || "").split(",").filter((c) => MARIMI.includes(c));
  const w = num("w");
  return { a: p.get("a") || "", b: p.get("b") || "", ea: num("ea"), eb: num("eb"), c: p.get("c") || "",
    m: marimi.length ? marimi : MARIMI_IMPLICIT, w: [3, 5, 10, 20].includes(w) ? w : 5 };
}
function scrieHash(push) {
  const p = new URLSearchParams();
  if (st.a) p.set("a", st.a);
  if (st.b) p.set("b", st.b);
  if (st.c) p.set("c", st.c);
  if (st.ea !== null) p.set("ea", st.ea);
  if (st.eb !== null) p.set("eb", st.eb);
  p.set("m", st.m.join(","));
  p.set("w", st.w);
  const h = "#" + p.toString();
  if (h === location.hash) return;
  if (push) location.hash = h;      // intrare nouă în istoric (declanșează hashchange)
  else history.replaceState(null, "", h);
}

// ---------- alegeri ----------
function optiuniSesiuni(sel, valoare) {
  sel.innerHTML = "";
  for (const s of lista) {
    const txt = `${dataRo(s.start)} · ${s.conditie || "necunoscut"} · ${s.profil} · ${s.randuri ?? "?"} rânduri`;
    sel.append(el("option", { value: s.id, text: txt }));
  }
  sel.value = valoare;
}

function umpleCategorii() {
  const nr = new Map();
  for (const s of [ses.a, ses.b]) for (const e of s.evenimente) {
    const c = categorie(e);
    if (c) nr.set(c, (nr.get(c) || 0) + 1);
  }
  const ord = [...nr.keys()].sort((x, y) => {
    const pr = (c) => (c === "steag:cadere_la_cuplare" ? 0 : c.startsWith("marcaj:Cuplez") ? 1 : c.startsWith("steag") ? 2 : c.startsWith("marcaj") ? 3 : 4);
    return pr(x) - pr(y) || x.localeCompare(y);
  });
  const sel = $("categorie");
  sel.innerHTML = "";
  for (const c of [...ord, CAT_TOATE]) {
    const na = evenimenteDin(ses.a, c).length, nb = evenimenteDin(ses.b, c).length;
    sel.append(el("option", { value: c, text: `${numeCategorie(c)} (A: ${na}, B: ${nb})` }));
  }
  if (!st.c || ![...sel.options].some((o) => o.value === st.c)) st.c = ord.includes("steag:cadere_la_cuplare") ? "steag:cadere_la_cuplare" : (ord[0] || CAT_TOATE);
  sel.value = st.c;
}

function umpleEvenimente(lit) {
  const s = ses[lit], sel = $("ev-" + lit), cheie = lit === "a" ? "ea" : "eb";
  const evs = evenimenteDin(s, st.c);
  sel.innerHTML = "";
  if (!evs.length) sel.append(el("option", { value: "", text: "(niciun eveniment de acest tip)" }));
  for (const e of evs) sel.append(el("option", { value: String(e.t_rel_s), text: textEv(e) }));
  // păstrează alegerea din hash dacă există în listă, altfel primul eveniment
  let alesul = evs.find((e) => st[cheie] !== null && Math.abs(e.t_rel_s - st[cheie]) < 5e-4);
  if (!alesul && evs.length) { // implicit: primul eveniment cu motorul deja pornit (rpm > 400 cu 3 s înainte)
    alesul = evs.find((e) => (valoareLa(s.t, s.v.rpm || [], e.t_rel_s - DT_INAINTE, TOL) || 0) > 400) || evs[0];
  }
  st[cheie] = alesul ? alesul.t_rel_s : null;
  if (alesul) sel.value = String(alesul.t_rel_s);
}

function umpleMarimi() {
  const disp = new Set([...ses.a.disp, ...ses.b.disp]);
  const c = $("marimi");
  c.innerHTML = "";
  st.m = st.m.filter((x) => disp.has(x));
  if (!st.m.length) st.m = MARIMI_IMPLICIT.filter((x) => disp.has(x));
  for (const m of MARIMI.filter((x) => disp.has(x))) {
    const un = unitateCol(m, ses.a.coloane);
    c.append(el("label", { class: "bifa-m", title: m }, el("input", { type: "checkbox", value: m, checked: st.m.includes(m),
      onchange: () => {
        st.m = [...c.querySelectorAll("input:checked")].map((i) => i.value);
        scrieHash(false);
        deseneazaGrafice();
      } }), eticheta(m) + (un ? ` (${un})` : "")));
  }
}

// ---------- grafic ----------
function curataGrafice() {
  grafice.forEach((g) => g.u.destroy());
  grafice = [];
  $("grafice-comp").innerHTML = "";
}

function felie(s, col, te, w) { // {x: timpi relativi la eveniment, y: valori} în [te−w, te+w]
  const v = s.v[col], a = indice(s.t, te - w), b = indice(s.t, te + w + 1e-9), x = [], y = [];
  for (let i = a; i < b; i++) { x.push(+(s.t[i] - te).toFixed(4)); y.push(v ? v[i] : null); }
  return { x, y };
}

function mergeaza(fa, fb) { // axa x comună (reuniune), nulluri unde seria nu are punct
  const x = [], ya = [], yb = [];
  let i = 0, j = 0;
  while (i < fa.x.length || j < fb.x.length) {
    const xa = i < fa.x.length ? fa.x[i] : Infinity, xb = j < fb.x.length ? fb.x[j] : Infinity;
    if (xa === xb) { x.push(xa); ya.push(fa.y[i++]); yb.push(fb.y[j++]); }
    else if (xa < xb) { x.push(xa); ya.push(fa.y[i++]); yb.push(null); }
    else { x.push(xb); ya.push(null); yb.push(fb.y[j++]); }
  }
  return [x, ya, yb];
}

function latimeZona() { return Math.max(260, Math.floor($("grafice-comp").clientWidth - 4)); }
function inaltime() { return window.innerWidth <= 640 ? 200 : 260; }

function valoareCursor(u, v, si, idx) {
  if (v !== null && v !== undefined) return fmtVal(v);
  const ix = idx === undefined || idx === null ? u.cursor.idx : idx;
  if (ix === null || ix === undefined) return "–";
  for (let k = ix, lim = 120; k >= 0 && lim > 0; k--, lim--) if (u.data[si][k] !== null && u.data[si][k] !== undefined) return "~" + fmtVal(u.data[si][k]);
  return "–";
}

function deseneazaGrafice() {
  const t0 = performance.now();
  curataGrafice();
  if (st.ea === null || st.eb === null) {
    $("grafice-comp").append(el("p", { class: "gol", text: "Nu există evenimente de acest tip în ambele sesiuni; alege alt tip sau alte sesiuni." }));
    return;
  }
  const c = culori(), w = st.w;
  const nume = { a: etichetaSes(ses.a, "A"), b: etichetaSes(ses.b, "B") };
  for (const col of st.m) {
    const fa = felie(ses.a, col, st.ea, w), fb = felie(ses.b, col, st.eb, w);
    const date = mergeaza(fa, fb);
    const un = unitateCol(col, ses.a.coloane);
    const zona = el("div", { class: "zona" });
    const card = el("section", { class: "card-grafic", "aria-label": eticheta(col) }, el("h3", {}, el("span", { text: eticheta(col) + (un ? ` (${un})` : "") })), zona);
    $("grafice-comp").append(card);
    const serie = (lit, culoare) => ({ label: nume[lit], stroke: culoare, width: 1.8, spanGaps: true, points: { size: 5 }, value: valoareCursor });
    const opts = {
      width: latimeZona() - 18, height: inaltime(), scales: { x: { time: false, auto: false, min: -w, max: w } },
      series: [{ label: "t față de eveniment", value: (u, v) => (v === null || v === undefined ? "–" : `${fmtSemn(v)} s`) },
        serie("a", c.a), serie("b", c.b)],
      axes: [
        { stroke: c.axa, grid: { stroke: c.grila, width: 1 }, ticks: { stroke: c.grila, width: 1 }, size: 34,
          values: (u, spl) => spl.map((v) => (v === 0 ? "0" : fmtSemn(v) + " s")) },
        { stroke: c.axa, grid: { stroke: c.grila, width: 1 }, ticks: { stroke: c.grila, width: 1 }, size: 56, values: (u, spl) => spl.map(fmtVal) },
      ],
      cursor: { sync: { key: CHEIE_SYNC, scales: ["x", null] }, drag: { x: true, y: false, setScale: true }, bind: { dblclick: () => null } },
      legend: { live: true },
      hooks: {
        draw: [(u) => linii(u, w)],
        setCursor: [(u) => laCursor(u)],
        ready: [(u) => { u.over.addEventListener("dblclick", reseteazaZoom); }],
      },
    };
    const u = new uPlot(opts, date, zona);
    grafice.push({ u, col, card });
  }
  // măsurătoare: după desenare (setTimeout, nu requestAnimationFrame)
  setTimeout(() => {
    const ms = performance.now() - t0;
    window.__masuraComparare = { ...(window.__masuraComparare || {}), grafice_ms: Math.round(ms), nr_grafice: grafice.length };
    afiseazaMasura();
  }, 0);
}

function linii(u, w) { // t = 0 (accent, plin), t−3 s și t+3 s (întrerupt)
  const c = culori(), ctx = u.ctx, dpr = window.devicePixelRatio || 1, { left, top, width, height } = u.bbox;
  ctx.save();
  ctx.beginPath(); ctx.rect(left, top, width, height); ctx.clip();
  for (const [x0, plin] of [[0, true], [-DT_INAINTE, false], [DT_DUPA, false]]) {
    if (x0 < -w || x0 > w) continue;
    const x = Math.round(u.valToPos(x0, "x", true));
    ctx.strokeStyle = plin ? c.accent : c.axa;
    ctx.lineWidth = (plin ? 2 : 1) * dpr;
    ctx.globalAlpha = plin ? 0.9 : 0.6;
    ctx.setLineDash(plin ? [] : [4 * dpr, 4 * dpr]);
    ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + height); ctx.stroke();
  }
  ctx.restore();
}

function laCursor(u) {
  const info = $("info-comp");
  const l = u.cursor.left;
  if (l === undefined || l === null || l < 0) return;
  info.textContent = `Cursor: ${fmtSemn(+u.posToVal(l, "x").toFixed(2))} s față de eveniment (liniile întrerupte: −3 s și +3 s, momentele „înainte” și „după” din tabel).`;
}

function reseteazaZoom() {
  grafice.forEach((g) => g.u.setScale("x", { min: -st.w, max: st.w }));
}

function afiseazaMasura() {
  const m = window.__masuraComparare || {};
  const p = $("masura-comp");
  if (p) p.textContent = `Măsurat: descărcare A ${m.desc_a_ms ?? "–"} ms, B ${m.desc_b_ms ?? "–"} ms (toate coloanele, fără reducere); `
    + `${m.nr_grafice ?? 0} grafice desenate în ${m.grafice_ms ?? "–"} ms; tabel calculat în ${m.tabel_ms ?? "–"} ms.`;
}

// ---------- tabel ----------
function calculeaza(s, evs) {
  return evs.map((e) => ({ e, m: Object.fromEntries(COL_TABEL.filter((c) => s.disp.includes(c)).map((c) => [c, masoara(s, c, e.t_rel_s)])) }));
}

function stat(rez, col, camp) { return rez.map((r) => r.m[col] && r.m[col][camp]).filter((x) => x !== null && x !== undefined); }

function tabelRezumat(ra, rb) {
  const cap1 = el("tr", {}, el("th", { rowspan: 2, text: "Mărime" }),
    el("th", { colspan: 4, class: "gr-a", text: `${etichetaSes(ses.a, "A")} · ${ra.length} evenimente` }),
    el("th", { colspan: 4, class: "gr-b", text: `${etichetaSes(ses.b, "B")} · ${rb.length} evenimente` }),
    el("th", { colspan: 2, text: "B − A" }));
  const sub = ["înainte (med.)", "minim (med.)", "cădere (medie)", "cădere (mediană)"];
  const cap2 = el("tr", {}, ...[0, 1].flatMap(() => sub.map((t) => el("th", { class: "nr", text: t }))),
    el("th", { class: "nr", text: "cădere medie" }), el("th", { class: "nr", text: "cădere mediană" }));
  const corp = [];
  for (const col of COL_TABEL) {
    if (!ses.a.disp.includes(col) && !ses.b.disp.includes(col)) continue;
    const f = (rez) => ({ in: medie(stat(rez, col, "inainte")), mn: medie(stat(rez, col, "min")),
      cm: medie(stat(rez, col, "cadere")), cd: mediana(stat(rez, col, "cadere")) });
    const A = f(ra), B = f(rb);
    const dif = (x, y) => (x === null || y === null ? null : y - x);
    const un = unitateCol(col, ses.a.coloane);
    corp.push(el("tr", {}, el("td", { class: "nume-m", text: eticheta(col) + (un ? ` (${un})` : "") }),
      ...[A, B].flatMap((X) => [X.in, X.mn, X.cm, X.cd].map((v, i) => el("td", { class: "nr" + (i >= 2 ? " tare" : ""), text: fmtVal(v) }))),
      el("td", { class: "nr tare", text: fmtSemn(dif(A.cm, B.cm)) }), el("td", { class: "nr tare", text: fmtSemn(dif(A.cd, B.cd)) })));
  }
  return el("div", { class: "derulare" }, el("table", { class: "tabel comp-rez" }, el("thead", {}, cap1, cap2), el("tbody", {}, corp)));
}

function tabelEvenimente(lit, rez) {
  const s = ses[lit], cheie = lit === "a" ? "ea" : "eb";
  const cols = COL_TABEL.filter((c) => s.disp.includes(c));
  const cap1 = el("tr", {}, el("th", { rowspan: 2, text: "Moment" }),
    cols.map((c) => el("th", { colspan: 4, class: "gr", text: eticheta(c) + (unitateCol(c, s.coloane) ? ` (${unitateCol(c, s.coloane)})` : "") })));
  const cap2 = el("tr", {}, cols.flatMap(() => ["înainte", "minim", "după", "cădere"].map((t) => el("th", { class: "nr", text: t }))));
  const corp = rez.map((r) => el("tr", { class: "ev-rand" + (st[cheie] !== null && Math.abs(r.e.t_rel_s - st[cheie]) < 5e-4 ? " ales" : ""),
    tabindex: 0, title: String(r.e.detalii),
    onclick: () => alegeDinTabel(lit, r.e.t_rel_s),
    onkeydown: (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); alegeDinTabel(lit, r.e.t_rel_s); } } },
  el("td", { class: "fara-rupere", text: fmtRel(r.e.t_rel_s) }),
  cols.flatMap((c) => { const m = r.m[c] || {}; return [m.inainte, m.min, m.dupa, m.cadere].map((v, i) => el("td", { class: "nr" + (i === 3 ? " tare" : ""), text: fmtVal(v) })); })));
  return el("div", { class: "sectiune" },
    el("h3", { class: lit === "a" ? "tit-a" : "tit-b", text: `${etichetaSes(s, lit.toUpperCase())} · ${rez.length} evenimente` }),
    rez.length ? el("div", { class: "derulare" }, el("table", { class: "tabel comp-ev" }, el("thead", {}, cap1, cap2), el("tbody", {}, corp)))
      : el("p", { class: "gol", text: "Niciun eveniment de acest tip în această sesiune." }));
}

function deseneazaTabele() {
  const t0 = performance.now();
  const ra = calculeaza(ses.a, evenimenteDin(ses.a, st.c)), rb = calculeaza(ses.b, evenimenteDin(ses.b, st.c));
  const r = $("rezumat-comp"), t = $("tabele-comp");
  r.innerHTML = ""; t.innerHTML = "";
  r.append(el("p", { class: "mic", text: `Pentru fiecare eveniment: „înainte” = valoarea cu ${DT_INAINTE} s înainte, „după” = la ${DT_DUPA} s după, „minim” = cea mai mică valoare între cele două momente, „cădere” = înainte − minim. Click pe un rând = aliniază graficul la acel eveniment.` }),
    el("h3", { text: "Rezumat pe sesiune" }), tabelRezumat(ra, rb));
  t.append(tabelEvenimente("a", ra), tabelEvenimente("b", rb));
  window.__masuraComparare = { ...(window.__masuraComparare || {}), tabel_ms: Math.round(performance.now() - t0) };
}

function alegeDinTabel(lit, t) {
  const cheie = lit === "a" ? "ea" : "eb";
  st[cheie] = t;
  $("ev-" + lit).value = String(t);
  scrieHash(false);
  deseneazaGrafice();
  deseneazaTabele();
  $("zona-comp").scrollIntoView({ block: "start" });
}

// ---------- orchestrare ----------
async function aplica() {
  const j = ++jeton;
  eroarePagina("");
  $("stare-comp").textContent = "Se încarcă…";
  try {
    const t0 = performance.now();
    const [a, b] = await Promise.all([incarcaSesiune(st.a), incarcaSesiune(st.b)]);
    if (j !== jeton) return;
    ses = { a, b };
    window.__masuraComparare = { desc_a_ms: Math.round(a.ms), desc_b_ms: Math.round(b.ms), total_incarcare_ms: Math.round(performance.now() - t0) };
    optiuniSesiuni($("sel-a"), st.a);
    optiuniSesiuni($("sel-b"), st.b);
    umpleCategorii();
    umpleEvenimente("a");
    umpleEvenimente("b");
    umpleMarimi();
    $("fereastra").value = String(st.w);
    scrieHash(false);
    $("zona-comp").hidden = false;
    $("zona-tab").hidden = false;
    $("stare-comp").textContent = `A: ${a.t.length} rânduri, B: ${b.t.length} rânduri.`;
    deseneazaGrafice();
    deseneazaTabele();
    afiseazaMasura();
  } catch (e) {
    if (j !== jeton) return;
    eroarePagina("Nu pot încărca sesiunile: " + e.message);
    $("stare-comp").textContent = "";
  }
}

function alegeImplicite() { // cea mai mare sesiune rece ca A și cea mai mare caldă ca B
  const mare = (cond) => [...lista].filter((s) => s.conditie === cond).sort((x, y) => (y.randuri || 0) - (x.randuri || 0))[0];
  const ids = new Set(lista.map((s) => s.id));
  if (!ids.has(st.a)) st.a = (mare("rece") || lista[0] || {}).id || "";
  if (!ids.has(st.b)) st.b = (mare("cald") || lista[1] || lista[0] || {}).id || "";
}

function dupaHash() {
  st = citesteHash();
  if (lista.length < 1) return;
  alegeImplicite();
  aplica();
}

async function porneste() {
  try { dict = { ...dict, ...(await (await fetch("/nume_ro.json")).json()) }; } catch (e) { /* nume brute */ }
  try {
    lista = (await api("/api/sesiuni")).filter((s) => s.randuri);
  } catch (e) { eroarePagina("Nu pot citi lista sesiunilor: " + e.message); return; }
  if (!lista.length) { eroarePagina("Nu există sesiuni cu date de comparat."); return; }
  const schimba = (cheie, lit) => () => {
    st[cheie] = $("sel-" + lit).value;
    st["e" + lit] = null;
    scrieHash(true); // intrare nouă în istoric; hashchange reface totul
  };
  $("sel-a").addEventListener("change", schimba("a", "a"));
  $("sel-b").addEventListener("change", schimba("b", "b"));
  $("categorie").addEventListener("change", () => {
    st.c = $("categorie").value; st.ea = st.eb = null;
    umpleEvenimente("a"); umpleEvenimente("b");
    scrieHash(false); deseneazaGrafice(); deseneazaTabele();
  });
  for (const lit of ["a", "b"]) $("ev-" + lit).addEventListener("change", () => {
    const v = parseFloat($("ev-" + lit).value);
    st["e" + lit] = isFinite(v) ? v : null;
    scrieHash(false); deseneazaGrafice(); deseneazaTabele();
  });
  $("fereastra").addEventListener("change", () => { st.w = Number($("fereastra").value); scrieHash(false); deseneazaGrafice(); });
  $("reset-zoom").addEventListener("click", reseteazaZoom);
  window.addEventListener("hashchange", dupaHash);
  window.addEventListener("resize", () => grafice.forEach((g) => g.u.setSize({ width: latimeZona() - 18, height: inaltime() })));
  if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (ses.a) deseneazaGrafice(); });
  dupaHash();
}

porneste();
