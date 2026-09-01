from unittest.mock import MagicMock

import discord

from src.adapters.discord_bot.actor_extractor import (
    get_actor_from_interaction,
    get_actor_from_member,
)
from src.domain.models import Actor


def test_get_actor_from_member_basic():
    member = MagicMock(spec=discord.Member)
    member.id = 12345
    member.roles = []
    perms = MagicMock()
    perms.administrator = False
    perms.manage_guild = False
    member.guild_permissions = perms

    actor = get_actor_from_member(member)
    assert isinstance(actor, Actor)
    assert actor.user_id == 12345
    assert actor.role_ids == frozenset()
    assert actor.is_admin is False


def test_get_actor_from_member_with_roles_and_admin():
    member = MagicMock(spec=discord.Member)
    member.id = 99999

    r1 = MagicMock(spec=discord.Role)
    r1.id = 101
    r2 = MagicMock(spec=discord.Role)
    r2.id = 202
    member.roles = [r1, r2]

    perms = MagicMock()
    perms.administrator = True
    perms.manage_guild = False
    member.guild_permissions = perms

    actor = get_actor_from_member(member)
    assert actor.user_id == 99999
    assert actor.role_ids == frozenset({101, 202})
    assert actor.is_admin is True


def test_get_actor_from_interaction():
    interaction = MagicMock(spec=discord.Interaction)
    member = MagicMock(spec=discord.Member)
    member.id = 777
    r = MagicMock(spec=discord.Role)
    r.id = 555
    member.roles = [r]
    perms = MagicMock()
    perms.administrator = False
    perms.manage_guild = True
    member.guild_permissions = perms

    interaction.user = member
    interaction.guild = None

    actor = get_actor_from_interaction(interaction)
    assert actor.user_id == 777
    assert 555 in actor.role_ids
    assert actor.is_admin is True
