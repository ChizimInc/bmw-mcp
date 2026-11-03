// Interfata loggerului: polling la 1 s pe API. Fara grafice.
"use strict";

const $ = (id) => document.getElementById(id);
const NUME_STARE = {
  oprit: "oprit", porneste: "pornește", inregistreaza: "înregistrează",
  opreste: "se oprește", reconectare: "reconectare", eroare: "eroare",
};
let profile = [];
let ultimulJurnal = 0;
let stareCurenta = null;
let marcajeAfisate = "";

async function api(cale, corp) {
  const opt = corp === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corp),
  };
  const r = await fetch(cale, opt);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.eroare || `Eroare ${r.status}`);
  return d;
}

function mesaj(text, eroare = false) {
  const m = $("mesaj");
  m.textContent = text;
  m.className = "mesaj" + (eroare ? " eroare" : "");
}

function timp(s) {
  s = Math.floor(s || 0);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(sec).padStart(2, "0");
}

function numar(v) {
  if (v === null || v === undefined || v === "") return "–";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(3).replace(/\.?0+$/, "");
  return String(v);
}

async function incarcaProfile() {
  try {
    profile = await api("/api/profile");
  } catch (e) {
    mesaj("Nu pot citi profilele: " + e.message, true);
    return;
  }
  const sel = $("profil");
  const ales = sel.value;
  sel.innerHTML = "";
  for (const p of profile) {
    const o = document.createElement("option");
    o.value = p.fisier;
    o.textContent = p.eroare ? `${p.nume} (invalid)` : p.nume;
    sel.appendChild(o);
  }
  if (ales) sel.value = ales;
  afiseazaDescriere();
}

function afiseazaDescriere() {
  const p = profile.find((x) => x.fisier === $("profil").value);
  const d = $("descriere");
  if (!p) { d.textContent = ""; return; }
  d.textContent = p.eroare || p.descriere || "";
  d.className = "descriere" + (p.eroare ? " mesaj eroare" : "");
}

function afiseazaMarcaje(lista, activ) {
  const cheie = JSON.stringify(lista) + activ;
  if (cheie === marcajeAfisate) return;
  marcajeAfisate = cheie;
  const box = $("marcaje");
  box.innerHTML = "";
  if (!lista || !lista.length) {
    box.innerHTML = '<p class="gol">Apar după Start.</p>';
    return;
  }
  for (const m of lista) {
    const b = document.createElement("button");
    b.disabled = !activ;
    if (m.tasta) {
      const t = document.createElement("span");
      t.className = "tasta";
      t.textContent = m.tasta;
      b.appendChild(t);
    }
    b.appendChild(document.createTextNode(m.eticheta));
    b.addEventListener("click", () => trimiteMarcaj(m.eticheta));
    box.appendChild(b);
  }
}

function afiseazaStare(s) {
  stareCurenta = s;
  $("conexiune").hidden = true;
  const st = $("s-stare");
  st.textContent = NUME_STARE[s.stare] || s.stare;
  st.className = "eticheta " + ({ inregistreaza: "verde", porneste: "galben", opreste: "galben",
    reconectare: "galben", eroare: "rosu" }[s.stare] || "");
  if (s.stare === "oprit" && s.motiv_oprire) st.textContent += ` (${s.motiv_oprire})`;

  const u = $("s-ultima");
  if (!s.activ || s.ultima_reusita_s === null) {
    u.textContent = s.activ ? "încă nicio citire" : "–";
    u.className = "eticheta" + (s.activ ? " rosu" : "");
  } else {
    const x = s.ultima_reusita_s;
    u.textContent = `acum ${x.toFixed(1)} s`;
    u.className = "eticheta " + (x < 2 ? "verde" : x <= 5 ? "galben" : "rosu");
  }
  $("s-profil").textContent = s.profil || "–";
  $("s-sursa").textContent = s.sursa || s.sursa_tip;
  $("s-timp").textContent = s.profil ? timp(s.timp_s) : "–";
  $("s-randuri").textContent = s.randuri;
  $("s-cps").textContent = s.activ ? s.cicluri_pe_s.toFixed(2) : "–";
  $("s-erori").textContent = s.erori;
  const steaguri = Object.entries(s.steaguri || {});
  $("s-steaguri").textContent = steaguri.length ? steaguri.map(([n, k]) => `${n}: ${k}`).join(", ") : "niciunul";
  $("s-folder").textContent = s.folder || "–";
  $("avertisment").textContent = s.avertisment;

  $("start").disabled = s.activ;
  $("stop").disabled = !s.activ;
  $("profil").disabled = s.activ;
  afiseazaMarcaje(s.marcaje, s.activ);

  const tb = $("valori");
  const intrari = Object.entries(s.valori || {});
  if (!intrari.length) {
    tb.innerHTML = '<tr><td colspan="3" class="gol">Nicio valoare încă.</td></tr>';
  } else {
    if (tb.rows.length !== intrari.length || tb.querySelector(".gol")) {
      tb.innerHTML = "";
      for (const [alias] of intrari) {
        const tr = tb.insertRow();
        tr.insertCell().textContent = alias;
        tr.insertCell();
        tr.insertCell();
      }
    }
    intrari.forEach(([alias, v], i) => {
      const c = tb.rows[i].cells;
      c[0].textContent = alias;
      c[1].textContent = numar(v.valoare);
      c[2].textContent = v.unitate || "";
    });
  }
}

async function actualizeazaJurnal() {
  const d = await api(`/api/jurnal?de_la=${ultimulJurnal}`);
  if (d.ultimul < ultimulJurnal) ultimulJurnal = 0;  // serverul a fost repornit
  const ol = $("jurnal");
  for (const [nr, text] of d.linii) {
    const li = document.createElement("li");
    li.textContent = text;
    if (text.includes(" EROARE: ")) li.className = "eroare";
    else if (text.includes(" Steag ")) li.className = "steag";
    else if (text.includes(" AVERTISMENT: ")) li.className = "avertisment";
    ol.insertBefore(li, ol.firstChild);
    ultimulJurnal = nr;
  }
  while (ol.children.length > 200) ol.removeChild(ol.lastChild);
}

async function bucla() {
  try {
    afiseazaStare(await api("/api/stare"));
    await actualizeazaJurnal();
  } catch (e) {
    $("conexiune").hidden = false;
  }
  setTimeout(bucla, 1000);
}

async function trimiteMarcaj(eticheta) {
  try {
    await api("/api/marcaj", { eticheta });
    mesaj(`Marcaj: ${eticheta}`);
  } catch (e) {
    mesaj(e.message, true);
  }
}

$("profil").addEventListener("change", afiseazaDescriere);

$("start").addEventListener("click", async () => {
  const conditie = document.querySelector('input[name="conditie"]:checked').value;
  $("start").disabled = true;
  try {
    await api("/api/start", { profil: $("profil").value, conditie, nota: $("nota").value });
    mesaj("Înregistrarea a pornit.");
  } catch (e) {
    mesaj(e.message, true);
  }
});

$("stop").addEventListener("click", async () => {
  if (!confirm("Oprești înregistrarea?")) return;
  $("stop").disabled = true;
  mesaj("Se oprește (citesc erorile de la final)…");
  try {
    const d = await api("/api/stop", {});
    mesaj("Oprit. Datele sunt în " + d.folder);
  } catch (e) {
    mesaj(e.message, true);
  }
});

$("erori").addEventListener("click", async () => {
  $("erori").disabled = true;
  mesaj("Citesc memoria de erori…");
  try {
    const d = await api("/api/erori", {});
    mesaj(d.in_inregistrare ? "Erorile se citesc la ciclul următor (vezi jurnalul)." : "Erori: " + d.rezumat, d.ok === false);
  } catch (e) {
    mesaj(e.message, true);
  } finally {
    $("erori").disabled = false;
  }
});

document.addEventListener("keydown", (ev) => {
  const tinta = ev.target;
  if (tinta.closest && tinta.closest("input, textarea, select")) return;
  if (ev.ctrlKey || ev.altKey || ev.metaKey || !/^[1-9]$/.test(ev.key)) return;
  if (!stareCurenta || !stareCurenta.activ) return;
  const m = (stareCurenta.marcaje || []).find((x) => x.tasta === ev.key);
  if (m) {
    ev.preventDefault();
    trimiteMarcaj(m.eticheta);
  }
});

incarcaProfile();
bucla();
