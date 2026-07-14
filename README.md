# Reyukai Member Management

A small Flask app for managing ~36,000 Reyukai members, with Shibicho-based
filtering, member CRUD, and a printable member list per Shibicho.
Built for a 2-person workflow (you + one office head), so it's kept deliberately simple.

## 1. Local setup

```bash
cd reyukai-app
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # then edit .env with your real Neon URL + secret key
```

## 2. Create a free Neon database

1. Go to https://neon.tech and sign up (no credit card needed).
2. Create a new project — this gives you a Postgres connection string.
3. Copy the connection string into `.env` as `DATABASE_URL`.
   Make sure it starts with `postgresql://` (not `postgres://`) and keeps `?sslmode=require`.

## 3. Initialize the database

```bash
export $(cat .env | xargs)          # loads DATABASE_URL into your shell (Mac/Linux)
flask --app app.py init-db          # creates the members and users tables
flask --app app.py create-user      # creates your login (prompts for username/password)
```

Run `create-user` twice — once for you, once for the office head — so you each
have your own login.

## 4. Run it locally

```bash
python app.py
```

Visit http://localhost:5000 and log in.

## 5. Deploy to Render (free tier)

1. Push this project to a GitHub repo.
2. On https://render.com, click **New > Web Service**, connect the repo.
3. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app` (already in the Procfile, Render should detect it)
   - **Instance Type:** Free
4. Add environment variables in Render's dashboard (Settings > Environment):
   - `DATABASE_URL` — your Neon connection string
   - `SECRET_KEY` — any random string
5. Deploy. Once live, run the same `init-db` and `create-user` commands using
   Render's Shell tab (under your service) so the tables exist in production too.

**Note:** Render's free tier spins the app down after ~15 minutes of no traffic.
The first request after that will take 30-60 seconds to wake up — expected, not a bug.

## What's included

- `/login` — session-based login, one account per user
- `/` — dashboard: total members, total receipts, breakdown by Shibicho
- `/members` — searchable, filterable (by Shibicho + Status), paginated member list
- `/members/add`, `/members/<id>/edit` — add/edit member form, with an Oya No.
  autocomplete that searches existing members by name and links the sponsor
  relationship (Oyaname is always derived from this link, never typed by hand)
- `/members/print` — printable member list per Shibicho
- `/receipts` — searchable, filterable receipt list, linked to members
- `/receipts/add`, `/receipts/<id>/edit` — add/edit receipt, with the same
  member-search autocomplete to link a receipt to the right member
- `/receipts/print` — printable receipt list per Shibicho

## Member fields (mirrors your "Members" sheet)

`S.N` (auto-generated ID), `full_name`, `address`, `Oya No.` / `Oyaname`
(self-referencing link to another member — pick the sponsor by name, the
Oyaname shown is always pulled live from that link), `entrance_date`,
`hozashu`, `jun_shibicho`, `shibicho`, `valid_upto`, `status`
(Active / Expired / Suspended), plus a free-text `notes` field for anything
that doesn't fit elsewhere.

A member who is listed as someone else's Oya can't be deleted until that
link is reassigned — this prevents orphaned sponsor references.

## Receipt fields (mirrors your "Recipt" sheet)

`receipt_no`, linked `member` (via search), plus a snapshot of
`full_name` / `shibicho` / `entrance_date` taken at the moment the receipt
is created (so old receipts stay accurate even if the member's details
change later), `renewal_date`, `status`.

## Not yet included

The "Info" sheet (Shibicho name → email, used for access control) isn't
wired in — you chose to keep simple username/password login instead. If you
want to switch to email-based access control later, this sheet's data would
become a `Shibicho` table checked against login email.

If you need more fields later, add columns to the relevant model in
`app.py` and update the form/list/print templates — straightforward since
the schema is easy to extend.

## Importing your 36,000 existing members

Once your member spreadsheet is ready, the fastest path is a one-off Python
script using `pandas` + `SQLAlchemy` to bulk-insert rows into the `members`
table — happy to build that script when you have the file ready.
