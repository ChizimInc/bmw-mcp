// Filele „Grafice” și „Tabel” ale paginii „Sesiuni” (Etapa 8). Doar citire.
// Se încarcă ÎNAINTEA lui sesiuni.js și folosește funcțiile lui (el, api, nr, minSec, eticheta, ...) la apel.
"use strict";

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
const COLOANE_EV = ["rpm", "sarcina", "pedala", "clapeta", "tmot"]; // tabelul „înainte / minim / după”
const FEREASTRA_EV_S = 5; // ±5 s în jurul evenimentului
const PUNCTE_ANSAMBLU = 5000, PUNCTE_DETALIU = 3000;
const CHEIE_SYNC = "sesiune";

// starea graficelor pentru sesiunea deschisă (se păstrează la schimbarea filelor)
let sg = null;
let grafice = []; // [{def, card, zona, u, date, brut, jeton, timer, mort}]
let propaga = false; // true cât timp setăm scala x pe toate graficele (evită bucla)
let obsRedim = null;

function stareGrafice() {
  if (!sg || sg.id !== detaliu.id) {
    sg = { id: detaliu.id, active: new Set(["Turație", "Sarcină și cuplu"]), libere: [], mod: "s",
      ev: { marcaj: true, steag: true, eroare: true }, fereastra: null, x: null, t0: null, t1: null,
      cache: new Map(), offOra: undefined, ordineLibere: 0 };
  }
  return sg;
}

function colDisponibile(d) {
  return new Set(Object.keys((d.rezumat || {}).coloane || {}));
}

function fmtVal(v) {
  if (v === null || v === undefined || !isFinite(v)) return "–";
  const p = +Number(v).toPrecision(5);
  return String(p).replace(".", ",");
}

function pad2(n) { return String(n).padStart(2, "0"); }

function fmtOra(sec, zec) { // secunde de la miezul nopții (local) → HH:MM:SS[.z]
  const z = ((sec % 86400) + 86400) % 86400;
  const h = Math.floor(z / 3600), m = Math.floor((z % 3600) / 60), s = z % 60;
  const ss = zec ? s.toFixed(zec).padStart(3 + zec, "0") : pad2(Math.floor(s));
  return `${pad2(h)}:${pad2(m)}:${ss}`;
}

function fmtRel(sec, zec) { // secunde de la start → m:ss[.z] sau h:mm:ss
  const s = Math.max(0, sec);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const rs = zec ? r.toFixed(zec).padStart(3 + zec, "0") : pad2(Math.floor(r));
  return h ? `${h}:${pad2(m)}:${rs}` : `${m}:${rs}`;
}

function secDinIso(iso) {
  const m = /[T ](\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)/.exec(iso || "");
  return m ? Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) : null;
}

// decalajul orei locale: ora (secunde de la miezul nopții) la t = 0; exact, din rândul de la t = 0
async function decalajOra() {
  const s = stareGrafice();
  if (s.offOra !== undefined) return s.offOra;
  let off = null;
  try {
    const r = await (await api(`/api/sesiuni/${encodeURIComponent(s.id)}/rand?t=0`)).json();
    const ora = secDinIso(r.t_iso);
    if (ora !== null && typeof r.t_rel_s === "number") off = ora - r.t_rel_s;
  } catch (e) { /* mai jos: alternative */ }
  if (off === null) {
    const ev = ((detaliu.date || {}).evenimente || []).find((e) => secDinIso(e.t_iso) !== null && typeof e.t_rel_s === "number");
    if (ev) off = secDinIso(ev.t_iso) - ev.t_rel_s;
  }
  if (off === null) off = secDinIso(((detaliu.date || {}).sesiune || {}).start);
  s.offOra = off;
  return off;
}

function culori() {
  const st = getComputedStyle(document.documentElement);
  const g = (n) => st.getPropertyValue(n).trim() || "#888";
  return {
    serii: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => g("--serie-" + i)),
    axa: g("--slab"), grila: g("--linie"), text: g("--text"), accent: g("--accent"),
    ev: { marcaj: g("--ev-marcaj"), steag: g("--ev-steag"), eroare: g("--ev-eroare") },
  };
}

// ---------- încărcare date ----------
function urlDate(id, cols, de_la, pana_la, max) {
  let u = `/api/sesiuni/${encodeURIComponent(id)}/date?coloane=${cols.map(encodeURIComponent).join(",")}`;
  if (de_la !== null && de_la !== undefined) u += `&de_la=${de_la}`;
  if (pana_la !== null && pana_la !== undefined) u += `&pana_la=${pana_la}`;
  if (max) u += `&max=${max}`;
  return u;
}

function catreUplot(d, cols) {
  return [d.t, ...cols.map((c) => d[c])];
}

// ---------- fila „Grafice” ----------
function tabGrafice(d) {
  const s = stareGrafice();
  const disp = colDisponibile(d);
  s.t_start = performance.now();
  s.masura = null;
  const disponibile = PRESETARI.map(([nume, cols]) => [nume, cols.filter((c) => disp.has(c))]).filter(([, c]) => c.length);
  s.preset = new Map(disponibile);
  s.disp = disp;

  const bara = el("div", { class: "bara-grafice" });
  const chipuri = el("fieldset", {}, el("legend", { text: "Grafice afișate" }),
    disponibile.map(([nume]) => el("label", {}, el("input", { type: "checkbox", checked: s.active.has(nume),
      onchange: (ev) => { if (ev.target.checked) s.active.add(nume); else s.active.delete(nume); sincronizeaza(); } }), nume)));
  const axaT = el("fieldset", {}, el("legend", { text: "Axa timpului" }),
    [["s", "secunde de la start"], ["ora", "ora locală"]].map(([v, text]) => el("label", {},
      el("input", { type: "radio", name: "axa-timp", value: v, checked: s.mod === v,
        onchange: async () => {
          if (v === "ora" && (await decalajOra()) === null) {
            mesajGrafice("Nu pot afla ora de start a sesiunii; rămâne axa în secunde.");
            document.querySelector('input[name="axa-timp"][value="s"]').checked = true;
            return;
          }
          s.mod = v;
          reconstruieste();
        } }), text)));
  const evFs = el("fieldset", {}, el("legend", { text: "Linii verticale" }),
    [["marcaj", "marcaje"], ["steag", "steaguri"], ["eroare", "erori noi"]].map(([k, text]) => el("label", {},
      el("input", { type: "checkbox", checked: s.ev[k], onchange: (ev) => { s.ev[k] = ev.target.checked; redeseneaza(); } }),
      el("span", { class: "cheie-ev " + k }), text)));
  bara.append(chipuri, axaT, evFs);

  // grafic liber: alegere de coloane
  const grupuri = new Map();
  const ordine = Object.keys(dict.coloane);
  [...disp].sort((a, b) => {
    const ia = ordine.indexOf(a), ib = ordine.indexOf(b);
    return (ia < 0 ? 1e6 : ia) - (ib < 0 ? 1e6 : ib) || a.localeCompare(b);
  }).forEach((a) => {
    const g = (dict.coloane[a] || {}).grup || "Altele";
    if (!grupuri.has(g)) grupuri.set(g, []);
    grupuri.get(g).push(a);
  });
  const bife = new Map();
  const liber = el("details", { class: "sectiune" }, el("summary", { text: "Grafic liber: alege coloanele" }),
    el("div", { class: "bara-grafice" }, [...grupuri].map(([g, cols]) => el("fieldset", {}, el("legend", { text: g }),
      cols.map((c) => {
        const i = el("input", { type: "checkbox", value: c });
        bife.set(c, i);
        return el("label", { title: c }, i, eticheta(c));
      })))),
    el("button", { type: "button", text: "Adaugă graficul", onclick: () => {
      const alese = [...bife].filter(([, i]) => i.checked).map(([c]) => c);
      if (!alese.length) { mesajGrafice("Bifează cel puțin o coloană."); return; }
      if (alese.length > 8) { mesajGrafice("Cel mult 8 coloane într-un grafic."); return; }
      mesajGrafice("");
      s.libere.push({ id: ++s.ordineLibere, cols: alese });
      bife.forEach((i) => { i.checked = false; });
      sincronizeaza();
    } }));

  const navig = el("div", { class: "bara-grafice" },
    el("button", { type: "button", text: "Vedere de ansamblu", title: "Dublu-click pe un grafic face același lucru", onclick: reseteaza }),
    el("button", { type: "button", text: "−", "aria-label": "Micșorează (mai mult din timp)", onclick: () => deplaseaza(2, 0) }),
    el("button", { type: "button", text: "+", "aria-label": "Mărește (mai puțin timp)", onclick: () => deplaseaza(0.5, 0) }),
    el("button", { type: "button", text: "←", "aria-label": "Mută spre început", onclick: () => deplaseaza(1, -0.5) }),
    el("button", { type: "button", text: "→", "aria-label": "Mută spre sfârșit", onclick: () => deplaseaza(1, 0.5) }),
    el("span", { class: "mic", text: "Zoom: trage cu mouse-ul pe grafic. Dublu-click = vedere de ansamblu. Cursorul e sincronizat între grafice; sub cursor, valorile apar în legendă („~” = ultima valoare citită, la grupurile lente)." }));

  const info = el("p", { class: "info-ev", id: "info-ev", role: "status" }, "Treci cu mouse-ul peste o linie verticală ca să vezi evenimentul.");
  const msg = el("p", { class: "mesaj eroare", id: "mesaj-grafice", role: "alert", hidden: true });
  const panou = el("div", { id: "panou-ev" });
  const zona = el("div", { id: "zona-grafice" });
  const masura = el("p", { class: "mic", id: "masura-grafice", role: "status" });
  if (!disponibile.length) zona.append(gol("Sesiunea nu are coloanele din presetări; folosește „Grafic liber”."));

  queueMicrotask(() => {
    if (obsRedim) obsRedim.disconnect();
    obsRedim = new ResizeObserver(() => redimensioneaza());
    obsRedim.observe(zona);
    sincronizeaza();
    afiseazaPanouEv();
  });
  return [bara, liber, navig, panou, msg, info, zona, masura];
}

function mesajGrafice(t) {
  const m = document.getElementById("mesaj-grafice");
  if (!m) return;
  m.textContent = t || "";
  m.hidden = !t;
}

function defGrafice() {
  const s = sg;
  const rez = [];
  for (const [nume, cols] of s.preset) if (s.active.has(nume)) rez.push({ cheie: "p:" + nume, titlu: nume, cols, liber: null });
  for (const l of s.libere) rez.push({ cheie: "l:" + l.id, titlu: "Grafic liber: " + l.cols.map(eticheta).join(", "), cols: l.cols, liber: l.id });
  return rez;
}

function sincronizeaza() {
  const zona = document.getElementById("zona-grafice");
  if (!zona || !sg) return;
  const dorite = defGrafice();
  const chei = new Set(dorite.map((d) => d.cheie));
  for (const g of grafice.filter((g) => !chei.has(g.def.cheie))) distruge(g);
  grafice = grafice.filter((g) => chei.has(g.def.cheie));
  for (const def of dorite) {
    let g = grafice.find((x) => x.def.cheie === def.cheie);
    if (!g) { g = creeazaCard(def); grafice.push(g); zona.append(g.card); incarcaInitial(g); }
    else zona.append(g.card); // păstrează ordinea cerută
  }
  grafice.sort((a, b) => dorite.findIndex((d) => d.cheie === a.def.cheie) - dorite.findIndex((d) => d.cheie === b.def.cheie));
}

function creeazaCard(def) {
  const zona = el("div", { class: "zona se-incarca", text: "Se încarcă…" });
  const titlu = el("h3", {}, el("span", { text: def.titlu }),
    def.liber ? el("button", { type: "button", text: "Elimină", onclick: () => {
      sg.libere = sg.libere.filter((l) => l.id !== def.liber);
      sincronizeaza();
    } }) : null);
  const card = el("section", { class: "card-grafic", "aria-label": def.titlu }, titlu, zona);
  return { def, card, zona, u: null, date: null, brut: null, jeton: 0, timer: null, mort: false };
}

function distruge(g) {
  g.mort = true;
  clearTimeout(g.timer);
  if (g.u) { g.u.destroy(); g.u = null; }
  g.card.remove();
}

function curataGrafice() { // apelat când se părăsește fila
  grafice.forEach(distruge);
  grafice = [];
  if (obsRedim) { obsRedim.disconnect(); obsRedim = null; }
}

function reconstruieste() {
  grafice.forEach(distruge);
  grafice = [];
  sincronizeaza();
}

function redeseneaza() {
  grafice.forEach((g) => g.u && g.u.redraw(false));
}

async function incarcaInitial(g) {
  const s = sg, fr = detaliu.fr, cheieCache = (fr ? `${fr.de}-${fr.pana}|` : "") + g.def.cols.join(",");
  try {
    let d = s.cache.get(cheieCache);
    const t0 = performance.now();
    if (!d) { // cu fragment: datele fragmentului la rezoluție completă (max 5000 de puncte doar pe fragment)
      d = await (await api(urlDate(s.id, g.def.cols, fr ? fr.de : null, fr ? fr.pana : null, PUNCTE_ANSAMBLU))).json();
      s.cache.set(cheieCache, d);
    }
    if (g.mort) return;
    g.descarcare = performance.now() - t0;
    g.brut = g.date = d;
    if (!d.t || !d.t.length) { g.zona.textContent = fr ? "Fără rânduri de date în fragment." : "Fără rânduri de date."; return; }
    if (fr) { s.t0 = fr.de; s.t1 = fr.pana; } // vederea de ansamblu = exact fragmentul
    else {
      s.t0 = s.t0 === null ? d.t[0] : Math.min(s.t0, d.t[0]);
      s.t1 = s.t1 === null ? d.t[d.t.length - 1] : Math.max(s.t1, d.t[d.t.length - 1]);
    }
    if (s.mod === "ora") await decalajOra();
    if (g.mort) return;
    construieste(g);
  } catch (e) {
    if (!g.mort) { g.zona.className = "zona"; g.zona.textContent = "Nu pot încărca datele: " + e.message; }
  }
}

function latimeCard(g) {
  return Math.max(260, Math.floor(g.card.clientWidth - 18));
}

function inaltimeGrafic() {
  return window.innerWidth <= 640 ? 190 : 240;
}

function construieste(g) {
  const s = sg, c = culori(), cols = g.def.cols;
  const off = s.mod === "ora" ? (s.offOra || 0) : 0;
  const unitati = [];
  const scaraUnit = (col) => {
    let un = unitateColoana(col, (detaliu.date || {}).coloane || {}) || "";
    if (un.startsWith("%")) un = "%"; // „% pedală”, „% clapetă” și „%” împart aceeași axă
    if (!unitati.includes(un)) unitati.push(un);
    return "u:" + un;
  };
  const serii = [{ label: s.mod === "ora" ? "Ora" : "Timp", value: (u, v) => (v === null || v === undefined ? "–"
    : s.mod === "ora" ? fmtOra(v + off, 2) : `${fmtRel(v, 1)} (${fmtVal(v)} s)`) }];
  cols.forEach((col, i) => {
    const un = unitateColoana(col, (detaliu.date || {}).coloane || {});
    serii.push({
      label: eticheta(col) + (un ? ` (${un})` : ""), scale: scaraUnit(col), stroke: c.serii[i % 8], width: 1.6,
      spanGaps: true, points: { size: 5 },
      value: (u, v, si, idx) => {
        if (v !== null && v !== undefined) return fmtVal(v);
        const ix = idx === undefined || idx === null ? u.cursor.idx : idx;
        const ser = u.data[si];
        if (ix === null || ix === undefined) return "–";
        for (let k = ix, lim = 400; k >= 0 && lim > 0; k--, lim--) if (ser[k] !== null && ser[k] !== undefined) return "~" + fmtVal(ser[k]);
        return "–";
      },
    });
  });
  const scale = { x: { time: false } };
  unitati.forEach((un) => { scale["u:" + un] = { auto: true }; });
  const axaX = {
    stroke: c.axa, grid: { stroke: c.grila, width: 1 }, ticks: { stroke: c.grila, width: 1 }, size: 34,
    splits: (u, ai, min, max, incr) => {
      const nice = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400];
      const pas = nice.find((n) => n >= incr) || incr;
      const prim = Math.ceil((min + off) / pas) * pas - off;
      const rez = [];
      for (let k = 0; prim + k * pas <= max + 1e-9 && k < 400; k++) rez.push(+(prim + k * pas).toFixed(3));
      return rez;
    },
    values: (u, spl) => {
      const pas = spl.length > 1 ? spl[1] - spl[0] : 1, zec = pas < 1 ? 1 : 0;
      return spl.map((v) => (s.mod === "ora" ? fmtOra(v + off, zec) : fmtRel(v, zec)));
    },
  };
  const axe = [axaX];
  unitati.forEach((un, i) => axe.push({
    scale: "u:" + un, side: i % 2 === 0 ? 3 : 1, stroke: c.axa, label: un || "", labelSize: un ? 18 : 0, labelFont: "12px system-ui",
    grid: { show: i === 0, stroke: c.grila, width: 1 }, ticks: { stroke: c.grila, width: 1 }, size: 54,
    values: (u, spl) => spl.map(fmtVal),
  }));

  g.zona.className = "zona";
  g.zona.textContent = "";
  const opts = {
    width: latimeCard(g), height: inaltimeGrafic(), scales: scale, series: serii, axes: axe,
    cursor: { sync: { key: CHEIE_SYNC, scales: [null, null] }, drag: { x: true, y: false, setScale: true },
      bind: { dblclick: () => null } },
    legend: { live: true },
    hooks: {
      draw: [(u) => deseneazaEv(u)],
      setScale: [(u, cheie) => laScala(g, u, cheie)],
      setCursor: [(u) => laCursor(u)],
      ready: [(u) => { u.over.addEventListener("dblclick", reseteaza); }],
    },
  };
  const date = catreUplot(g.date, cols);
  g.u = new uPlot(opts, date, g.zona);
  if (s.x) { // fereastra aleasă (salt la eveniment sau zoom păstrat la reconstruire)
    propaga = true;
    try { g.u.setScale("x", { min: s.x.min, max: s.x.max }); } finally { propaga = false; }
    g.timer = setTimeout(() => cereDetaliu(g), 100);
  }
  anuntaDesenat(g);
}

function anuntaDesenat(g) {
  const s = sg;
  if (!s || s.masura) return;
  if (grafice.every((x) => x.u || x.mort || (x.zona && !x.zona.classList.contains("se-incarca")))) {
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (!sg || sg.masura) return;
      const total = performance.now() - sg.t_start;
      const desc = Math.max(0, ...grafice.map((x) => x.descarcare || 0));
      sg.masura = { total, desc };
      const m = document.getElementById("masura-grafice");
      if (m) m.textContent = `Măsurat: ${Math.round(total)} ms până la afișarea celor ${grafice.length} grafice (descărcarea datelor: ${Math.round(desc)} ms).`;
      window.__masuraGrafice = sg.masura;
    }));
  }
}

function redimensioneaza() {
  grafice.forEach((g) => g.u && g.u.setSize({ width: latimeCard(g), height: inaltimeGrafic() }));
}

// ---------- zoom, detaliu la zoom ----------
function puneDate(g, date) {
  // setData(…, false) păstrează zoom-ul, dar nu recalculează indicii vizibili; redraw(true) îi recalculează
  g.interna = true;
  try { g.u.setData(catreUplot(date, g.def.cols), false); g.u.redraw(true); } finally { g.interna = false; }
}

function laScala(g, u, cheie) {
  if (cheie !== "x" || !sg || g.interna) return;
  const { min, max } = u.scales.x;
  if (g.ultX && g.ultX[0] === min && g.ultX[1] === max) return; // același interval (ex. după setData): nu face nimic
  g.ultX = [min, max];
  if (!propaga) {
    sg.x = (sg.t0 !== null && min <= sg.t0 + 1e-6 && max >= sg.t1 - 1e-6) ? null : { min, max };
    propaga = true;
    try { grafice.forEach((o) => { if (o.u && o !== g) o.u.setScale("x", { min, max }); }); } finally { propaga = false; }
  }
  clearTimeout(g.timer);
  g.timer = setTimeout(() => cereDetaliu(g), 220);
}

async function cereDetaliu(g) {
  if (!g.u || g.mort || !sg) return;
  const { min, max } = g.u.scales.x;
  const lat = max - min, total = (sg.t1 - sg.t0) || 1;
  const jeton = ++g.jeton;
  if (lat >= 0.95 * total) {
    if (g.date !== g.brut) { g.date = g.brut; puneDate(g, g.brut); }
    return;
  }
  try {
    const d = await (await api(urlDate(sg.id, g.def.cols, (min - 0.25 * lat).toFixed(3), (max + 0.25 * lat).toFixed(3), PUNCTE_DETALIU))).json();
    if (g.mort || jeton !== g.jeton || !g.u) return;
    g.date = d;
    puneDate(g, d);
  } catch (e) { /* rămâne vederea curentă */ }
}

function seteazaX(min, max) {
  sg.x = (min <= sg.t0 + 1e-6 && max >= sg.t1 - 1e-6) ? null : { min, max };
  propaga = true;
  try { grafice.forEach((g) => g.u && g.u.setScale("x", { min, max })); } finally { propaga = false; }
}

function reseteaza() {
  if (!sg) return;
  sg.fereastra = null;
  afiseazaPanouEv();
  seteazaX(sg.t0, sg.t1);
}

function deplaseaza(factor, deplasare) {
  const g = grafice.find((x) => x.u);
  if (!g || !sg) return;
  const { min, max } = g.u.scales.x;
  const lat = (max - min) * factor, centru = (min + max) / 2 + deplasare * (max - min);
  let a = centru - lat / 2, b = centru + lat / 2;
  if (a < sg.t0) { b += sg.t0 - a; a = sg.t0; }
  if (b > sg.t1) { a -= b - sg.t1; b = sg.t1; }
  seteazaX(Math.max(a, sg.t0), Math.min(b, sg.t1));
}

// ---------- evenimente pe grafic ----------
function evenimenteVizibile() {
  return ((detaliu && detaliu.date.evenimente) || []).filter((e) => typeof e.t_rel_s === "number" && sg.ev[e.tip]);
}

function deseneazaEv(u) {
  if (!sg) return;
  const c = culori(), ctx = u.ctx, dpr = window.devicePixelRatio || 1, { left, top, width, height } = u.bbox;
  ctx.save();
  ctx.beginPath();
  ctx.rect(left, top, width, height);
  ctx.clip();
  const sel = sg.fereastra && sg.fereastra.ev;
  for (const e of evenimenteVizibile()) {
    const x = Math.round(u.valToPos(e.t_rel_s, "x", true));
    if (x < left - 2 || x > left + width + 2) continue;
    const alesul = sel && sel === e;
    ctx.strokeStyle = alesul ? c.accent : c.ev[e.tip];
    ctx.lineWidth = (alesul ? 3 : 1) * dpr;
    ctx.globalAlpha = alesul ? 1 : 0.75;
    ctx.setLineDash(e.tip === "steag" || alesul ? [] : [5 * dpr, 4 * dpr]);
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + height);
    ctx.stroke();
  }
  ctx.restore();
}

function laCursor(u) {
  const info = document.getElementById("info-ev");
  if (!info || !sg) return;
  const left = u.cursor.left;
  if (left === undefined || left === null || left < 0) return;
  const { min, max } = u.scales.x;
  const pxPeSec = (u.bbox.width / (window.devicePixelRatio || 1)) / ((max - min) || 1);
  const t = u.posToVal(left, "x");
  let cel = null, dist = 1e9;
  for (const e of evenimenteVizibile()) {
    const dx = Math.abs(e.t_rel_s - t) * pxPeSec;
    if (dx < dist) { dist = dx; cel = e; }
  }
  if (cel && dist <= 7) info.textContent = `${fmtRel(cel.t_rel_s, 1)} · ${cel.tip}: ${cel.detalii}`;
  else info.textContent = `Cursor: ${fmtRel(t, 1)} de la start. Treci peste o linie verticală ca să vezi evenimentul.`;
}

// ---------- salt de la un eveniment ----------
function sariLaEveniment(e) {
  if (typeof e.t_rel_s !== "number") return;
  const s = stareGrafice();
  const fr = detaliu.fr;
  if (fr && (e.t_rel_s < fr.de || e.t_rel_s > fr.pana)) { // evenimentul e în afara fragmentului: se renunță la fragment
    detaliu.fr = null;
    detaliu.rezFr = null;
    s.cache.clear(); s.t0 = s.t1 = null;
    actualizeazaFragment();
  }
  const lim = detaliu.fr;
  s.fereastra = { t: e.t_rel_s, ev: e, valori: null };
  s.x = { min: lim ? Math.max(e.t_rel_s - FEREASTRA_EV_S, lim.de) : e.t_rel_s - FEREASTRA_EV_S,
    max: lim ? Math.min(e.t_rel_s + FEREASTRA_EV_S, lim.pana) : e.t_rel_s + FEREASTRA_EV_S };
  for (const nume of ["Turație", "Sarcină și cuplu", "Temperaturi"]) s.active.add(nume);
  alegeTab("grafice");
}

function valoareLa(t, v, tc, tol) { // valoarea nenulă cea mai apropiată de tc, în ±tol secunde
  let lo = 0, hi = t.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (t[m] < tc) lo = m + 1; else hi = m; }
  let cel = null, dist = tol + 1e-9;
  for (let k = lo - 1; k >= 0 && tc - t[k] <= tol; k--) if (v[k] !== null && v[k] !== undefined) { cel = v[k]; dist = tc - t[k]; break; }
  for (let k = lo; k < t.length && t[k] - tc <= tol; k++) {
    if (v[k] !== null && v[k] !== undefined) { if (t[k] - tc < dist) cel = v[k]; break; }
  }
  return cel;
}

async function afiseazaPanouEv() {
  const p = document.getElementById("panou-ev");
  if (!p || !sg) return;
  p.innerHTML = "";
  const f = sg.fereastra;
  if (!f) return;
  const id = sg.id;
  const e = f.ev;
  const cols = COLOANE_EV.filter((c) => sg.disp.has(c));
  const tb = tabel(["Mărime", ["Înainte", true], ["Minim", true], ["Moment minim", true], ["După", true], ["Minim − înainte", true]], []);
  const corp = tb.querySelector("tbody");
  p.append(el("div", { class: "panou-ev" },
    el("h3", { text: `Eveniment la ${fmtRel(e.t_rel_s, 1)} (${e.tip})` }),
    el("p", { text: e.detalii }),
    el("p", { class: "mic", text: `Fereastra afișată: ±${FEREASTRA_EV_S} s. „Înainte” = valoarea cu 3 s înainte de eveniment, „După” = la 3 s după; „Minim” = cea mai mică valoare din fereastră (și când a apărut, față de eveniment).` }),
    cols.length ? tb : gol("Sesiunea nu are mărimile pentru acest tabel."),
    el("button", { type: "button", text: "Închide fereastra (vedere de ansamblu)", onclick: reseteaza })));
  if (!cols.length) return;
  corp.append(el("tr", {}, el("td", { colspan: 6, class: "gol", text: "Se calculează…" })));
  try {
    const d = await (await api(urlDate(id, cols, e.t_rel_s - FEREASTRA_EV_S, e.t_rel_s + FEREASTRA_EV_S))).json();
    if (!sg || sg.id !== id || sg.fereastra !== f) return;
    corp.innerHTML = "";
    for (const c of cols) {
      const v = d[c], t = d.t;
      let min = null, tmin = null;
      v.forEach((x, i) => { if (x !== null && (min === null || x < min)) { min = x; tmin = t[i]; } });
      const inainte = valoareLa(t, v, e.t_rel_s - 3, 1.5), dupa = valoareLa(t, v, e.t_rel_s + 3, 1.5);
      const un = unitateColoana(c, (detaliu.date || {}).coloane || {});
      corp.append(el("tr", {},
        el("td", { title: c, text: eticheta(c) + (un ? ` (${un})` : "") }),
        el("td", { class: "nr", text: fmtVal(inainte) }),
        el("td", { class: "nr", text: fmtVal(min) }),
        el("td", { class: "nr fara-rupere", text: tmin === null ? "–" : `${(tmin - e.t_rel_s >= 0 ? "+" : "−")}${Math.abs(tmin - e.t_rel_s).toFixed(1).replace(".", ",")} s` }),
        el("td", { class: "nr", text: fmtVal(dupa) }),
        el("td", { class: "nr", text: inainte === null || min === null ? "–" : fmtVal(min - inainte) })));
    }
  } catch (err) {
    corp.innerHTML = "";
    corp.append(el("tr", {}, el("td", { colspan: 6, class: "gol", text: "Nu pot calcula tabelul: " + err.message })));
  }
}

// tema (deschis/închis) se citește la construirea graficelor; la schimbare se reconstruiesc
if (window.matchMedia) {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (grafice.length) reconstruieste(); });
}

// ---------- fila „Tabel” (virtualizat) ----------
const INALTIME_RAND = 26;
const LATIME_COL = 92;

function parseTimp(txt) {
  const t = String(txt || "").trim().replace(",", ".");
  if (!t) return null;
  const m = /^(\d+):(\d{1,2}(?:\.\d+)?)$/.exec(t);
  if (m) return Number(m[1]) * 60 + Number(m[2]);
  const v = Number(t);
  return isFinite(v) ? v : null;
}

function limitaInf(a, x) { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (a[m] < x) lo = m + 1; else hi = m; } return lo; }
function limitaSup(a, x) { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (a[m] <= x) lo = m + 1; else hi = m; } return lo; }

function tabTabel(d) {
  const id = d.id;
  const radacina = el("div", { id: "zona-tabel" }, gol("Se încarcă tabelul…"));
  const t0 = performance.now();
  const cols = ["ciclu", ...Object.keys((d.rezumat || {}).coloane || {}).filter((c) => c !== "ciclu")];
  (async () => {
    try {
      const date = detaliu.tabel && detaliu.tabel.id === id ? detaliu.tabel.date
        : await (await api(urlDate(id, [...cols, "marcaj", "steaguri"], null, null, 0))).json();
      if (!detaliu || detaliu.id !== id || tabCurent !== "tabel") return;
      detaliu.tabel = { id, date };
      const off = await decalajOra();
      if (!detaliu || detaliu.id !== id || tabCurent !== "tabel") return;
      const ms = performance.now() - t0;
      radacina.innerHTML = "";
      radacina.append(...construiesteTabel(d, date, cols, off, ms));
    } catch (e) {
      radacina.innerHTML = "";
      radacina.append(gol("Nu pot încărca tabelul: " + e.message));
    }
  })();
  return radacina;
}

function construiesteTabel(d, date, cols, off, msIncarcare) {
  const t = date.t, n = t.length;
  const ordine = Object.keys(dict.coloane);
  const defs = cols.filter((c) => date[c]).map((c) => ({
    k: c, titlu: eticheta(c), unit: unitateColoana(c, d.coloane || {}), grup: (dict.coloane[c] || {}).grup || "Altele",
  }));
  defs.sort((a, b) => {
    const ia = ordine.indexOf(a.k), ib = ordine.indexOf(b.k);
    return (ia < 0 ? 1e6 : ia) - (ib < 0 ? 1e6 : ib);
  });
  const grupuri = [...new Set(defs.map((c) => c.grup))];
  const ascunse = new Set();
  const marcate = [];
  for (let i = 0; i < n; i++) if (date.marcaj[i] || date.steaguri[i]) marcate.push(i);

  let vis = [], colV = [], randuri = [], primul = -1, ultimul = -1, versiune = 0;
  const scroller = el("div", { class: "tv-scroller", tabindex: "0", role: "region", "aria-label": "Tabelul datelor sesiunii" });
  const inner = el("div", { class: "tv-inner" });
  const antet = el("div", { class: "tv-antet" });
  const corp = el("div", { class: "tv-corp" });
  inner.append(antet, corp);
  scroller.append(inner);
  const numar = el("p", { class: "mic", role: "status" });

  const celule = () => [
    { k: "#t", latime: 76, text: true, fix: 0, titlu: "Timp", unit: "s" },
    { k: "#ora", latime: 92, text: true, fix: 76, titlu: "Ora", unit: "locală", ultimaFixa: true },
    ...colV.map((c) => ({ ...c, latime: LATIME_COL })),
    { k: "marcaj", latime: 170, text: true, titlu: "Marcaj", unit: "" },
    { k: "steaguri", latime: 220, text: true, titlu: "Steaguri", unit: "" },
  ];

  function reconstruiesteColoane() {
    colV = defs.filter((c) => !ascunse.has(c.grup));
    const cs = celule();
    const latTot = cs.reduce((a, c) => a + c.latime, 0);
    inner.style.width = latTot + "px";
    antet.style.width = latTot + "px";
    antet.innerHTML = "";
    for (const c of cs) {
      antet.append(el("div", { class: "tv-c" + (c.text ? " text" : "") + (c.fix !== undefined ? " fix" + (c.ultimaFixa ? " fix2" : "") : ""),
        style: `width:${c.latime}px;` + (c.fix !== undefined ? `left:${c.fix}px` : ""), title: c.k.startsWith("#") || c.k === "marcaj" || c.k === "steaguri" ? c.titlu : `${c.k} — ${c.titlu}` },
      el("div", { class: "et", text: c.titlu }), el("div", { class: "un", text: c.unit || "" })));
    }
    randuri.forEach((r) => r.el.remove());
    randuri = [];
    versiune++;
    primul = ultimul = -1;
    deseneaza();
  }

  function rand() {
    const cs = celule();
    const r = el("div", { class: "tv-rand", style: `width:${cs.reduce((a, c) => a + c.latime, 0)}px` });
    const cel = cs.map((c) => {
      const x = el("div", { class: "tv-c" + (c.text ? " text" : "") + (c.fix !== undefined ? " fix" + (c.ultimaFixa ? " fix2" : "") : ""),
        style: `width:${c.latime}px;` + (c.fix !== undefined ? `left:${c.fix}px` : "") });
      r.append(x);
      return x;
    });
    corp.append(r);
    return { el: r, cel, i: -1, v: -1, cs };
  }

  function umple(r, pozitie) {
    const i = vis[pozitie];
    if (r.i === i && r.v === versiune) { r.el.style.transform = `translateY(${pozitie * INALTIME_RAND}px)`; return; }
    r.i = i; r.v = versiune;
    r.el.style.transform = `translateY(${pozitie * INALTIME_RAND}px)`;
    r.el.style.display = "";
    r.el.className = "tv-rand" + (date.marcaj[i] ? " rm" : date.steaguri[i] ? " rs" : "");
    const cs = r.cs;
    for (let j = 0; j < cs.length; j++) {
      const k = cs[j].k;
      let txt;
      if (k === "#t") txt = fmtVal(t[i]);
      else if (k === "#ora") txt = off === null ? "–" : fmtOra(t[i] + off, 1);
      else if (k === "marcaj" || k === "steaguri") txt = date[k][i];
      else {
        const v = date[k][i];
        txt = v === null || v === undefined ? "" : (k === "ciclu" ? String(v) : fmtVal(v));
      }
      r.cel[j].textContent = txt;
    }
  }

  let cadru = 0;
  function deseneaza() {
    cadru = 0;
    const vh = scroller.clientHeight || 400;
    const dela = Math.max(0, Math.floor(scroller.scrollTop / INALTIME_RAND) - 8);
    const panala = Math.min(vis.length, Math.ceil((scroller.scrollTop + vh) / INALTIME_RAND) + 8);
    const nevoie = Math.max(0, panala - dela);
    while (randuri.length < nevoie) randuri.push(rand());
    for (let k = 0; k < randuri.length; k++) {
      if (k < nevoie) {
        // rândurile sunt legate de poziția (dela + k) → același rând din date rămâne pe același element la scroll mic
        umple(randuri[k], dela + k);
      } else randuri[k].el.style.display = "none";
    }
    primul = dela; ultimul = panala;
  }
  scroller.addEventListener("scroll", () => { if (!cadru) cadru = requestAnimationFrame(deseneaza); }, { passive: true });
  if (window.ResizeObserver) new ResizeObserver(() => { if (scroller.isConnected) deseneaza(); }).observe(scroller);

  const fDe = el("input", { type: "text", id: "tv-de", placeholder: "ex. 120 sau 2:00", "aria-label": "De la timpul (secunde sau m:ss)" });
  const fPana = el("input", { type: "text", id: "tv-pana", placeholder: "ex. 180 sau 3:00", "aria-label": "Până la timpul (secunde sau m:ss)" });
  const fMarcate = el("input", { type: "checkbox", id: "tv-marcate" });
  function filtreaza() {
    const fr = detaliu && detaliu.fr; // fragmentul global e limita; filtrul de aici se aplică în interiorul lui
    let de = parseTimp(fDe.value), pana = parseTimp(fPana.value);
    if (fr) { de = de === null ? fr.de : Math.max(de, fr.de); pana = pana === null ? fr.pana : Math.min(pana, fr.pana); }
    const a = de === null ? 0 : limitaInf(t, de), b = pana === null ? n : limitaSup(t, pana);
    if (fMarcate.checked) vis = marcate.filter((i) => i >= a && i < b);
    else { vis = new Array(Math.max(0, b - a)); for (let k = 0; k < vis.length; k++) vis[k] = a + k; }
    corp.style.height = vis.length * INALTIME_RAND + "px";
    scroller.scrollTop = 0;
    randuri.forEach((r) => { r.v = -1; });
    numar.textContent = `${vis.length.toLocaleString("ro-RO")} din ${n.toLocaleString("ro-RO")} rânduri afișate.`
      + (de !== null || pana !== null ? (fr ? " Fragment activ: " : " Interval: ") + (de === null ? "început" : fmtRel(de, 1)) + " – " + (pana === null ? "sfârșit" : fmtRel(pana, 1)) + "." : "");
    deseneaza();
  }
  fDe.addEventListener("input", filtreaza);
  fPana.addEventListener("input", filtreaza);
  fMarcate.addEventListener("change", filtreaza);

  const bifeGrupuri = el("div", { class: "grupuri-col" }, grupuri.map((g) => el("label", {},
    el("input", { type: "checkbox", checked: true, onchange: (ev) => { if (ev.target.checked) ascunse.delete(g); else ascunse.add(g); reconstruiesteColoane(); } }), g)));

  const bara = el("div", { class: "bara-tabel" },
    el("label", {}, "De la timp", fDe), el("label", {}, "Până la timp", fPana),
    el("label", { class: "bifa" }, fMarcate, "doar rândurile cu marcaj sau steag"),
    el("button", { type: "button", text: "Șterge filtrele", onclick: () => { fDe.value = ""; fPana.value = ""; fMarcate.checked = false; filtreaza(); } }));
  const grupDetalii = el("details", { class: "sectiune" }, el("summary", { text: "Grupuri de coloane afișate" }), bifeGrupuri);

  reconstruiesteColoane();
  filtreaza();
  // măsurare: primul desen
  requestAnimationFrame(() => {
    const mas = `Măsurat: ${Math.round(msIncarcare)} ms pentru descărcare și pregătire (${n.toLocaleString("ro-RO")} rânduri × ${defs.length} coloane); se desenează doar rândurile vizibile.`;
    numar.title = mas;
    window.__masuraTabel = { ms: msIncarcare, randuri: n, coloane: defs.length };
    const m = document.getElementById("masura-tabel");
    if (m) m.textContent = mas;
  });
  return [bara, grupDetalii, numar, scroller,
    el("p", { class: "mic", id: "masura-tabel", role: "status" }),
    el("p", { class: "mic", text: "Celulele goale = grup lent necitit în acel ciclu. Verde = rând cu marcaj, galben = rând cu steag. Numele scurt al coloanei apare la hover pe antet." })];
}
