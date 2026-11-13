// 0.32.336 (pedido do dono, 13/11): BOT LIVE — página da live lo-fi do BOT. Este arquivo roda ANTES de sala.js e monta a
// configuração (window.SALA_CFG) a partir do link do OBS (?cfg=...) ou do que ficou salvo neste navegador. Padrão: dados da Robinhood.
(function () {
  "use strict";
  const KEY = "botlive_cfg";
  // 0.32.338: o BOT LIVE tem carteira própria (simulada, estratégia da Robinhood da 0.32.308): sem escolha de rede nem FICTÍCIA/REAL
  const DEF = { botlive: true, mkey: "botlive_modo", rede: "hood", carteira: "sim", api: "/api/botlive/painel", nome: "BOT", titulo: "BOT TRABALHANDO AO VIVO",
    sub: "lo-fi beats para copiar trader", ceu: "", musica: false, vol: 45, sfx: false, baloes: true, privado: false, painel: true, limpa: false };
  let cfg = Object.assign({}, DEF);
  try { const s = JSON.parse(localStorage.getItem(KEY) || "null"); if (s && typeof s === "object") Object.assign(cfg, s); } catch (e) { /* sem armazenamento */ }
  try {
    const q = new URLSearchParams(location.search).get("cfg");
    if (q) { const u = JSON.parse(decodeURIComponent(escape(atob(q)))); if (u && typeof u === "object") Object.assign(cfg, u); }
  } catch (e) { /* link inválido: fica o salvo */ }
  cfg.botlive = true; cfg.mkey = DEF.mkey; cfg.rede = "hood"; cfg.carteira = "sim"; cfg.api = DEF.api;
  window.BOTLIVE_DEF = DEF; window.BOTLIVE_KEY = KEY;
  window.SALA_CFG = cfg;
})();
