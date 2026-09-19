import csv
import hmac
import os
import random
import re
import secrets
import sqlite3
from enum import Enum
from pathlib import Path
import flask


BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "tweets.csv"
DATABASE = BASE_DIR / "labels.db"
HASH_KEY_FILE = BASE_DIR / ".email_hash_key"
EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+"
)

class Emotion(Enum):
    SADNESS = 0
    JOY = 1
    LOVE = 2
    ANGER = 3
    FEAR = 4
    SURPRISE = 5

app = flask.Flask(__name__)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", TEMPLATES_AUTO_RELOAD=True)


@app.context_processor
def template_assets():
    def asset_version(filename):
        return (BASE_DIR / filename).stat().st_mtime_ns
    return {"asset_version": asset_version}


def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    database_existed = DATABASE.exists()
    with get_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                participant_id TEXT NOT NULL,
                tweet_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        has_index = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'responses_participant_tweet'"
        ).fetchone()
        if has_index:
            return
        duplicate = connection.execute(
            "SELECT 1 FROM responses GROUP BY participant_id, tweet_id HAVING COUNT(*) > 1 LIMIT 1"
        ).fetchone()
        if duplicate:
            raise RuntimeError("Existing duplicate answers need review before enabling continuous labeling.")
        backup_path = Path(str(DATABASE) + ".before-continuous.bak")
        if database_existed and not backup_path.exists():
            with sqlite3.connect(backup_path) as backup:
                connection.backup(backup)
        connection.execute(
            "CREATE UNIQUE INDEX responses_participant_tweet ON responses (participant_id, tweet_id)"
        )


def load_hash_key():
    if not HASH_KEY_FILE.exists():
        with get_db() as connection:
            has_responses = connection.execute("SELECT 1 FROM responses LIMIT 1").fetchone()
        if has_responses:
            raise RuntimeError("Restore .email_hash_key before using the existing responses.")
        try:
            descriptor = os.open(HASH_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as key_file:
                key_file.write(secrets.token_bytes(32))
    key = HASH_KEY_FILE.read_bytes()
    if len(key) != 32:
        raise RuntimeError("Invalid .email_hash_key; restore the original 32-byte key.")
    return key


def normalize_email(email):
    email = email.strip()
    if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("Invalid email")
    local, domain = email.rsplit("@", 1)
    if len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local:
        raise ValueError("Invalid email")
    return f"{local}@{domain.lower()}"


def load_tweets():
    with DATA_FILE.open(newline="", encoding="utf-8") as file:
        return [
            {
                "id": row["id"],
                "text": row["tweet"],
                "ground_truth": Emotion(int(row["emotion"])).name.lower(),
            }
            for row in csv.DictReader(file, skipinitialspace=True)
        ]


def configure_app():
    init_db()
    key = load_hash_key()
    app.config["EMAIL_HASH_KEY"] = key
    app.secret_key = hmac.new(key, b"labeler-session-signing", "sha256").digest()


def participant_task(participant_id):
    tweets = load_tweets()
    with get_db() as connection:
        responses = connection.execute(
            "SELECT tweet_id, label FROM responses WHERE participant_id = ? ORDER BY id",
            (participant_id,),
        ).fetchall()
    by_id = {tweet["id"]: tweet for tweet in tweets}
    saved = [
        {"id": str(row["tweet_id"]), "text": by_id[str(row["tweet_id"])]["text"], "label": row["label"]}
        for row in responses if str(row["tweet_id"]) in by_id
    ]
    saved_ids = {tweet["id"] for tweet in saved}
    remaining = [
        {"id": tweet["id"], "text": tweet["text"], "label": None}
        for tweet in tweets if tweet["id"] not in saved_ids
    ]
    random.shuffle(remaining)
    return {"tweets": saved + remaining, "completedCount": len(saved)}


@app.get("/tokens.css")
def design_tokens():
    return flask.send_file(BASE_DIR / "tokens.css", mimetype="text/css")


@app.get("/")
def index():
    emotions = sorted(emotion.name.lower() for emotion in Emotion)
    participant_id = flask.session.get("participant_id")
    task = participant_task(participant_id) if participant_id else None
    return flask.render_template("index.html", task=task, emotions=emotions)


@app.post("/start")
def start():
    try:
        email = normalize_email(flask.request.form.get("email", ""))
    except ValueError:
        return flask.render_template(
            "error.html", message="Please enter a valid email address before submitting."
        ), 400

    key = app.config.get("EMAIL_HASH_KEY")
    if not key:
        return flask.render_template(
            "error.html", message="The task is temporarily unavailable. Please try again later."
        ), 503
    flask.session.clear()
    flask.session["participant_id"] = hmac.new(key, email.encode("utf-8"), "sha256").hexdigest()
    return flask.redirect(flask.url_for("index"))


@app.post("/leave")
def leave():
    flask.session.clear()
    return flask.redirect(flask.url_for("index"))


@app.post("/submit")
def submit():
    participant_id = flask.session.get("participant_id")
    if not participant_id:
        return flask.jsonify(error="Enter your email again, then retry this answer."), 401
    payload = flask.request.get_json(silent=True)
    if not isinstance(payload, dict):
        return flask.jsonify(error="A message and emotion are required."), 400
    tweet_id = payload.get("tweet_id")
    label = payload.get("label")
    valid_ids = {tweet["id"] for tweet in load_tweets()}
    if not isinstance(tweet_id, str) or tweet_id not in valid_ids or label not in (
        emotion.name.lower() for emotion in Emotion
    ):
        return flask.jsonify(error="A message or emotion was invalid."), 400
    with get_db() as connection:
        connection.execute(
            """
            INSERT INTO responses (participant_id, tweet_id, label) VALUES (?, ?, ?)
            ON CONFLICT(participant_id, tweet_id) DO UPDATE
            SET label = excluded.label, timestamp = CURRENT_TIMESTAMP
            WHERE responses.label != excluded.label
            """,
            (participant_id, int(tweet_id), label),
        )
    return flask.jsonify(saved=True)


@app.get("/results")
def results():
    tweets = {int(tweet["id"]): tweet for tweet in load_tweets()}
    with get_db() as connection:
        responses = connection.execute(
            """
            SELECT participant_id, tweet_id, label, timestamp
            FROM responses
            ORDER BY id DESC
            """
        ).fetchall()

    display_rows = []
    for response in responses:
        tweet = tweets.get(response["tweet_id"], {})
        display_rows.append(
            {
                "participant_id": response["participant_id"],
                "tweet_id": response["tweet_id"],
                "text": tweet.get("text", "Tweet not found"),
                "label": response["label"],
                "ground_truth": tweet.get("ground_truth", "unknown"),
                "timestamp": response["timestamp"],
            }
        )

    return flask.render_template("results.html", responses=display_rows)


if __name__ == "__main__":
    configure_app()
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1")
