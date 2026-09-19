import csv
import hmac
import os
import random
import re
import secrets
import sqlite3
from enum import Enum
from pathlib import Path

from flask import Flask, render_template, request


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


app = Flask(__name__)


def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
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


@app.get("/")
def index():
    # The tweets stay in a simple CSV; each page load gets a random sample.
    tweets = random.sample(load_tweets(), 5)
    emotions = sorted(emotion.name.lower() for emotion in Emotion)
    return render_template("index.html", tweets=tweets, emotions=emotions, error=None)


@app.post("/submit")
def submit():
    try:
        email = normalize_email(request.form.get("email", ""))
    except ValueError:
        return render_template(
            "error.html", message="Please enter a valid email address before submitting."
        ), 400

    tweet_ids = request.form.getlist("tweet_id")

    key = app.config.get("EMAIL_HASH_KEY")
    if not key:
        return render_template(
            "error.html", message="The task is temporarily unavailable. Please try again later."
        ), 503
    participant_id = hmac.new(key, email.encode("utf-8"), "sha256").hexdigest()

    if len(tweet_ids) != 5 or len(set(tweet_ids)) != 5:
        return render_template(
            "error.html", message="Exactly five distinct tweets must be labeled."
        ), 400

    valid_ids = {tweet["id"] for tweet in load_tweets()}
    rows = []
    for tweet_id in tweet_ids:
        label = request.form.get(f"label_{tweet_id}", "")
        if tweet_id not in valid_ids or label not in (
            emotion.name.lower() for emotion in Emotion
        ):
            return render_template(
                "error.html", message="A tweet or emotion label was invalid."
            ), 400
        rows.append((participant_id, int(tweet_id), label))

    with get_db() as connection:
        connection.executemany(
            "INSERT INTO responses (participant_id, tweet_id, label) VALUES (?, ?, ?)",
            rows,
        )

    return render_template("thanks.html", participant_id=participant_id)


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

    return render_template("results.html", responses=display_rows)


if __name__ == "__main__":
    init_db()
    app.config["EMAIL_HASH_KEY"] = load_hash_key()
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1")
