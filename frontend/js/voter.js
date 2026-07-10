/* js/voter.js — drives the redesigned voter portal: home dashboard with
   live turnout, modal-based register/login, and the ballot/confirmation
   views. */

const msgBox = () => document.getElementById("msg");

let pendingToken = null;
let currentStudentId = null;
let currentElectionId = null;
let currentBallot = null;

function refreshIcons() {
  if (window.lucide) lucide.createIcons();
}

function reanimate(el) {
  el.style.animation = "none";
  void el.offsetHeight;
  el.style.animation = "";
}

const VIEWS = ["home", "ballot", "confirmation"];

function showView(name) {
  VIEWS.forEach(v => document.getElementById("view-" + v).classList.add("hidden"));
  const el = document.getElementById("view-" + name);
  el.classList.remove("hidden");
  reanimate(el);
  clearMessage(msgBox());
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function openModal(name) {
  const modal = document.getElementById("modal-" + name);
  modal.classList.remove("hidden");
  modal.classList.add("flex");
  reanimate(modal.firstElementChild);
  if (name === "login") {
    document.getElementById("login-step-1").classList.remove("hidden");
    document.getElementById("login-step-2").classList.add("hidden");
  }
  if (name === "register") {
    document.getElementById("register-step-form").classList.remove("hidden");
    document.getElementById("register-step-done").classList.add("hidden");
    document.getElementById("reg-id").value = "";
    document.getElementById("reg-pw").value = "";
    document.getElementById("reg-pw-confirm").value = "";
  }
}

function closeModal(name) {
  const modal = document.getElementById("modal-" + name);
  modal.classList.add("hidden");
  modal.classList.remove("flex");
}

function updateAuthUI() {
  const loggedIn = !!Session.getVoterToken();
  document.getElementById("auth-buttons-logged-out").classList.toggle("hidden", loggedIn);
  document.getElementById("auth-buttons-logged-in").classList.toggle("hidden", !loggedIn);
  document.getElementById("auth-buttons-logged-in").classList.toggle("flex", loggedIn);
  refreshIcons();
}

function logout() {
  Session.clearVoterToken();
  updateAuthUI();
  backToHome();
}

function backToHome() {
  showView("home");
  loadHome();
}

/* ---- Registration ---- */

async function doRegister() {
  const studentId = document.getElementById("reg-id").value.trim();
  const password = document.getElementById("reg-pw").value;
  const confirmPassword = document.getElementById("reg-pw-confirm").value;

  if (password !== confirmPassword) {
    return showMessage(msgBox(), "Passwords don't match — please retype them.", "error");
  }

  const { ok, data } = await API.post("/voter/register", { student_id: studentId, password });
  if (!ok) return showMessage(msgBox(), data.error || "Registration failed.", "error");

  Session.saveDemoSecret(studentId, data.totp_secret);
  document.getElementById("reg-secret-display").textContent = data.totp_secret;
  document.getElementById("register-step-form").classList.add("hidden");
  document.getElementById("register-step-done").classList.remove("hidden");
  refreshIcons();
}

/* ---- Login ---- */

async function doLoginStep1() {
  const studentId = document.getElementById("login-id").value.trim();
  const password = document.getElementById("login-pw").value;
  const { ok, data } = await API.post("/voter/login", { student_id: studentId, password });
  if (!ok) return showMessage(msgBox(), data.error || "Login failed.", "error");

  pendingToken = data.pending_token;
  currentStudentId = studentId;
  document.getElementById("login-step-1").classList.add("hidden");
  document.getElementById("login-step-2").classList.remove("hidden");
}

async function autofillOtp() {
  const secret = Session.getDemoSecret(currentStudentId);
  if (!secret) return showMessage(msgBox(), "No demo secret saved for this ID in this browser — enter the code manually.", "info");
  const { ok, data } = await API.post("/dev/generate-otp", { secret });
  if (!ok) return showMessage(msgBox(), data.error || "Could not generate a demo code.", "error");
  document.getElementById("login-otp").value = data.code;
}

async function doLoginStep2() {
  const code = document.getElementById("login-otp").value.trim();
  const { ok, data } = await API.post("/voter/login/verify-otp", { pending_token: pendingToken, code });
  if (!ok) return showMessage(msgBox(), data.error || "Verification failed.", "error");

  Session.setVoterToken(data.session_token);
  closeModal("login");
  updateAuthUI();
  loadHome();
}

/* ---- Home dashboard: ongoing elections + live turnout (public, no login needed) ---- */

async function loadHome() {
  const container = document.getElementById("elections-grid");
  container.innerHTML = `<div class="flex items-center justify-center gap-2 text-slate-400 py-10"><span class="spinner"></span> Loading elections…</div>`;

  const { ok, data } = await API.get("/voter/public/elections");
  if (!ok) { container.innerHTML = `<p class="text-slate-400">Could not load elections.</p>`; return; }

  if (!data.elections.length) {
    container.innerHTML = `<div class="text-center py-14 text-slate-400 glass-card rounded-2xl"><i data-lucide="calendar-x" class="w-10 h-10 mx-auto mb-3 opacity-50"></i><p>There are no open elections right now. Check back soon.</p></div>`;
    refreshIcons();
    return;
  }

  const loggedIn = !!Session.getVoterToken();
  container.innerHTML = data.elections.map(e => {
    const pct = e.turnout_percent;
    const actionLabel = loggedIn ? "View &amp; vote" : "Log in to vote";
    const actionClasses = loggedIn
      ? "bg-seal hover:bg-seal-dark text-white shadow-lg shadow-seal/20"
      : "bg-white/10 hover:bg-white/15 text-white border border-white/15";
    const onclick = loggedIn ? `openBallot(${e.election_id})` : `openModal('login')`;
    return `
      <div class="glass-card rounded-2xl p-6 transition">
        <div class="flex items-start justify-between mb-3 gap-3">
          <h3 class="font-display text-lg text-white leading-snug">${escapeHtml(e.title)}</h3>
          <span class="shrink-0 inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-verified-light bg-verified/20 border border-verified/30 px-2.5 py-1 rounded-full"><i data-lucide="radio" class="w-3 h-3"></i> Live</span>
        </div>
        <p class="text-sm text-slate-400 mb-4 flex items-center gap-1.5"><i data-lucide="clock" class="w-3.5 h-3.5"></i> Closes ${escapeHtml(e.end_time)}</p>

        <div class="mb-1 flex items-center justify-between text-xs text-slate-400">
          <span>Turnout</span>
          <span class="font-semibold text-slate-200">${pct}%</span>
        </div>
        <div class="w-full bg-white/10 rounded-full h-2 overflow-hidden">
          <div class="h-full bg-gradient-to-r from-verified to-seal rounded-full transition-all" style="width:${pct}%"></div>
        </div>
        <p class="text-xs text-slate-500 mt-1.5">${e.voted_count} of ${e.total_voters} registered voters</p>

        <button onclick="${onclick}" class="mt-5 w-full py-2.5 rounded-full font-semibold text-sm transition ${actionClasses}">${actionLabel}</button>
      </div>
    `;
  }).join("");
  refreshIcons();
}

/* ---- Ballot ---- */

async function openBallot(electionId) {
  const { ok, data } = await API.get(`/voter/elections/${electionId}/ballot`, Session.getVoterToken());
  if (!ok) return showMessage(msgBox(), data.error || "Could not load ballot.", "error");

  currentElectionId = electionId;
  currentBallot = data.ballot;
  document.getElementById("ballot-title").textContent = data.ballot.title;

  const form = document.getElementById("ballot-form");
  form.innerHTML = data.ballot.positions.map(pos => `
    <div>
      <h3 class="font-display text-lg text-ink-900 mb-3">${escapeHtml(pos.title)}</h3>
      <div class="grid sm:grid-cols-2 gap-4">
        ${pos.candidates.map(c => `
          <label class="candidate-card relative block bg-white border-2 border-paper-200 rounded-2xl p-5 text-center cursor-pointer hover:shadow-md hover:-translate-y-0.5 transition">
            <input type="radio" name="position-${pos.position_id}" value="${c.candidate_id}" class="absolute opacity-0 pointer-events-none">
            <span class="check-badge absolute top-3 right-3 w-6 h-6 rounded-full bg-verified text-white flex items-center justify-center opacity-0 scale-50 transition"><i data-lucide="check" class="w-3.5 h-3.5"></i></span>
            ${c.photo
              ? `<img src="${c.photo}" alt="${escapeHtml(c.name)}" class="w-20 h-20 rounded-full object-cover mx-auto mb-3 border-2 border-paper-200">`
              : `<div class="w-20 h-20 rounded-full bg-paper-100 text-slate-400 flex items-center justify-center mx-auto mb-3"><i data-lucide="user" class="w-9 h-9"></i></div>`}
            <div class="font-semibold text-ink-900">${escapeHtml(c.name)}</div>
            <div class="text-xs text-slate-500 mt-1">${escapeHtml(c.bio || "")}</div>
          </label>
        `).join("")}
      </div>
    </div>
  `).join("");

  refreshIcons();
  showView("ballot");
}

async function submitVote() {
  const selections = {};
  for (const pos of currentBallot.positions) {
    const checked = document.querySelector(`input[name="position-${pos.position_id}"]:checked`);
    if (!checked) return showMessage(msgBox(), `Please select a candidate for ${pos.title}.`, "error");
    selections[pos.position_id] = parseInt(checked.value, 10);
  }

  const { ok, data } = await API.post(`/voter/elections/${currentElectionId}/vote`, { selections }, Session.getVoterToken());
  if (!ok) return showMessage(msgBox(), data.error || "Could not cast vote.", "error");

  document.getElementById("tx-hash").textContent = data.transaction_hash;
  showView("confirmation");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : str;
  return div.innerHTML;
}

(async function init() {
  updateAuthUI();
  await loadHome();
  showView("home");
})();
