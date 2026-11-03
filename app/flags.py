"""Feature flags, served by Cloudflare Flagship through OpenFeature.

When the three FLAGSHIP_* environment variables are set, flags are evaluated by
Cloudflare Flagship. When they are not (local dev, tests, CI), OpenFeature's
built-in no-op provider is used and every flag returns its safe default below,
so the app always runs.
"""

import logging
import os

from openfeature import api
from openfeature.evaluation_context import EvaluationContext

log = logging.getLogger(__name__)

# Flag keys, kept in one place so code and scripts/create_flags.sh agree.
NEW_HOMEPAGE = "new-homepage"  # boolean: show the redesigned homepage
NOTES_API = "notes-api"  # boolean: kill switch for the notes API
MAX_NOTE_LENGTH = "max-note-length"  # number: max characters per note

# Safe defaults, used if Flagship is unreachable or not configured.
DEFAULTS = {
    NEW_HOMEPAGE: False,
    NOTES_API: True,
    MAX_NOTE_LENGTH: 500,
}


def init_flags() -> str:
    """Register the Flagship provider if configured. Returns the provider in use."""
    app_id = os.getenv("FLAGSHIP_APP_ID")
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    token = os.getenv("FLAGSHIP_API_TOKEN")
    if not (app_id and account_id and token):
        log.warning("Flagship not configured - feature flags will use their defaults.")
        return "defaults"

    from flagship import FlagshipServerProvider

    api.set_provider(
        FlagshipServerProvider(
            app_id=app_id,
            account_id=account_id,
            auth_token=token,
            timeout=2.0,
            # Re-use results for 30s so each request doesn't call Cloudflare.
            cache_ttl=float(os.getenv("FLAGSHIP_CACHE_TTL", "30")),
        )
    )
    return "flagship"


def context_for(user_id: str | None, plan: str | None = None) -> EvaluationContext:
    """Who the flag is being evaluated for. user_id keeps percentage rollouts sticky."""
    attrs = {"plan": plan} if plan else {}
    return EvaluationContext(targeting_key=user_id or "anonymous", attributes=attrs)


def is_on(key: str, ctx: EvaluationContext) -> bool:
    return api.get_client().get_boolean_value(key, DEFAULTS[key], ctx)


def number(key: str, ctx: EvaluationContext) -> int:
    return api.get_client().get_integer_value(key, DEFAULTS[key], ctx)


def snapshot(ctx: EvaluationContext) -> dict:
    """Current value of every flag for this user - handy for debugging."""
    return {
        NEW_HOMEPAGE: is_on(NEW_HOMEPAGE, ctx),
        NOTES_API: is_on(NOTES_API, ctx),
        MAX_NOTE_LENGTH: number(MAX_NOTE_LENGTH, ctx),
    }
