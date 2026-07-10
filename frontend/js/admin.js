/* js/admin.js — drives the admin dashboard: voters, elections (create,
   edit while draft, open/close), results, and the anomaly scanner. */

const loginMsg = () => document.getElementById("login-msg");
const dashMsg = () => document.getElementById("dash-msg");

function refreshIcons() {
  if (window.lucide) lucide.createIcons();
}

const NAV_ACTIVE = ["bg-white/10", "text-white", "font-semibold"];
const NAV_INACTIVE = ["text-paper-100/70", "hover:bg-white/5", "hover:text-white"];

let createStartPicker, createEndPicker;

async function adminLogin() {
  const username = document.getElementById("admin-user").value.trim();
  const password = document.getElementById("admin-pass").value;
  const { ok, data } = await API.post("/admin/login", { username, password });
  if (!ok) return showMessage(loginMsg(), data.error || "Sign-in failed.", "error");

  Session.setAdminToken(data.token);
  document.getElementById("view-admin-login").classList.add("hidden");
  document.getElementById("view-dashboard").classList.remove("hidden");
  refreshIcons();
  showTab("voters");
}

function adminLogout() {
  Session.clearAdminToken();
  document.getElementById("view-dashboard").classList.add("hidden");
  document.getElementById("view-admin-login").classList.remove("hidden");
}

function showTab(tab) {
  ["voters", "elections", "results", "security"].forEach(t => {
    document.getElementById("tab-" + t).classList.toggle("hidden", t !== tab);
  });
  document.querySelectorAll(".nav-link[data-tab]").forEach(btn => {
    const active = btn.dataset.tab === tab;
    btn.classList.remove(...NAV_ACTIVE, ...NAV_INACTIVE);
    btn.classList.add(...(active ? NAV_ACTIVE : NAV_INACTIVE));
  });
  clearMessage(dashMsg());
  if (tab === "voters") loadAuthorizedVoters();
  if (tab === "elections") { initCreateFormPickers(); loadElectionsManage(); }
  if (tab === "results") loadElectionsForResultsDropdown();
  refreshIcons();
}

function initCreateFormPickers() {
  if (createStartPicker) return; // only need to set these up once
  const opts = {
    enableTime: true,
    dateFormat: "Y-m-dTH:i",
    altInput: true,
    altFormat: "F j, Y \\a\\t h:i K",
    minDate: "today",
  };
  createStartPicker = flatpickr("#el-start", opts);
  createEndPicker = flatpickr("#el-end", opts);
}

async function uploadVoters() {
  const raw = document.getElementById("voter-ids").value;
  const ids = raw.split("\n").map(s => s.trim()).filter(Boolean);
  if (!ids.length) return showMessage(dashMsg(), "Enter at least one student ID.", "error");

  const { ok, data } = await API.post("/admin/voters/upload", { student_ids: ids }, Session.getAdminToken());
  if (!ok) return showMessage(dashMsg(), data.error || "Upload failed.", "error");
  showMessage(dashMsg(), `Added ${data.added} student ID(s) to the authorized voter list.`, "success");
  document.getElementById("voter-ids").value = "";
  loadAuthorizedVoters();
}

async function loadAuthorizedVoters() {
  const display = document.getElementById("voters-list-display");
  display.innerHTML = `<div class="flex items-center gap-2 text-slate-400 py-6"><span class="spinner"></span> Loading list…</div>`;

  const { ok, data } = await API.get("/admin/voters/list", Session.getAdminToken());
  if (!ok) { display.innerHTML = `<p class="text-slate-400 text-sm">Could not load the list.</p>`; return; }

  if (!data.total) {
    display.innerHTML = `<p class="text-slate-400 text-sm">No student IDs authorized yet — add some above.</p>`;
    return;
  }

  const rows = data.entries.map(e => `
    <tr class="border-b border-paper-100">
      <td class="py-2 text-sm font-mono text-slate-500">${escapeHtmlA(e.hash_fingerprint)}…</td>
      <td class="py-2 text-sm">
        ${e.is_registered
          ? `<span class="inline-flex items-center gap-1 text-xs font-semibold text-verified"><i data-lucide="check-circle-2" class="w-3.5 h-3.5"></i> Registered</span>`
          : `<span class="inline-flex items-center gap-1 text-xs font-semibold text-slate-400"><i data-lucide="clock" class="w-3.5 h-3.5"></i> Not yet registered</span>`}
      </td>
      <td class="py-2 text-sm text-slate-400">${escapeHtmlA(e.added_at)}</td>
    </tr>
  `).join("");

  display.innerHTML = `
    <div class="text-sm text-slate-500 mb-3">${data.registered_count} of ${data.total} authorized IDs have registered.</div>
    <div class="bg-white rounded-2xl border border-paper-200 shadow-card p-6 overflow-x-auto">
      <table class="w-full">
        <thead><tr class="text-xs uppercase tracking-wide text-slate-400"><th class="text-left pb-2">ID fingerprint</th><th class="text-left pb-2">Status</th><th class="text-left pb-2">Added</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <p class="text-xs text-slate-400 mt-3 flex items-start gap-1.5"><i data-lucide="info" class="w-3.5 h-3.5 shrink-0 mt-0.5"></i> Student IDs are stored as one-way hashes and can't be shown in original form — the fingerprint above confirms an entry exists without exposing the ID itself.</p>
  `;
  refreshIcons();
}

async function createElection() {
  const title = document.getElementById("el-title").value.trim();
  const start_time = document.getElementById("el-start").value.trim();
  const end_time = document.getElementById("el-end").value.trim();

  if (!title) return showMessage(dashMsg(), "Enter a title for the election.", "error");
  if (!start_time || !end_time) return showMessage(dashMsg(), "Pick a start and end date/time.", "error");

  const { ok, data } = await API.post("/admin/elections", { title, start_time, end_time }, Session.getAdminToken());
  if (!ok) return showMessage(dashMsg(), data.error || "Could not create election.", "error");
  showMessage(dashMsg(), "Election created as a draft. Add positions and candidates below.", "success");
  document.getElementById("el-title").value = "";
  createStartPicker.clear();
  createEndPicker.clear();
  loadElectionsManage();
}

async function loadElectionsManage() {
  const container = document.getElementById("elections-manage-list");
  container.innerHTML = `<div class="flex items-center gap-2 text-slate-400 py-6"><span class="spinner"></span> Loading elections…</div>`;
  const { ok, data } = await API.get("/admin/elections", Session.getAdminToken());
  if (!ok) { container.innerHTML = `<p class="text-slate-400">Could not load elections.</p>`; return; }

  if (!data.elections.length) {
    container.innerHTML = `<p class="text-slate-400 text-sm">No elections yet — create one above.</p>`;
    return;
  }

  const cards = await Promise.all(data.elections.map(async (e) => {
    const detail = await API.get(`/admin/elections/${e.election_id}`, Session.getAdminToken());
    const structure = detail.ok ? detail.data.election : null;
    return renderElectionManageCard(e, structure);
  }));
  container.innerHTML = cards.join("");
  refreshIcons();

  // Wire up edit-mode flatpickr instances for any draft elections.
  data.elections.filter(e => e.status === "draft").forEach(e => {
    const opts = { enableTime: true, dateFormat: "Y-m-dTH:i", altInput: true, altFormat: "F j, Y \\a\\t h:i K", minDate: "today" };
    const startEl = document.getElementById(`edit-start-${e.election_id}`);
    const endEl = document.getElementById(`edit-end-${e.election_id}`);
    if (startEl) flatpickr(startEl, { ...opts, defaultDate: e.start_time });
    if (endEl) flatpickr(endEl, { ...opts, defaultDate: e.end_time });
  });
}

const STATUS_BADGE = {
  draft: "bg-paper-100 text-slate-500",
  open: "bg-verified-light text-verified",
  closed: "bg-red-50 text-seal",
};

function renderElectionManageCard(e, structure) {
  const positions = structure ? structure.positions : [];
  const positionsHtml = positions.map(pos => `
    <div class="mt-4 pl-4 border-l-2 border-paper-200">
      <strong class="text-sm text-ink-900">${escapeHtmlA(pos.title)}</strong>
      <ul class="mt-1.5 space-y-1">
        ${pos.candidates.map(c => `
          <li class="flex items-center text-sm text-slate-600">
            ${c.photo ? `<img class="w-6 h-6 rounded-full object-cover mr-2 border border-paper-200" src="${c.photo}">` : `<span class="w-6 h-6 rounded-full bg-paper-100 mr-2"></span>`}
            ${escapeHtmlA(c.name)}${c.bio ? ` — <span class="text-slate-400">${escapeHtmlA(c.bio)}</span>` : ""}
          </li>
        `).join("") || `<li class="text-sm text-slate-400 italic">No candidates yet</li>`}
      </ul>
      ${e.status === "draft" ? `
        <div class="flex items-center gap-2 mt-3">
          <input type="text" id="cname-${pos.position_id}" placeholder="Candidate name" class="flex-1 px-3 py-2 text-sm border border-paper-200 rounded-lg bg-paper-50 focus:outline-none focus:ring-2 focus:ring-ink-700">
          <input type="text" id="cbio-${pos.position_id}" placeholder="Bio (optional)" class="flex-1 px-3 py-2 text-sm border border-paper-200 rounded-lg bg-paper-50 focus:outline-none focus:ring-2 focus:ring-ink-700">
          <input type="file" accept="image/*" id="cphoto-${pos.position_id}" onchange="previewCandidatePhoto(${pos.position_id})" class="text-xs w-36">
          <img class="preview hidden w-9 h-9 rounded-full object-cover border border-paper-200" id="cphoto-preview-${pos.position_id}">
          <button onclick="addCandidate(${pos.position_id})" class="px-4 py-2 text-sm rounded-full border border-paper-200 hover:bg-paper-100 font-medium transition shrink-0">Add</button>
        </div>
      ` : ""}
    </div>
  `).join("");

  const addPositionHtml = e.status === "draft" ? `
    <div class="flex items-center gap-2 mt-4">
      <input type="text" id="pname-${e.election_id}" placeholder="New position title (e.g. Treasurer)" class="flex-1 px-3 py-2 text-sm border border-paper-200 rounded-lg bg-paper-50 focus:outline-none focus:ring-2 focus:ring-ink-700">
      <button onclick="addPosition(${e.election_id})" class="px-4 py-2 text-sm rounded-full border border-paper-200 hover:bg-paper-100 font-medium transition shrink-0">Add position</button>
    </div>
  ` : "";

  let actionButtons = "";
  if (e.status === "draft") {
    actionButtons = `
      <button onclick="toggleEditElection(${e.election_id})" class="px-4 py-2 text-sm rounded-full border border-paper-200 hover:bg-paper-100 font-medium transition flex items-center gap-1.5"><i data-lucide="pencil" class="w-3.5 h-3.5"></i> Edit</button>
      <button onclick="openElection(${e.election_id})" class="px-5 py-2 text-sm rounded-full bg-seal hover:bg-seal-dark text-white font-semibold shadow-md transition">Open for voting</button>
    `;
  } else if (e.status === "open") {
    actionButtons = `<button onclick="closeElection(${e.election_id})" class="px-5 py-2 text-sm rounded-full bg-seal hover:bg-seal-dark text-white font-semibold shadow-md transition">Close election</button>`;
  }

  const editFormHtml = e.status === "draft" ? `
    <div id="edit-form-${e.election_id}" class="hidden mt-4 pt-4 border-t border-paper-100">
      <label class="block text-xs font-semibold text-ink-800 mb-1">Title</label>
      <input type="text" id="edit-title-${e.election_id}" value="${escapeHtmlA(e.title)}" class="w-full mb-3 px-3 py-2 text-sm border border-paper-200 rounded-lg bg-paper-50 focus:outline-none focus:ring-2 focus:ring-ink-700">
      <div class="grid sm:grid-cols-2 gap-3 mb-3">
        <div>
          <label class="block text-xs font-semibold text-ink-800 mb-1">Start</label>
          <input type="text" id="edit-start-${e.election_id}" class="w-full px-3 py-2 text-sm border border-paper-200 rounded-lg bg-paper-50 focus:outline-none focus:ring-2 focus:ring-ink-700">
        </div>
        <div>
          <label class="block text-xs font-semibold text-ink-800 mb-1">End</label>
          <input type="text" id="edit-end-${e.election_id}" class="w-full px-3 py-2 text-sm border border-paper-200 rounded-lg bg-paper-50 focus:outline-none focus:ring-2 focus:ring-ink-700">
        </div>
      </div>
      <div class="flex gap-2">
        <button onclick="saveElectionEdit(${e.election_id})" class="px-4 py-2 text-sm rounded-full bg-ink-800 hover:bg-ink-700 text-white font-semibold transition">Save changes</button>
        <button onclick="toggleEditElection(${e.election_id})" class="px-4 py-2 text-sm rounded-full border border-paper-200 hover:bg-paper-100 font-medium transition">Cancel</button>
      </div>
    </div>
  ` : "";

  return `
    <div class="bg-white rounded-2xl border border-paper-200 shadow-card p-6">
      <div class="flex items-start justify-between gap-3">
        <h3 class="font-display text-lg text-ink-900">${escapeHtmlA(e.title)}</h3>
        <span class="shrink-0 text-[11px] font-bold uppercase tracking-wider px-2.5 py-1 rounded-full ${STATUS_BADGE[e.status]}">${e.status}</span>
      </div>
      <p class="text-xs text-slate-400 mt-1">${escapeHtmlA(e.start_time)} → ${escapeHtmlA(e.end_time)}</p>
      ${positionsHtml}
      ${addPositionHtml}
      ${editFormHtml}
      <div class="flex items-center gap-2 mt-5">${actionButtons}</div>
    </div>
  `;
}

function toggleEditElection(electionId) {
  document.getElementById(`edit-form-${electionId}`).classList.toggle("hidden");
}

async function saveElectionEdit(electionId) {
  const title = document.getElementById(`edit-title-${electionId}`).value.trim();
  const start_time = document.getElementById(`edit-start-${electionId}`).value.trim();
  const end_time = document.getElementById(`edit-end-${electionId}`).value.trim();

  const { ok, data } = await API.patch(`/admin/elections/${electionId}`, { title, start_time, end_time }, Session.getAdminToken());
  if (!ok) return showMessage(dashMsg(), data.error || "Could not save changes.", "error");
  showMessage(dashMsg(), "Election updated.", "success");
  loadElectionsManage();
}

async function addPosition(electionId) {
  const input = document.getElementById(`pname-${electionId}`);
  const title = input.value.trim();
  if (!title) return;
  const { ok, data } = await API.post(`/admin/elections/${electionId}/positions`, { title }, Session.getAdminToken());
  if (!ok) return showMessage(dashMsg(), data.error || "Could not add position.", "error");
  loadElectionsManage();
}

const candidatePhotoCache = {};

async function previewCandidatePhoto(positionId) {
  const fileInput = document.getElementById(`cphoto-${positionId}`);
  const preview = document.getElementById(`cphoto-preview-${positionId}`);
  const file = fileInput.files[0];
  if (!file) return;
  try {
    const resized = await resizeImageFile(file);
    candidatePhotoCache[positionId] = resized;
    preview.src = `data:${resized.mime};base64,${resized.base64}`;
    preview.classList.remove("hidden");
  } catch (err) {
    showMessage(dashMsg(), "Could not process that image. Try a different file.", "error");
  }
}

async function addCandidate(positionId) {
  const name = document.getElementById(`cname-${positionId}`).value.trim();
  const bio = document.getElementById(`cbio-${positionId}`).value.trim();
  if (!name) return;

  const photo = candidatePhotoCache[positionId];
  const body = { name, bio };
  if (photo) { body.photo_base64 = photo.base64; body.photo_mime = photo.mime; }

  const { ok, data } = await API.post(`/admin/positions/${positionId}/candidates`, body, Session.getAdminToken());
  if (!ok) return showMessage(dashMsg(), data.error || "Could not add candidate.", "error");
  delete candidatePhotoCache[positionId];
  loadElectionsManage();
}

async function openElection(electionId) {
  const { ok, data } = await API.post(`/admin/elections/${electionId}/open`, {}, Session.getAdminToken());
  if (!ok) return showMessage(dashMsg(), data.error || "Could not open election.", "error");
  showMessage(dashMsg(), "Election is now open for voting. An RSA keypair was generated for this election.", "success");
  loadElectionsManage();
}

async function closeElection(electionId) {
  const { ok, data } = await API.post(`/admin/elections/${electionId}/close`, {}, Session.getAdminToken());
  if (!ok) return showMessage(dashMsg(), data.error || "Could not close election.", "error");
  showMessage(dashMsg(), "Election closed. Results can now be tallied from the Results tab.", "success");
  loadElectionsManage();
}

async function loadElectionsForResultsDropdown() {
  const { ok, data } = await API.get("/admin/elections", Session.getAdminToken());
  const select = document.getElementById("results-election-select");
  if (!ok) return;
  select.innerHTML = data.elections.map(e => `<option value="${e.election_id}">${escapeHtmlA(e.title)} (${e.status})</option>`).join("");
}

async function loadResults() {
  const electionId = document.getElementById("results-election-select").value;
  const display = document.getElementById("results-display");
  if (!electionId) return;
  display.innerHTML = `<div class="flex items-center gap-2 text-slate-400 py-6"><span class="spinner"></span> Decrypting and tallying votes…</div>`;

  const [electionDetail, results] = await Promise.all([
    API.get(`/admin/elections/${electionId}`, Session.getAdminToken()),
    API.get(`/admin/elections/${electionId}/results`, Session.getAdminToken()),
  ]);

  if (!results.ok) {
    display.innerHTML = `<div class="p-4 rounded-xl bg-red-50 text-seal-dark text-sm">${escapeHtmlA(results.data.error || "Could not load results.")}</div>`;
    return;
  }

  const positions = electionDetail.ok ? electionDetail.data.election.positions : [];
  const candidateName = {};
  positions.forEach(pos => pos.candidates.forEach(c => { candidateName[c.candidate_id] = c.name; }));

  const sections = positions.map(pos => {
    const tally = results.data.results[pos.position_id] || {};
    const rowsHtml = Object.entries(tally)
      .sort((a, b) => b[1] - a[1])
      .map(([cid, count]) => `<tr class="border-b border-paper-100"><td class="py-2 text-sm">${escapeHtmlA(candidateName[cid] || ("Candidate " + cid))}</td><td class="py-2 text-sm font-semibold text-right">${count}</td></tr>`)
      .join("") || `<tr><td colspan="2" class="py-2 text-sm text-slate-400 italic">No votes for this position</td></tr>`;
    return `
      <div class="bg-white rounded-2xl border border-paper-200 shadow-card p-6 mb-4">
        <h3 class="font-display text-lg text-ink-900 mb-3">${escapeHtmlA(pos.title)}</h3>
        <table class="w-full"><thead><tr class="text-xs uppercase tracking-wide text-slate-400"><th class="text-left pb-2">Candidate</th><th class="text-right pb-2">Votes</th></tr></thead><tbody>${rowsHtml}</tbody></table>
      </div>
    `;
  }).join("");

  const tamperNote = results.data.tampered_detected > 0
    ? `<div class="p-4 rounded-xl bg-red-50 text-seal-dark text-sm mb-4 flex items-center gap-2"><i data-lucide="alert-triangle" class="w-4 h-4"></i> ${results.data.tampered_detected} vote record(s) failed integrity verification and were excluded.</div>`
    : `<div class="p-4 rounded-xl bg-verified-light text-verified-dark text-sm mb-4 flex items-center gap-2"><i data-lucide="shield-check" class="w-4 h-4"></i> All ${results.data.total_votes} vote record(s) passed integrity verification.</div>`;

  display.innerHTML = tamperNote + sections;
  refreshIcons();
}

async function loadAnomalies() {
  const display = document.getElementById("anomalies-display");
  display.innerHTML = `<div class="flex items-center gap-2 text-slate-400 py-6"><span class="spinner"></span> Scanning login behavior…</div>`;
  const { ok, data } = await API.get("/admin/security/anomalies", Session.getAdminToken());
  if (!ok) { display.innerHTML = `<div class="p-4 rounded-xl bg-red-50 text-seal-dark text-sm">Could not run anomaly scan.</div>`; return; }

  if (!data.flagged.length) {
    display.innerHTML = `<div class="p-4 rounded-xl bg-verified-light text-verified-dark text-sm flex items-center gap-2"><i data-lucide="shield-check" class="w-4 h-4"></i> No anomalies flagged in current login activity.</div>`;
    refreshIcons();
    return;
  }

  const rows = data.flagged.map(f => `
    <tr class="border-b border-paper-100">
      <td class="py-2 text-sm">${escapeHtmlA(f.timestamp)}</td>
      <td class="py-2 text-sm">${f.voter_id ?? "—"}</td>
      <td class="py-2 text-sm font-semibold">${f.anomaly_score}</td>
      <td class="py-2 text-sm">${f.otp_seconds_taken != null ? f.otp_seconds_taken.toFixed(2) + "s" : "—"}</td>
      <td class="py-2 text-sm">${f.recent_attempts_by_device}</td>
    </tr>
  `).join("");

  display.innerHTML = `
    <div class="p-4 rounded-xl bg-paper-100 text-ink-800 text-sm mb-4">${data.count} login event(s) flagged as anomalous, most suspicious first.</div>
    <div class="bg-white rounded-2xl border border-paper-200 shadow-card p-6 overflow-x-auto">
      <table class="w-full">
        <thead><tr class="text-xs uppercase tracking-wide text-slate-400"><th class="text-left pb-2">Time</th><th class="text-left pb-2">Voter ID</th><th class="text-left pb-2">Score</th><th class="text-left pb-2">OTP entry time</th><th class="text-left pb-2">Attempts (5 min)</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function escapeHtmlA(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : str;
  return div.innerHTML;
}

(function init() {
  if (Session.getAdminToken()) {
    document.getElementById("view-admin-login").classList.add("hidden");
    document.getElementById("view-dashboard").classList.remove("hidden");
    showTab("voters");
  }
  refreshIcons();
})();
