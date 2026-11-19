from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import main


class ReactionAwardBotTests(unittest.TestCase):
    @patch("main.time.sleep")
    @patch("main.requests.request")
    def test_rate_limit_retries_are_bounded(self, request, sleep):
        request.return_value = Mock(status_code=429, headers={"Retry-After": "1.5"})

        with self.assertRaisesRegex(RuntimeError, "remained rate limited"):
            main.request_json("GET", "https://example.com", allow_missing=True)

        self.assertEqual(request.call_count, main.REQUEST_MAX_ATTEMPTS)
        self.assertEqual(sleep.call_count, main.REQUEST_MAX_ATTEMPTS - 1)
        sleep.assert_called_with(1.75)

    @patch("main.time.sleep")
    @patch("main.requests.request")
    def test_rate_limit_does_not_wait_beyond_budget(self, request, sleep):
        request.return_value = Mock(status_code=429, headers={"Retry-After": "3600"})

        with self.assertRaisesRegex(RuntimeError, "exceeds the retry budget"):
            main.request_json("GET", "https://example.com")

        sleep.assert_not_called()

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

    @patch("main.count_unique_reaction_users")
    @patch("main.fetch_messages_for_channel")
    @patch("main.fetch_channels_to_scan")
    def test_verifies_only_messages_that_can_reach_the_ranking(
        self,
        fetch_channels_to_scan,
        fetch_messages_for_channel,
        count_unique_reaction_users,
    ):
        fetch_channels_to_scan.return_value = [{"id": "channel", "type": 0, "name": "general"}]
        fetch_messages_for_channel.return_value = [
            {
                "id": f"message-{index}",
                "author": {"id": f"author-{index}", "username": f"Author {index}"},
                "content": f"Message {index}",
                "reactions": [{"count": upper_bound}],
            }
            for index, upper_bound in enumerate([10, 9, 8, 3])
        ]
        count_unique_reaction_users.side_effect = [5, 4, 1]

        candidates = main.find_top_candidates({}, "bot", main.get_window()[0], main.get_window()[1], limit=2)

        self.assertEqual([candidate.voter_count for candidate in candidates], [5, 4])
        self.assertEqual(count_unique_reaction_users.call_count, 3)

    def test_reaction_count_is_an_upper_bound_for_unique_users(self):
        message = {"reactions": [{"count": 4}, {"count": 3}]}

        self.assertEqual(main.get_reaction_count_upper_bound(message), 7)

    def test_adds_separator_after_trailing_url_in_preview(self):
        self.assertEqual(
            main.format_message_preview("詳しくはこちら https://example.com/news?id=42", 80),
            "詳しくはこちら https://example.com/news?id=42 ",
        )

    def test_does_not_add_separator_to_normal_preview(self):
        self.assertEqual(
            main.format_message_preview("今日は楽しかった", 80),
            "今日は楽しかった",
        )

    def test_announcement_separates_trailing_url_from_closing_quote(self):
        candidate = main.AwardCandidate(
            voter_count=3,
            message_id="message",
            channel_id="channel",
            author_id="author",
            author_name="Author",
            content="詳しくはこちら https://example.com/news?id=42",
        )

        announcement = main.build_announcement([candidate])

        self.assertIn(
            "「詳しくはこちら https://example.com/news?id=42 」",
            announcement,
        )


if __name__ == "__main__":
    unittest.main()
