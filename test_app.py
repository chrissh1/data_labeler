import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import flask
from jinja2 import DictLoader

import app as labeling
from scripts.build_assets import build_assets
from batch_contract import BatchContract


class LabelingTests(BatchContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        data_file = self.directory / 'tweets.csv'
        data_file.write_text(
            'id, tweet, emotion\n'
            '0, "A sad message, with a comma", 0\n'
            '1, A joyful message, 1\n2, A loving message, 2\n'
            '3, An angry message, 3\n4, A fearful message, 4\n'
            '5, A surprised message, 5\n', encoding='utf-8')
        for name, value in (
            ('DATA_FILE', data_file),
            ('DATABASE', self.directory / 'labels.db'),
            ('HASH_KEY_FILE', self.directory / '.email_hash_key'),
        ):
            patcher = patch.object(labeling, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        config = patch.dict(labeling.app.config, EMAIL_HASH_KEY=b'test-key' * 4,
                            SECRET_KEY='test-session-key', TESTING=True,
                            DATABASE_URL=None, APP_CONFIGURED=True)
        config.start()
        self.addCleanup(config.stop)
        labeling.init_db()
        self.client = labeling.app.test_client()
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_imported_app_initializes_on_first_request(self):
        with patch.dict(labeling.app.config, APP_CONFIGURED=False, EMAIL_HASH_KEY=None,
                        SECRET_KEY=None):
            response = self.start()
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.save().status_code, 200)
            self.assertTrue(labeling.app.config['APP_CONFIGURED'])

    def test_failed_initialization_can_retry_on_the_next_request(self):
        with patch.dict(labeling.app.config, APP_CONFIGURED=False), \
                patch.object(labeling, 'init_db', side_effect=[RuntimeError('Database unavailable'), None]):
            with self.assertRaisesRegex(RuntimeError, 'Database unavailable'):
                self.client.get('/')
            self.assertFalse(labeling.app.config['APP_CONFIGURED'])
            self.assertEqual(self.start().status_code, 302)
            self.assertTrue(labeling.app.config['APP_CONFIGURED'])

    def test_environment_hash_key_is_used_without_creating_a_file(self):
        with patch.dict(os.environ, EMAIL_HASH_KEY='ab' * 32):
            self.assertEqual(labeling.load_hash_key(), bytes.fromhex('ab' * 32))
        self.assertFalse(labeling.HASH_KEY_FILE.exists())

    def test_invalid_environment_key_does_not_fall_back_to_a_generated_key(self):
        for key in ('', 'not-hex', 'ab' * 31):
            with self.subTest(key=key), patch.dict(os.environ, EMAIL_HASH_KEY=key):
                with self.assertRaisesRegex(RuntimeError, 'EMAIL_HASH_KEY'):
                    labeling.load_hash_key()
        self.assertFalse(labeling.HASH_KEY_FILE.exists())

    def test_vercel_refuses_sqlite_fallback(self):
        with patch.dict(os.environ, VERCEL='1'):
            with self.assertRaisesRegex(RuntimeError, 'DATABASE_URL'):
                labeling.configure_app()

    def test_remote_database_requires_a_persistent_environment_key(self):
        with patch.dict(os.environ, DATABASE_URL='postgresql://localhost/labeler_test'):
            with self.assertRaisesRegex(RuntimeError, 'EMAIL_HASH_KEY'):
                labeling.configure_app()

    def test_vercel_page_does_not_require_local_static_files(self):
        with patch.dict(os.environ, VERCEL='1', VERCEL_GIT_COMMIT_SHA='test-deployment'), \
                patch.object(labeling, 'BASE_DIR', self.directory):
            html = self.client.get('/').get_data(as_text=True)
        self.assertIn('/static/style.css?v=test-deployment', html)
        self.assertIn('/static/task.js?v=test-deployment', html)

    def test_vercel_build_copies_assets_without_private_files(self):
        static = self.directory / 'static'
        static.mkdir()
        (static / 'style.css').write_text('body { color: navy; }')
        (static / 'task.js').write_text('"use strict";')
        (self.directory / 'tokens.css').write_text(':root {}')
        (self.directory / '.env').write_text('PRIVATE=example')
        build_assets(self.directory)
        build_assets(self.directory)
        public = self.directory / 'public'
        self.assertEqual({p.relative_to(public).as_posix() for p in public.rglob('*') if p.is_file()},
                         {'static/style.css', 'static/task.js', 'tokens.css'})
        for relative in ('static/style.css', 'static/task.js', 'tokens.css'):
            self.assertEqual((public / relative).read_bytes(), (self.directory / relative).read_bytes())

    def test_numeric_csv_decodes_all_emotions_and_quoted_text(self):
        tweets = labeling.load_tweets()
        self.assertEqual(tweets[0]['text'], 'A sad message, with a comma')
        self.assertEqual([tweet['ground_truth'] for tweet in tweets],
                         ['sadness', 'joy', 'love', 'anger', 'fear', 'surprise'])

    def test_template_edits_are_rendered_without_stale_cached_markup(self):
        loader = DictLoader({'reload-probe.html': 'Before edit'})
        environment = labeling.app.jinja_env
        with patch.object(environment, 'loader', loader), labeling.app.app_context():
            environment.cache.clear()
            self.addCleanup(environment.cache.clear)
            self.assertEqual(flask.render_template('reload-probe.html'), 'Before edit')
            loader.mapping['reload-probe.html'] = 'After edit'
            self.assertEqual(flask.render_template('reload-probe.html'), 'After edit')

    def test_missing_hash_key_blocks_start(self):
        with patch.dict(labeling.app.config, EMAIL_HASH_KEY=None):
            self.assertEqual(self.start().status_code, 503)

    def test_key_is_private_persistent_and_not_replaced_when_data_exists(self):
        key = labeling.load_hash_key()
        self.assertEqual(len(key), 32)
        self.assertEqual(labeling.load_hash_key(), key)
        self.assertEqual(labeling.HASH_KEY_FILE.stat().st_mode & 0o777, 0o600)
        self.start()
        self.save()
        labeling.HASH_KEY_FILE.unlink()
        with self.assertRaises(RuntimeError):
            labeling.load_hash_key()

    def test_invalid_key_is_not_overwritten(self):
        labeling.HASH_KEY_FILE.write_bytes(b'invalid')
        with self.assertRaises(RuntimeError):
            labeling.load_hash_key()
        self.assertEqual(labeling.HASH_KEY_FILE.read_bytes(), b'invalid')

    def test_existing_database_is_backed_up_before_unique_index(self):
        with labeling.get_db() as connection:
            connection.execute('DROP INDEX IF EXISTS responses_participant_tweet')
            connection.execute("INSERT INTO responses (participant_id, tweet_id, label) VALUES ('existing-hash', 0, 'joy')")
        labeling.init_db()
        backup = Path(str(labeling.DATABASE) + '.before-continuous.bak')
        self.assertTrue(backup.exists())
        with sqlite3.connect(backup) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM responses').fetchone()[0], 1)
        self.assertEqual(len(self.rows()), 1)
        labeling.init_db()
        self.assertEqual(len(self.rows()), 1)

    def test_legacy_duplicate_answers_are_preserved_and_migration_stops(self):
        with labeling.get_db() as connection:
            connection.execute('DROP INDEX IF EXISTS responses_participant_tweet')
            connection.executemany('INSERT INTO responses (participant_id, tweet_id, label) VALUES (?, ?, ?)',
                                   [('legacy-hash', 0, 'joy'), ('legacy-hash', 0, 'love')])
        with self.assertRaisesRegex(RuntimeError, 'duplicate'):
            labeling.init_db()
        self.assertEqual(len(self.rows()), 2)


if __name__ == '__main__':
    unittest.main()
