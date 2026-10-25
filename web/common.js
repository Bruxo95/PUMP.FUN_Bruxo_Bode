/* Comum às duas páginas: configuração pública, cliente do Supabase (login Google) e chamadas à API. */
(function () {
  "use strict";
  const BB = (window.BB = { cfg: null, sb: null });
  const LOGO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/><path d="M15.2 11.5l-2 3h2.6l-2 3"/></svg>';
  BB.logo = LOGO;

  BB.init = async function () {
    if (BB.sb) return BB.sb;
    const r = await fetch("/api/public-config", { cache: "no-store" });
    BB.cfg = await r.json();
    if (!BB.cfg.configured) throw new Error("O servidor ainda não tem SUPABASE_URL / SUPABASE_ANON_KEY no .env.");
    if (!window.supabase) throw new Error("Não consegui carregar a biblioteca de login (sem internet?).");
    BB.sb = window.supabase.createClient(BB.cfg.supabase_url, BB.cfg.supabase_anon_key, {
      auth: { flowType: "pkce", persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    });
    return BB.sb;
  };

  BB.login = async function () {
    const sb = await BB.init();
    const base = (BB.cfg.base_url || location.origin).replace(/\/$/, "");
    const { error } = await sb.auth.signInWithOAuth({ provider: "google", options: { redirectTo: base + "/app" } });
    if (error) throw error;
  };

  BB.session = async function () {
    const sb = await BB.init();
    const { data } = await sb.auth.getSession();
    return data && data.session;
  };

  BB.logout = async function () {
    try { await (await BB.init()).auth.signOut(); } catch (e) { /* segue */ }
    location.href = "/";
  };

  /* Chamada à API com o token do usuário. 401 → volta para a página inicial. */
  BB.api = async function (path, opts) {
    opts = opts || {};
    const s = await BB.session();
    if (!s) { location.href = "/"; throw new Error("sem sessão"); }
    const h = Object.assign({ Authorization: "Bearer " + s.access_token }, opts.headers || {});
    let body = opts.body;
    if (body !== undefined && typeof body !== "string") { body = JSON.stringify(body); h["Content-Type"] = "application/json"; }
    const r = await fetch(path, { method: opts.method || (body !== undefined ? "POST" : "GET"), headers: h, body: body, cache: "no-store" });
    if (r.status === 401) { location.href = "/?sessao=expirada"; throw new Error("sessão expirada"); }
    let js = {};
    try { js = await r.json(); } catch (e) { js = { error: "resposta inválida do servidor" }; }
    if (!r.ok && !js.error) js.error = "erro " + r.status;
    return js;
  };

  BB.esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
})();
