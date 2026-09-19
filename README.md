# Emotion Labeling Task

A small Flask + SQLite research interface. Participants label short messages one at a time until they have labeled every tweet in the dataset. Each participant gets a separate queue; answers from other participants do not remove tweets from it.

The current CSV contains 101 examples from the [DAIR.AI Emotion dataset](https://huggingface.co/datasets/dair-ai/emotion), with columns `id`, `tweet`, and `emotion`. Numeric codes follow `Emotion` in `app.py`: 0 = sadness, 1 = joy, 2 = love, 3 = anger, 4 = fear, 5 = surprise. The interface displays names and stores labels as names. Ground truth is shown only in results.

## Run locally

Use Python 3.9 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>. Restart the server after Python code changes; debug mode is off by default. Templates reload when edited, and asset URLs change with the stylesheet/script versions so a page refresh loads matching files. JavaScript and cookies are required for labeling.

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

The app automatically creates `labels.db` and a private `.email_hash_key` file. The server uses HMAC-SHA-256 and stores only the full 64-character hash in the existing `participant_id` column. It does not save or log the email. A signed, HTTP-only session cookie remembers the hash, not the email. The session-signing secret is derived separately from the persistent key.

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
```

The browser checks require an installed Chrome/Chromium and use disposable CSV fixtures, SQLite storage, and a fresh browser profile. Set `CHROME_BINARY` if Chrome is not in its default macOS location or available as `google-chrome`/`chromium` on PATH. Optional screenshots also require Node with built-in WebSocket support:

```bash
python3 scripts/check_browser.py --screenshots /tmp/labeler-ui-review
```

Tests cover independent participant queues, immediate saves, corrections, concurrent retries, resuming, exhaustion, invalid input, key persistence, and migration. Browser checks exercise the tutorial, save failures, lost confirmations, retries, the full dataset, and layouts at 320, 375, 414, and 768 pixels. Screenshot mode also checks that Results opens another tab.

## Files

- `app.py`: Flask routes, participant queues, hashing, validation, and SQLite writes.
- `tweets.csv`: the labeled dataset.
- `templates/`: tutorial, start form, labeling, results, and error pages.
- `static/task.js`: sequential labeling and tutorial behavior.
- `static/style.css`, `tokens.css`, `design.md`: shared styles and the simple research-form design.
- `test_app.py`, `scripts/`: regression and browser checks.
- `labels.db`, `.email_hash_key`, `labels.db.*`: private local state excluded from Git; also exclude these from shared ZIP files.

## Data and ethics note

The dataset card describes educational and research use. Emotion labels simplify context-dependent human expression, so neither participant labels nor ground truth should be interpreted as an objective measurement of someone's internal emotional state.

Dataset citation: Saravia et al. (2018), “CARER: Contextualized Affect Representations for Emotion Recognition,” EMNLP 2018.
