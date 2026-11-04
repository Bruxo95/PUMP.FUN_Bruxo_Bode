/* 0.32.208: a Robinhood Chain (/hood) é o terceiro projeto, também separado.
   0.32.169 (pedido do dono, 03/11): depois do login o admin escolhe o projeto. PUMP FUN (Solana) e BNB · Four.Meme
   ficam em páginas separadas (/app e /bnb), sem misturar. Usuário comum vai direto ao painel da pump.fun. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const pick = (h) => { try { sessionStorage.setItem("pf_hub", h); } catch (e) { /* segue sem lembrar */ } };
  document.querySelectorAll("[data-logo]").forEach((e) => (e.innerHTML = BB.logo));
  $("boot").innerHTML = BB.loader("Carregando", { grid: 4, pattern: "sweep", font: 15, cell: 7, glow: true });
  document.querySelectorAll("[data-hub]").forEach((a) => a.addEventListener("click", () => pick(a.dataset.hub)));
  $("out").addEventListener("click", BB.logout);
  (async function () {
    let s = null;
    try { s = await BB.session(); } catch (e) { /* sem sessão: volta ao início */ }
    if (!s) { location.href = "/"; return; }
    const me = await BB.api("/api/me", { quiet: true });
    if (me.error || me.role !== "admin") { pick("pump"); location.replace("/app"); return; }
    $("who").textContent = (me.nome || "") + (me.email ? " · " + me.email : "");
    $("ver").textContent = "versão " + String(me.version || "").split(" · ")[0];
    $("boot").hidden = true; $("hub").hidden = false;
  })();
})();
