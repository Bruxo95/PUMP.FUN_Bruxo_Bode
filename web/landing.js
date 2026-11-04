/* Página inicial: botão "Entrar com Google" e, se já tiver sessão, "Abrir painel". */
(function () {
  "use strict";
  const err = document.getElementById("lpErr");
  const show = (m) => { err.textContent = m; err.hidden = false; };
  document.querySelectorAll("[data-logo]").forEach((e) => (e.innerHTML = BB.logo));
  const q = new URLSearchParams(location.search);
  if (q.get("sessao") === "expirada") show("Sua sessão expirou. Entre de novo com o Google.");
  if (q.get("error_description")) show("O login não terminou: " + q.get("error_description"));

  fetch("/health").then((r) => r.json()).then((h) => (document.getElementById("ver").textContent = "versão " + h.version)).catch(() => {});

  let logged = false;
  document.querySelectorAll("[data-login]").forEach((b) =>
    b.addEventListener("click", async () => {
      // 0.32.209 (pedido do dono): entrar pela página inicial sempre abre a escolha da rede (a escolha antiga da aba é esquecida)
      try { sessionStorage.removeItem("pf_hub"); } catch (e) { /* */ }
      if (logged) { location.href = "/app"; return; }
      try { b.disabled = true; await BB.login(); } catch (e) { show(e.message || String(e)); b.disabled = false; }
    })
  );

  BB.session().then((s) => {
    if (!s) return;
    logged = true;
    document.querySelectorAll("[data-start]").forEach((b) => (b.textContent = "Abrir painel"));
  }).catch((e) => show(e.message || String(e)));
})();
