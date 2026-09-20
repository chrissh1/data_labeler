"""Integration tests run by scripts/check_postgres.py against a disposable server."""

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import psycopg
import psycopg.conninfo

import app as labeling
from batch_contract import BatchContract


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Run scripts/check_postgres.py')
class PostgresTests(BatchContract, unittest.TestCase):
    def setUp(self):
        url = os.environ['TEST_DATABASE_URL']
        options = psycopg.conninfo.conninfo_to_dict(url)
        if options.get('dbname') != 'labeler_test' or not options.get('host', '').startswith('/'):
            self.fail('Integration tests require a disposable labeler_test database on a Unix socket.')
        environment = patch.dict(os.environ, DATABASE_URL=url, EMAIL_HASH_KEY='ab' * 32, VERCEL='1')
        environment.start()
        self.addCleanup(environment.stop)
        config = patch.dict(labeling.app.config, APP_CONFIGURED=False, TESTING=True,
                            EMAIL_HASH_KEY=None, SECRET_KEY=None)
        config.start()
        self.addCleanup(config.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        data_file = root / 'tweets.csv'
        data_file.write_text('id,tweet,emotion\n' + ''.join(f'{i},Example tweet {i},{i}\n' for i in range(6)))
        for name, value in [('DATA_FILE', data_file), ('DATABASE', root / 'labels.db'),
                            ('HASH_KEY_FILE', root / '.email_hash_key')]:
            patcher = patch.object(labeling, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = labeling.app.test_client()
        self.assertEqual(self.client.get('/').status_code, 200)
        with labeling.get_db() as connection:
            connection.execute('TRUNCATE labeler.responses RESTART IDENTITY')

    def test_first_request_initializes_hosted_app_without_local_state(self):
        self.assertEqual(self.start().status_code, 302)
        self.assertEqual(self.save().status_code, 200)
        self.assertFalse(labeling.DATABASE.exists())
        self.assertFalse(labeling.HASH_KEY_FILE.exists())
        self.assertTrue(labeling.app.config['SESSION_COOKIE_SECURE'])
        with labeling.get_db() as connection:
            self.assertIsNone(connection.prepare_threshold)
        self.assertTrue(connection.closed)

    def test_concurrent_schema_initialization_preserves_responses(self):
        self.start()
        self.save()
        original = self.rows()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(labeling.init_db) for _ in range(2)]
            for future in futures:
                future.result()
        self.assertEqual(self.rows(), original)

    def test_failed_transaction_rolls_back_and_releases_connection(self):
        with self.assertRaises(psycopg.errors.NotNullViolation):
            with labeling.get_db() as connection:
                connection.execute("INSERT INTO labeler.responses (participant_id, tweet_id, label) VALUES (%s, 0, 'joy')", ('cd' * 32,))
                connection.execute('INSERT INTO labeler.responses (participant_id, tweet_id, label) VALUES (NULL, 1, NULL)')
        self.assertTrue(connection.closed)
        self.assertEqual(self.rows(), [])


if __name__ == '__main__':
    unittest.main()
