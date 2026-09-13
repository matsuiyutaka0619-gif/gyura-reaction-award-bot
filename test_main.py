from __future__ import annotations

import unittest
from unittest.mock import patch

import main


class ReactionAwardBotTests(unittest.TestCase):
    @patch("main.fetch_archived_public_threads")
    @patch("main.fetch_active_threads")
    @patch("main.fetch_guild_channels")
    def test_discovers_text_channels_and_forum_threads(
        self,
        fetch_guild_channels,
        fetch_active_threads,
        fetch_archived_public_threads,
    ):
        fetch_guild_channels.return_value = [
            {"id": "text", "type": 0, "name": "general"},
            {"id": "forum", "type": 15, "name": "forum"},
            {"id": "voice", "type": 2, "name": "voice"},
        ]
        fetch_active_threads.return_value = [
            {"id": "active-post", "type": 11, "parent_id": "forum", "name": "active"},
        ]
        fetch_archived_public_threads.side_effect = lambda parent_id, _headers, _start: (
            [{"id": "archived-post", "type": 11, "parent_id": "forum", "name": "archived"}]
            if parent_id == "forum"
            else []
        )

        channels = main.fetch_channels_to_scan({}, main.get_window()[0])

        self.assertEqual(
            {channel["id"] for channel in channels},
            {"text", "active-post", "archived-post"},
        )

    def test_announcement_supports_top_five(self):
        candidates = [
            main.AwardCandidate(
                voter_count=10 - index,
                message_id=f"message-{index}",
                channel_id="channel",
                author_id=f"author-{index}",
                author_name=f"Author {index}",
                content=f"Message {index}",
            )
            for index in range(5)
        ]

        announcement = main.build_announcement(candidates)

        for rank in range(1, 6):
            self.assertIn(f"{rank}位", announcement)


if __name__ == "__main__":
    unittest.main()
