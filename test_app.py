import tempfile
import unittest
import hashlib
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import app as labeling


class PageElements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        self.elements.append((tag, dict(attributes)))


class NumericCsvTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        data_file = Path(directory.name) / "tweets.csv"
        data_file.write_text(
            'id, tweet, emotion\n'
            '0, "A sad message, with a comma", 0\n'
            '1, A joyful message, 1\n'
            '2, A loving message, 2\n'
            '3, An angry message, 3\n'
            '4, A fearful message, 4\n'
            '5, A surprised message, 5\n',
            encoding="utf-8",
        )
        for name, value in (
            ("DATA_FILE", data_file),
            ("DATABASE", Path(directory.name) / "labels.db"),
            ("HASH_KEY_FILE", Path(directory.name) / ".email_hash_key"),
        ):
            patcher = patch.object(labeling, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        labeling.init_db()
        config = patch.dict(labeling.app.config, EMAIL_HASH_KEY=b"test-key" * 4, TESTING=True)
        config.start()
        self.addCleanup(config.stop)
        self.client = labeling.app.test_client()

    def test_numeric_csv_maps_text_and_all_emotion_codes(self):
        tweets = labeling.load_tweets()
        self.assertEqual(tweets[0]["id"], "0")
        self.assertEqual(tweets[0]["text"], "A sad message, with a comma")
        self.assertEqual(
            [tweet["ground_truth"] for tweet in tweets],
            ["sadness", "joy", "love", "anger", "fear", "surprise"],
        )

    def test_get_displays_five_messages_and_named_emotion_choices(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertEqual(html.count('name="tweet_id"'), 5)
        self.assertEqual(html.count('<p class="tweet-text">“'), 5)
        self.assertNotIn('<p class="tweet-text">“”</p>', html)
        for label in ("sadness", "joy", "love", "anger", "fear", "surprise"):
            self.assertEqual(html.count(f'value="{label}"'), 5)

    def test_task_starts_with_one_tweet_email_and_tutorial(self):
        html = self.client.get("/").get_data(as_text=True)
        elements = PageElements(html).elements
        cards = [attrs for tag, attrs in elements if tag == "fieldset"]
        self.assertEqual(len(cards), 5)
        self.assertEqual(sum("hidden" not in card for card in cards), 1)
        emails = [attrs for tag, attrs in elements if tag == "input" and attrs.get("name") == "email"]
        self.assertEqual(len(emails), 1)
        self.assertEqual(emails[0]["type"], "email")
        self.assertIn("required", emails[0])
        self.assertTrue(any(tag == "dialog" for tag, _ in elements))
        self.assertNotIn('name="participant_id"', html)
        self.assertIn("View instructions", html)

    def test_submission_and_results_use_names_with_numeric_csv(self):
        labels = ["sadness", "joy", "love", "anger", "fear"]
        form = {"email": "participant@example.com", "tweet_id": list("01234")}
        form.update({f"label_{index}": label for index, label in enumerate(labels)})
        response = self.client.post("/submit", data=form)
        self.assertEqual(response.status_code, 200)
        with labeling.get_db() as connection:
            rows = connection.execute("SELECT label FROM responses ORDER BY id").fetchall()
        self.assertEqual([row["label"] for row in rows], labels)
        response = self.client.get("/results")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("A sad message, with a comma", html)
        for label in labels:
            self.assertIn(f"<td>{label}</td>", html)

    def test_invalid_emotion_is_rejected_without_saving_responses(self):
        form = {"email": "participant@example.com", "tweet_id": list("01234")}
        form.update({f"label_{index}": "joy" for index in range(5)})
        form["label_4"] = "invalid"
        self.assertEqual(self.client.post("/submit", data=form).status_code, 400)
        with labeling.get_db() as connection:
            count = connection.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
        self.assertEqual(count, 0)

    def submit_email(self, email):
        form = {"email": email, "tweet_id": list("01234")}
        form.update({f"label_{index}": "joy" for index in range(5)})
        return self.client.post("/submit", data=form)

    def test_only_full_keyed_hash_is_saved_and_displayed(self):
        email = "participant@example.com"
        response = self.submit_email(email)
        self.assertEqual(response.status_code, 200)
        with labeling.get_db() as connection:
            rows = connection.execute("SELECT * FROM responses").fetchall()
        identifiers = {row["participant_id"] for row in rows}
        self.assertEqual(len(rows), 5)
        self.assertEqual(len(identifiers), 1)
        identifier = identifiers.pop()
        self.assertRegex(identifier, r"\A[0-9a-f]{64}\Z")
        self.assertNotEqual(identifier, hashlib.sha256(email.encode()).hexdigest())
        self.assertNotIn(email, str([tuple(row) for row in rows]))
        for page in (response, self.client.get("/results")):
            self.assertIn(identifier, page.get_data(as_text=True))
            self.assertNotIn(email, page.get_data(as_text=True))
            self.assertNotIn(email, str(page.headers))

    def test_hash_is_stable_and_normalizes_whitespace_and_domain_case(self):
        self.assertEqual(self.submit_email(" participant@EXAMPLE.COM ").status_code, 200)
        self.assertEqual(self.submit_email("participant@example.com").status_code, 200)
        self.assertEqual(self.submit_email("someone-else@example.com").status_code, 200)
        with labeling.get_db() as connection:
            identifiers = [row[0] for row in connection.execute(
                "SELECT participant_id FROM responses ORDER BY id"
            )]
        self.assertEqual(identifiers[0], identifiers[5])
        self.assertNotEqual(identifiers[0], identifiers[10])

    def test_different_secret_produces_different_identifier(self):
        self.submit_email("participant@example.com")
        with patch.dict(labeling.app.config, EMAIL_HASH_KEY=b"another-test-key" * 2):
            self.submit_email("participant@example.com")
        with labeling.get_db() as connection:
            count = connection.execute(
                "SELECT COUNT(DISTINCT participant_id) FROM responses"
            ).fetchone()[0]
        self.assertEqual(count, 2)

    def test_invalid_email_is_rejected_without_saving_responses(self):
        for email in ("", " ", "not-an-email", "a@@example.com", "a b@example.com",
                      "a@-example.com", "a@example..com", "a\n@example.com", "a" * 65 + "@example.com"):
            with self.subTest(email=email):
                self.assertEqual(self.submit_email(email).status_code, 400)
        with labeling.get_db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM responses").fetchone()[0], 0)

    def test_missing_hash_key_rejects_submission_without_saving(self):
        with patch.dict(labeling.app.config, EMAIL_HASH_KEY=None):
            self.assertEqual(self.submit_email("participant@example.com").status_code, 503)
        with labeling.get_db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM responses").fetchone()[0], 0)

    def test_persistent_key_is_private_and_reused(self):
        first = labeling.load_hash_key()
        self.assertEqual(len(first), 32)
        self.assertEqual(labeling.load_hash_key(), first)
        self.assertEqual(labeling.HASH_KEY_FILE.stat().st_mode & 0o777, 0o600)

    def test_missing_key_with_existing_responses_does_not_replace_identity(self):
        self.submit_email("participant@example.com")
        with self.assertRaises(RuntimeError):
            labeling.load_hash_key()
        self.assertFalse(labeling.HASH_KEY_FILE.exists())

    def test_invalid_key_file_is_not_overwritten(self):
        labeling.HASH_KEY_FILE.write_bytes(b"invalid")
        with self.assertRaises(RuntimeError):
            labeling.load_hash_key()
        self.assertEqual(labeling.HASH_KEY_FILE.read_bytes(), b"invalid")

    def test_incomplete_duplicate_and_unknown_tweets_are_not_saved(self):
        for ids in (list("0123"), list("01233"), list("01239")):
            with self.subTest(ids=ids):
                form = {"email": "participant@example.com", "tweet_id": ids}
                form.update({f"label_{tweet_id}": "joy" for tweet_id in ids})
                self.assertEqual(self.client.post("/submit", data=form).status_code, 400)
        form = {"email": "participant@example.com", "tweet_id": list("01234")}
        form.update({f"label_{index}": "joy" for index in range(4)})
        self.assertEqual(self.client.post("/submit", data=form).status_code, 400)
        with labeling.get_db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM responses").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
