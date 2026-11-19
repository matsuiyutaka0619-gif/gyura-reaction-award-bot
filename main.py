from __future__ import annotations

import json
import os
import re
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
MESSAGE_CHANNEL_TYPES = {0, 5}
THREAD_PARENT_CHANNEL_TYPES = {0, 5, 15, 16}
THREAD_CHANNEL_TYPES = {10, 11, 12}
DEFAULT_AWARD_LIMIT = 5
REQUEST_MAX_ATTEMPTS = 5
REQUEST_BACKOFF_SECONDS = 2
DISCORD_MAX_RATE_LIMIT_WAIT_SECONDS = 120
TRAILING_URL_PATTERN = re.compile(r"https?://[^\s<>]+$", re.IGNORECASE)


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
class CandidateMessage:
    reaction_upper_bound: int
    scan_order: int
    channel_id: str
    message: dict[str, Any]


@dataclass
class Config:
    guild_id: str
    excluded_channel_ids: set[str]
    timezone_name: str
    award_time: str
    message_preview_length: int
    award_limit: int


def load_config(path: str = "config.json") -> Config:
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)

    return Config(
        guild_id=str(data["guild_id"]),
        excluded_channel_ids={str(channel_id) for channel_id in data.get("excluded_channel_ids", [])},
        timezone_name=data.get("timezone", "Asia/Tokyo"),
        award_time=data.get("award_time", "05:00"),
        message_preview_length=int(data.get("message_preview_length", 80)),
        award_limit=int(data.get("award_limit", DEFAULT_AWARD_LIMIT)),
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
    attempt = 0

    while True:
        attempt += 1

        try:
            response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        except requests.RequestException as error:
            if attempt < REQUEST_MAX_ATTEMPTS:
                wait_seconds = REQUEST_BACKOFF_SECONDS * attempt
                print(f"Request failed, retrying in {wait_seconds}s: {error}", file=sys.stderr)
                time.sleep(wait_seconds)
                continue

            if allow_missing:
                print(f"Skipping unavailable Discord API request after retries: {url}", file=sys.stderr)
                return None

            raise

        if response.status_code == 429:
            if attempt >= REQUEST_MAX_ATTEMPTS:
                raise RuntimeError("Discord API remained rate limited after retries.")
            try:
                retry_after = float(response.headers.get("Retry-After") or response.json()["retry_after"])
            except (ValueError, TypeError, KeyError):
                retry_after = REQUEST_BACKOFF_SECONDS * attempt
            if not 0 <= retry_after <= DISCORD_MAX_RATE_LIMIT_WAIT_SECONDS:
                raise RuntimeError("Discord API rate limit wait exceeds the retry budget.")
            print(f"Discord API rate limited. Retrying in {retry_after + 0.25:g}s.", file=sys.stderr)
            time.sleep(retry_after + 0.25)
            continue

        if 500 <= response.status_code < 600:
            if attempt < REQUEST_MAX_ATTEMPTS:
                wait_seconds = REQUEST_BACKOFF_SECONDS * attempt
                print(
                    f"Discord API returned {response.status_code}, retrying in {wait_seconds}s: {url}",
                    file=sys.stderr,
                )
                time.sleep(wait_seconds)
                continue

            if allow_missing:
                print(
                    f"Skipping unavailable Discord API request after {REQUEST_MAX_ATTEMPTS} attempts: {url}",
                    file=sys.stderr,
                )
                return None

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

    if current.timetz().replace(tzinfo=None) >= award_time:
        end_date = current.date()
    else:
        end_date = current.date() - timedelta(days=1)

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


def format_message_preview(content: str, max_length: int) -> str:
    """Keep Discord from treating the closing Japanese quote as URL text."""
    preview = truncate_message(content, max_length)

    if TRAILING_URL_PATTERN.search(preview):
        return f"{preview} "

    return preview


def fetch_bot_user_id(headers: dict[str, str]) -> str:
    user = request_json("GET", f"{DISCORD_API_BASE}/users/@me", headers=headers)
    if not user:
        raise RuntimeError("Bot user could not be fetched. Check DISCORD_BOT_TOKEN.")
    return str(user["id"])


def fetch_guild_channels(headers: dict[str, str]) -> list[dict[str, Any]]:
    channels = request_json("GET", f"{DISCORD_API_BASE}/guilds/{CONFIG.guild_id}/channels", headers=headers)
    if not channels:
        return []

    return channels


def fetch_active_threads(headers: dict[str, str]) -> list[dict[str, Any]]:
    response = request_json(
        "GET",
        f"{DISCORD_API_BASE}/guilds/{CONFIG.guild_id}/threads/active",
        headers=headers,
        allow_missing=True,
    )
    if not response:
        return []

    return response.get("threads", [])


def fetch_archived_public_threads(
    parent_channel_id: str,
    headers: dict[str, str],
    start: datetime,
) -> list[dict[str, Any]]:
    threads: list[dict[str, Any]] = []
    before: str | None = None

    while True:
        params: dict[str, Any] = {"limit": 100}
        if before:
            params["before"] = before

        response = request_json(
            "GET",
            f"{DISCORD_API_BASE}/channels/{parent_channel_id}/threads/archived/public",
            headers=headers,
            allow_missing=True,
            params=params,
        )
        if not response:
            break

        batch = response.get("threads", [])
        if not batch:
            break

        threads.extend(batch)
        archive_timestamps = [
            thread.get("thread_metadata", {}).get("archive_timestamp")
            for thread in batch
        ]
        archive_timestamps = [value for value in archive_timestamps if value]

        if archive_timestamps:
            oldest_archive = min(parse_discord_timestamp(value) for value in archive_timestamps)
            if oldest_archive < start:
                break
            before = min(archive_timestamps)
        else:
            break

        if not response.get("has_more"):
            break

    return threads


def fetch_channels_to_scan(
    headers: dict[str, str],
    start: datetime,
) -> list[dict[str, Any]]:
    guild_channels = fetch_guild_channels(headers)
    parent_channels = {
        str(channel["id"]): channel
        for channel in guild_channels
        if channel.get("type") in THREAD_PARENT_CHANNEL_TYPES
        and str(channel.get("id")) not in CONFIG.excluded_channel_ids
    }
    channels_to_scan: dict[str, dict[str, Any]] = {
        channel_id: channel
        for channel_id, channel in parent_channels.items()
        if channel.get("type") in MESSAGE_CHANNEL_TYPES
    }

    threads = fetch_active_threads(headers)
    for parent_channel_id in parent_channels:
        threads.extend(fetch_archived_public_threads(parent_channel_id, headers, start))

    for thread in threads:
        thread_id = str(thread.get("id", ""))
        parent_id = str(thread.get("parent_id", ""))
        if (
            thread_id
            and thread.get("type") in THREAD_CHANNEL_TYPES
            and thread_id not in CONFIG.excluded_channel_ids
            and parent_id in parent_channels
        ):
            channels_to_scan[thread_id] = thread

    return list(channels_to_scan.values())


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


def get_reaction_count_upper_bound(message: dict[str, Any]) -> int:
    return sum(max(0, int(reaction.get("count", 0))) for reaction in message.get("reactions", []))


def find_top_candidates(
    headers: dict[str, str],
    bot_user_id: str,
    start: datetime,
    end: datetime,
    limit: int | None = None,
) -> list[AwardCandidate]:
    candidate_limit = CONFIG.award_limit if limit is None else limit
    if candidate_limit <= 0:
        return []

    possible_candidates: list[CandidateMessage] = []
    scan_order = 0

    channels = fetch_channels_to_scan(headers, start)
    print(f"Discovered {len(channels)} readable message channels and threads.")

    for channel in channels:
        channel_id = str(channel["id"])
        channel_name = channel.get("name", channel_id)
        print(f"Scanning #{channel_name} ({channel_id})")

        for message in fetch_messages_for_channel(channel_id, headers, start, end):
            author = message.get("author", {})
            if str(author.get("id")) == bot_user_id:
                continue

            if not message.get("reactions"):
                continue

            reaction_upper_bound = get_reaction_count_upper_bound(message)
            if reaction_upper_bound <= 0:
                continue

            possible_candidates.append(
                CandidateMessage(
                    reaction_upper_bound=reaction_upper_bound,
                    scan_order=scan_order,
                    channel_id=channel_id,
                    message=message,
                )
            )
            scan_order += 1

    possible_candidates.sort(
        key=lambda candidate: (-candidate.reaction_upper_bound, candidate.scan_order)
    )
    verified_candidates: list[tuple[int, AwardCandidate]] = []

    print(
        f"Found {len(possible_candidates)} messages with reactions. "
        "Verifying only candidates that can still reach the ranking."
    )

    for possible_candidate in possible_candidates:
        if len(verified_candidates) >= candidate_limit:
            current_cutoff = sorted(
                (candidate.voter_count for _, candidate in verified_candidates),
                reverse=True,
            )[candidate_limit - 1]
            if possible_candidate.reaction_upper_bound < current_cutoff:
                break

        message = possible_candidate.message
        channel_id = possible_candidate.channel_id
        voter_count = count_unique_reaction_users(channel_id, message, headers, bot_user_id)
        if voter_count <= 0:
            continue

        author = message.get("author", {})
        candidate = AwardCandidate(
            voter_count=voter_count,
            message_id=str(message["id"]),
            channel_id=channel_id,
            author_id=str(author.get("id", "")),
            author_name=author.get("global_name") or author.get("username") or "unknown",
            content=message.get("content", ""),
        )
        verified_candidates.append((possible_candidate.scan_order, candidate))

    print(
        f"Verified exact reaction users for {len(verified_candidates)} "
        f"of {len(possible_candidates)} candidate messages."
    )

    verified_candidates.sort(key=lambda item: (-item[1].voter_count, item[0]))
    return [candidate for _, candidate in verified_candidates[:candidate_limit]]


def build_announcement(candidates: list[AwardCandidate]) -> str:
    if not candidates:
        return "🏆 本日のギュラ鯖リアクション賞🏆\n\n本日は対象メッセージがありませんでした。"

    rank_labels = ["🥇 1位", "🥈 2位", "🥉 3位", "4️⃣ 4位", "5️⃣ 5位"]
    lines = ["🏆 本日のギュラ鯖リアクション賞🏆"]

    for index, candidate in enumerate(candidates):
        preview = format_message_preview(candidate.content, CONFIG.message_preview_length)
        lines.extend(
            [
                "",
                rank_labels[index] if index < len(rank_labels) else f"{index + 1}位",
                f"投稿者: <@{candidate.author_id}>",
                f"リアクション人数: {candidate.voter_count}",
                "",
                f"「{preview}」",
                "",
                "元メッセージ:",
                candidate.link,
            ]
        )

    return "\n".join(lines)


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
    candidates = find_top_candidates(headers, bot_user_id, start, end)
    announcement = build_announcement(candidates)
    post_webhook(announcement)

    print("Announcement posted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
