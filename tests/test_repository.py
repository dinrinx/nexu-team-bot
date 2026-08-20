import tempfile
import unittest
from pathlib import Path

from aiogram.fsm.storage.base import StorageKey

from bot.constants import STATUS_HAS_TEAM, STATUS_LOOKING
from bot.database import Database, Profile, now_iso
from bot.storage import SQLiteStorage


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.db = Database(self.db_path)
        self.db.init_schema()

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def make_profile(self, user_id: int, **overrides) -> Profile:
        payload = {
            "user_id": user_id,
            "name": f"User {user_id}",
            "championships": ["КЛЮЧ"],
            "roles": ["аналитика и цифры"],
            "status": STATUS_LOOKING,
            "looking_for_roles": [],
            "city": "Москва",
            "username": f"@user{user_id}",
            "contact": f"@user{user_id}",
            "about": "О себе",
            "photo_file_id": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        payload.update(overrides)
        return Profile(**payload)

    def test_profile_roundtrip(self) -> None:
        profile = self.make_profile(1)
        self.db.upsert_profile(profile)

        loaded = self.db.get_profile(1)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.name, "User 1")
        self.assertEqual(loaded.championships, ["КЛЮЧ"])

    def test_match_creation(self) -> None:
        self.db.upsert_profile(self.make_profile(1))
        self.db.upsert_profile(self.make_profile(2))

        self.assertTrue(self.db.save_reaction(1, 2, "like"))
        self.assertFalse(self.db.is_mutual_like(1, 2))
        self.assertTrue(self.db.save_reaction(2, 1, "like"))
        self.assertTrue(self.db.is_mutual_like(2, 1))
        self.assertTrue(self.db.create_match(2, 1))
        self.assertFalse(self.db.create_match(1, 2))

        matches = self.db.get_matches_for_user(1)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0][0].user_id, 2)

    def test_feed_filters_and_delete_cascade(self) -> None:
        self.db.upsert_profile(self.make_profile(1))
        self.db.upsert_profile(
            self.make_profile(
                2,
                championships=["DEADLINE"],
                roles=["дизайн слайдов"],
                status=STATUS_HAS_TEAM,
                looking_for_roles=["аналитика и цифры"],
            )
        )
        self.db.upsert_profile(self.make_profile(3, championships=["КЛЮЧ", "DEADLINE"]))

        filtered = self.db.get_feed_candidates(
            1,
            {
                "championships": ["DEADLINE"],
                "roles": ["дизайн слайдов"],
                "looking_for_roles": ["аналитика и цифры"],
            },
        )
        self.assertEqual([profile.user_id for profile in filtered], [2])

        self.db.save_reaction(1, 2, "like")
        self.db.save_reaction(2, 1, "like")
        self.db.create_match(1, 2)
        self.db.delete_profile(2)

        self.assertIsNone(self.db.get_profile(2))
        self.assertEqual(self.db.get_matches_for_user(1), [])

    def test_reaction_requires_existing_profiles(self) -> None:
        self.db.upsert_profile(self.make_profile(1))
        self.assertFalse(self.db.save_reaction(1, 999, "like"))
        self.assertFalse(self.db.create_match(1, 999))
        self.assertFalse(self.db.save_reaction(1, 1, "like"))


class SQLiteStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "storage.sqlite3"
        self.storage = SQLiteStorage(self.db_path)
        self.key = StorageKey(bot_id=1, chat_id=10, user_id=20)

    async def asyncTearDown(self) -> None:
        await self.storage.close()
        self.temp_dir.cleanup()

    async def test_state_and_data_persist_between_instances(self) -> None:
        await self.storage.set_state(self.key, "ProfileForm:name")
        await self.storage.set_data(self.key, {"draft": {"name": "Diana"}})
        await self.storage.close()

        reopened = SQLiteStorage(self.db_path)
        self.addAsyncCleanup(reopened.close)
        self.assertEqual(await reopened.get_state(self.key), "ProfileForm:name")
        self.assertEqual(await reopened.get_data(self.key), {"draft": {"name": "Diana"}})


if __name__ == "__main__":
    unittest.main()
