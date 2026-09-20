# Emotion Labeling Task

A small Flask research interface using SQLite locally or Supabase PostgreSQL when deployed. Participants label short messages one at a time until they have labeled every tweet in the dataset. Each participant gets a separate queue; answers from other participants do not remove tweets from it.

The current CSV contains 101 examples from the [DAIR.AI Emotion dataset](https://huggingface.co/datasets/dair-ai/emotion), with columns `id`, `tweet`, and `emotion`. Numeric codes follow `Emotion` in `app.py`: 0 = sadness, 1 = joy, 2 = love, 3 = anger, 4 = fear, 5 = surprise. The interface displays names and stores labels as names. Ground truth is shown only in results.

## Run locally

Use Python 3.10 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>. Restart the server after Python code changes; debug mode is off by default. Templates reload when edited, and asset URLs change with the stylesheet/script versions so a page refresh loads matching files. JavaScript and cookies are required for labeling.

## Supabase and Vercel

The app uses PostgreSQL whenever `DATABASE_URL` is set. Without it, local runs use SQLite. On Vercel, both `DATABASE_URL` and `EMAIL_HASH_KEY` are required; the app refuses to fall back to temporary local storage. Configuration runs before Flask opens the first request's session, including when Vercel imports the app instead of running `python app.py`.

### Fill in your local .env

If `.env` does not exist, copy `.env.example` to `.env`. It is ignored by Git. Set these two variables:

```dotenv
DATABASE_URL='postgresql://postgres.grtffvszvltdfedmeloe:YOUR_URL_ENCODED_PASSWORD@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require'
EMAIL_HASH_KEY='YOUR_64_CHARACTER_HEX_KEY'
```

Replace `YOUR_URL_ENCODED_PASSWORD` with your **database password**, not a Supabase API key. Percent-encode reserved characters in the password (for example, `@` becomes `%40`, `#` becomes `%23`, and `%` becomes `%25`). The database name is `postgres`, without a trailing period. Copy the connection details from **Connect → Transaction pooler** in your Supabase project if they change. Transaction mode is intended for serverless applications; the driver disables prepared statements and closes each connection after its transaction. [Supabase connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres)

Use the same hashing key locally and on Vercel to preserve participant identities. The private `.env` prepared during this change already contains the existing key. To export it again, run this **in your own terminal** and copy the output into `EMAIL_HASH_KEY`:

```bash
python3 -c "from pathlib import Path; print(Path('.email_hash_key').read_bytes().hex())"
```

For a brand-new installation with no existing key or labels, generate it once using `python3 -c "import secrets; print(secrets.token_hex(32))"`. Keep the value stable across deployments. Do not commit `.env` or share its contents.

The app does not automatically load `.env`. To run locally against Supabase in macOS/Linux, load your own file in the shell first:

```bash
source .venv/bin/activate
pip install -r requirements.txt
set -a
source .env
set +a
python app.py
```

To return to local SQLite, use a fresh terminal without those variables, or run `unset DATABASE_URL EMAIL_HASH_KEY` before starting the app.

### Configure Vercel

1. Open your Vercel project → **Settings → Environment Variables** (or **Environment Variables** in the project sidebar).
2. Add `DATABASE_URL` with the complete connection string, including the encoded password and `?sslmode=require`. Paste the value without surrounding quotes.
3. Add `EMAIL_HASH_KEY` with the same 64-character value from your private `.env`, without quotes.
4. Enable **Production**. If you also enable **Preview**, preview deployments will read and write the same labels; use a separate database for isolated preview data.
5. Deploy the updated code, including `requirements.txt`, `schema.sql`, `vercel.json`, and `scripts/build_assets.py`. Environment changes require a **new deployment**; redeploy after saving them. [Vercel environment variables](https://vercel.com/docs/environment-variables/managing-environment-variables)

No Supabase API key, browser database credentials, or Supabase Auth setup is needed. The first request creates `labeler.responses` automatically using `schema.sql`. In Supabase's Table Editor, choose the **labeler** schema to view it. The database role must be allowed to create this schema and table; the supplied `postgres` connection has those privileges. This schema is not added to Supabase's public Data API. The app's existing `/results` page remains accessible to site visitors.

The Vercel build copies the existing CSS/JS and tokens into `public/`, which Vercel serves from its CDN. The source files remain in `static/` and `tokens.css`; do not edit generated files in `public/`. Asset links on Vercel use the deployment's commit ID instead of reading file timestamps from the function's filesystem. [Vercel Flask assets](https://vercel.com/docs/frameworks/backend/flask#serving-static-assets)

After deployment, verify: open the homepage, enter an email, save one label, refresh to resume, and open Results in its separate tab. Check Vercel's runtime logs if a request fails.

Existing local SQLite labels stay in `labels.db`; they are **not automatically uploaded to Supabase**. A new Supabase table starts empty. Keep both the local database and original hashing key if you want to migrate those earlier labels. Reverting code or changing `DATABASE_URL` does not copy labels between databases; preserve/export the hosted responses before switching storage.

## Participant flow

1. Read the first-visit tutorial, then enter an email. Only basic format is checked; there is no verification email or ownership check.
2. Choose an emotion and select **Save & next**. Each answer is saved before the next message appears. An unsuccessful save keeps the selection and offers a retry.
3. Use **Back** to review or change an answer. Saving a correction replaces that participant's previous label for the tweet. Repeated saves do not add duplicate rows.
4. Stop whenever you like. Refreshing resumes after your saved answers. Re-entering the same email in a later visit restores the same progress. Unsaved selections do not survive refreshing.
5. After every tweet is labeled, a completion message appears. **Review answers** allows corrections.
6. **Results** opens `/results` in a separate browser tab. Select **Refresh results** to see later saves. The table shows participant hash, tweet ID, text, chosen label, ground truth, and timestamp.

Unanswered tweets are shuffled when the task page loads. Saved answers appear first for review. New tweets added to the CSV become available on the next page load; keep tweet IDs stable. **Change email** ends the current browser session without deleting any saved answers.

The tutorial can always be reopened with **Instructions**. Completion is remembered using local storage. When storage is blocked, instructions appear on each visit and labeling still works. This version shows the updated tutorial once even if the earlier five-message tutorial was completed.

## Privacy and storage

For local SQLite runs, the app automatically creates `labels.db` and a private `.email_hash_key` file. Hosted runs use PostgreSQL and the environment key instead, with no local database or key writes. The server uses HMAC-SHA-256 and stores only the full 64-character hash in the existing `participant_id` column. It does not save or log the email. A signed, HTTP-only session cookie remembers the hash, not the email. The session-signing secret is derived separately from the persistent key; Vercel cookies also require HTTPS.

Normalization removes surrounding whitespace and lowercases the email domain. The local part before `@` retains its case, dots, and plus tags; use the same spelling each time. Participant hashes remain visible on `/results` and allow contributions to be linked.

Keep `.email_hash_key` private and outside source control. Back it up securely, separately from the database, and reuse it across restarts and deployments. The app refuses to generate a replacement when responses exist. Losing or changing the key breaks participant matching. Raw emails cannot be reconstructed from the database to recover those identities.

## Existing databases and rollback

On first startup with an older database, the app creates `labels.db.before-continuous.bak` before adding a unique index on `(participant_id, tweet_id)`. Existing responses are preserved and count toward participants' progress. Subsequent startups reuse the index and leave the backup untouched.

If the old database contains duplicate answers for a participant/tweet pair, startup stops without discarding rows. Those conflicting answers need an explicit resolution before migration; the app does not choose one silently.

To roll back: stop the server, preserve the current database separately, restore `labels.db.before-continuous.bak` as `labels.db`, restore the earlier application code, and keep the original `.email_hash_key`. Labels collected after the backup will remain only in the preserved current database.

## Verification

```bash
python3 -m unittest -v
node --check static/task.js
python3 scripts/check_browser.py
python3 scripts/check_postgres.py
python3 scripts/build_assets.py
```

The browser checks require an installed Chrome/Chromium and use disposable CSV fixtures, SQLite storage, and a fresh browser profile. Set `CHROME_BINARY` if Chrome is not in its default macOS location or available as `google-chrome`/`chromium` on PATH. Optional screenshots also require Node with built-in WebSocket support:

```bash
python3 scripts/check_browser.py --screenshots /tmp/labeler-ui-review
```

Tests cover independent participant queues, immediate saves, corrections, concurrent retries, resuming, exhaustion, invalid input, key persistence, and migration. Browser checks exercise the tutorial, save failures, lost confirmations, retries, the full dataset, and layouts at 320, 375, 414, and 768 pixels. Screenshot mode also checks that Results opens another tab.

`check_postgres.py` requires locally installed PostgreSQL binaries (`initdb`, `pg_ctl`, and `createdb`) on PATH. It creates an isolated PostgreSQL server using temporary storage and a Unix socket, runs `test_postgres.py`, then stops the server and cleans up. It does not use your Supabase credentials. Those integration tests are skipped during ordinary unit-test discovery; run the script to exercise the real PostgreSQL path. Browser checks also ignore hosted database environment settings and always use disposable SQLite storage.

## Files

- `app.py`: Flask routes, participant queues, hashing, validation, and SQLite/PostgreSQL writes.
- `schema.sql`: hosted response schema, initialized automatically on startup.
- `.env.example`: connection and hashing-key placeholders; `.env` is private local configuration.
- `vercel.json`, `scripts/build_assets.py`: Vercel's asset build.
- `tweets.csv`: the labeled dataset.
- `templates/`: tutorial, start form, labeling, results, and error pages.
- `static/task.js`: sequential labeling and tutorial behavior.
- `static/style.css`, `tokens.css`, `design.md`: shared styles and the simple research-form design.
- `test_app.py`, `test_postgres.py`, `scripts/`: regression, database integration, and browser checks.
- `labels.db`, `.email_hash_key`, `labels.db.*`, `.env`: private local state excluded from Git; also exclude these from shared ZIP files.

## Data and ethics note

The dataset card describes educational and research use. Emotion labels simplify context-dependent human expression, so neither participant labels nor ground truth should be interpreted as an objective measurement of someone's internal emotional state.

Dataset citation: Saravia et al. (2018), “CARER: Contextualized Affect Representations for Emotion Recognition,” EMNLP 2018.
