// Pagina „Live”: citire fără înregistrare (Etapele 11–13). Interoghează /api/live la ~0,7 s și ține în memorie
// doar fereastra afișată. Nu scrie nimic pe disc, în afară de „Salvează” cerut explicit. Doar citire.
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

let dict = { coloane: {}, unitati: {} };
let D = null; // {t:[], ciclu:[], c:{alias:[]}, cursor, evCursor, evs:[], unitati:{}, aliasuri:[], profil}
let ultima = {}; // alias -> ultima valoare nenulă
let ultimaPeRand = {}; // alias -> true dacă ultimul rând are valoare
let stare = null; // ultimul răspuns /api/live
let activeP = new Set(["Turație", "Sarcină și cuplu"]);
let ferestra = 30;
let inghetat = false;
let xInghetat = null; // intervalul x păstrat cât timp graficele sunt înghețate
let grafice = []; // [{nume, cols, card, zona, u}]
let cronometru = null, cerereInZbor = false, jeton = 0;
let obs = null;

function el(eticheta, atribute, ...copii) {
  const e = document.createElement(eticheta);
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

function eticheta(a) { const d = dict.coloane[a]; return d && d.eticheta ? d.eticheta : a; }
function unitate(a) {
  const d = dict.coloane[a];
  if (d && d.unitate_afisata !== undefined && d.unitate_afisata !== "") return d.unitate_afisata;
  const brut = D && D.unitati ? String(D.unitati[a] || "").trim() : "";
  return dict.unitati[brut] || brut;
}

function culori() {
  const st = getComputedStyle(document.documentElement);
  const g = (n) => st.getPropertyValue(n).trim() || "#888";
  return { serii: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => g("--serie-" + i)), axa: g("--slab"), grila: g("--linie"),
    ev: { marcaj: g("--ev-marcaj"), steag: g("--ev-steag"), eroare: g("--ev-eroare") } };
}

// ---------- date ----------
function reseteazaDate() {
  D = { t: [], ciclu: [], c: {}, cursor: 0, evCursor: 0, evs: [], unitati: {}, aliasuri: [], profil: null };
  ultima = {}; ultimaPeRand = {};
}

function adauga(r) {
  if (r.reset) { const aliasuri = D.aliasuri, u = D.unitati; reseteazaDate(); D.aliasuri = aliasuri; D.unitati = u; }
  if (r.aliasuri) D.aliasuri = r.aliasuri;
  D.unitati = r.unitati || D.unitati;
  D.profil = r.profil || D.profil;
  const n = r.t.length;
  for (const a of D.aliasuri) {
    const nou = r[a] || new Array(n).fill(null);
    (D.c[a] = D.c[a] || new Array(D.t.length).fill(null)).push(...nou);
    if (n) {
      const v = nou[n - 1];
      ultimaPeRand[a] = v !== null && v !== undefined;
      for (let i = n - 1; i >= 0; i--) if (nou[i] !== null && nou[i] !== undefined) { ultima[a] = nou[i]; break; }
    }
  }
  D.t.push(...r.t);
  D.ciclu.push(...r.ciclu);
  D.cursor = r.ciclu_ultim;
  for (const e of r.evenimente || []) D.evs.push(e);
  D.evCursor = r.ev_ultim !== undefined ? r.ev_ultim : D.evCursor;
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
  let r = null;
  try {
    r = await api(`/api/live?de_la_ciclu=${D.cursor}&de_la_ev=${D.evCursor}`);
    if (j !== jeton) return;
    eroarePagina("");
    stare = r;
    if (r.stare === "oprit" && !r.mod) { /* nimic de citit */ } else adauga(r);
    afiseazaStare(r);
    deseneaza();
  } catch (e) {
    if (j !== jeton) return;
    if (e.cod === 409) { stare = null; eroarePagina(e.message + " Mergi la ecranul Înregistrare."); afiseazaStare({ stare: "oprit", activ: false }); }
    else eroarePagina("Nu pot citi starea: " + e.message);
  } finally {
    cerereInZbor = false;
    clearTimeout(cronometru);
    cronometru = setTimeout(ciclu, stare && stare.activ ? INTERVAL_ACTIV_MS : INTERVAL_OPRIT_MS);
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
  deseneazaGrafice();
}

function deseneazaCartele() {
  const z = $("cartele");
  if (!D || !D.t.length) { if (!z.querySelector(".cv")) return; }
  const aliasuri = CARTELE.filter((a) => D && D.aliasuri.includes(a));
  if (!aliasuri.length) return;
  if (z.dataset.chei !== aliasuri.join(",")) {
    z.innerHTML = "";
    z.dataset.chei = aliasuri.join(",");
    for (const a of aliasuri) z.append(el("div", { class: "cv", id: "cv-" + a, title: a },
      el("div", { class: "et", text: eticheta(a) }), el("div", {}, el("span", { class: "val" }), el("span", { class: "un" }))));
  }
  for (const a of aliasuri) {
    const c = $("cv-" + a);
    c.querySelector(".val").textContent = a in ultima ? fmtVal(ultima[a]) : "–";
    c.querySelector(".un").textContent = unitate(a);
    c.classList.toggle("vechi", a in ultima && !ultimaPeRand[a]); // grup lent: ultima valoare citită, nu din ultimul ciclu
  }
}

function presetariDisponibile() {
  const disp = new Set(D ? D.aliasuri : []);
  return PRESETARI.map(([n, cols]) => [n, cols.filter((c) => disp.has(c))]).filter(([, c]) => c.length);
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
      reconstruiesteGrafice();
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
  deseneazaGrafice(true);
}

function deseneazaGrafice() {
  if (!D) return;
  deseneazaBifePresetari();
  const zona = $("zona-grafice");
  const dorite = presetariDisponibile().filter(([n]) => activeP.has(n));
  if (!dorite.length && !grafice.length) return;
  if (grafice.map((g) => g.nume).join("|") !== dorite.map(([n]) => n).join("|")) {
    for (const g of grafice) { if (g.u) g.u.destroy(); g.card.remove(); }
    grafice = dorite.map(([nume, cols]) => {
      const z = el("div", { class: "zona" });
      const card = el("section", { class: "card-grafic", "aria-label": nume }, el("h3", { text: nume }), z);
      zona.append(card);
      return { nume, cols, card, zona: z, u: null };
    });
  }
  if (inghetat) return;
  for (const g of grafice) {
    const date = [D.t, ...g.cols.map((c) => D.c[c] || new Array(D.t.length).fill(null))];
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
  if (!profil) { m.textContent = "Alege un profil."; return; }
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

async function porneste() {
  try { dict = { ...dict, ...(await (await fetch("/nume_ro.json")).json()) }; } catch (e) { /* nume brute */ }
  reseteazaDate();
  let profile = [];
  try { profile = await api("/api/profile"); } catch (e) { eroarePagina("Nu pot citi profilele: " + e.message); }
  const sel = $("profil");
  for (const p of profile) sel.append(el("option", { value: p.fisier, text: p.eroare ? `${p.nume} (invalid)` : p.nume, disabled: !!p.eroare }));
  const descr = () => { const p = profile.find((x) => x.fisier === sel.value); $("descriere-profil").textContent = p && p.descriere ? p.descriere : ""; };
  sel.addEventListener("change", descr);
  descr();
  try { // marcajele profilului ales (din starea curentă, dacă rulează)
    const s = await api("/api/stare");
    if (s.profil && s.activ) sel.value = (profile.find((p) => p.nume === s.profil) || {}).fisier || sel.value;
    const lista = (profile.find((p) => p.fisier === sel.value) || {}).marcaje || s.marcaje || [];
    const z = $("marcaje");
    lista.forEach((m) => z.append(el("button", { type: "button", disabled: true, "data-tasta": m.tasta || "",
      text: (m.tasta ? `${m.tasta}. ` : "") + m.eticheta, onclick: () => marcaj(m.eticheta) })));
  } catch (e) { /* fără marcaje */ }
  $("start").addEventListener("click", start);
  $("stop").addEventListener("click", opreste);
  $("sv-buton").addEventListener("click", salveaza);
  $("in-buton").addEventListener("click", inregistreaza);
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
