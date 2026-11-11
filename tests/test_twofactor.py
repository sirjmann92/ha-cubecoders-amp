"""Two-factor login: secret parsing and the replacement ampapi login flow."""

import time
from datetime import datetime

import pyotp
import pytest
from ampapi import Bridge, Core
from ampapi.dataclass import APIParams, LoginResults

from custom_components.cubecoders import twofactor

PASSWORD = "hunter2"
SECRET = pyotp.random_base32()


# ------------------------------------------------------------ secret parsing


@pytest.mark.parametrize(
    "raw",
    [
        SECRET,
        " ".join(SECRET[i : i + 4] for i in range(0, len(SECRET), 4)).lower(),
        f'"{SECRET}"',
        pyotp.TOTP(SECRET).provisioning_uri(name="homeassistant", issuer_name="AMP"),
    ],
    ids=["plain", "spaced-lowercase", "quoted", "otpauth-link"],
)
def test_normalize_secret_accepts(raw: str) -> None:
    """Setup keys in the forms people actually paste are accepted."""
    assert twofactor.normalize_secret(raw) == SECRET


def test_normalize_secret_empty_means_no_2fa() -> None:
    """A blank field disables 2FA."""
    assert twofactor.normalize_secret("  ") == ""
    assert twofactor.normalize_secret(None) == ""


@pytest.mark.parametrize("raw", ["123456", "not!base32!at!all!!"])
def test_normalize_secret_rejects(raw: str) -> None:
    """A 6-digit code or junk is rejected with a clear error."""
    with pytest.raises(twofactor.InvalidTotpSecret):
        twofactor.normalize_secret(raw)


# ------------------------------------------------------------ login flow


class FakeAMP:
    """Stands in for ampapi's HTTP layer (Base._call_api)."""

    def __init__(self, *, reject_reused: bool = False) -> None:
        self.reject_reused = reject_reused
        self.used_codes: set[str] = set()
        self.sessions: set[str] = set()
        self.remember: set[str] = set()
        self.log: list[str] = []

    async def call_api(self, api_self, api, parameters=None, **_kwargs):
        if api == "Core/Login":
            return self._login(parameters)
        session = api_self._bridge._sessions.get(api_self.instance_id)
        if session is None or session.id not in self.sessions:
            raise PermissionError("Unauthorized Access")
        return {"ok": True}

    def _login(self, body: dict) -> LoginResults:
        token, password = body.get("token"), body.get("password")
        if password == "" and token in self.remember:
            kind, ok = "remember", True
        elif password == PASSWORD and token == pyotp.TOTP(SECRET).now():
            kind = "totp"
            ok = not (self.reject_reused and token in self.used_codes)
            self.used_codes.add(token)
        else:
            kind, ok = "bad", False
        self.log.append(kind if ok else f"{kind}-rejected")
        if not ok:
            return LoginResults(success=False, result=0, result_reason="nope")
        session_id, remember = f"S{len(self.sessions)}", f"R{len(self.remember)}"
        self.sessions.add(session_id)
        self.remember.add(remember)
        return LoginResults(
            success=True, result=10, session_id=session_id, remember_me_token=remember
        )


@pytest.fixture
def amp(monkeypatch):
    """A fresh fake AMP panel with ampapi wired to it and 2FA enabled."""

    def make(secret: str = SECRET, **kwargs) -> FakeAMP:
        fake = FakeAMP(**kwargs)

        async def fake_call_api(self, api, parameters=None, **kw):
            return await fake.call_api(self, api, parameters, **kw)

        monkeypatch.setattr("ampapi.base.Base._call_api", fake_call_api)
        bridge = Bridge(
            api_params=APIParams(url="http://amp:8080", user="ha", password=PASSWORD)
        )
        bridge._sessions.clear()
        twofactor._remember_tokens.clear()
        twofactor._state["last_code"] = None
        twofactor.set_secret(secret)
        return fake

    yield make
    twofactor.set_secret("")


async def test_login_with_code_then_session_then_remember_token(amp) -> None:
    """First login uses the 2FA code; later ones reuse the session or token."""
    fake = amp()
    core = Core()

    assert await core.call_end_point("Core/GetStatus") == {"ok": True}
    assert fake.log == ["totp"]

    await core.call_end_point("Core/GetStatus")
    assert fake.log == ["totp"]  # valid session reused

    core._bridge._sessions["0"].ttl = datetime(2000, 1, 1)
    await core.call_end_point("Core/GetStatus")
    assert fake.log == ["totp", "remember"]  # no new 2FA code needed


async def test_reused_code_waits_for_next(amp, monkeypatch) -> None:
    """If AMP refuses an already-used code, wait for the next one and retry."""
    fake = amp(reject_reused=True)
    current = pyotp.TOTP(SECRET).now()
    fake.used_codes.add(current)
    following = pyotp.TOTP(SECRET).at(int(time.time()) + 30)

    # login try 1, AMP's check, retry (same code -> wait), after wait, AMP's check
    codes = iter([current, current, current, following, following])
    monkeypatch.setattr(pyotp.TOTP, "now", lambda _self: next(codes, following))
    waits: list[float] = []

    async def no_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(twofactor.asyncio, "sleep", no_sleep)

    assert await Core().call_end_point("Core/GetStatus") == {"ok": True}
    assert fake.log == ["totp-rejected", "totp"]
    assert len(waits) == 1


async def test_wrong_secret_is_an_auth_failure(amp) -> None:
    """A wrong secret surfaces as PermissionError (Invalid authentication in HA)."""
    fake = amp(secret=pyotp.random_base32())
    with pytest.raises(PermissionError):
        await Core().call_end_point("Core/GetStatus")
    assert fake.log == ["bad-rejected", "bad-rejected"]


async def test_no_secret_uses_library_login(amp, monkeypatch) -> None:
    """With no secret configured, ampapi's own login runs unchanged."""
    amp(secret="")
    called = []

    async def original(_self):
        called.append(True)

    monkeypatch.setattr(twofactor, "_ORIGINAL_CONNECT", original)
    await twofactor._connect(Core())
    assert called == [True]
