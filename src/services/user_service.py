from __future__ import annotations

import logging

from src.domain.enums import NotificationPreference
from src.domain.models import UserPreference
from src.ports.repositories import IUserPreferenceRepo

logger = logging.getLogger("dgg_pm.services.user")


class UserService:
    """Application service for managing user preferences and personal notification settings."""

    def __init__(self, user_pref_repo: IUserPreferenceRepo):
        self.repo = user_pref_repo

    async def get_preference(self, guild_id: int, user_discord_id: int) -> NotificationPreference:
        """Retrieves user notification preference, defaulting to DM if unset."""
        pref = await self.repo.get_preference(guild_id, user_discord_id)
        if not pref:
            return NotificationPreference.DM
        return pref.notify_preference

    async def set_preference(
        self,
        guild_id: int,
        user_discord_id: int,
        notify_preference: NotificationPreference,
    ) -> UserPreference:
        """Persists updated user notification preference."""
        logger.info(
            "Setting notification preference for user %s in guild %s to %s",
            user_discord_id,
            guild_id,
            notify_preference,
        )
        return await self.repo.set_preference(guild_id, user_discord_id, notify_preference)

    async def get_preferences_bulk(
        self,
        guild_id: int,
        user_ids: list[int],
    ) -> dict[int, NotificationPreference]:
        """Fetches preferences for multiple users in a guild (e.g. for batch notification routing)."""
        return await self.repo.get_preferences_bulk(guild_id, user_ids)
