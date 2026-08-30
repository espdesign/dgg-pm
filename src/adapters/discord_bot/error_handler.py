"""Centralized error handling and translation helper for the Discord bot UI layer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from src.domain.exceptions import DggPmError, StaleVersionError

if TYPE_CHECKING:
    pass

logger = logging.getLogger("dgg_pm.adapters.discord_bot.error_handler")


def translate_error(error: Exception, action_description: str) -> tuple[str, bool]:
    """Translates an exception into a user-friendly Discord message.

    Returns:
        tuple[str, bool]: (message_text, is_unexpected_error)
    """
    if isinstance(error, StaleVersionError):
        return (
            "⚠️ This task was already modified by another user. Please refresh the card and try again.",
            False,
        )
    if isinstance(error, (DggPmError, ValueError)):
        return (f"❌ {error}", False)
    if isinstance(error, discord.Forbidden):
        return (
            "❌ The bot lacks required Discord permissions in this channel or server "
            "(e.g., manage threads, send messages, manage roles).",
            False,
        )
    if isinstance(error, discord.HTTPException):
        return ("❌ A Discord API error occurred while processing your request. Please try again.", False)

    # Unknown exception: sanitize error message so internal concerns, traces, or queries do not leak to UI
    return (
        f"❌ An unexpected error occurred while {action_description}. Please try again later.",
        True,
    )


async def send_interaction_error(
    interaction: discord.Interaction,
    error: Exception,
    action_description: str,
    target_logger: logging.Logger | None = None,
    *,
    ephemeral: bool = True,
) -> str:
    """Logs the exception appropriately and sends a safe, user-friendly message to Discord.

    - Known exceptions (StaleVersionError, DomainError, ValueError, discord.Forbidden) are logged
      at DEBUG/WARNING and translated to helpful user text.
    - Unknown exceptions are logged with a full stack trace via logger.exception() and
      translated to a safe generic message that prevents internal concerns leaking to the UI.
    """
    log = target_logger or logger
    message, is_unexpected = translate_error(error, action_description)

    if is_unexpected:
        log.exception("Unexpected error while %s: %s", action_description, error)
    elif isinstance(error, (discord.Forbidden, discord.HTTPException)):
        log.warning("Discord API error while %s: %s", action_description, error)
    else:
        log.debug("Known business error while %s: %s", action_description, error)

    try:
        is_done = False
        if hasattr(interaction, "response"):
            resp = interaction.response
            if callable(getattr(resp, "is_done", None)):
                done_res = resp.is_done()
                if isinstance(done_res, bool):
                    is_done = done_res
                elif getattr(getattr(resp, "defer", None), "called", False) or getattr(
                    getattr(resp, "send_message", None), "called", False
                ):
                    is_done = True

        if is_done and hasattr(interaction, "followup") and callable(getattr(interaction.followup, "send", None)):
            res = interaction.followup.send(message, ephemeral=ephemeral)
            if hasattr(res, "__await__"):
                await res
        elif hasattr(interaction, "response") and callable(getattr(interaction.response, "send_message", None)):
            res = interaction.response.send_message(message, ephemeral=ephemeral)
            if hasattr(res, "__await__"):
                await res
    except Exception as send_err:
        log.exception("Failed to send error response to Discord interaction: %s", send_err)

    return message
