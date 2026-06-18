from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, time as datetime_time, timedelta, timezone
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests


DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_EPOCH_MS = 1420070400000
CHANNEL_TYPES_TO_SCAN = {0, 5}


@dataclass
class AwardCandidate:
    voter_count: int
    message_id: str
    channel_id: str
    author_id: str
    author_name: str
    content: str

    @property
    def link(self) -> str:
        return f"https://discord.com/channels/{CONFIG.guild_id}/{self.channel_id}/{self.message_id}"


@dataclass
class Config:
    guild_id: str
    excluded_channel_ids: set[str]
    timezone_name: str
    award_time: str
    message_preview_length: int


def load_config(path: str = "config.json") -> Config:
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)

    return Config(
        guild_id=str(data["guild_id"]),
        excluded_channel_ids={str(channel_id) for channel_id in data.get("excluded_channel_ids", [])},
        timezone_name=data.get("timezone", "Asia/Tokyo"),
        award_time=data.get("award_time", "20:45"),
        message_preview_length=int(data.get("message_preview_length", 80)),
    )


CONFIG = load_config()


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    allow_missing: bool = False,
    **kwargs: Any,
) -> Any:
    while True:
        response = requests.request(method, url, headers=headers, timeout=30, **kwargs)

        if response.status_code == 429:
            retry_after = response.json().get("retry_after", 1)
            time.sleep(float(retry_after) + 0.25)
            continue

        if allow_missing and response.status_code in {403, 404}:
            return None

        response.raise_for_status()

        if response.content:
            return response.json()

        return None


def parse_award_time(value: str) -> datetime_time:
    hour, minute = value.split(":", 1)
    return datetime_time(hour=int(hour), minute=int(minute))


def get_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    tz = ZoneInfo(CONFIG.timezone_name)
    current = now.astimezone(tz) if now else datetime.now(tz)
    award_time = parse_award_time(CONFIG.award_time)

    end_date = current.date()
    end = datetime.combine(end_date, award_time, tzinfo=tz) - timedelta(minutes=1)
    start = datetime.combine(end_date - timedelta(days=1), award_time, tzinfo=tz)

    return start, end.replace(second=59, microsecond=999999)


def datetime_to_snowflake(value: datetime) -> int:
    timestamp_ms = int(value.astimezone(timezone.utc).timestamp() * 1000)
    return (timestamp_ms - DISCORD_EPOCH_MS) << 22


def parse_discord_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def truncate_message(content: str, max_length: int) -> str:
    normalized = " ".join(content.split())

    if not normalized:
        return "（本文なし）"

    if len(normalized) <= max_length:
        return normalized

    return normalized[: max_length - 3].rstrip() + "..."


def fetch_bot_user_id(headers: dict[str, str]) -> str:
    user = request_json("GET", f"{DISCORD_API_BASE}/users/@me", headers=headers)
    if not user:
        raise RuntimeError("Bot user could not be fetched. Check DISCORD_BOT_TOKEN.")
    return str(user["id"])


def fetch_channels(headers: dict[str, str]) -> list[dict[str, Any]]:
    channels = request_json("GET", f"{DISCORD_API_BASE}/guilds/{CONFIG.guild_id}/channels", headers=headers)
    if not channels:
        return []

    return [
        channel
        for channel in channels
        if channel.get("type") in CHANNEL_TYPES_TO_SCAN
        and str(channel.get("id")) not in CONFIG.excluded_channel_ids
    ]


def fetch_messages_for_channel(
    channel_id: str,
    headers: dict[str, str],
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    before = str(datetime_to_snowflake(end + timedelta(milliseconds=1)))

    while True:
        batch = request_json(
            "GET",
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            headers=headers,
            allow_missing=True,
            params={"limit": 100, "before": before},
        )

        if not batch:
            break

        oldest_seen: datetime | None = None

        for message in batch:
            created_at = parse_discord_timestamp(message["timestamp"])
            oldest_seen = created_at if oldest_seen is None else min(oldest_seen, created_at)

            if start <= created_at <= end:
                messages.append(message)

        if oldest_seen and oldest_seen < start:
            break

        before = str(batch[-1]["id"])

    return messages


def get_reaction_emoji_identifier(reaction: dict[str, Any]) -> str:
    emoji = reaction.get("emoji", {})
    name = emoji.get("name")
    emoji_id = emoji.get("id")

    if not name:
        return ""

    if emoji_id:
        return f"{name}:{emoji_id}"

    return name


def fetch_reaction_user_ids(
    channel_id: str,
    message_id: str,
    reaction: dict[str, Any],
    headers: dict[str, str],
    bot_user_id: str,
) -> set[str]:
    emoji_identifier = get_reaction_emoji_identifier(reaction)
    if not emoji_identifier:
        return set()

    encoded_emoji = quote(emoji_identifier, safe="")
    user_ids: set[str] = set()
    after: str | None = None

    while True:
        params = {"limit": 100}
        if after:
            params["after"] = after

        users = request_json(
            "GET",
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}",
            headers=headers,
            allow_missing=True,
            params=params,
        )

        if not users:
            break

        for user in users:
            user_id = str(user.get("id", ""))
            if user_id and user_id != bot_user_id:
                user_ids.add(user_id)

        if len(users) < 100:
            break

        after = str(users[-1]["id"])

    return user_ids


def count_unique_reaction_users(
    channel_id: str,
    message: dict[str, Any],
    headers: dict[str, str],
    bot_user_id: str,
) -> int:
    voter_ids: set[str] = set()

    for reaction in message.get("reactions", []):
        voter_ids.update(
            fetch_reaction_user_ids(
                channel_id,
                str(message["id"]),
                reaction,
                headers,
                bot_user_id,
            )
        )

    return len(voter_ids)


def find_winner(headers: dict[str, str], bot_user_id: str, start: datetime, end: datetime) -> AwardCandidate | None:
    winner: AwardCandidate | None = None

    for channel in fetch_channels(headers):
        channel_id = str(channel["id"])
        channel_name = channel.get("name", channel_id)
        print(f"Scanning #{channel_name} ({channel_id})")

        for message in fetch_messages_for_channel(channel_id, headers, start, end):
            author = message.get("author", {})
            if str(author.get("id")) == bot_user_id:
                continue

            if not message.get("reactions"):
                continue

            voter_count = count_unique_reaction_users(channel_id, message, headers, bot_user_id)
            if voter_count <= 0:
                continue

            candidate = AwardCandidate(
                voter_count=voter_count,
                message_id=str(message["id"]),
                channel_id=channel_id,
                author_id=str(author.get("id", "")),
                author_name=author.get("global_name") or author.get("username") or "unknown",
                content=message.get("content", ""),
            )

            if not winner or candidate.voter_count > winner.voter_count:
                winner = candidate

    return winner


def build_announcement(winner: AwardCandidate | None) -> str:
    if not winner:
        return "🏆 本日のギュラ鯖リアクション賞🏆\n\n本日は対象メッセージがありませんでした。"

    preview = truncate_message(winner.content, CONFIG.message_preview_length)

    return (
        "🏆 本日のギュラ鯖リアクション賞🏆 \n\n"
        f"投稿者: <@{winner.author_id}>\n"
        f"リアクション人数: {winner.voter_count}\n\n"
        f"「{preview}」\n\n"
        "元メッセージ:\n"
        f"{winner.link}"
    )


def post_webhook(content: str) -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is missing.")

    request_json("POST", webhook_url, json={"content": content})


def main() -> int:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        print("DISCORD_BOT_TOKEN is missing.", file=sys.stderr)
        return 1

    headers = {"Authorization": f"Bot {token}"}
    start, end = get_window()

    print(f"Aggregation window: {start.isoformat()} - {end.isoformat()}")
    bot_user_id = fetch_bot_user_id(headers)
    winner = find_winner(headers, bot_user_id, start, end)
    announcement = build_announcement(winner)
    post_webhook(announcement)

    print("Announcement posted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
