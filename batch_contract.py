"""Shared HTTP behavior checks for SQLite and PostgreSQL test fixtures."""

import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import psycopg

import app as labeling


class BatchContract:
    def start(self, email='participant@example.com', client=None):
        return (client or self.client).post('/start', data={'email': email})

    def task(self, client=None):
        response = (client or self.client).get('/')
        self.assertEqual(response.status_code, 200)
        match = re.search(r'<script id="task-data" type="application/json">(.*?)</script>',
                          response.get_data(as_text=True), re.DOTALL)
        self.assertIsNotNone(match)
        return json.loads(match[1])

    def payload(self, task=None, label='joy'):
        task = task or self.task()
        return {'batch_id': task['batchId'], 'answers': [
            {'tweet_id': tweet['id'], 'label': label} for tweet in task['tweets']]}

    def save(self, payload=None, client=None):
        client = client or self.client
        if payload is None:
            payload = self.payload(self.task(client))
        return client.post('/submit', json=payload)

    def rows(self):
        with labeling.get_db() as connection:
            return connection.execute(f'SELECT * FROM {labeling.response_table()} ORDER BY id').fetchall()

    def test_start_keeps_only_hashed_email_in_session(self):
        self.assertEqual(self.start().status_code, 302)
        with self.client.session_transaction() as session:
            self.assertRegex(session['participant_id'], r'\A[0-9a-f]{64}\Z')
            self.assertNotIn('participant@example.com', str(dict(session)))

    def test_batch_contains_five_distinct_unlabeled_tweets_without_ground_truth(self):
        self.start()
        task = self.task()
        self.assertEqual(len(task['tweets']), 5)
        self.assertEqual(len({tweet['id'] for tweet in task['tweets']}), 5)
        self.assertTrue(all(tweet['label'] is None for tweet in task['tweets']))
        self.assertTrue(all('ground_truth' not in tweet for tweet in task['tweets']))
        self.assertFalse(task['submitted'])
        self.assertEqual(task['completedCount'], 0)
        self.assertEqual(self.rows(), [])

    def test_batch_is_stable_across_refresh_and_results_navigation(self):
        self.start()
        original = self.task()
        self.assertEqual(self.client.get('/results').status_code, 200)
        self.assertEqual(self.task(), original)
        html = self.client.get('/').get_data(as_text=True)
        self.assertNotRegex(html, r'id="results-link"[^>]*target="_blank"')

    def test_submitting_complete_batch_saves_all_answers_and_shows_confirmation(self):
        self.start()
        task = self.task()
        response = self.save(self.payload(task))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['saved'])
        self.assertEqual(len(self.rows()), 5)
        saved = self.task()
        self.assertEqual(saved['batchId'], task['batchId'])
        self.assertTrue(saved['submitted'])
        self.assertEqual(saved['completedCount'], 5)
        html = self.client.get('/results').get_data(as_text=True)
        self.assertIn(self.rows()[0]['participant_id'], html)
        self.assertNotIn('participant@example.com', html)

    def test_incomplete_duplicate_foreign_and_invalid_answers_save_nothing(self):
        self.start()
        task = self.task()
        payload = self.payload(task)
        outside = next(str(i) for i in range(6) if str(i) not in {t['id'] for t in task['tweets']})
        cases = [None, [], {}, {'tweet_id': task['tweets'][0]['id'], 'label': 'joy'},
                 {**payload, 'answers': payload['answers'][:-1]},
                 {**payload, 'answers': []}, {**payload, 'answers': {}},
                 {**payload, 'answers': payload['answers'][:-1] + [payload['answers'][0]]},
                 {**payload, 'answers': payload['answers'][:-1] + [{'tweet_id': outside, 'label': 'joy'}]},
                 {**payload, 'answers': payload['answers'][:-1] + [{'tweet_id': [], 'label': 'joy'}]},
                 {**payload, 'answers': payload['answers'][:-1] + [{'tweet_id': task['tweets'][-1]['id'], 'label': []}]},
                 {**payload, 'answers': payload['answers'][:-1] + [{'tweet_id': task['tweets'][-1]['id'], 'label': 'invalid'}]}]
        for case in cases:
            with self.subTest(payload=case):
                self.assertEqual(self.client.post('/submit', json=case).status_code, 400)
                self.assertEqual(self.rows(), [])

    def test_retry_is_idempotent_and_cannot_change_submitted_batch(self):
        self.start()
        payload = self.payload()
        self.assertEqual(self.save(payload).status_code, 200)
        original = [dict(row) for row in self.rows()]
        self.assertEqual(self.save(payload).status_code, 200)
        self.assertEqual([dict(row) for row in self.rows()], original)
        payload['answers'][0]['label'] = 'love'
        self.assertEqual(self.save(payload).status_code, 409)
        self.assertEqual([dict(row) for row in self.rows()], original)

    def test_next_batch_has_only_remaining_tweet_then_completion(self):
        self.start()
        first = self.task()
        self.save(self.payload(first))
        self.assertEqual(self.client.post('/next-batch').status_code, 302)
        last = self.task()
        self.assertEqual(len(last['tweets']), 1)
        self.assertNotIn(last['tweets'][0]['id'], {tweet['id'] for tweet in first['tweets']})
        self.assertEqual(self.save(self.payload(last)).status_code, 200)
        self.assertEqual(len(self.rows()), 6)
        self.assertEqual(self.task()['remainingCount'], 0)
        self.client.post('/leave')
        self.start()
        self.assertEqual(self.task()['tweets'], [])
        self.assertEqual(self.task()['completedCount'], 6)

    def test_cannot_skip_unsubmitted_batch(self):
        self.start()
        original = self.task()
        self.assertEqual(self.client.post('/next-batch').status_code, 409)
        self.assertEqual(self.task(), original)
        self.assertEqual(self.rows(), [])

    def test_reentering_email_skips_saved_tweets_and_keeps_existing_labels(self):
        self.start(' participant@EXAMPLE.COM ')
        first = self.task()
        self.save(self.payload(first))
        self.client.post('/leave')
        self.start()
        task = self.task()
        self.assertEqual(task['completedCount'], 5)
        self.assertEqual(len(task['tweets']), 1)
        self.assertEqual(len(self.rows()), 5)

    def test_participants_have_independent_batches_and_stale_batch_cannot_cross_identity(self):
        self.start()
        payload = self.payload()
        self.save(payload)
        self.start('another@example.com')
        self.assertEqual(self.save(payload).status_code, 409)
        task = self.task()
        self.assertEqual(task['completedCount'], 0)
        self.assertEqual(len(task['tweets']), 5)
        self.save(self.payload(task))
        self.assertEqual(len(self.rows()), 10)
        self.assertEqual(len({row['participant_id'] for row in self.rows()}), 2)

    def test_concurrent_retries_save_exactly_one_batch(self):
        self.start()
        payload = self.payload()
        clients = [labeling.app.test_client(), labeling.app.test_client()]
        cookie_name = labeling.app.config['SESSION_COOKIE_NAME']
        for client in clients:
            client.set_cookie(cookie_name, self.client.get_cookie(cookie_name).value)
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(lambda client: self.save(payload, client).status_code, clients))
        self.assertEqual(statuses, [200, 200])
        self.assertEqual(len(self.rows()), 5)

    def test_overlapping_batch_conflict_preserves_all_previously_saved_labels(self):
        self.start()
        first = self.payload()
        other = labeling.app.test_client()
        self.start(client=other)
        second = self.payload(self.task(other), label='fear')
        self.assertEqual(self.save(first).status_code, 200)
        original = [dict(row) for row in self.rows()]
        self.assertEqual(self.save(second, other).status_code, 409)
        self.assertEqual([dict(row) for row in self.rows()], original)

    def test_existing_individual_labels_are_preserved_and_excluded_from_batches(self):
        self.start()
        with self.client.session_transaction() as session:
            participant_id = session['participant_id']
        parameter = labeling.sql_parameter()
        with labeling.get_db() as connection:
            connection.execute(f'INSERT INTO {labeling.response_table()} (participant_id, tweet_id, label) VALUES ({parameter}, 0, {parameter})',
                               (participant_id, 'fear'))
        batch = self.task()
        self.assertEqual(batch['completedCount'], 1)
        self.assertEqual(len(batch['tweets']), 5)
        self.assertNotIn('0', {tweet['id'] for tweet in batch['tweets']})
        self.assertEqual(self.save(self.payload(batch)).status_code, 200)
        self.assertEqual(len(self.rows()), 6)
        self.assertEqual(next(row['label'] for row in self.rows() if row['tweet_id'] == 0), 'fear')

    def test_database_failure_rolls_back_all_answers(self):
        self.start()
        payload = self.payload()
        rejected_id = sorted(int(answer['tweet_id']) for answer in payload['answers'])[2]
        postgres = bool(labeling.app.config.get('DATABASE_URL'))
        with labeling.get_db() as connection:
            if postgres:
                connection.execute(f'ALTER TABLE labeler.responses ADD CONSTRAINT test_failure CHECK(tweet_id <> {rejected_id})')
            else:
                connection.execute(f"CREATE TRIGGER test_failure BEFORE INSERT ON responses WHEN NEW.tweet_id = {rejected_id} BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        try:
            with self.assertRaises((sqlite3.IntegrityError, psycopg.IntegrityError)):
                self.save(payload)
            self.assertEqual(self.rows(), [])
        finally:
            with labeling.get_db() as connection:
                connection.execute('ALTER TABLE labeler.responses DROP CONSTRAINT test_failure' if postgres else 'DROP TRIGGER test_failure')
        self.assertEqual(self.save(payload).status_code, 200)
        self.assertEqual(len(self.rows()), 5)

    def test_empty_dataset_has_no_batch_to_submit(self):
        labeling.DATA_FILE.write_text('id,tweet,emotion\n', encoding='utf-8')
        self.start()
        task = self.task()
        self.assertEqual(task['tweets'], [])
        self.assertEqual(task['totalCount'], 0)
        self.assertEqual(self.save(self.payload(task)).status_code, 400)

    def test_invalid_email_and_signed_out_sessions_cannot_submit(self):
        for email in ('', 'not-an-email', 'a@@example.com', 'a b@example.com'):
            self.assertEqual(self.start(email).status_code, 400)
        self.assertEqual(self.client.post('/submit', json={}).status_code, 401)
        self.assertEqual(self.client.post('/next-batch').status_code, 401)
        self.assertEqual(self.rows(), [])
