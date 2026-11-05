// Pagina „Live”: citire fără înregistrare (Etapele 11–13) și, cu profilul toate_senzorii, TOATE valorile de la toți
// senzorii. Interoghează /api/live la ~0,7 s și ține în memorie doar fereastra afișată. Nu scrie nimic pe disc, în afară
// de „Salvează” cerut explicit. Doar citire.
"use strict";

const $ = (id) => document.getElementById(id);
const PRESETARI = [
  ["Turație", ["rpm", "rpm_tinta", "pedala"]],
  ["Viteză", ["viteza"]],
  ["Temperaturi", ["tmot", "taer"]],
  ["Sarcină și cuplu", ["sarcina", "sarcina_tinta", "cuplu", "maf", "clapeta"]],
  ["Amestec", ["fr1", "fr2", "te", "te2"]],
  ["Came și avans", ["avans", "came_ev", "came_adm"]],
  ["Neregularitate cilindri", ["lu1", "lu2", "lu3", "lu4"]],
  ["Sonde lambda", ["sonda_pre_b1", "sonda_pre_b2", "sonda_post_b1", "sonda_post_b2"]],
  ["Baterie", ["ub"]],
];
const CARTELE = ["rpm", "pedala", "sarcina", "cuplu", "clapeta", "tmot", "viteza", "ub", "maf", "avans"];
const INTERVAL_ACTIV_MS = 700, INTERVAL_OPRIT_MS = 2500;
const RETINE_S = 660; // cât timp se păstrează în browser (10 min + rezervă)
const MAX_SELECTIE = 8;

let dict = { coloane: {}, unitati: {}, stat: {}, joburi: {} };
// D: {t:[], ciclu:[], c:{alias:[]} (doar coloanele cerute), cursor, evCursor, evs:[], mapare:{alias:{job,rezultat,unitate}},
//     aliasuri:[], unitati:{}, vMapare:-1, valori:{alias:ultima valoare brută}, profil}
let D = null;
let ultimaPeRand = {}; // alias -> true dacă ultimul rând are valoare
let stare = null; // ultimul răspuns /api/live
let activeP = new Set(["Turație", "Sarcină și cuplu"]);
let selectate = new Set(); // aliasuri bifate în tabel -> graficul „Selecție”
let ferestra = 30;
let inghetat = false;
let xInghetat = null; // intervalul x păstrat cât timp graficele sunt înghețate
let grafice = []; // [{cheie, nume, cols, card, zona, u}]
let cronometru = null, cerereInZbor = false, jeton = 0;
let obs = null;
let profile = [];
let deschise = new Set(); // joburile deschise în tabel
let celule = {}; // alias -> {val, un, tr, bifa}
let cautare = "";

function el(eticheta_, atribute, ...copii) {
  const e = document.createElement(eticheta_);
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

async function api(cale, corp) {
  const opt = corp === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corp) };
  const r = await fetch(cale, opt);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(d.eroare || `Eroare ${r.status}`); e.cod = r.status; throw e; }
  return d;
}

function eroarePagina(text) {
  const p = $("eroare-pagina");
  p.textContent = text || "";
  p.hidden = !text;
}

function fmtVal(v) {
  if (v === null || v === undefined || !isFinite(v)) return "–";
  return String(+Number(v).toPrecision(5)).replace(".", ",");
}
function pad2(n) { return String(n).padStart(2, "0"); }
function fmtRel(sec, zec) {
  const s = Math.max(0, sec), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const rs = zec ? r.toFixed(zec).padStart(3 + zec, "0") : pad2(Math.floor(r));
  return h ? `${h}:${pad2(m)}:${rs}` : `${m}:${rs}`;
}

// etichetă: dicționarul de coloane (aliasuri din profil), apoi dicționarul STAT_* (aliasuri automate), apoi numele brut
function eticheta(a) {
  const d = dict.coloane[a];
  if (d && d.eticheta) return d.eticheta;
  const m = D && D.mapare[a];
  if (m) return dict.stat[m.rezultat] || m.rezultat;
  return a;
}
function unitate(a) {
  const d = dict.coloane[a];
  if (d && d.unitate_afisata !== undefined && d.unitate_afisata !== "") return d.unitate_afisata;
  const brut = D && D.unitati ? String(D.unitati[a] || "").trim() : "";
  return dict.unitati[brut] || brut;
}
function numeJob(job) { return dict.joburi[job] || job; }

function culori() {
  const st = getComputedStyle(document.documentElement);
  const g = (n) => st.getPropertyValue(n).trim() || "#888";
  return { serii: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => g("--serie-" + i)), axa: g("--slab"), grila: g("--linie"),
    ev: { marcaj: g("--ev-marcaj"), steag: g("--ev-steag"), eroare: g("--ev-eroare") } };
}

// ---------- date ----------
function reseteazaDate() {
  D = { t: [], ciclu: [], c: {}, cursor: 0, evCursor: 0, evs: [], mapare: {}, aliasuri: [], unitati: {}, vMapare: -1, valori: {}, profil: null };
  ultimaPeRand = {};
}

// coloanele pentru care ținem istoric: cartele + toate presetările + selecția (restul se văd doar ca valoare curentă)
function coloaneCerute() {
  const s = new Set([...CARTELE, ...PRESETARI.flatMap(([, c]) => c), ...selectate]);
  return [...s].filter((a) => D.mapare[a]);
}

function adauga(r, cerute, prima) {
  if (r.reset && !prima) {
    const { mapare, aliasuri, unitati, vMapare, valori } = D;
    reseteazaDate();
    Object.assign(D, { mapare, aliasuri, unitati, vMapare, valori });
  }
  if (r.mapare) { D.mapare = r.mapare; D.aliasuri = r.aliasuri; D.unitati = r.unitati || {}; }
  if (r.v_mapare !== undefined) D.vMapare = r.v_mapare;
  D.valori = r.valori || D.valori;
  D.profil = r.profil || D.profil;
  for (const e of r.evenimente || []) D.evs.push(e);
  D.evCursor = r.ev_ultim !== undefined ? r.ev_ultim : D.evCursor;
  if (prima) return; // primul răspuns aduce doar structura (mapare, valori); datele se cer apoi cu coloanele necesare
  const n = r.t.length;
  for (const a of cerute) {
    const nou = r[a] || new Array(n).fill(null);
    (D.c[a] = D.c[a] || new Array(D.t.length).fill(null)).push(...nou);
    if (n) ultimaPeRand[a] = nou[n - 1] !== null && nou[n - 1] !== undefined;
  }
  D.t.push(...r.t);
  D.ciclu.push(...r.ciclu);
  D.cursor = r.ciclu_ultim;
  taie();
}

function taie() { // păstrează ~RETINE_S secunde; taie rar (în blocuri), nu la fiecare rând
  const tmax = D.t.length ? D.t[D.t.length - 1] : 0;
  let k = 0;
  while (k < D.t.length && D.t[k] < tmax - RETINE_S) k++;
  if (k > 200 || (k > 0 && D.t.length > 20000)) {
    D.t.splice(0, k); D.ciclu.splice(0, k);
    for (const a of Object.keys(D.c)) D.c[a].splice(0, k);
  }
  D.evs = D.evs.filter((e) => e.t >= tmax - RETINE_S).slice(-300);
}

// ---------- interogare ----------
async function ciclu() {
  if (cerereInZbor) return;
  cerereInZbor = true;
  const j = jeton;
  let r = null, repeta = false;
  try {
    const prima = D.vMapare === -1; // întâi doar structura (sute de coloane cu toate_senzorii), apoi coloanele necesare
    const cerute = prima ? [] : coloaneCerute();
    r = await api(`/api/live?de_la_ciclu=${prima ? 0 : D.cursor}&de_la_ev=${D.evCursor}&de_la_mapare=${D.vMapare}&coloane=${cerute.map(encodeURIComponent).join(",")}`);
    if (j !== jeton) return;
    eroarePagina("");
    stare = r;
    if (r.stare === "oprit" && !r.mod) { /* nimic de citit */ } else { adauga(r, cerute, prima); repeta = prima && r.v_mapare !== undefined; }
    afiseazaStare(r);
    deseneaza();
  } catch (e) {
    if (j !== jeton) return;
    if (e.cod === 409) { stare = null; eroarePagina(e.message + " Mergi la ecranul Înregistrare."); afiseazaStare({ stare: "oprit", activ: false }); }
    else eroarePagina("Nu pot citi starea: " + e.message);
  } finally {
    cerereInZbor = false;
    clearTimeout(cronometru);
    cronometru = setTimeout(ciclu, repeta ? 0 : stare && stare.activ ? INTERVAL_ACTIV_MS : INTERVAL_OPRIT_MS);
  }
}

// ---------- afișare ----------
const NUME_STARE = { oprit: "oprit", porneste: "pornește", live: "citește live", opreste: "se oprește",
  reconectare: "reconectare", eroare: "eroare" };

function afiseazaStare(s) {
  const activ = !!s.activ;
  const st = $("s-stare");
  st.textContent = NUME_STARE[s.stare] || s.stare;
  st.className = "eticheta " + ({ live: "verde", porneste: "galben", opreste: "galben", reconectare: "galben", eroare: "rosu" }[s.stare] || "");
  if (s.stare === "oprit" && s.motiv_oprire) st.textContent += ` (${s.motiv_oprire})`;
  const u = $("s-ultima");
  if (!activ || s.ultima_reusita_s === null || s.ultima_reusita_s === undefined) {
    u.textContent = activ ? "încă nicio citire" : "–";
    u.className = "eticheta" + (activ ? " rosu" : "");
  } else {
    u.textContent = `acum ${s.ultima_reusita_s.toFixed(1)} s`;
    u.className = "eticheta " + (s.ultima_reusita_s < 2 ? "verde" : s.ultima_reusita_s <= 5 ? "galben" : "rosu");
  }
  $("s-cps").textContent = activ && s.cicluri_pe_s !== undefined ? s.cicluri_pe_s.toFixed(2) : "–";
  $("s-timp").textContent = s.timp_s !== undefined ? fmtRel(s.timp_s, 0) : "–";
  $("s-erori").textContent = s.erori !== undefined ? s.erori : "–";
  $("s-steaguri").textContent = s.steaguri_total !== undefined ? String(s.steaguri_total) : "–";
  $("start").disabled = activ;
  $("stop").disabled = !activ;
  $("profil").disabled = activ;
  const areDate = D && D.t.length > 0;
  $("sv-buton").disabled = !areDate || !(s.mod === "live");
  $("in-buton").disabled = !$("profil").value;
  for (const b of document.querySelectorAll("#marcaje button")) b.disabled = !activ;
}

function deseneaza() {
  deseneazaCartele();
  deseneazaTabel();
  deseneazaGrafice();
}

function deseneazaCartele() {
  const z = $("cartele");
  const aliasuri = CARTELE.filter((a) => D && D.mapare[a]);
  if (!aliasuri.length) return;
  if (z.dataset.chei !== aliasuri.join(",")) {
    z.innerHTML = "";
    z.dataset.chei = aliasuri.join(",");
    for (const a of aliasuri) z.append(el("div", { class: "cv", id: "cv-" + a, title: a },
      el("div", { class: "et", text: eticheta(a) }), el("div", {}, el("span", { class: "val" }), el("span", { class: "un" }))));
  }
  for (const a of aliasuri) {
    const c = $("cv-" + a);
    const v = D.valori[a];
    c.querySelector(".val").textContent = typeof v === "number" ? fmtVal(v) : "–";
    c.querySelector(".un").textContent = unitate(a);
    c.classList.toggle("vechi", typeof v === "number" && ultimaPeRand[a] === false); // grup lent: ultima valoare citită
  }
}

// ---------- tabelul cu TOATE valorile ----------
function formateaza(alias, v) {
  if (v === undefined || v === null) return "–";
  if (typeof v === "string") return v;
  const m = D.mapare[alias];
  if (m && /_EIN$/i.test(m.rezultat)) return v ? "da" : "nu";
  return fmtVal(v);
}

function deseneazaTabel() {
  const z = $("tabel-valori");
  if (!D || !D.aliasuri.length) return;
  if (z.dataset.v !== String(D.vMapare) || z.dataset.p !== String(D.profil)) construiesteTabel(z);
  for (const [a, c] of Object.entries(celule)) {
    const t = formateaza(a, D.valori[a]);
    if (c.val.textContent !== t) c.val.textContent = t;
    c.val.classList.toggle("text", typeof D.valori[a] === "string");
    const nume = unitate(a);
    if (c.un.textContent !== nume) c.un.textContent = nume;
  }
}

function construiesteTabel(z) {
  z.dataset.v = String(D.vMapare);
  z.dataset.p = String(D.profil);
  z.innerHTML = "";
  celule = {};
  const grupuri = new Map();
  for (const a of D.aliasuri) {
    const job = D.mapare[a].job;
    if (!grupuri.has(job)) grupuri.set(job, []);
    grupuri.get(job).push(a);
  }
  for (const [job, aliasuri] of grupuri) {
    const corp = el("tbody");
    for (const a of aliasuri) {
      const m = D.mapare[a];
      const val = el("td", { class: "val" }), un = el("td", { class: "un" });
      const bifa = el("input", { type: "checkbox", checked: selectate.has(a), "aria-label": `Grafic: ${eticheta(a)}`,
        onchange: (ev) => comutaSelectie(a, ev.target) });
      const tr = el("tr", { "data-alias": a, "data-text": `${eticheta(a)} ${a} ${m.rezultat} ${job} ${numeJob(job)}`.toLowerCase() },
        el("td", { title: `${a} · ${m.rezultat}` }, eticheta(a), el("span", { class: "tehnic-rez", text: m.rezultat })),
        val, un, el("td", { class: "gr" }, el("label", {}, bifa, el("span", { class: "gr-txt", text: " Grafic" }))));
      corp.append(tr);
      celule[a] = { val, un, tr, bifa };
    }
    const d = el("details", { class: "grup-valori", "data-job": job, open: deschise.has(job) || null,
      ontoggle: (ev) => { if (!cautare) { if (ev.target.open) deschise.add(job); else deschise.delete(job); } } },
    el("summary", {}, numeJob(job), el("span", { class: "mic", text: `${aliasuri.length} valori${numeJob(job) !== job ? " · " + job : ""}` })),
    el("div", { class: "derulare" }, el("table", {}, corp)));
    z.append(d);
  }
  $("numar-valori").textContent = `(${D.aliasuri.length} valori din ${grupuri.size} joburi)`;
  aplicaFiltru();
}

function aplicaFiltru() {
  const q = cautare.trim().toLowerCase();
  for (const d of document.querySelectorAll("#tabel-valori .grup-valori")) {
    let vizibile = 0;
    for (const tr of d.querySelectorAll("tr")) {
      const arata = !q || tr.dataset.text.includes(q);
      tr.hidden = !arata;
      if (arata) vizibile++;
    }
    d.hidden = vizibile === 0;
    if (q && vizibile) d.open = true;
    else if (!q) d.open = deschise.has(d.dataset.job);
  }
}

function comutaSelectie(alias, bifa) {
  if (bifa.checked) {
    if (selectate.size >= MAX_SELECTIE) {
      bifa.checked = false;
      eroarePagina(`Cel mult ${MAX_SELECTIE} mărimi în graficul „Selecție”.`);
      return;
    }
    eroarePagina("");
    selectate.add(alias);
    if (D && !D.c[alias]) D.c[alias] = new Array(D.t.length).fill(null); // istoricul începe de la bifare
  } else selectate.delete(alias);
  deseneazaGrafice();
}

// ---------- grafice ----------
function presetariDisponibile() {
  return PRESETARI.map(([n, cols]) => [n, cols.filter((c) => D && D.mapare[c])]).filter(([, c]) => c.length);
}

function deseneazaBifePresetari() {
  const f = $("presetari");
  const chei = presetariDisponibile().map(([n]) => n).join("|");
  if (f.dataset.chei === chei) return;
  f.dataset.chei = chei;
  f.querySelectorAll("label").forEach((l) => l.remove());
  for (const [nume] of presetariDisponibile()) {
    f.append(el("label", {}, el("input", { type: "checkbox", checked: activeP.has(nume), onchange: (ev) => {
      if (ev.target.checked) activeP.add(nume); else activeP.delete(nume);
      deseneazaGrafice();
    } }), nume));
  }
}

function xFereastra() {
  if (xInghetat) return xInghetat;
  const t0 = D.t.length ? D.t[0] : 0, tmax = D.t.length ? D.t[D.t.length - 1] : ferestra;
  return tmax - t0 < ferestra ? [t0, t0 + ferestra] : [tmax - ferestra, tmax]; // până se umple fereastra, crește spre dreapta
}

function reconstruiesteGrafice() {
  for (const g of grafice) { if (g.u) g.u.destroy(); g.card.remove(); }
  grafice = [];
  deseneazaGrafice();
}

function deseneazaGrafice() {
  if (!D) return;
  deseneazaBifePresetari();
  const zona = $("zona-grafice");
  const dorite = presetariDisponibile().filter(([n]) => activeP.has(n));
  const sel = [...selectate].filter((a) => D.mapare[a]);
  if (sel.length) dorite.push(["Selecție", sel]);
  if (!dorite.length && !grafice.length) return;
  const cheie = (n, c) => n + ":" + c.join(",");
  if (grafice.map((g) => g.cheie).join("|") !== dorite.map(([n, c]) => cheie(n, c)).join("|")) {
    for (const g of grafice) { if (g.u) g.u.destroy(); g.card.remove(); }
    grafice = dorite.map(([nume, cols]) => {
      const z = el("div", { class: "zona" });
      const card = el("section", { class: "card-grafic", "aria-label": nume }, el("h3", { text: nume }), z);
      zona.append(card);
      return { cheie: cheie(nume, cols), nume, cols, card, zona: z, u: null };
    });
  }
  if (inghetat) return;
  for (const g of grafice) {
    const date = [D.t, ...g.cols.map((c) => D.c[c] || (D.c[c] = new Array(D.t.length).fill(null)))];
    if (!g.u) { if (D.t.length) construieste(g, date); }
    else g.u.setData(date, true);
  }
  const info = $("info-grafice");
  if (D.t.length) info.textContent = `${D.t.length.toLocaleString("ro-RO")} rânduri în memorie (ultimele ${Math.round((D.t[D.t.length - 1] - D.t[0]))} s). Nimic nu se salvează.`;
}

function construieste(g, date) {
  const c = culori(), unitati = [];
  const scara = (col) => {
    let un = unitate(col) || "";
    if (un.startsWith("%")) un = "%";
    if (!unitati.includes(un)) unitati.push(un);
    return "u:" + un;
  };
  const serii = [{ label: "Timp", value: (u, v) => (v === null || v === undefined ? "–" : fmtRel(v, 1)) }];
  g.cols.forEach((col, i) => {
    const un = unitate(col);
    serii.push({ label: eticheta(col) + (un ? ` (${un})` : ""), scale: scara(col), stroke: c.serii[i % 8], width: 1.6, spanGaps: true,
      points: { show: false }, value: (u, v) => fmtVal(v) });
  });
  const scales = { x: { time: false, range: () => xFereastra() } };
  unitati.forEach((un) => { scales["u:" + un] = { auto: true }; });
  const axe = [{ stroke: c.axa, grid: { stroke: c.grila, width: 1 }, ticks: { stroke: c.grila, width: 1 }, size: 34,
    values: (u, spl) => spl.map((v) => fmtRel(v, 0)) }];
  unitati.forEach((un, i) => axe.push({ scale: "u:" + un, side: i % 2 === 0 ? 3 : 1, stroke: c.axa, label: un || "", labelSize: un ? 18 : 0,
    labelFont: "12px system-ui", grid: { show: i === 0, stroke: c.grila, width: 1 }, ticks: { stroke: c.grila, width: 1 }, size: 54,
    values: (u, spl) => spl.map(fmtVal) }));
  g.zona.textContent = "";
  g.u = new uPlot({ width: Math.max(260, g.card.clientWidth - 18), height: window.innerWidth <= 640 ? 190 : 230, scales, series: serii, axes: axe,
    cursor: { drag: { x: false, y: false } }, legend: { live: true }, hooks: { draw: [(u) => deseneazaEv(u)] } }, date, g.zona);
}

function deseneazaEv(u) {
  if (!D) return;
  const c = culori(), ctx = u.ctx, dpr = window.devicePixelRatio || 1, { left, top, width, height } = u.bbox;
  ctx.save();
  ctx.beginPath(); ctx.rect(left, top, width, height); ctx.clip();
  for (const e of D.evs) {
    if (!c.ev[e.tip]) continue; // doar marcaj, steag, eroare
    const x = Math.round(u.valToPos(e.t, "x", true));
    if (x < left - 2 || x > left + width + 2) continue;
    ctx.strokeStyle = c.ev[e.tip]; ctx.lineWidth = dpr; ctx.globalAlpha = 0.8;
    ctx.setLineDash(e.tip === "steag" ? [] : [5 * dpr, 4 * dpr]);
    ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + height); ctx.stroke();
  }
  ctx.restore();
}

function redimensioneaza() {
  for (const g of grafice) if (g.u) g.u.setSize({ width: Math.max(260, g.card.clientWidth - 18), height: window.innerWidth <= 640 ? 190 : 230 });
}

// ---------- acțiuni ----------
async function start() {
  eroarePagina("");
  try {
    reseteazaDate();
    celule = {};
    $("tabel-valori").dataset.v = "";
    jeton++;
    reconstruiesteGrafice();
    await api("/api/live/start", { profil: $("profil").value });
    ciclu();
  } catch (e) { eroarePagina("Nu pot porni citirea live: " + e.message); }
}

async function opreste() {
  try { await api("/api/live/stop", {}); } catch (e) { eroarePagina("Nu pot opri: " + e.message); }
  ciclu();
}

async function marcaj(eticheta_) {
  try { await api("/api/marcaj", { eticheta: eticheta_ }); } catch (e) { eroarePagina("Marcaj: " + e.message); }
}

async function salveaza() {
  const m = $("sv-mesaj");
  m.textContent = "Se salvează…";
  try {
    const r = await api("/api/live/salveaza", { secunde: Number($("sv-secunde").value), conditie: $("sv-conditie").value, nota: $("sv-nota").value });
    m.textContent = "";
    m.append("Salvat. ", el("a", { href: `/sesiuni.html#${encodeURIComponent(r.id)}`, text: "Deschide sesiunea" }));
  } catch (e) { m.textContent = "Nu pot salva: " + e.message; }
}

async function inregistreaza() {
  const m = $("in-mesaj"), profil = $("profil").value;
  const p = profile.find((x) => x.fisier === profil);
  if (!profil) { m.textContent = "Alege un profil."; return; }
  if (p && p.doar_live) { m.textContent = `Profilul „${p.nume}” e doar pentru citire live; alege altul pentru înregistrare.`; return; }
  if (stare && stare.activ && !window.confirm("Oprești citirea live și începi o înregistrare nouă? Datele din live nu intră în ea.")) return;
  m.textContent = "Se oprește live…";
  try {
    if (stare && stare.activ) await api("/api/live/stop", {});
    m.textContent = "Se pornește înregistrarea…";
    await api("/api/start", { profil, conditie: $("in-conditie").value, nota: $("in-nota").value });
    location.href = "/index.html";
  } catch (e) { m.textContent = "Nu pot începe înregistrarea: " + e.message; }
}

function taste(ev) {
  if (ev.ctrlKey || ev.altKey || ev.metaKey || /^(INPUT|TEXTAREA|SELECT)$/.test((ev.target.tagName || ""))) return;
  if (!/^[1-9]$/.test(ev.key) || !stare || !stare.activ) return;
  const b = [...document.querySelectorAll("#marcaje button")].find((x) => x.dataset.tasta === ev.key);
  if (b) b.click();
}

function hintProfil() {
  const p = profile.find((x) => x.fisier === $("profil").value);
  $("descriere-profil").textContent = p && p.descriere ? p.descriere : "";
  $("hint-toti").textContent = p && p.doar_live
    ? "Profil „toate senzorii”: la pornire se descoperă joburile STATUS_* din calculator, iar toate rezultatele lor apar mai jos."
    : "Vrei absolut toate datele de la toți senzorii? Oprește citirea și alege profilul „toate_senzorii”.";
}

async function porneste() {
  try { dict = { ...dict, ...(await (await fetch("/nume_ro.json")).json()) }; } catch (e) { /* nume brute */ }
  reseteazaDate();
  try { profile = await api("/api/profile"); } catch (e) { eroarePagina("Nu pot citi profilele: " + e.message); }
  const sel = $("profil");
  for (const p of profile) sel.append(el("option", { value: p.fisier, text: p.eroare ? `${p.nume} (invalid)` : p.doar_live ? `${p.nume} (toți senzorii)` : p.nume, disabled: !!p.eroare }));
  const implicit = profile.find((p) => p.doar_live && !p.eroare);
  if (implicit) sel.value = implicit.fisier;
  sel.addEventListener("change", hintProfil);
  try { // marcajele profilului ales (din starea curentă, dacă rulează)
    const s = await api("/api/stare");
    if (s.profil && s.activ) sel.value = (profile.find((p) => p.nume === s.profil) || {}).fisier || sel.value;
    const lista = (profile.find((p) => p.fisier === sel.value) || {}).marcaje || s.marcaje || [];
    const z = $("marcaje");
    lista.forEach((m) => z.append(el("button", { type: "button", disabled: true, "data-tasta": m.tasta || "",
      text: (m.tasta ? `${m.tasta}. ` : "") + m.eticheta, onclick: () => marcaj(m.eticheta) })));
  } catch (e) { /* fără marcaje */ }
  hintProfil();
  $("start").addEventListener("click", start);
  $("stop").addEventListener("click", opreste);
  $("sv-buton").addEventListener("click", salveaza);
  $("in-buton").addEventListener("click", inregistreaza);
  $("cauta-valori").addEventListener("input", (ev) => { cautare = ev.target.value; aplicaFiltru(); });
  $("deschide-tot").addEventListener("click", () => { for (const d of document.querySelectorAll("#tabel-valori .grup-valori")) { d.open = true; deschise.add(d.dataset.job); } });
  $("inchide-tot").addEventListener("click", () => { deschise.clear(); for (const d of document.querySelectorAll("#tabel-valori .grup-valori")) d.open = false; });
  $("goleste-selectia").addEventListener("click", () => {
    selectate.clear();
    for (const c of Object.values(celule)) c.bifa.checked = false;
    deseneazaGrafice();
  });
  $("ingheata").addEventListener("click", () => {
    inghetat = !inghetat;
    xInghetat = inghetat ? xFereastra() : null;
    // înghețat = copii ale datelor (uPlot ține referințe la tablourile care continuă să crească)
    if (inghetat) for (const g of grafice) if (g.u) g.u.setData(g.u.data.map((a) => a.slice()), false);
    $("ingheata").setAttribute("aria-pressed", String(inghetat));
    $("ingheata").textContent = inghetat ? "Reia derularea" : "Îngheață graficele";
    $("zona-grafice").classList.toggle("live-ingheta", inghetat);
    if (!inghetat) deseneazaGrafice();
  });
  for (const r of document.querySelectorAll('input[name="fereastra"]')) {
    r.addEventListener("change", () => { ferestra = Number(r.value); if (!inghetat) deseneazaGrafice(); for (const g of grafice) if (g.u) g.u.redraw(true); });
  }
  document.addEventListener("keydown", taste);
  obs = new ResizeObserver(() => redimensioneaza());
  obs.observe($("zona-grafice"));
  if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => reconstruiesteGrafice());
  ciclu();
}

porneste();
