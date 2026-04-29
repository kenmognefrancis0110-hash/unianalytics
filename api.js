/**
 * api.js — UniAnalytics PARAEU — VERSION CORRIGÉE
 */
const API_BASE = localStorage.getItem('api_url') || 'http://127.0.0.1:8000';

(function(){
  const t = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', t);
})();

async function apiGet(path) {
  const r = await fetch(API_BASE + path, { signal: AbortSignal.timeout(5000) });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function apiPost(path, body) {
  const r = await fetch(API_BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(5000)
  });
  const data = await r.json();
  if (!r.ok) {
    let msg = data.detail;
    if (Array.isArray(msg)) msg = msg.map(e => `${e.loc[e.loc.length-1]} invalide`).join(' | ');
    throw new Error(msg || 'Erreur serveur');
  }
  return data;
}

async function apiPut(path, body) {
  const r = await fetch(API_BASE + path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(5000)
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || 'Erreur serveur');
  return data;
}

async function apiDelete(path) {
  const r = await fetch(API_BASE + path, { method: 'DELETE' });
  return r.json();
}

let API_OK = false;

async function checkAPI() {
  try {
    const r = await fetch(API_BASE + '/ping', { signal: AbortSignal.timeout(2000) });
    API_OK = r.ok;
  } catch { API_OK = false; }

  ['api-dot','api-dot2'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.className = 'api-dot' + (API_OK ? '' : ' off');
  });
  const lbl = document.getElementById('api-label');
  if (lbl) lbl.textContent = API_OK ? 'API EN LIGNE' : 'MODE DÉMO';
  return API_OK;
}

function toast(msg, err = false) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.className = 'show' + (err ? ' err' : '');
  setTimeout(() => { t.className = ''; }, 3500);
}

function getChartColors() {
  const cs = getComputedStyle(document.documentElement);
  return {
    accent:  cs.getPropertyValue('--accent').trim()  || '#38bdf8',
    accent2: cs.getPropertyValue('--accent2').trim() || '#818cf8',
    green:   cs.getPropertyValue('--green').trim()   || '#34d399',
    red:     cs.getPropertyValue('--red').trim()     || '#f87171',
    yellow:  cs.getPropertyValue('--yellow').trim()  || '#fbbf24',
    text2:   cs.getPropertyValue('--text2').trim()   || '#94a3b8',
    border:  cs.getPropertyValue('--border').trim()  || '#1f2d4a',
  };
}

const CHARTS = {};
function destroyChart(id) {
  if (CHARTS[id]) { CHARTS[id].destroy(); delete CHARTS[id]; }
}

const _bc = (typeof BroadcastChannel !== 'undefined')
  ? new BroadcastChannel('unianalytics') : null;

function broadcastRefresh(type) {
  if (_bc) _bc.postMessage({ type: type || 'refresh', ts: Date.now() });
}

if (_bc) {
  _bc.onmessage = (ev) => {
    if (ev.data.type === 'refresh') {
      if (typeof loadDashboard   === 'function') loadDashboard();
      if (typeof loadPerformance === 'function') loadPerformance();
      if (typeof loadAnciens     === 'function') loadAnciens();
      if (typeof loadEtudiants   === 'function') loadEtudiants();
    }
  };
}
