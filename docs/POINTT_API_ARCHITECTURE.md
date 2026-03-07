# POINTT API Architecture for Bosch EasyControl CT200

> **For user setup instructions, see the [main README](../README.md).**
> This document is for developers and advanced users who want to understand how the POINTT API integration works.

## Overview

The Bosch EasyControl CT200 thermostat does **not** expose hourly energy data via its local API. The local API (`/energy/history`) only returns **daily totals**. However, the Bosch mobile app shows real hourly energy data by using the **POINTT cloud API**.

This document describes the architecture for integrating POINTT API support into the Home Assistant Bosch custom component.

## The Problem

| Data Source | Endpoint | Granularity | Notes |
|-------------|----------|-------------|-------|
| Local API (EasyControl) | `/energy/history?entry=N` | **Daily only** | Returns `{"d": "DD-MM-YYYY", "eCH": kWh, "eHW": kWh}` |
| POINTT Cloud API | `/energy/historyHourly` | **Hourly** | Returns `{"d": "DD-MM-YYYY", "h": "0-23", "gCh": kWh, "gHw": kWh}` |

The current integration divides daily totals by 24 to create fake hourly values, which is useless for energy price correlation.

## POINTT API Details

### Base URL
```
https://pointt-api.bosch-thermotechnology.com/pointt-api/api/v1/gateways/{device_id}/resource
```

Where `device_id` is the Bosch serial number without dashes (e.g., `101021162`).

### Authentication

OAuth2 Authorization Code Flow with PKCE:
- **Token URL**: `https://singlekey-id.com/auth/connect/token`
- **Client ID**: `762162C0-FA2D-4540-AE66-6489F189FADC`
- **Redirect URI**: `com.bosch.tt.dashtt.pointt://app/login`
- **Scopes**: `openid email profile offline_access pointt.gateway.claiming pointt.gateway.removal pointt.gateway.list pointt.gateway.users pointt.gateway.resource.dashapp pointt.castt.flow.token-exchange bacon`

Tokens are obtained via browser login (SingleKey-ID) and can be refreshed automatically.

### Hourly Energy Endpoint

**Endpoint**: `/energy/historyHourly`

**Pagination**: Uses `?next=N` parameter. Each response includes a `next` value for the next page.

**Response Structure**:
```json
{
  "id": "/energy/historyHourly",
  "type": "energyRecordings",
  "value": [
    {
      "entries": [
        {
          "d": "05-03-2026",
          "h": "6",
          "T": 6.7,
          "gCh": 11.69,
          "gHw": 2.21
        }
      ],
      "next": 40
    }
  ]
}
```

**Fields**:
| Field | Description |
|-------|-------------|
| `d` | Date in `DD-MM-YYYY` format |
| `h` | Hour (0-23) |
| `T` | Outdoor temperature (°C) |
| `gCh` | Gas consumption for Central Heating (kWh) |
| `gHw` | Gas consumption for Hot Water (kWh) |

**Data Range**: Approximately 3 days of hourly data, updated in near real-time (slight delay from device sync to cloud).

### Pagination Flow

```
1. GET /energy/historyHourly
   → Returns entries for oldest data, next=40

2. GET /energy/historyHourly?next=40
   → Returns more entries, next=55

3. GET /energy/historyHourly?next=55
   → Returns more entries, next=70

... continues until `next` is empty (reached current hour)
```

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────────┐
│                     Home Assistant                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐     ┌──────────────────┐                  │
│  │   Config Flow    │────▶│  Options Flow    │                  │
│  │  (Initial Setup) │     │ (POINTT Toggle)  │                  │
│  └──────────────────┘     └────────┬─────────┘                  │
│                                    │                             │
│                                    ▼                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    BoschGatewayEntry                      │   │
│  │  - Manages local Bosch connection                         │   │
│  │  - Optionally initializes PointtEnergyClient              │   │
│  │  - Stores POINTT tokens in config entry                   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                      │
│            ┌──────────────┴──────────────┐                      │
│            ▼                              ▼                      │
│  ┌──────────────────┐          ┌──────────────────┐             │
│  │   Local Bosch    │          │ PointtEnergyClient│             │
│  │   API Client     │          │  (pointt_api.py) │             │
│  │                  │          │                  │             │
│  │ - Climate        │          │ - OAuth2 auth    │             │
│  │ - Sensors        │          │ - Token refresh  │             │
│  │ - Daily energy   │          │ - Hourly energy  │             │
│  └────────┬─────────┘          └────────┬─────────┘             │
│           │                              │                       │
│           ▼                              ▼                       │
│  ┌──────────────────┐          ┌──────────────────┐             │
│  │  Energy Sensors  │          │ External Stats   │             │
│  │  (entity state)  │          │ (HA Statistics)  │             │
│  └──────────────────┘          └──────────────────┘             │
│                                          │                       │
│                                          ▼                       │
│                                ┌──────────────────┐             │
│                                │ Energy Dashboard │             │
│                                └──────────────────┘             │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **On startup**: `BoschGatewayEntry` checks if POINTT is enabled and has valid tokens
2. **If enabled**: Creates `PointtEnergyClient` with stored tokens
3. **On update cycle** (every ~60s or configured interval):
   - Calls `get_hourly_energy()` which paginates through all available data
   - Parses entries into `[{"datetime": dt, "ch": kWh, "hw": kWh}, ...]`
   - Inserts data into HA statistics via `async_add_external_statistics()`
4. **Token refresh**: Automatic when access token expires (tokens valid ~1 hour)

### Files

| File | Purpose |
|------|---------|
| `pointt_api.py` | OAuth2 helpers + PointtEnergyClient class |
| `__init__.py` | BoschGatewayEntry with POINTT initialization |
| `config_flow.py` | Options flow for POINTT auth (callback URL or direct tokens) |
| `sensor/energy.py` | Energy sensors that optionally use POINTT data |
| `sensor/statistic_helper.py` | Helper for inserting external statistics |

### Authentication Flow (User Setup)

```
1. User enables "POINTT API" in integration options
2. User runs: ./scripts/run_playwright_ha.sh
3. Browser opens SingleKey-ID login page
4. User logs in with Bosch account
5. Script captures OAuth callback URL
6. User pastes callback URL into Home Assistant
7. Integration extracts code, exchanges for tokens
8. Tokens stored in config entry (encrypted by HA)
9. Integration starts fetching hourly data
```

## Statistics Behavior

### How Updates Work

Every update cycle, the integration:

1. **Fetches ALL available hourly data** (~3 days, following pagination)
2. **Converts to StatisticData** with datetime as the key
3. **Inserts via `async_add_external_statistics()`**

Home Assistant's external statistics are **keyed by datetime**. This means:

- **New hours**: Added to the database
- **Existing hours**: Updated/overwritten with latest values
- **Missing hours**: Filled in if the API provides them

### Implications

| Scenario | Behavior |
|----------|----------|
| First run | All ~3 days of hourly data inserted |
| Regular update | Last ~3 days refreshed, new hours added |
| After HA restart | Same - fetches all available, merges with existing |
| Data correction by Bosch | Automatically updated on next poll |
| Gap in polling (HA offline) | Filled in when polling resumes (up to 3 days) |

**Important**: Data older than ~3 days is NOT available from the POINTT API. If Home Assistant is offline for more than 3 days, that historical data is lost.

### Statistics vs Entity State

| Aspect | Entity State | External Statistics |
|--------|--------------|---------------------|
| Storage | HA state machine | Long-term statistics DB |
| History | Recorder (configurable retention) | Permanent |
| Energy Dashboard | Not usable directly | Required for Energy Dashboard |
| Value | Current/latest cumulative total | Hourly increments with timestamps |

The POINTT integration writes to **External Statistics** for Energy Dashboard compatibility.

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `experimental_pointt_api` | `false` | Enable POINTT cloud API for hourly energy |
| `pointt_access_token` | - | OAuth2 access token (auto-refreshed) |
| `pointt_refresh_token` | - | OAuth2 refresh token (long-lived) |
| `pointt_expires_at` | - | Token expiry timestamp |

## Scripts

### Prerequisites

```bash
# Install uv (Python package runner) - one time
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Playwright browser - one time
uv run --with playwright python -m playwright install chromium
```

### Available Scripts

| Script | Purpose |
|--------|---------|
| `scripts/run_playwright_ha.sh` | Automated OAuth login, outputs callback URL for HA |
| `scripts/run_playwright.sh` | Full OAuth flow, outputs both tokens and tests API |
| `scripts/pointt_oauth_manual.py` | Manual OAuth flow (for debugging) |

### How the OAuth Scripts Work

1. **Playwright** launches a Chromium browser with stealth mode (bypasses bot detection)
2. User logs in to Bosch SingleKey-ID
3. Script intercepts the OAuth callback redirect (custom `com.bosch.tt.dashtt.pointt://` scheme)
4. For `--ha` mode: prints the callback URL for pasting into Home Assistant
5. For full mode: exchanges the code for tokens and tests the API

## Limitations

1. **Cloud dependency**: Requires internet connection to Bosch cloud
2. **3-day window**: Only ~3 days of hourly history available
3. **Slight delay**: Data syncs from device to cloud, may be minutes behind
4. **OAuth complexity**: Requires browser-based login (bot detection)
5. **Token management**: Refresh tokens may expire after extended periods

## Future Improvements

- [ ] Automatic re-authentication when refresh token expires
- [ ] Configurable poll interval for POINTT data
- [ ] Separate sensors for POINTT data (vs modifying existing energy sensors)
- [ ] Support for other Bosch devices that use POINTT API

---

## GitHub Issue Template

Use this template when reporting POINTT API issues:

```markdown
### Device Information
- **Device**: Bosch EasyControl CT200 / Buderus TC100.2
- **Serial**: (first 4 digits only)
- **HA Version**:
- **Integration Version**:

### Issue Description
<!-- Describe what's happening -->

### Expected Behavior
<!-- What should happen -->

### Debug Logs
<!-- Enable debug logging and paste relevant logs -->
```yaml
logger:
  logs:
    custom_components.bosch: debug
    custom_components.bosch.pointt_api: debug
```

### Steps to Reproduce
1.
2.
3.

### Additional Context
<!-- Screenshots, debug scan output, etc. -->
```
