# Emotion Labeling Task

A small Flask + SQLite labeling interface. Each page load samples five different messages from a 101-item subset of the [DAIR.AI Emotion dataset](https://huggingface.co/datasets/dair-ai/emotion). The CSV uses the columns `id`, `tweet`, and `emotion`. Numeric emotion codes are defined by `Emotion` in `app.py`: 0 = sadness, 1 = joy, 2 = love, 3 = anger, 4 = fear, and 5 = surprise. The interface displays emotion names and stores participant labels as names.

## Run it

Python 3.9 or newer is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>.

The app creates `labels.db` and a private `.email_hash_key` file automatically the first time it starts. You do not need to install or configure a separate database server. Restart the server after code changes; debug mode is off by default.

## Participant flow and privacy

- The first visit opens a tutorial explaining the research motivation and labeling instructions. Completion is remembered in that browser using local storage. **View instructions** reopens it. If storage is blocked, the tutorial appears on each visit and labeling still works.
- Participants enter an email address. Only its format is checked; there is no verification email or ownership check.
- Messages appear one at a time. **Next** requires an answer; **Back** preserves previous selections. **Submit labels** saves all five together. Refreshing starts a new set and discards unfinished answers. JavaScript is required.
- The server computes HMAC-SHA-256 and stores the full 64-character hexadecimal hash in the existing `participant_id` column. Confirmation and results pages display that hash. The app does not save or log the submitted email, and it does not store it in cookies or browser storage.
- Email normalization removes surrounding whitespace and lowercases the domain. The local part before `@` retains its case, dots, and plus tags; use the same spelling each time to get the same participant identifier.
- Keep `.email_hash_key` private, outside source control, and back it up securely separately from the database. Reuse it after restarts or deployments. Losing or changing it breaks participant matching. The app refuses to generate a replacement key when responses already exist. To recover, restore the original key; it cannot be reconstructed from the database.
- Results remain accessible at `/results`. The hashes allow contributions to be linked but do not establish who submitted them.

No database schema migration is needed. The existing local database was empty when this flow was introduced; older datasets containing manually assigned participant IDs are not automatically converted into email hashes.

## Test and take the required screenshot

Run the automated regression tests with `python3 -m unittest -v`.

With Chrome installed, run `python3 scripts/check_browser.py` for real browser checks of the tutorial, navigation, validation, submission, results, and mobile layout. The script uses temporary fixtures, a disposable SQLite database, and a fresh Chrome profile. Set `CHROME_BINARY` if Chrome is not in its default macOS location or available as `google-chrome`/`chromium` on PATH.

1. Open the task page, complete the tutorial, and enter an email such as `test-participant@example.com`.
2. Label each message, selecting **Next** to continue, then **Submit labels** on the fifth.
3. Select **View collected data**, or open <http://127.0.0.1:5000/results>.
4. The table will show the participant hash, tweet ID, chosen label, ground truth, and time for all five rows. Take your screenshot there.

## Files

- `app.py`: Flask routes, CSV loading, validation, and SQLite writes.
- `tweets.csv`: 101 labeled examples from the dataset; ground truth is never shown on the labeling page.
- `test_app.py`: CSV, route, submission, and validation regression tests using temporary data and storage.
- `scripts/check_browser.py` and `scripts/browser_checks.html`: browser integration checks with disposable fixtures.
- `templates/`: labeling, confirmation, error, and results pages.
- `static/style.css`: lightweight styling.
- `static/task.js`: sequential navigation and first-visit tutorial behavior.
- `labels.db`: generated locally after the app starts; intentionally excluded from the ZIP and Git.
- `.email_hash_key`: automatically generated private HMAC key; excluded from Git and must also be excluded from any shared ZIP.

## Data and ethics note

The dataset card says the dataset is for educational and research use. Emotion labels simplify context-dependent human expression into six classes, so neither participant labels nor ground truth should be interpreted as an objective measurement of a person's internal emotional state.

Dataset citation: Saravia et al. (2018), “CARER: Contextualized Affect Representations for Emotion Recognition,” EMNLP 2018.
