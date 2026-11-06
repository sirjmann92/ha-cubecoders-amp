"""Two-factor (TOTP) login support for AMP panels that require 2FA.

cc-ampapi 1.1.2 has a 2FA option, but it never works: with use_2fa=True it
generates the code and then skips the Core/Login call entirely, and it insists
on the secret being wrapped in quote characters that it never strips. This
module replaces ampapi's Base._connect with a version that logs in properly.

Login order for each AMP target (the ADS controller and each proxied instance):
  1. a remember-me token from an earlier successful login, if we have one
  2. username + password + the current 6-digit TOTP code

Remember-me tokens mean a fresh 2FA code is rarely needed, which matters
because one refresh logs in to every instance and some AMP builds refuse to
accept the same 2FA code twice.

With no secret configured, the library's original login is used unchanged.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import time
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from ampapi import base as amp_base
from ampapi.dataclass import APISession, LoginResults
from pyotp import TOTP

_LOGGER = logging.getLogger(__name__)

TOTP_STEP = 30

_state: dict[str, Any] = {"secret": "", "last_code": None}
# AMP target id ("0" = ADS controller, otherwise an instance id) -> token
_remember_tokens: dict[str, str] = {}

_ORIGINAL_CONNECT = amp_base.Base._connect


class InvalidTotpSecret(ValueError):
    """The 2FA secret is not a usable base32 TOTP secret."""


def normalize_secret(raw: str | None) -> str:
    """Return a clean base32 secret, or "" when none was given.

    Accepts the bare secret (spaces/dashes allowed, any case, optional quotes)
    or a full otpauth://totp/...?secret=... link decoded from AMP's QR code.
    """
    value = (raw or "").strip().strip("'\"").strip()
    if not value:
        return ""
    if value.lower().startswith("otpauth://"):
        value = parse_qs(urlparse(value).query).get("secret", [""])[0]
    secret = value.replace(" ", "").replace("-", "").upper()
    if len(secret) < 16:
        msg = "2FA secret is too short; use the setup key, not a 6-digit code"
        raise InvalidTotpSecret(msg)
    try:
        base64.b32decode(secret + "=" * (-len(secret) % 8))
    except (binascii.Error, ValueError) as exception:
        msg = "2FA secret is not valid base32"
        raise InvalidTotpSecret(msg) from exception
    return secret


def set_secret(secret: str) -> None:
    """Set the (already normalized) secret used for every AMP login."""
    if secret != _state["secret"]:
        _remember_tokens.clear()
    _state["secret"] = secret


async def _fresh_code(secret: str) -> str:
    """Return the current TOTP code, never reusing the last code we sent.

    Waits for the next 30-second window only when the current code has
    already been used, so normal logins are never delayed.
    """
    code = TOTP(secret).now()
    if code == _state["last_code"]:
        wait = TOTP_STEP - (time.time() % TOTP_STEP) + 1
        _LOGGER.debug("2FA code already used; waiting %.0fs for the next one", wait)
        await asyncio.sleep(wait)
        code = TOTP(secret).now()
    _state["last_code"] = code
    return code


def _session_valid(self: amp_base.Base) -> bool:
    session = self._bridge._sessions.get(self.instance_id)
    if not isinstance(session, APISession) or session.id in ("", "0"):
        return False
    return (datetime.now() - session.ttl).total_seconds() <= self.session_ttl


async def _try_login(self: amp_base.Base, parameters: dict[str, Any]) -> LoginResults | None:
    try:
        result = await self._call_api(
            api="Core/Login",
            parameters=parameters,
            format_data=True,
            format_=LoginResults,
        )
    except Exception:  # a failed attempt falls through to the next one
        _LOGGER.debug("AMP login attempt raised", exc_info=True)
        return None
    if isinstance(result, LoginResults) and result.success and result.session_id:
        return result
    _LOGGER.debug(
        "AMP login attempt refused: %s",
        getattr(result, "result_reason", None) or result,
    )
    return None


async def _connect(self: amp_base.Base) -> LoginResults | None:
    """Replacement for ampapi's Base._connect with working 2FA."""
    secret = _state["secret"]
    if not secret:
        return await _ORIGINAL_CONNECT(self)
    if _session_valid(self):
        return None

    bridge = self._bridge
    target = self.instance_id
    result: LoginResults | None = None

    # 1. Remember-me tokens: this target's own, then the controller's.
    for key in dict.fromkeys((target, "0")):
        token = _remember_tokens.get(key)
        if not token:
            continue
        result = await _try_login(
            self,
            {"username": bridge.user, "password": "", "token": token, "rememberMe": True},
        )
        if result is not None:
            break
        if key == target:
            _remember_tokens.pop(key, None)

    # 2. Password + 2FA code; one retry with the next code if AMP refuses.
    if result is None:
        for _ in range(2):
            result = await _try_login(
                self,
                {
                    "username": bridge.user,
                    "password": bridge.password,
                    "token": await _fresh_code(secret),
                    "rememberMe": True,
                },
            )
            if result is not None:
                break

    if result is None:
        _LOGGER.warning(
            "AMP 2FA login failed for target %s; check the password, the 2FA "
            "secret, and that Home Assistant's clock is correct",
            target,
        )
        return None

    bridge._sessions[target] = APISession(id=result.session_id, ttl=datetime.now())
    if result.remember_me_token:
        _remember_tokens[target] = result.remember_me_token
    return result


def install() -> None:
    """Swap in the 2FA-aware login (idempotent)."""
    if amp_base.Base._connect is not _connect:
        amp_base.Base._connect = _connect


install()
