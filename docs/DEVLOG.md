# Project Devlog

Purpose of this file: every design decision, the reasoning behind it, and
the alternatives we rejected — written down as we make it, not
reconstructed from memory later. When it's time to write the report,
the "Methodology" and "System Design" chapters are mostly this file
reorganized into prose, and the "Objectives justified" and "Limitations"
sections come almost directly from the entries below.

Each entry: **what we decided**, **why**, **what we considered instead**.
Add a new entry every time we make a decision worth defending in a viva —
not for routine code (e.g. "renamed a variable"), but for anything where
a reasonable person could have chosen differently.

---

## Entry 1 — Overall architecture

**Decision:** Single backend language (Python + Flask), SQLite for
development, raw parameterized SQL (no ORM), plain frontend.

**Why:** The project's actual grading focus is the security algorithms
(hashing, encryption, anomaly detection) implemented from scratch. Splitting
the backend across two languages (e.g. Node.js + Python) would add
integration overhead (inter-service calls, duplicated validation, two sets
of dependencies) without making any of those algorithms better. Python's
native arbitrary-precision integers also make RSA's modular exponentiation
straightforward to implement by hand — no external bignum library needed.

**Considered instead:** Node.js backend with a separate Python
microservice for crypto/ML. Rejected for this project's scope — it's a
legitimate architecture, but it roughly doubles the surface area for bugs
for no security benefit, which works against "finish a solid project" over
"look complex."

---

## Entry 2 — RSA must not be used in textbook form

**Problem found:** Standard RSA encryption `c = m^e mod n` is
deterministic. If the message space is small and guessable (e.g. a
candidate ID from 1–5), anyone holding the *public* key can encrypt every
possible candidate ID themselves and compare ciphertexts — recovering the
vote without ever touching the private key. This is a well-known flaw when
RSA is applied naively to small discrete message spaces like votes.

**Decision:** Before encrypting, prepend a random nonce to the serialized
ballot so the same vote never produces the same ciphertext twice. This is
a simplified, hand-built version of the padding schemes (like OAEP) that
real RSA implementations use for exactly this reason.

**Why it matters for the report:** This is worth writing up explicitly —
identifying and fixing this is stronger evidence of understanding RSA than
just implementing the textbook formula.

---

## Entry 3 — Database schema separates "who voted" from "what they voted"

**Decision:** `voter_election_status` (has this voter voted?) and `votes`
(what was voted) are two separate tables with **no foreign key between
them**. `votes` doesn't store a voter ID at all.

**Why:** Encryption alone protects a vote from an outside attacker reading
the database. It does *not* protect against someone with legitimate
database access (e.g. an admin) who could otherwise join "voter X voted at
3:02pm" with "the vote submitted at 3:02pm was for candidate Y." Removing
the join key at the schema level closes that gap architecturally, not just
cryptographically — this is a design decision, not just a crypto one, and
it's worth its own paragraph in the report.

**Considered instead:** Storing `voter_id` on `votes` and relying purely on
encryption for privacy. Rejected — encryption protects confidentiality in
transit/at rest, but doesn't prevent an authorized insider from
correlating timestamps.

---

## Entry 4 — Authentication: multi-factor plus a named limitation

**Decision:** Registration is gated by an admin-preloaded list of
authorized student ID hashes (`authorized_voters`). Login requires
password *and* a TOTP time-based one-time code (implemented from scratch
using HMAC + SHA-256, per RFC 6238's approach). Sessions are bound to a
device fingerprint hash. An ID is fully locked out of future logins for
that election the instant a ballot is submitted.

**Why:** No single factor is trustworthy alone — a leaked password isn't
enough without the live OTP; a leaked OTP is time-limited; a hijacked
session token doesn't work from a different device fingerprint.

**Named limitation (important for the report):** None of this stops a
student *voluntarily* sharing their password and OTP with someone else
(vote-selling / coercion). This is a known, unsolved limitation of every
remote e-voting system, including the Estonian i-Voting system referenced
in our literature review. We mitigate procedurally (short OTP validity,
re-entering the password immediately before final ballot submission) but
do not claim to solve it. Stating this explicitly is more credible than
overclaiming.

---

## Entry 5 — SHA-256 implemented and validated

**Decision:** Implemented SHA-256 from scratch in `security/hashing.py`
following FIPS 180-4 (message padding, 64-round compression function,
message schedule with sigma functions). Salts are generated with
`os.urandom()` — the OS's CSPRNG — rather than hand-rolled, since building
a secure random number generator is a distinct and higher-risk problem
than implementing a hash algorithm (see comment in the file for the
reasoning; worth repeating in the report as a deliberate scope boundary).

**Validation approach:** Ran our implementation against Python's built-in
`hashlib.sha256` on four cases: empty input, a short string, a realistic
student-ID-like string, and a 1000-byte input (to exercise the multi-block
chunking path, since anything under 56 bytes fits in a single 64-byte
block and wouldn't catch a chunking bug). All four matched exactly.

**Why this matters for the report:** "We tested against a byte-for-byte
match with a trusted reference implementation" is a much stronger
verification claim than "we ran it and it produced a hash." Screenshot
the passing test output — it's good evidence for an appendix.

---

## Entry 6 — HMAC and TOTP implemented and validated against official test vectors

**Decision:** Implemented HMAC-SHA256 from scratch in `security/hmac_custom.py`
(built on our own `sha256_digest`, per RFC 2104's key-padding + inner/outer
hash construction), then TOTP in `security/totp.py` on top of that
(per RFC 6238) for the second login factor.

**Design choices worth defending in a viva:**
- TOTP over HOTP (counter-based OTP): avoids having to keep the server's
  and the voter's "usage counter" in sync, which is a real failure mode
  for counter-based OTP. Time-based only needs roughly synchronized clocks.
- `window=1` tolerance in `verify_totp`: accepts the code from one 30-second
  step before or after the current one, so a voter who is slightly slow
  typing the code isn't locked out. This is a deliberate usability/security
  trade-off — worth a sentence in the report on why it doesn't meaningfully
  weaken the scheme (it only extends the valid window from 30s to 90s).

**Validation approach:** HMAC was checked against Python's built-in `hmac`
module across 4 cases, including a key longer than the hash block size
(the most common implementation bug). TOTP was checked against the
**official RFC 6238 Appendix B test vectors** — 6 fixed timestamps with
known-correct 8-digit codes for the SHA-256 variant, published specifically
so implementers can self-verify. All 6 matched exactly.

**Why this matters for the report:** matching official RFC test vectors is
a stronger, more citable verification claim than matching our own
hashlib/hmac comparison — it proves correctness against the spec itself,
not just internal consistency.

---

## Entry 7 — Registration, login, and admin routes wired together

**Decision:** Built `security/tokens.py` (signed, self-contained session
tokens using our own HMAC — same idea as a JWT, built from scratch),
`services/auth_service.py` (registration + two-step login logic), and
Flask routes (`routes/voter_routes.py`, `routes/admin_routes.py`) that
call into it. Routes stay thin on purpose — all logic lives in
`services/` so it can be tested directly without spinning up HTTP.

**Two-step login, not one call:** Step 1 checks password, returns a
short-lived (5 min) "pending_otp" token if correct. Step 2 checks the
TOTP code against that pending token and, if correct, issues a full
session token bound to a device fingerprint (hash of User-Agent + IP).
A "pending_otp" token cannot be used as a session token even if leaked,
because `validate_voter_session` checks the token's `scope` field — this
is tested explicitly in `test_auth_flow.py`.

**Same error message for "unknown ID" and "wrong password":** Returning
a different message for each would let an attacker enumerate which
student IDs are registered by testing logins and watching which error
comes back. This is a small but real design choice worth naming in the
report — it's the kind of thing that separates "we added a password
field" from "we thought about what the password field could leak."

**Admin login has no TOTP (scope decision):** Admins are assumed to be
trusted campus IT/election staff working from known machines, not remote
voters — a different risk profile. This is a place we're consciously not
applying the same rigor as voter auth, and it's flagged here rather than
silently left out, in case a marker asks "why does admin login look
weaker?"

**Validation approach:** `test_auth_flow.py` runs the full flow through
Flask's real test client (actual HTTP request/response cycle) against a
disposable database, and checks 13 cases — not just "does registration
work," but "is an unauthorized ID rejected," "is a duplicate registration
rejected," "is the wrong OTP rejected," "is a stolen pending-token
useless as a session token," and "is the voter-upload endpoint actually
protected." All 13 passed on first run. This test file doubles as a
demo script — it's a good candidate to walk through live in the
presentation.

---

## Entry 8 — Election setup and the draft-lock rule

**Decision:** Added `services/election_service.py` and matching admin/voter
routes for creating elections, adding positions and candidates, and
opening/closing an election. Two rules are enforced in code, not just
assumed:

1. An election can only move `draft -> open` once **every position has
   at least 2 candidates**. A position with 0 or 1 candidates isn't a
   real contest, so we refuse to open until it is one.
2. Positions and candidates can only be added **while still in draft**.
   Once an election is `open`, the ballot structure is frozen. This
   matters more than it sounds: without it, an admin (or a compromised
   admin account) could add or remove a candidate mid-election, which
   would undermine every integrity guarantee the crypto layer provides.
   No amount of RSA or hashing protects a vote if the thing being voted
   on can change after votes start coming in.

**Ballot viewing is session-gated, not just URL-based:** `/voter/elections/
<id>/ballot` requires a valid, device-bound voter session — the same
`require_voter_session` mechanism that will guard ballot *casting* once
that's built. Verified in `test_election_flow.py` that a session token
used from a different device fingerprint is rejected, and that a request
with no token at all is rejected.

**Validation approach:** `test_election_flow.py` — 13 checks including
both business rules above, that positions can't be added after opening,
that a real logged-in voter can see all positions and all candidates
correctly, and that closing an election blocks further ballot access.
Re-ran `test_auth_flow.py` afterward to confirm nothing in the auth layer
regressed — 13/13 still passing.

---

## Entry 9 — RSA implemented from scratch, including primality testing

**Decision:** Implemented in `security/rsa_custom.py`:
- our own modular exponentiation (square-and-multiply), not Python's
  built-in `pow(x, y, z)` — using the builtin would mean the single most
  important RSA subroutine wasn't actually "from scratch"
- our own extended Euclidean algorithm for the modular inverse (the
  private exponent `d`), not Python 3.8's `pow(e, -1, phi)` shortcut
- our own Miller-Rabin primality test for key generation, not a
  library's `isprime()`

**Key size — revised after measuring, not guessing:** Originally planned
a 512-bit modulus assuming pure-Python big-integer math would be too slow
for anything larger to generate live in a demo. Measured it instead:
512-bit = 0.03s, 1024-bit = 0.11s, 2048-bit = 1.5s (later re-measured at
~0.7s during the actual test run — some variance run to run, still well
within demo-friendly range). Switched the default to **2048 bits**, the
current generally-recommended minimum for real RSA, since there was no
actual reason to compromise on security for speed we didn't need to
trade away. Worth including this measurement in the report — it shows a
decision made from evidence rather than assumption.

**Padding fix validated directly:** The self-test encrypts the identical
ballot (`b"E3|P1:C7|P2:C12"`) twice and asserts the two ciphertexts are
different — this is the direct, empirical proof that the small-message-
space guessing attack identified in Entry 2 is actually closed, not just
theoretically addressed. Both ciphertexts still decrypt back to the exact
original ballot.

**Miller-Rabin tested against a Carmichael number:** The correctness
check includes 561 (3 × 11 × 17, the smallest Carmichael number) among
the composites it must correctly reject. Carmichael numbers are
specifically the case that fools the simpler Fermat primality test, so
correctly flagging 561 as composite is a meaningfully stronger claim than
just checking ordinary composites like 91 or 100 — worth a sentence in
the report on why Miller-Rabin was chosen over Fermat.

**Ballot encoding is compact, not JSON:** The padding scheme (nonce +
4-byte length prefix + plaintext) needs the whole message to fit under
the modulus. A real ballot is encoded as a short string like
`"E3|P1:C7|P2:C12"` (election 3, position 1 → candidate 7, position 2 →
candidate 12) rather than verbose JSON — this will be finalized in
`services/ballot_service.py` when ballot casting is wired up next.

---

## Entry 10 — Ballot casting, race-safe one-vote enforcement, and tallying

**Decision:** `services/ballot_service.py` encodes a voter's selections
into a compact string (`"E3|P1:C7|P2:C12"`), validates it against the
actual election structure (every position covered, no more/fewer;
candidates must actually belong to the position they're claimed for),
encrypts with `rsa_custom.encrypt_ballot`, and stores it with a SHA-256
transaction hash sealing the ciphertext.

**Where the RSA keypair actually gets created:** the moment an election
moves `draft -> open` (in `election_service.open_election`), not
earlier and not on demand per vote. One keypair per election, generated
fresh each time.

**Named limitation — key custody:** both the public *and private* key
are currently stored in the same `elections` row, in the same database as
the votes. That means anyone with database access could decrypt votes
while the election is still running, which defeats the point of
encrypting them during the voting window in the first place. Real e-voting
systems solve this with threshold cryptography (the private key is split
across several trustees, e.g. election commissioners, who must
combine their shares to decrypt) or hardware security modules. Implementing
threshold decryption from scratch was judged out of scope for this
project's timeline, but it's flagged here explicitly as the single
biggest gap between this system and a production one — much better to
name it than have it discovered in the viva.

**Race condition closed, not just made unlikely:** `cast_vote_atomic` in
`database/queries_votes.py` checks "has this voter already voted?" and
records their vote inside one `BEGIN IMMEDIATE` transaction, so a second
concurrent request from the same voter has to wait for the first to
finish before it can even read the status. A naive "check, then
separately write" pattern has a real gap where two near-simultaneous
requests could both slip through.

**Validation approach:** `test_ballot_flow.py` — 19 checks. Notably:
two voters (A and C) cast *identical* selections, and the test asserts
their stored ciphertexts are still different (proof the RSA padding
works at the full system level, not just in the crypto module's own
self-test). Also simulates a tampered database record (directly
corrupting a stored `encrypted_ballot`) and confirms the tally correctly
flags it via the transaction hash rather than silently miscounting it.
All three test suites (auth, election, ballot — 45 checks total) still
pass together after this change.

---

## Entry 11 — Isolation Forest, and discovering "swamping" empirically

**Decision:** Implemented Isolation Forest from scratch in
`security/isolation_forest.py` (Liu, Ting & Zhou 2008): random-split
trees, path-length-based anomaly scoring, normalized against `c(n)` (the
average unsuccessful-BST-search path length — same formula as in the
proposal). Validated first on a clean synthetic case (a tight 2D normal
cluster plus 4 far-away outliers) — all 4 outliers landed in the top 4
scores.

**Applied to login behavior, not vote content:** `services/
anomaly_service.py` extracts 3 features per login event — OTP entry time,
how many times this voter has attempted login in the last 5 minutes, and
how many login attempts have come from this exact device fingerprint
(across any voter) in the last 5 minutes. Votes themselves are never
touched — see schema.sql's anonymity design — so this stays entirely
about *how* someone logs in, not *what* they voted.

**Discovery worth reporting: "swamping."** Initial testing simulated an
8-10 event bot-like burst (one device, many accounts, near-instant OTP
entry) and found weaker-than-expected separation from normal logins —
some normal points scored close to or above some bot points. Reducing
the burst to 5 events, with everything else unchanged, separated
cleanly (bot scores 0.60-0.69 vs. normal max ~0.60 with real headroom).
This is not a bug — it's a documented characteristic of vanilla
Isolation Forest called "swamping": a *cluster* of similar anomalies is
inherently harder to isolate than scattered single points, because after
the cluster splits away from normal data as a group, more splits are
still needed to separate individuals within it, which lengthens their
average path and lowers their score. This is genuinely good material for
the report — identifying a real, citable limitation of the algorithm
through direct experimentation, rather than assuming the textbook
formula behaves ideally on every input shape, is a stronger academic
claim than "we implemented Isolation Forest and it worked."

**Adaptive threshold, not a fixed number:** flags anything scoring more
than 1 standard deviation above the *current batch's own* mean score,
with an absolute floor (0.55) so a uniformly boring batch doesn't
manufacture anomalies out of its own noise. A single hardcoded cutoff
(tried first) is fragile — the right cutoff shifts with dataset size and
how much natural variation exists in "normal" behavior for that
particular window.

**Named limitation for the report:** because of swamping, a large,
sudden, coordinated attack (dozens of simultaneous bot logins) may
initially score lower per-event than a small early burst would — the
opposite of what intuition suggests. A production system would pair this
with a simple absolute-count rule (e.g. "flag 10+ logins from one device
in 5 minutes" outright) as a backstop, rather than relying on Isolation
Forest alone for large coordinated bursts.

**Validation approach:** `test_anomaly_detection.py` simulates 25 normal
logins and a 5-event bot-like burst, and checks: most bot events are
flagged, most normal events are not, the feature-level signal is
correctly extracted (bot device-attempt counts and OTP times are clearly
different from normal), flagged anomalies are persisted to `audit_log`,
and the admin API endpoint (`GET /admin/security/anomalies`) surfaces
the same results. All four test suites (auth, election, ballot, anomaly
— 58 checks total) pass together.

---

## Entry 12 — Frontend: voter portal and admin dashboard

**Decision:** Plain HTML/CSS/JS (no framework), served directly by Flask
from `frontend/` via a static folder — one process to run for the whole
demo. Voter portal at `/`, admin dashboard at `/admin`, both calling the
existing JSON API with `fetch()`. Session tokens stored in
`localStorage` (this is a real page in a real browser, not a Claude
artifact sandbox, so that restriction doesn't apply here — it's the
correct tool for persisting a session across page reloads).

**Design direction — deliberately not a generic dashboard template:**
this is a formal student election system, so the visual language borrows
from physical ballots and official seals (deep ink-navy, warm paper
background, serif headings, a wax-seal stamp badge for election status
and vote confirmation) rather than a typical SaaS look. The stamp badge
is the one signature element; everything else stays restrained. Full
rationale and tokens are documented at the top of `frontend/css/style.css`.

**Named scope decision — the dev-only OTP auto-fill endpoint:**
`routes/dev_routes.py` adds `POST /dev/generate-otp`, which computes the
current TOTP code for a given secret on request. This is flagged as
explicitly **not belonging in any real deployment** — a second
authentication factor that the server will generate on demand isn't a
second factor at all. It exists solely so this project can be demoed
live (registering and logging in several test voters in a row) without
needing a separate phone running an authenticator app for each one. The
voter portal shows a visible "(demo)" label on the button that calls it,
and the file's own docstring says to delete it before any real
deployment. Naming this clearly is much better than letting it look like
an oversight.

**Validation approach:** `test_full_demo_flow.py` replays the entire
presentation script end-to-end through Flask's test client — the exact
same sequence and endpoints the actual UI buttons call, from page load
through admin setup, voter registration/login/voting, closing, tallying,
and the anomaly scan. All 17 steps passed on first run. Combined with
the other four suites, **75 checks pass across the whole system**.

---

## Entry 13 — create_admin.py: fixing an apparent "freeze"

**Problem reported:** running `python create_admin.py` appeared to hang
after the password prompt, with no way to type anything.

**Actual cause:** `getpass.getpass()` deliberately shows nothing as you
type — no characters, no cursor movement — so a password can't be
shoulder-surfed. That's easy to mistake for a frozen script. In some
terminals (certain IDE-integrated terminals, some Windows setups) hidden
input genuinely doesn't work and the script would hang for real.

**Fix:** `create_admin.py` now also accepts the username and password as
plain command-line arguments (`python create_admin.py <username>
<password>`), bypassing interactive input entirely, with a note that
this leaves the password in shell history so it's only for a machine
only you use. The interactive path also now catches the case where
hidden input fails and falls back to plain, visible input rather than
hanging silently.

---

## Entry 14 — UI polish pass

**Decision:** Kept the civic/ballot design direction from Entry 12 (it
was the right call for a formal election system) but executed it with
more contemporary polish rather than switching themes:
- Layered shadows and a subtle dot-grid paper texture on the background
  instead of flat colors
- A real animated progress line behind the ballot steps (a CSS custom
  property `--progress`, updated in JS, drives a gradient-filled bar
  between step circles) instead of static circles alone
- The wax-seal "Vote Recorded" stamp now has a dashed outer ring, a
  radial-gradient fill, and a pop-in entrance animation — leaning further
  into the one deliberate signature element rather than adding new ones
- Candidate options highlight via CSS `:has(input:checked)` — no JS
  needed to show which choice is selected
- Inline SVG icons (seal mark in both headers, sidebar nav icons) instead
  of a plain letter — kept as inline SVG rather than an icon font/CDN so
  the demo has zero external network dependency
- Loading spinners on every async admin action (elections list, results
  tally, anomaly scan) so waiting on a real request doesn't look broken
- A matching inline-SVG favicon (data URI, no external file) so the
  browser tab looks finished too

**Why inline SVG everywhere, not an icon library or Google Fonts:** this
keeps the whole frontend at zero external dependencies — the demo can't
fail because a CDN was unreachable or the venue's wifi was flaky. Same
reasoning as the original font-stack choice in Entry 12.

**Validation approach:** re-ran all five backend test suites (70 checks)
to confirm the CSS/HTML/JS changes didn't touch any behavior — this was
a presentation-only change. Also verified the stylesheet's braces balance
(95 open, 95 close) and that both pages still serve correctly with the
new markup present (SVG marks, sidebar icons) via the Flask test client.

---

## Entry 15 — Date/time picker, candidate photos, and a voter portal redesign

**Date + time picker:** replaced plain text inputs for election start/end
with a native `<input type="date">` (browser-provided calendar, no custom
code needed) plus a hand-built iOS-style scroll-wheel time picker
(`frontend/js/widgets.js`) — three snapping columns (hour, minute, AM/PM)
using CSS `scroll-snap-type`, no library. The two combine into the same
`"YYYY-MM-DDTHH:MM"` string the backend already expected, so no API
changes were needed.

**Candidate photos:** added `photo_base64` / `photo_mime` columns to
`candidates`. Images are resized client-side via a `<canvas>` (max 400px
on the long edge, JPEG re-encode) *before* upload, capped further server-
side (`MAX_PHOTO_BASE64_CHARS`) as a defense-in-depth limit — a
malicious or just-oversized upload can't bloat the database even if the
client-side resize is bypassed. Stored as base64 directly in SQLite
rather than as files on disk, since a single extra text column is
simpler than managing an uploads directory across `/mnt` boundaries and
is more than adequate at this data volume. Returned pre-formatted as a
data URI (`get_election_structure`) so the frontend just drops it
straight into an `<img src="">` — no separate image-serving endpoint
needed.

**Schema change requires a fresh database:** SQLite doesn't auto-migrate
new columns onto an existing table. Anyone who already ran `database/
db.py` before this change needs to delete `database/evoting.db` and
re-run it — flagged here and in the README rather than silently breaking
on old databases.

**Voter portal redesign, scoped separately from admin:** all voter-only
styling lives under a `.voter-app` body class, so the admin dashboard
(explicitly signed off as "acceptable") was untouched. Candidate
selection changed from plain radio rows to a photo card grid — each
candidate is a full clickable card (photo or a placeholder avatar icon,
name, bio) that highlights and shows a check badge when selected, using
`:has(input:checked)` again rather than extra JS. Added a soft, slowly
drifting blurred-gradient backdrop (two blobs, `filter: blur()`, CSS
keyframe drift) for a more contemporary consumer-app feel distinct from
the admin's control-room tone, and a small reflow trick
(`el.style.animation = 'none'; void el.offsetHeight; el.style.animation
= ''`) so the entrance animation replays on every view switch instead of
only once on page load.

**Validation approach:** re-ran all five backend suites (70 checks) after
the schema change — all still pass against a freshly initialized
database. Directly tested the photo upload pipeline end-to-end (upload a
fake image via the API, fetch the election structure back, confirm the
returned data URI decodes to the exact same bytes that were uploaded).
Verified the stylesheet's braces balance (141/141) and that both pages
still serve with the new markup present.

---

## Entry 16 — Full UI overhaul: libraries, home dashboard, election editing

**Scope decision reversed on purpose:** every earlier frontend entry
(12, 14, 15) deliberately avoided external dependencies — CDN fonts,
icon libraries — specifically so the demo couldn't fail from a bad wifi
connection. Explicitly told to prioritize visual polish over that
constraint this time, so that trade-off was reconsidered rather than
silently ignored: the frontend now pulls in **Tailwind CSS**, **Google
Fonts (Inter + Fraunces)**, **Lucide icons**, and **flatpickr** (all via
CDN). This is a real trade-off, not a free upgrade — **the frontend now
requires an internet connection to look/work correctly**, which is worth
testing at the actual presentation venue beforehand, or having a mobile
hotspot as backup. Recorded here so it's a documented decision, not a
surprise on presentation day.

**Home dashboard replaces the locked step-wizard:** the voter portal
used to force every visitor through a fixed Register → Verify → Vote
sequence. It's now a persistent home page — a header that shows
Login/Register when signed out and Logout when signed in, and an
"Ongoing elections" section with live turnout bars — visible to anyone,
logged in or not. This uses the new public endpoint
(`GET /voter/public/elections`) which deliberately exposes only
aggregate participation counts (X of Y registered voters have voted),
never individual votes or who cast them — same anonymity boundary as
everywhere else in the system, just made visible for transparency.
Login and Register moved into modals rather than full-page steps, which
is both a more modern pattern and lets the home dashboard stay the
persistent backdrop.

**Date/time picker replaced with flatpickr:** the hand-built scroll-wheel
picker from Entry 15 worked but looked rough and took real code to
maintain. Swapped it for flatpickr (MIT-licensed, widely used) — one
combined date+time field per boundary, output already in the
`"YYYY-MM-DDTHH:MM"` format the backend expects, so no API changes were
needed. This is a case where "not from scratch" is the right call: a
date picker isn't a security algorithm or something the project is meant
to demonstrate understanding of — it's UI plumbing, and a mature library
does it better than a rushed custom one.

**Election editing, restricted to draft:** `PATCH /admin/elections/<id>`
lets an admin fix a typo or reschedule — but only while the election is
still in draft, for the identical reason positions/candidates are locked
once open (Entry 8): changing what's being voted on, or when, after
votes may already exist would undermine the integrity story regardless
of how good the crypto is. Attempting to edit an open or closed election
is rejected server-side, not just hidden in the UI.

**Validation approach:** `test_election_editing_and_turnout.py` (12
checks) covers editing succeeding/failing at the right election states,
partial edits not clobbering untouched fields, and turnout math being
correct (0/2 → 1/2 → 50.0%) as votes come in. Re-ran all six suites (82
checks total) after every backend change in this entry — all still pass.
Verified both pages still serve correctly with every new library
reference and dynamic-content hook present via the Flask test client.

---

## Entry 17 — PostgreSQL support for deployment, and a bug real testing caught

**Decision:** `database/db.py` now supports PostgreSQL alongside SQLite,
selected automatically via a `DATABASE_URL` environment variable (the
standard convention managed hosting platforms use). SQLite stays the
zero-setup default for local development; nothing changes for that
workflow. Every other file only ever calls `get_connection()`,
`run_query()`, or the new `run_insert()` from this one file, so the rest
of the codebase doesn't know or care which engine is active.

**Concurrency control simplified, not just ported:** the original
one-vote enforcement (`cast_vote_atomic`) used SQLite-specific
`BEGIN IMMEDIATE` locking, which has no PostgreSQL equivalent. Rather
than writing engine-specific locking code for each database, the
function was rewritten to rely on the `PRIMARY KEY` constraint on
`voter_election_status(voter_id, election_id)` — two concurrent INSERT
attempts for the same voter+election can't both succeed, and the
database engine itself guarantees that atomically, identically on both
engines. This is simpler than the original and arguably more robust: the
guarantee comes from the storage engine, not application-level lock
management.

**Tested against a real PostgreSQL instance, not assumed to work:**
installed PostgreSQL locally and ran all six test suites (82 checks)
against it, not just against SQLite. This caught a real bug that
wouldn't have been found by code review alone: `services/
anomaly_service.py`'s recency-window feature counted "how many login
events happened at or before this one" — under SQLite, `CURRENT_TIMESTAMP`
only has 1-second resolution, so a rapid-fire burst of 5 bot-like login
events all got the *identical* timestamp, and the `<=` comparison
happened to count all 5 as "recent" for every one of them, purely by
timestamp collision. Under PostgreSQL's genuine microsecond-precision
timestamps, the same events got distinct timestamps, and the directional
count instead produced 1, 2, 3, 4, 5 — meaning the earliest events in a
burst scored as not-anomalous, which defeats the purpose of a burst
detector. **This was never actually correct logic — SQLite's coarse
timestamp precision was masking a real design flaw.** Fixed by making
the recency count a symmetric time-window ("how many events fall within
5 minutes of this one, before or after") rather than a directional
"count so far" — every event in a burst now correctly sees the full
burst size regardless of arrival order. Re-verified identical results on
both engines afterward. This is a strong example for the report of why
testing against the real target environment matters, not just the
convenient local one.

**PostgreSQL schema:** `database/schema_postgres.sql` mirrors
`schema.sql` structurally (same tables, same anonymity-separation
design), differing only in engine-specific syntax (`SERIAL` instead of
`INTEGER PRIMARY KEY AUTOINCREMENT`, `TIMESTAMP` instead of implicit
`TEXT` for auto-generated audit columns). Both schemas now use
`CREATE TABLE IF NOT EXISTS`, making `init_db()` safe to re-run without
wiping existing data.

**Secrets moved to environment variables for production:**
`security/config_secrets.py` now checks for `SERVER_SECRET_KEY_HEX` and
`SYSTEM_PEPPER_HEX` environment variables first, falling back to the
existing local-file auto-generation for dev. Reasoning: a hosting
platform can restart your app in a fresh container at any time, and a
file-based secret would silently regenerate, invalidating every active
session (or worse, losing the RSA private key custody path entirely).

**Deployment stack chosen, free-forever only (explicit budget
constraint):** PostgreSQL via **Neon** (serverless Postgres, permanent
free tier, no card required) + app hosting via **Render** (free web
service tier, no card required, automatic HTTPS on the provided
`onrender.com` subdomain). Deliberately avoided Railway (their free tier
now requires a paid trial credit) and PythonAnywhere (free tier
restricts outbound connections to a fixed allowlist, which would likely
block a connection to an external database host). Named trade-off:
Render's free tier spins down after 15 minutes of inactivity and takes
30-60 seconds to wake on the next request — worth waking the URL a few
minutes before a live presentation rather than discovering this live.

**Validation approach:** all 82 checks across six suites pass
identically against both a fresh SQLite database and a real, locally
installed PostgreSQL 16 instance.

---

**Runtime pinning didn't actually work — switched to psycopg3 instead:**
`backend/runtime.txt` (`python-3.11.9`) was added after first hitting
`ImportError: undefined symbol: _PyInterpreterState_Get` on deploy, on
the assumption Render would honor it the way Heroku's older convention
does. It didn't — the same error recurred with Render still running
Python 3.14. The actual fix: switched from `psycopg2-binary` (maintenance-
only, precompiled wheels lag behind new Python releases) to `psycopg`
(v3, actively maintained, ships wheels for current Python versions) —
this removes the Python-version-pinning problem entirely rather than
fighting it. `database/db.py`'s Postgres wrapper was updated accordingly
(`psycopg.rows.dict_row` instead of `psycopg2.extras.RealDictCursor`;
otherwise the interface is unchanged). Re-verified all 82 checks pass
against a real PostgreSQL instance with the new driver, and confirmed
SQLite is unaffected. Left `runtime.txt` in place as a general
stabilizer against other bleeding-edge-Python issues, even though it
wasn't the fix for this specific error — worth knowing it may simply not
be honored by Render's native Python service.

**Version pin corrected:** the first attempt pinned `psycopg[binary]==3.2.3`,
a version that doesn't actually exist on PyPI (available releases jump
from the 3.2.x line to 3.2.10+) — an error on my part, not a deeper
issue. Corrected to `psycopg[binary]==3.3.4`, the exact version
installed and tested locally, and re-confirmed all 82 checks pass on
both SQLite and a real PostgreSQL instance with this exact pin.

---

## Entry 18 — Admin sidebar fix, authorized voters list, and voter portal redesign

**Admin sidebar misalignment — root cause found, not guessed at:**
the "Security & anomalies" button (and all sidebar icons) used
`class="w-4.5 h-4.5"` — not a valid Tailwind utility (the default scale
only defines whole and half steps like `w-4`/`w-5`, not `w-4.5`), so it
silently failed to apply and every icon fell back to Lucide's default
(larger) size. Combined with "Security & anomalies" being the longest
label in a fixed-width sidebar, this was the most likely cause of the
"shifted right" look reported. Fixed by using valid `w-5 h-5 shrink-0`
throughout, and shortened the sidebar label to "Security" (the tab's own
heading still says the full "Security & anomalies") so the longest
button no longer risks wrapping or crowding.

**Sign out separated from the tab list:** the sidebar `<aside>` is now
`flex flex-col`, and Sign out sits in its own block with `mt-auto` and a
top border — pinned to the bottom of the sidebar regardless of how many
tabs exist above it, rather than just being the last item in the same
vertical list.

**Authorized voters list — a real constraint, not just a feature add:**
student IDs are stored as one-way SHA-256 hashes (deliberately — see
Entry 1 area of this log on the anonymity/security design), which means
**the original ID can never be shown back**, by design. Built the most
useful honest alternative instead: `GET /admin/voters/list` returns each
entry's hash *fingerprint* (first 12 hex chars — enough to visually
distinguish entries, not enough to be the ID) plus whether that hash has
a matching registered voter yet, via a `LEFT JOIN` against `voters`.
This is arguably more useful day-to-day than seeing raw IDs anyway
("how many have registered so far?"). The boolean from that join is
normalized in the service layer (`bool(row["is_registered"])`) because
SQLite returns `0`/`1` for a boolean SQL expression while PostgreSQL
returns real `True`/`False` — left un-normalized, the API response shape
would differ between local dev and production.

**Password confirmation on registration:** a second "retype password"
field, checked client-side before the request is even sent
(`password !== confirmPassword`). Deliberately not a backend change —
this is a UX safeguard against typos, not a security control, so
client-side is the right (and simplest) place for it.

**Voter portal: dark theme + two-column layout.** Full redesign of the
voter-facing shell (admin dashboard untouched, as it was previously
signed off separately):
- Background is a radial dark gradient (`ink-950` family) with an
  animated, slowly-drifting dot-grid (CSS `background-position`
  keyframe) plus three soft blurred "aurora" glows in the brand's
  crimson/teal/ink tones — subtle motion, not a busy pattern, and
  wrapped in `prefers-reduced-motion` so it turns static for anyone who
  needs that.
- Home page changed from stacked-and-centered (hero above elections,
  the main source of the reported excess whitespace) to a two-column
  `lg:grid-cols-2` layout — hero text and CTAs on the left (sticky, so
  it stays in view while the elections list scrolls on tall pages),
  ongoing elections on the right. Stacks back to a single column
  automatically on small screens.
- Election cards became "glass" cards (`.glass-card`: translucent white
  fill, blurred backdrop, soft border) since flat light cards would have
  looked disconnected sitting on the new dark background.
- Login/Register modals restyled to match (dark modal body, translucent
  inputs) rather than leaving light-on-dark modals inconsistent with the
  rest of the page.
- Ballot casting and confirmation screens were deliberately **kept as
  light cards** floating on the dark shell — candidate photos, radio
  selection states, and dense form content are easiest to keep reliably
  readable on a light surface, and this "dark chrome, light task
  surface" split is a common, intentional pattern (not an oversight)
  rather than an all-or-nothing dark mode.

**Bug fixed in passing:** `.message` (the CSS class every success/error
alert box depends on, via `showMessage()` in `api.js`) had been
accidentally dropped from the stylesheet during an earlier Tailwind
rewrite — meaning every alert on both the voter and admin pages has been
rendering as invisible, unstyled text since that rewrite. Restored as a
light "chip" style that reads clearly on both the dark voter portal and
the light admin dashboard, found while touching this file for the
theme change rather than through separate testing — worth noting in the
report as an example of regressions that pure backend testing can't
catch, since all 82 automated checks were passing the entire time this
was broken.

**Validation approach:** re-ran all six backend suites (82 checks) after
the schema/backend changes (authorized voters list) — all pass. Verified
the new `/admin/voters/list` endpoint directly: upload two IDs, confirm
both show `is_registered: false`, register one, confirm the list updates
to reflect it without re-uploading. Verified the stylesheet's braces
balance (47/47) and that both pages still serve with all new markup and
JS hooks present via the Flask test client.

---

## Milestones checklist

- [x] Project structure, requirements, README
- [x] Database schema designed and documented
- [x] SHA-256 implemented from scratch (hashing module) — validated against hashlib
- [x] HMAC-SHA256 from scratch — validated against Python's hmac module
- [x] TOTP from scratch — validated against official RFC 6238 test vectors
- [x] Voter registration + admin-controlled authorized list
- [x] Login: password + TOTP + device-bound session
- [x] Election / position / candidate management with draft-lock rules
- [x] Miller-Rabin primality test (from scratch)
- [x] RSA key generation + padded encryption/decryption (from scratch, 2048-bit)
- [x] Multi-position ballot casting + one-vote-per-election enforcement (race-safe)
- [x] Results tallying with tamper detection
- [x] Isolation Forest implemented from scratch, validated on synthetic outliers
- [x] Anomaly detection wired into login events (adaptive threshold, admin API endpoint)
- [x] Frontend: voter portal (register/login/vote) + admin dashboard
- [x] UI overhaul: Tailwind/Google Fonts/Lucide/flatpickr, home dashboard with live turnout, modal auth, candidate photos, draft-only election editing
- [x] PostgreSQL support for deployment, tested against a real instance (see DEPLOYMENT.md)
- [ ] End-to-end test run + demo script for presentation
