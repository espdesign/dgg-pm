from __future__ import annotations

from typing import Any

import discord

from src.domain.models import Actor


def get_actor_from_member(
    user: discord.Member | discord.User | Any,
    guild: discord.Guild | None = None,
) -> Actor:
    """Extracts an Actor value object from a Discord Member, User, or mock object."""
    user_id = getattr(user, "id", 0)
    is_admin = False
    role_ids: set[int] = set()

    # 1. Guild permissions / administrator check
    perms = getattr(user, "guild_permissions", None)
    if perms is not None:
        admin = getattr(perms, "administrator", False)
        manage_guild = getattr(perms, "manage_guild", False)
        is_admin = bool(admin or manage_guild)

    # 2. Roles extraction
    roles = getattr(user, "roles", None)
    if roles:
        role_ids = {r.id for r in roles if hasattr(r, "id")}
    elif guild and hasattr(guild, "get_member"):
        member = guild.get_member(user_id)
        if member and hasattr(member, "roles"):
            role_ids = {r.id for r in member.roles if hasattr(r, "id")}
            member_perms = getattr(member, "guild_permissions", None)
            if member_perms:
                is_admin = bool(
                    getattr(member_perms, "administrator", False) or getattr(member_perms, "manage_guild", False)
                )

    return Actor(
        user_id=user_id,
        role_ids=frozenset(role_ids),
        is_admin=is_admin,
    )


def get_actor_from_interaction(interaction: discord.Interaction) -> Actor:
    """Extracts an Actor value object from a Discord Interaction."""
    return get_actor_from_member(interaction.user, guild=interaction.guild)
