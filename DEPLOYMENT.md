# Deployment Guide (free tier only — no credit card required anywhere)

This gets your e-voting system running on a real public URL with HTTPS,
using:
- **Neon** (neon.tech) — PostgreSQL, permanent free tier, no card required
- **Render** (render.com) — app hosting, free web service tier, no card required

Total cost: **$0**. See `docs/DEVLOG.md` Entry 17 for why these two
specifically (and why Railway/PythonAnywhere were avoided).

**One thing to know going in:** Render's free tier "spins down" your app
after 15 minutes with no traffic, and takes 30-60 seconds to wake back up
on the next request. Before presenting, open your Render URL a few
minutes early so it's already awake.

---

## Step 1 — Push your code to GitHub

If you haven't already:

```bash
cd evoting-system
git init
git add .
git commit -m "Initial commit"
```

Create a new repository on github.com (empty, no README), then:

```bash
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main
```

Your `.gitignore` already excludes `venv/`, `__pycache__/`, `*.db`, and
`backend/security/.secrets/` — none of your local secrets or database
will get pushed, which is correct (production uses different secrets,
set as environment variables — see Step 3).

---

## Step 2 — Create your database on Neon

1. Go to **neon.tech** and sign up (email is enough, no card).
2. Create a new project. Neon gives you a **connection string** that
   looks like:
   ```
   postgresql://your_user:your_password@ep-xxxx-xxxx.region.aws.neon.tech/neondb?sslmode=require
   ```
3. Copy that connection string — you'll use it twice: once locally (this
   step) and once in Render (Step 3).

**Initialize the schema and create your admin account** — do this from
your own machine, pointing at the live Neon database:

```bash
cd evoting-system/backend

# macOS/Linux:
export DATABASE_URL="postgresql://your_user:your_password@ep-xxxx.neon.tech/neondb?sslmode=require"
# Windows (PowerShell):
$env:DATABASE_URL="postgresql://your_user:your_password@ep-xxxx.neon.tech/neondb?sslmode=require"

pip install "psycopg[binary]"   # if you haven't already
python database/db.py
python create_admin.py youradminname youradminpassword
```

This connects out to Neon and creates all your tables and your admin
account — it works from anywhere with internet, not just from Render.

---

## Step 3 — Deploy the app on Render

1. Go to **render.com** and sign up (no card required for the free tier).
2. **New +** → **Web Service** → connect your GitHub repo.
3. Fill in:
   - **Root Directory:** `backend`
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Instance Type:** Free
4. Add environment variables (click **Add Environment Variable** for
   each one — type only the exact key name shown, nothing else, no
   backticks/quotes/extra text):
   - Key `DATABASE_URL`, Value: the exact same Neon connection string from Step 2
   - Key `SERVER_SECRET_KEY_HEX`, Value: generate one on your own machine:
     ```bash
     python -c "import os; print(os.urandom(32).hex())"
     ```
     paste only the printed hex string
   - Key `SYSTEM_PEPPER_HEX`, Value: run that same command again — it
     prints a **different** random string each time — paste that one here
   - **Optional but recommended:** SMTP variables so registration actually
     emails verification codes instead of falling back to dev mode (see
     "Setting up email sending" below) — `SMTP_HOST`, `SMTP_PORT`,
     `SMTP_USERNAME`, `SMTP_PASSWORD`
5. Click **Create Web Service**. Render will build and deploy — first
   deploy takes a few minutes.
6. Once live, Render gives you a URL like `https://your-app.onrender.com`
   — HTTPS is automatic, nothing to configure.

Visit:
- `https://your-app.onrender.com/` — voter portal
- `https://your-app.onrender.com/admin` — admin dashboard
- `https://your-app.onrender.com/health` — should return
  `{"status": "ok", "database": "PostgreSQL", ...}`

---

## Before you present

- [ ] Open your Render URL 5-10 minutes early to wake it from sleep
- [ ] Log into the admin dashboard once to confirm it connects
- [ ] Do one full dry-run vote (register a test student ID, log in, vote)
- [ ] Bring a mobile hotspot as backup if the venue's wifi is uncertain
      (both Tailwind/fonts/icons and the app itself need internet)

## Setting up email sending (optional — free, but has a manual step)

Registration verification codes are emailed to students. Without SMTP
configured, the server falls back to returning the code directly in the
API response (clearly labeled "dev mode" — see `services/
email_service.py` and `docs/DEVLOG.md`), which is fine for demoing but
not for a real election, since anyone could read the code without
checking any inbox.

**Free option: Gmail with an "app password"** (not your normal Gmail
password — a separate, revocable one Google generates specifically for
this):

1. Go to your Google Account → **Security** → make sure **2-Step
   Verification** is turned on (required before app passwords are
   available).
2. Still under Security, find **App passwords** (search "app passwords"
   in the account settings search bar if you don't see it directly).
3. Create one for "Mail" — Google shows you a 16-character password once.
   Copy it.
4. In Render's Environment tab, add:
   - `SMTP_HOST` = `smtp.gmail.com`
   - `SMTP_PORT` = `587`
   - `SMTP_USERNAME` = your full Gmail address
   - `SMTP_PASSWORD` = the 16-character app password from step 3 (not
     your regular Gmail password)

Gmail's free sending limit is generous enough for a class election
(hundreds of emails/day). If you'd rather not use a personal Gmail
account, **Brevo** (formerly Sendinblue) has a genuinely free-forever
tier (300 emails/day, no card required) built specifically for this kind
of transactional email — sign up, find their SMTP credentials under
their dashboard's SMTP/API settings, and use those instead of Gmail's.

**Important:** actual email delivery could not be tested from this
project's development environment (no outbound access to mail servers
during development — see docs/DEVLOG.md). Send yourself one test
registration once this is configured, before relying on it for a real
election.

## Migrations (schema changes after you've already deployed)

If you deployed before a feature that changed the database (like
publishing results) was added, you need to run a **migration** against
your live Neon database once — this adds new columns without touching
any existing data.

From your own machine, pointing at the same Neon connection string you
used in Step 2:

```bash
cd evoting-system/backend
export DATABASE_URL="postgresql://your_user:your_password@ep-xxxx.neon.tech/neondb?sslmode=require"
python database/migrate_add_results_published.py
python database/migrate_add_email_hash.py
```

You should see `Migration complete: ...`. This is safe to run more than
once — it checks whether each column already exists before adding it,
so re-running it does nothing the second time. Your existing elections,
voters, and votes are untouched.

**After running `migrate_add_email_hash.py` specifically:** any student
IDs that were authorized *before* this migration have no email on file
(`email_hash` is `NULL`) and won't be able to register until you
re-upload them with an email through the admin dashboard's Authorized
Voters tab — re-uploading an already-authorized ID updates its email
rather than erroring, so this is safe to do.

You do **not** need to redeploy on Render for this — migrations run
directly against the database, independent of the app code. Just make
sure Render is running the latest code (`git push` as usual) so it knows
about the new columns/endpoints.

## Troubleshooting

**"Environment variable keys must consist of alphabetic characters,
digits, '_', '-', or '.'"** — something other than the plain variable
name got into the Key field (usually backticks or extra text from a
copy-paste). Re-type just `DATABASE_URL` (or whichever key) by hand
rather than pasting, with nothing else in the box.

**`ImportError: ...psycopg2/_psycopg...: undefined symbol:
_PyInterpreterState_Get`** on startup — this means Render is running a
newer Python than the old `psycopg2-binary` package's precompiled wheel
supports. In practice, `runtime.txt` / a `PYTHON_VERSION` environment
variable didn't reliably fix this on Render. The actual fix (already
applied in this project): use `psycopg` (v3) instead of `psycopg2` —
it's actively maintained with wheels for current Python versions, so
there's no version to pin in the first place. If you ever see this error
again, check `requirements.txt` says `psycopg[binary]`, not
`psycopg2-binary`, and that `database/db.py` imports `psycopg`, not
`psycopg2`.

## If something changes later

- **Redeploying:** just `git push` — Render redeploys automatically on
  every push to your connected branch.
- **Rotating secrets:** change the environment variable in Render's
  dashboard and redeploy. Note this invalidates all current sessions
  (everyone would need to log in again) — fine between elections, not
  something to do while one is actively open.
- **The dev-only OTP endpoint** (`/dev/generate-otp`, see
  `routes/dev_routes.py`) is still live in this deployment, which is
  fine for a demo but **must be removed** before any real, binding
  student election — see that file's docstring.
