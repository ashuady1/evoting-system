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

pip install psycopg2-binary   # if you haven't already
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
4. Add environment variables (under "Environment"):
   - `DATABASE_URL` — the exact same Neon connection string from Step 2
   - `SERVER_SECRET_KEY_HEX` — generate one:
     ```bash
     python -c "import os; print(os.urandom(32).hex())"
     ```
   - `SYSTEM_PEPPER_HEX` — generate a **different** one the same way
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
