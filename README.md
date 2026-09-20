# Emotion Labeling Task

## Run locally

Use Python 3.10 or newer. From the project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. Stop the server with Ctrl+C.

For future runs:

```bash
source .venv/bin/activate
python app.py
```

By default, the app uses a local SQLite database created automatically. No `.env` file is needed.

To use Supabase locally instead, load your configured `.env` before starting the app:

```bash
set -a
source .env
set +a
python app.py
```

The `.env` file must contain `DATABASE_URL` and `EMAIL_HASH_KEY`; it is not loaded automatically. To switch back to SQLite, run `unset DATABASE_URL EMAIL_HASH_KEY` before starting the app.
