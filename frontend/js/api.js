/* js/api.js — shared fetch helper + token storage.
   Note on localStorage: this is a real page served by your own Flask app
   and running in your own browser (not a Claude.ai artifact sandbox), so
   localStorage works normally here and is the right tool for persisting
   a session across page reloads during a demo. */

const API = {
  async post(path, body, token) {
    const headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(path, { method: "POST", headers, body: JSON.stringify(body || {}) });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  },

  async patch(path, body, token) {
    const headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(path, { method: "PATCH", headers, body: JSON.stringify(body || {}) });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  },

  async get(path, token) {
    const headers = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(path, { method: "GET", headers });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  },
};

const Session = {
  getVoterToken() { return localStorage.getItem("voter_session_token"); },
  setVoterToken(t) { localStorage.setItem("voter_session_token", t); },
  clearVoterToken() { localStorage.removeItem("voter_session_token"); },

  getAdminToken() { return localStorage.getItem("admin_session_token"); },
  setAdminToken(t) { localStorage.setItem("admin_session_token", t); },
  clearAdminToken() { localStorage.removeItem("admin_session_token"); },

  // Demo convenience only — see routes/dev_routes.py. Stores a voter's TOTP
  // secret locally so the "auto-fill code" button can work without a real
  // authenticator app during a live demo.
  saveDemoSecret(studentId, secret) { localStorage.setItem("demo_totp_" + studentId, secret); },
  getDemoSecret(studentId) { return localStorage.getItem("demo_totp_" + studentId); },
};

function showMessage(container, text, kind) {
  container.innerHTML = `<div class="message ${kind}">${text}</div>`;
}

function clearMessage(container) {
  container.innerHTML = "";
}
