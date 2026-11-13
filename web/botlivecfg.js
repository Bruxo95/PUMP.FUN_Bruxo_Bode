// 0.32.337 (pedido do dono, 13/11): configuração simples do BOT LIVE (/botlive). Grava em localStorage (botlive_cfg, a mesma que a SALA
// LIVE lê) e monta o link do OBS, que leva a configuração inteira (o OBS tem navegador próprio, sem o que ficou salvo aqui).
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const cfg = window.SALA_CFG, DEF = window.BOTLIVE_DEF, KEY = window.BOTLIVE_KEY;
  const TG = { cMus: "musica", cSfx: "sfx", cBal: "baloes", cPriv: "privado", cPan: "painel", cClean: "limpa" };
  let savedT = null;
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(cfg)); } catch (e) { /* sem armazenamento */ }
    $("cSaved").textContent = "salvo ✓"; clearTimeout(savedT); savedT = setTimeout(() => { $("cSaved").textContent = ""; }, 1500);
    paint();
  }
  function obsLink() {
    const o = Object.assign({}, cfg); delete o.botlive; delete o.mkey;
    return location.origin + "/botlive/sala?cfg=" + encodeURIComponent(btoa(unescape(encodeURIComponent(JSON.stringify(o)))));
  }
  function paint() {
    Object.entries(TG).forEach(([id, k]) => {
      const b = $(id), on = !!cfg[k];
      b.classList.toggle("on", on); b.classList.toggle("off", !on); b.textContent = on ? "Ligado" : "Desligado"; b.setAttribute("aria-checked", on ? "true" : "false");
    });
    $("cVolN").textContent = "· " + cfg.vol + "%";
    $("cLink").textContent = obsLink();
  }
  function fill() {
    $("cRede").value = cfg.rede; $("cCart").value = cfg.carteira; $("cNome").value = cfg.nome || ""; $("cTit").value = cfg.titulo || "";
    $("cSub").value = cfg.sub || ""; $("cCeu").value = cfg.ceu || ""; $("cVol").value = cfg.vol;
    paint();
  }
  [["cRede", "rede"], ["cCart", "carteira"], ["cCeu", "ceu"]].forEach(([id, k]) => $(id).addEventListener("change", (e) => { cfg[k] = e.target.value; save(); }));
  [["cNome", "nome"], ["cTit", "titulo"], ["cSub", "sub"]].forEach(([id, k]) => $(id).addEventListener("input", (e) => { cfg[k] = e.target.value.slice(0, 60); save(); }));
  $("cVol").addEventListener("input", (e) => { cfg.vol = +e.target.value; save(); });
  Object.entries(TG).forEach(([id, k]) => $(id).addEventListener("click", () => { cfg[k] = !cfg[k]; save(); }));
  $("cCopy").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(obsLink()); $("cCopy").textContent = "Copiado!"; } catch (e) { $("cCopy").textContent = "Selecione o link e copie"; }
    setTimeout(() => { $("cCopy").textContent = "Copiar link do OBS"; }, 2000);
  });
  $("cReset").addEventListener("click", () => { Object.assign(cfg, DEF); save(); fill(); });
  // a SALA LIVE escolhe a carteira pelo que foi salvo aqui (e não pelo último botão FICTÍCIA/REAL apertado lá)
  $("goSala").addEventListener("click", () => { try { localStorage.setItem("botlive_modo", cfg.carteira === "real" ? "real" : "sim"); } catch (e) { /* */ } });

  $("boot").innerHTML = BB.loader("Carregando", { grid: 4, pattern: "sweep", font: 15, cell: 7, glow: true });
  (async function () {
    let s = null;
    try { s = await BB.session(); } catch (e) { /* sem sessão */ }
    if (!s) { location.href = "/"; return; }
    fill();
    $("boot").hidden = true; $("bl").hidden = false;
  })();
})();
