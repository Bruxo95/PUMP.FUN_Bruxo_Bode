// Prova local de renderização: sem navegador, rede, login ou transações.
// Execute da raiz: node docs/auditoria/2026-10-25/poc-web-render.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../../..');
const nodes = new Map();
const node = id => {
  if (!nodes.has(id)) nodes.set(id, {
    innerHTML: '', textContent: '', hidden: false, clientWidth: 600, clientHeight: 260,
    classList: { toggle() {}, add() {}, remove() {} },
  });
  return nodes.get(id);
};
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const sandbox = {
  BB: { esc },
  document: { getElementById: node, addEventListener() {}, querySelectorAll() { return []; } },
  localStorage: { getItem() { return null; } },
  window: {}, location: { hash: '' }, console,
  setTimeout() {}, setInterval() {},
};
let source = fs.readFileSync(path.join(root, 'web/app.js'), 'utf8');
assert.ok(source.includes('  boot();'), 'O ponto de instrumentação mudou; revisar a prova.');
source = source.replace('  boot();',
  '  globalThis.audit = { set(d, w) { D = d; W = w; }, renderReal, renderTraders };');
vm.createContext(sandbox);
vm.runInContext(source, sandbox);

const marker = '<b data-audit-probe="1">RPC error</b>';
sandbox.audit.set({ cfg: {}, real: {}, real_wallet: {} }, { configured: true, error: marker });
sandbox.audit.renderReal();
const rawRpcMarkup = node('wKpis').innerHTML.includes(marker);
assert.equal(rawRpcMarkup, true);
console.log(JSON.stringify({ probe: 'rpc_error_is_inserted_as_html', confirmed: rawRpcMarkup }));

sandbox.audit.set({
  cfg: { pump_lb_min_trades: 0 },
  leaderboard: [{ rank: 1, wallet: '11111111111111111111111111111111', name: marker,
    tokens: marker, days_active: marker, eligible: false }],
  lb_status: {}, followed: [], ranking: [], banned: [],
}, {});
sandbox.audit.renderTraders();
const nameEscaped = node('tLb').innerHTML.includes(esc(marker));
const numericFieldsMarkup = node('tLb').innerHTML.includes(marker);
assert.equal(nameEscaped, true);
assert.equal(numericFieldsMarkup, true);
console.log(JSON.stringify({ probe: 'leaderboard_render', nameEscaped, numericFieldsMarkup }));
console.log('Limitacao: esta prova confirma HTML em innerHTML; nao prova execucao de JavaScript nem invasao.');
