"""Integration tests run by scripts/check_postgres.py against a disposable server."""

import json
import os
import re
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import psycopg
import psycopg.conninfo

import app as labeling


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Run scripts/check_postgres.py')
class PostgresTests(unittest.TestCase):
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
        data_file.write_text('id,tweet,emotion\n0,A sad message,0\n1,A joyful message,1\n')
        for name, value in [('DATA_FILE', data_file), ('DATABASE', root / 'labels.db'),
                            ('HASH_KEY_FILE', root / '.email_hash_key')]:
            patcher = patch.object(labeling, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = labeling.app.test_client()
        self.assertEqual(self.client.get('/').status_code, 200)
        with labeling.get_db() as connection:
            connection.execute('TRUNCATE labeler.responses RESTART IDENTITY')

    def start(self, email='participant@example.com', client=None):
        return (client or self.client).post('/start', data={'email': email})

    def save(self, tweet_id='0', label='joy', client=None):
        return (client or self.client).post('/submit', json={'tweet_id': tweet_id, 'label': label})

    def rows(self):
        with labeling.get_db() as connection:
            return connection.execute('SELECT * FROM labeler.responses ORDER BY id').fetchall()

    def task(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        return json.loads(re.search(r'<script id="task-data" type="application/json">(.*?)</script>',
                                   response.get_data(as_text=True), re.DOTALL)[1])

    def test_first_request_initializes_hosted_app_without_local_state(self):
        self.assertEqual(self.start().status_code, 302)
        self.assertEqual(self.save().status_code, 200)
        self.assertFalse(labeling.DATABASE.exists())
        self.assertFalse(labeling.HASH_KEY_FILE.exists())
        self.assertTrue(labeling.app.config['SESSION_COOKIE_SECURE'])
        with labeling.get_db() as connection:
            self.assertIsNone(connection.prepare_threshold)
        self.assertTrue(connection.closed)

    def test_save_retry_correction_resume_and_completion(self):
        self.start()
        self.assertEqual(self.save().status_code, 200)
        original = self.rows()[0]
        self.assertEqual(self.save().status_code, 200)
        self.assertEqual(self.rows()[0], original)
        self.assertEqual(self.save(label='love').status_code, 200)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]['id'], original['id'])
        self.assertEqual(self.rows()[0]['label'], 'love')
        self.client.post('/leave')
        self.start()
        self.assertEqual(self.task()['completedCount'], 1)
        self.assertEqual(self.save('1').status_code, 200)
        self.assertEqual(self.task()['completedCount'], 2)
        html = self.client.get('/results').get_data(as_text=True)
        self.assertIn(original['participant_id'], html)
        self.assertNotIn('participant@example.com', html)
        self.assertNotIn('+00:00 UTC', html)
        self.assertRegex(html, r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC')
        labeling.app.config['APP_CONFIGURED'] = False
        self.assertEqual(self.task()['completedCount'], 2)

    def test_other_participant_receives_independent_queue(self):
        self.start()
        self.save()
        self.start('another@example.com')
        self.assertEqual(self.task()['completedCount'], 0)
        self.save(label='fear')
        self.assertEqual(len(self.rows()), 2)
        self.assertNotEqual(self.rows()[0]['participant_id'], self.rows()[1]['participant_id'])

    def test_concurrent_retries_persist_one_response(self):
        clients = [labeling.app.test_client(), labeling.app.test_client()]
        for client in clients:
            self.start(client=client)
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(lambda client: self.save(client=client).status_code, clients))
        self.assertEqual(statuses, [200, 200])
        self.assertEqual(len(self.rows()), 1)

    def test_concurrent_schema_initialization_preserves_responses(self):
        self.start()
        self.save()
        original = self.rows()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(labeling.init_db) for _ in range(2)]
            for future in futures:
                future.result()
        self.assertEqual(self.rows(), original)

    def test_invalid_submissions_do_not_write(self):
        self.assertEqual(self.save().status_code, 401)
        self.start()
        for payload in ({}, {'tweet_id': '99', 'label': 'joy'},
                        {'tweet_id': '0', 'label': "joy'); DROP TABLE labeler.responses; --"}):
            self.assertEqual(self.client.post('/submit', json=payload).status_code, 400)
        self.assertEqual(self.rows(), [])

    def test_failed_transaction_rolls_back_and_releases_connection(self):
        with self.assertRaises(psycopg.errors.NotNullViolation):
            with labeling.get_db() as connection:
                connection.execute("INSERT INTO labeler.responses (participant_id, tweet_id, label) VALUES (%s, 0, 'joy')", ('cd' * 32,))
                connection.execute('INSERT INTO labeler.responses (participant_id, tweet_id, label) VALUES (NULL, 1, NULL)')
        self.assertTrue(connection.closed)
        self.assertEqual(self.rows(), [])


if __name__ == '__main__':
    unittest.main()
