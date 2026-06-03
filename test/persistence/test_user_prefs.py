import os
import sqlite3
import unittest
from datetime import datetime, timezone

from src.persistence.user_prefs import UserPrefs, SqliteUserPrefsPersistence


class TestSqliteUserPrefsPersistence(unittest.TestCase):
    def setUp(self):
        self.db_path = "test_user_prefs.sqlite"
        self.persistence = SqliteUserPrefsPersistence(self.db_path)
        self.persistence._initialize_db()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_initialize_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='user_prefs'"
            )
            self.assertIsNotNone(cursor.fetchone())

    def test_persist_and_get_user_prefs(self):
        user_id = "test_user"
        user_prefs = UserPrefs(user_id)
        user_prefs.respond_to_testing = UserPrefs.Preference.from_values(
            value=True, time_set=datetime.now(timezone.utc), num_changes=0
        )

        self.persistence.persist_user_prefs(user_id, user_prefs)
        retrieved_prefs = self.persistence.get_user_prefs(user_id)

        self.assertEqual(retrieved_prefs.user_id, user_id)
        self.assertTrue(retrieved_prefs.respond_to_testing.value)
        self.assertEqual(retrieved_prefs.respond_to_testing.num_changes, 0)

    def test_update_user_prefs(self):
        user_id = "test_user"
        user_prefs = UserPrefs(user_id)
        user_prefs.respond_to_testing = UserPrefs.Preference.from_values(
            value=True, time_set=datetime.now(timezone.utc), num_changes=0
        )

        self.persistence.persist_user_prefs(user_id, user_prefs)
        user_prefs.respond_to_testing.value = False
        self.persistence.persist_user_prefs(user_id, user_prefs)
        retrieved_prefs = self.persistence.get_user_prefs(user_id)

        self.assertFalse(retrieved_prefs.respond_to_testing.value)
        self.assertEqual(retrieved_prefs.respond_to_testing.num_changes, 1)

    def test_multiple_settings(self):
        user_id = "test_user"
        user_prefs = UserPrefs(user_id)
        user_prefs.respond_to_testing = UserPrefs.Preference.from_values(
            value=True, time_set=datetime.now(timezone.utc), num_changes=0
        )
        user_prefs.another_setting = UserPrefs.Preference.from_values(
            value="value", time_set=datetime.now(timezone.utc), num_changes=0
        )

        self.persistence.persist_user_prefs(user_id, user_prefs)
        retrieved_prefs = self.persistence.get_user_prefs(user_id)

        self.assertEqual(retrieved_prefs.user_id, user_id)
        self.assertTrue(retrieved_prefs.respond_to_testing.value)
        self.assertEqual(retrieved_prefs.another_setting.value, "value")

    def test_field_change_does_not_update_others(self):
        user_id = "test_user"
        user_prefs = UserPrefs(user_id)
        user_prefs.respond_to_testing = UserPrefs.Preference.from_values(
            value=True, time_set=datetime.now(timezone.utc), num_changes=0
        )
        user_prefs.another_setting = UserPrefs.Preference.from_values(
            value="value", time_set=datetime.now(timezone.utc), num_changes=0
        )
        original_time_set_testing = user_prefs.respond_to_testing.time_set
        original_time_set_another = user_prefs.another_setting.time_set

        self.persistence.persist_user_prefs(user_id, user_prefs)

        # Change only one field
        user_prefs.respond_to_testing.value = False
        self.persistence.persist_user_prefs(user_id, user_prefs)

        retrieved_prefs = self.persistence.get_user_prefs(user_id)

        self.assertFalse(retrieved_prefs.respond_to_testing.value)
        self.assertEqual(retrieved_prefs.respond_to_testing.num_changes, 1)
        self.assertNotEqual(
            retrieved_prefs.respond_to_testing.time_set,
            original_time_set_testing,
            "Expected time set to have been updated",
        )
        self.assertEqual(retrieved_prefs.another_setting.value, "value")
        self.assertEqual(retrieved_prefs.another_setting.num_changes, 0)
        self.assertEqual(
            retrieved_prefs.another_setting.time_set, original_time_set_another
        )


if __name__ == "__main__":
    unittest.main()
