"""POINTT API client for Bosch EasyControl hourly energy data (Experimental).

Uses OAuth2 authorization code flow with PKCE (same as Bosch mobile app).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import urllib.parse
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlencode

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

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
            body = await resp.text()
            _LOGGER.warning("Token refresh failed: %s - %s", resp.status, body[:200])
            raise PointtAuthError(f"Token refresh failed: {resp.status}")

        result = await resp.json()

    if "access_token" not in result:
        raise PointtAuthError("No access_token in refresh response")

    expires_in = result.get("expires_in", 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    _LOGGER.debug("Token refreshed successfully, expires in %ds", expires_in)

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


ISSUE_ID_POINTT_AUTH = "pointt_auth_failed"


def create_pointt_auth_issue(hass: HomeAssistant, device_id: str) -> None:
    """Create a repair issue for POINTT authentication failure."""
    _LOGGER.warning("POINTT: Creating repair issue for auth failure (device: %s)", device_id)
    ir.async_create_issue(
        hass,
        "bosch",
        f"{ISSUE_ID_POINTT_AUTH}_{device_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="pointt_auth_failed",
        translation_placeholders={"device_id": device_id},
    )


def clear_pointt_auth_issue(hass: HomeAssistant, device_id: str) -> None:
    """Clear the POINTT authentication repair issue."""
    ir.async_delete_issue(hass, "bosch", f"{ISSUE_ID_POINTT_AUTH}_{device_id}")


class PointtEnergyClient:
    """POINTT API client for fetching hourly energy data."""

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        session: aiohttp.ClientSession,
        token_data: dict,
        token_update_callback=None,
    ) -> None:
        """Initialize client.

        Args:
            hass: Home Assistant instance
            device_id: Gateway serial number (without dashes)
            session: aiohttp session
            token_data: Dict with access_token, refresh_token, expires_at
            token_update_callback: Called with new token_data when refreshed
        """
        self._hass = hass
        self._device_id = device_id
        self._session = session
        self._token_data = token_data
        self._token_update_callback = token_update_callback
        self._base_url = f"{POINTTAPI_BASE}{device_id}/resource/"
        # Cache to avoid duplicate API calls from multiple sensors
        self._cache: list[dict] = []
        self._cache_time: datetime | None = None
        self._cache_ttl = timedelta(minutes=5)
        # Lock to prevent concurrent token refresh and API calls
        self._fetch_lock = asyncio.Lock()
        # Track auth failure state
        self._auth_failed = False

    async def _ensure_token(self) -> str:
        """Ensure we have a valid token, refresh if needed."""
        # Skip if auth has already failed (prevents duplicate refresh attempts)
        if self._auth_failed:
            raise PointtAuthError("Auth previously failed, re-authentication required")

        if is_token_expired(self._token_data.get("expires_at")):
            refresh_token = self._token_data.get("refresh_token")
            if not refresh_token:
                self._auth_failed = True
                create_pointt_auth_issue(self._hass, self._device_id)
                raise PointtAuthError("No refresh token available")

            _LOGGER.debug("POINTT: Refreshing access token...")
            try:
                new_tokens = await refresh_access_token(self._session, refresh_token)
                self._token_data = new_tokens

                if self._token_update_callback:
                    await self._token_update_callback(new_tokens)

                # Clear any previous auth failure
                if self._auth_failed:
                    self._auth_failed = False
                    clear_pointt_auth_issue(self._hass, self._device_id)

            except PointtAuthError:
                self._auth_failed = True
                create_pointt_auth_issue(self._hass, self._device_id)
                raise

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
        """Get HOURLY energy data from POINTT API.

        Uses /energy/historyHourly endpoint with pagination (via ?next=N).
        Returns real hourly data up to the current hour.
        Results are cached for 5 minutes to avoid duplicate API calls.

        Returns list of:
        [{"datetime": datetime, "ch": kWh, "hw": kWh}, ...]
        """
        # Use lock to prevent concurrent fetches (avoids duplicate token refresh)
        async with self._fetch_lock:
            # Return cached data if still valid
            now = datetime.now(timezone.utc)
            if self._cache and self._cache_time and (now - self._cache_time) < self._cache_ttl:
                _LOGGER.debug("POINTT: Returning cached data (%d entries)", len(self._cache))
                return self._cache

            all_entries = []
            next_page = None
            page = 0
            max_pages = 20  # Safety limit

            try:
                while page < max_pages:
                    page += 1

                    # Build URL with pagination
                    if next_page:
                        path = f"/energy/historyHourly?next={next_page}"
                    else:
                        path = "/energy/historyHourly"

                    data = await self._get(path)

                    if not isinstance(data, dict):
                        _LOGGER.warning("POINTT: Unexpected response type: %s", type(data))
                        break

                    # Structure: {"value": [{"entries": [...], "next": N}]}
                    value = data.get("value", [])
                    if not value or not isinstance(value, list):
                        break

                    first_block = value[0] if value else {}
                    entries = first_block.get("entries", [])

                    if entries:
                        all_entries.extend(entries)

                    # Check for next page
                    next_page = first_block.get("next")
                    if not next_page:
                        break

                if not all_entries:
                    _LOGGER.warning("POINTT: No entries in historyHourly")
                    return []

                result = self._parse_hourly_data(all_entries)

                if result:
                    oldest = min(e["datetime"] for e in result)
                    latest = max(e["datetime"] for e in result)
                    _LOGGER.info("POINTT: Got %d hourly entries from %s to %s", len(result), oldest, latest)

                    # Cache the result
                    self._cache = result
                    self._cache_time = datetime.now(timezone.utc)

                return result

            except Exception as err:
                _LOGGER.error("POINTT: Failed to fetch hourly energy data: %s", err)
                return []

    def _parse_hourly_data(self, entries: list) -> list[dict]:
        """Parse hourly energy data from historyHourly endpoint.

        Input format: [{"d": "02-03-2026", "h": "14", "T": 8.9, "gCh": 0.56, "gHw": 0.15}, ...]
        """
        result = []

        for entry in entries:
            try:
                date_str = entry.get("d")  # "DD-MM-YYYY"
                hour_str = entry.get("h")  # "0" to "23"

                if not date_str or hour_str is None:
                    continue

                # Parse date and hour
                dt = datetime.strptime(f"{date_str} {hour_str}", "%d-%m-%Y %H")
                dt = dt.replace(tzinfo=timezone.utc)

                # Get energy values
                ch = float(entry.get("gCh", 0) or 0)
                hw = float(entry.get("gHw", 0) or 0)

                result.append({"datetime": dt, "ch": ch, "hw": hw})

            except (ValueError, KeyError, TypeError) as err:
                _LOGGER.debug("POINTT: Error parsing hourly entry %s: %s", entry, err)
                continue

        _LOGGER.info("POINTT: Parsed %d hourly energy entries", len(result))
        return result
