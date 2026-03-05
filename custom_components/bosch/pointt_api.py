"""POINTT API client for Bosch EasyControl hourly energy data (Experimental).

Uses OAuth2 authorization code flow with PKCE (same as Bosch mobile app).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import urllib.parse
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlencode

import aiohttp

_LOGGER = logging.getLogger(__name__)

# OAuth constants (from ha_bosch / Bosch mobile app)
TOKEN_URL = "https://singlekey-id.com/auth/connect/token"
CLIENT_ID = "762162C0-FA2D-4540-AE66-6489F189FADC"
REDIRECT_URI = "com.bosch.tt.dashtt.pointt://app/login"
CODE_VERIFIER = "abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklm"
SCOPES = [
    "openid", "email", "profile", "offline_access",
    "pointt.gateway.claiming", "pointt.gateway.removal",
    "pointt.gateway.list", "pointt.gateway.users",
    "pointt.gateway.resource.dashapp",
    "pointt.castt.flow.token-exchange", "bacon",
]

POINTTAPI_BASE = "https://pointt-api.bosch-thermotechnology.com/pointt-api/api/v1/gateways/"


class PointtAuthError(Exception):
    """POINTT authentication error."""
    pass


def build_auth_url() -> str:
    """Build the OAuth authorization URL for user login."""
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(CODE_VERIFIER.encode()).digest()
    ).decode().rstrip("=")

    params = {
        "redirect_uri": urllib.parse.quote_plus(REDIRECT_URI),
        "client_id": CLIENT_ID,
        "response_type": "code",
        "prompt": "login",
        "state": "_yUmSV3AjUTXfn6DSZQZ-g",
        "nonce": "5iiIvx5_9goDrYwxxUEorQ",
        "scope": urllib.parse.quote(" ".join(SCOPES)),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "style_id": "tt_bsch",
        "suppressed_prompt": "login",
    }
    query = unquote(urlencode(params))
    encoded_query = urllib.parse.quote(query)
    return_url = urllib.parse.quote_plus("/auth/connect/authorize/callback?")
    return f"https://singlekey-id.com/auth/en-us/login?ReturnUrl={return_url}{encoded_query}"


def extract_code_from_callback(url: str) -> str | None:
    """Extract authorization code from callback URL."""
    if not url or "code=" not in url:
        return None
    try:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        codes = params.get("code", [])
        return codes[0] if codes else None
    except Exception:
        return None


async def exchange_code_for_tokens(session: aiohttp.ClientSession, code: str) -> dict:
    """Exchange authorization code for access/refresh tokens."""
    data = {
        "grant_type": "authorization_code",
        "scope": " ".join(SCOPES),
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "code_verifier": CODE_VERIFIER,
    }

    async with session.post(TOKEN_URL, data=data) as resp:
        if resp.status != 200:
            body = await resp.text()
            _LOGGER.error("Token exchange failed: %s - %s", resp.status, body[:200])
            raise PointtAuthError(f"Token exchange failed: {resp.status}")

        result = await resp.json()

    if "access_token" not in result:
        raise PointtAuthError("No access_token in response")

    expires_in = result.get("expires_in", 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    return {
        "access_token": result["access_token"],
        "refresh_token": result.get("refresh_token", ""),
        "expires_at": expires_at.isoformat(),
    }


async def refresh_access_token(session: aiohttp.ClientSession, refresh_token: str) -> dict:
    """Refresh the access token."""
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": " ".join(SCOPES),
        "client_id": CLIENT_ID,
    }

    async with session.post(TOKEN_URL, data=data) as resp:
        if resp.status != 200:
            _LOGGER.warning("Token refresh failed: %s", resp.status)
            raise PointtAuthError("Token refresh failed")

        result = await resp.json()

    if "access_token" not in result:
        raise PointtAuthError("No access_token in refresh response")

    expires_in = result.get("expires_in", 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    return {
        "access_token": result["access_token"],
        "refresh_token": result.get("refresh_token", refresh_token),
        "expires_at": expires_at.isoformat(),
    }


def is_token_expired(expires_at: str | None, margin_seconds: int = 300) -> bool:
    """Check if token is expired or within margin of expiry."""
    if not expires_at:
        return True
    try:
        expiry = datetime.fromisoformat(expires_at)
        return datetime.now(timezone.utc) >= (expiry - timedelta(seconds=margin_seconds))
    except (TypeError, ValueError):
        return True


class PointtEnergyClient:
    """POINTT API client for fetching hourly energy data."""

    def __init__(
        self,
        device_id: str,
        session: aiohttp.ClientSession,
        token_data: dict,
        token_update_callback=None,
    ) -> None:
        """Initialize client.

        Args:
            device_id: Gateway serial number (without dashes)
            session: aiohttp session
            token_data: Dict with access_token, refresh_token, expires_at
            token_update_callback: Called with new token_data when refreshed
        """
        self._device_id = device_id
        self._session = session
        self._token_data = token_data
        self._token_update_callback = token_update_callback
        self._base_url = f"{POINTTAPI_BASE}{device_id}/resource/"

    async def _ensure_token(self) -> str:
        """Ensure we have a valid token, refresh if needed."""
        if is_token_expired(self._token_data.get("expires_at")):
            refresh_token = self._token_data.get("refresh_token")
            if not refresh_token:
                raise PointtAuthError("No refresh token available")

            _LOGGER.debug("POINTT: Refreshing access token...")
            new_tokens = await refresh_access_token(self._session, refresh_token)
            self._token_data = new_tokens

            if self._token_update_callback:
                await self._token_update_callback(new_tokens)

        return self._token_data.get("access_token", "")

    async def _get(self, path: str) -> dict | list | str:
        """Make authenticated GET request."""
        token = await self._ensure_token()
        url = self._base_url + path.lstrip("/")
        headers = {"Authorization": f"Bearer {token}"}

        async with self._session.get(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            if resp.status in (401, 403):
                raise PointtAuthError(f"Auth failed: {resp.status}")
            if resp.status != 200:
                body = await resp.text()
                _LOGGER.debug("POINTT GET %s failed: %s - %s", path, resp.status, body[:200])
                return {}

            content_type = resp.content_type or ""
            if "application/json" in content_type:
                return await resp.json()
            return await resp.text()

    async def get_hourly_energy(self, days: int = 3) -> list[dict]:
        """Get energy data from POINTT API.

        Note: The POINTT /energy/history endpoint returns DAILY data, not hourly.
        Format: [{"d": "DD-MM-YYYY", "T": temp, "gCh": kWh, "gHw": kWh}, ...]

        Returns list of:
        [{"datetime": datetime, "ch": kWh, "hw": kWh}, ...]
        """
        try:
            # Try to get energy history
            data = await self._get("/energy/history")
            _LOGGER.debug("POINTT energy/history response type: %s", type(data))

            if isinstance(data, list):
                return self._parse_energy_data(data)
            elif isinstance(data, dict):
                # POINTT returns: {"id": "/energy/history", "value": [...]}
                if "value" in data:
                    return self._parse_energy_data(data["value"])
                if "entries" in data:
                    return self._parse_energy_data(data["entries"])
                if "history" in data:
                    return self._parse_energy_data(data["history"])

            _LOGGER.warning("POINTT: Unexpected energy data format: %s", str(data)[:200])
            return []

        except Exception as err:
            _LOGGER.error("POINTT: Failed to fetch energy data: %s", err)
            return []

    def _parse_energy_data(self, data: list) -> list[dict]:
        """Parse energy data from API response.

        POINTT API returns daily data in format:
        [{"d": "08-11-2022", "T": 14.8, "gCh": 4.05, "gHw": 0.0}, ...]
        """
        result = []

        for entry in data:
            try:
                # Try various date formats
                dt = None
                for key in ["datetime", "timestamp", "date", "d", "time"]:
                    if key in entry and entry[key]:
                        val = entry[key]
                        if isinstance(val, str):
                            # Try parsing with various formats
                            for fmt in [
                                "%d-%m-%Y",  # POINTT format: "08-11-2022"
                                "%Y-%m-%dT%H:%M:%S%z",
                                "%Y-%m-%dT%H:%M:%SZ",
                                "%Y-%m-%dT%H:%M:%S",
                                "%Y-%m-%d %H:%M:%S",
                                "%Y-%m-%d",
                            ]:
                                try:
                                    dt = datetime.strptime(val, fmt)
                                    break
                                except ValueError:
                                    continue
                        elif isinstance(val, (int, float)):
                            dt = datetime.fromtimestamp(val, tz=timezone.utc)
                        if dt:
                            break

                if not dt:
                    _LOGGER.debug("POINTT: Could not parse date from entry: %s", entry)
                    continue

                # Ensure datetime is timezone-aware (UTC)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)

                # Get energy values (gCh = gas central heating, gHw = gas hot water)
                ch = 0
                hw = 0
                for ch_key in ["gCh", "ch", "eCH", "centralHeating", "heating", "gasHeating"]:
                    if ch_key in entry and entry[ch_key] is not None:
                        ch = float(entry[ch_key])
                        break
                for hw_key in ["gHw", "hw", "eHW", "hotWater", "water", "gasHotWater"]:
                    if hw_key in entry and entry[hw_key] is not None:
                        hw = float(entry[hw_key])
                        break

                result.append({"datetime": dt, "ch": ch, "hw": hw})

            except (ValueError, KeyError, TypeError) as err:
                _LOGGER.debug("POINTT: Error parsing entry %s: %s", entry, err)
                continue

        _LOGGER.info("POINTT: Parsed %d energy entries", len(result))
        return result
