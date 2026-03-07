# Bosch Thermostat Custom Component for Home Assistant

Home Assistant custom component for Bosch thermostats with **real hourly energy data** support for EasyControl CT200 via POINTT cloud API.

**Latest version requires Home Assistant 2025.7+ and Python >= 3.12.**

## Supported Devices

| Device Type | Protocol | Energy Data |
|-------------|----------|-------------|
| **EasyControl CT200** | XMPP (cloud) | Hourly via POINTT API |
| **Buderus Logamatic TC100.2** | XMPP (cloud) | Hourly via POINTT API |
| IVT RC300/RC200/RC35/RC30/RC20 | HTTP (local) or XMPP | Hourly via local API |
| NEFIT/Junkers CT100 | XMPP (cloud) | Daily only |

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations**
3. Click the three dots menu (top right) → **Custom repositories**
4. Add this repository URL and select **Integration** as the category
5. Search for "Bosch thermostat" and install
6. Restart Home Assistant

### Manual Installation

1. Download this repository
2. Copy the `custom_components/bosch` folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings → Devices & Services**
2. Click **+ Add Integration**
3. Search for "Bosch thermostat"
4. Follow the setup wizard:
   - Choose your device type (IVT, NEFIT, or EasyControl)
   - Enter your device credentials (IP/serial, access token, password)

**Note**: All sensors are disabled by default. Go to the integration device "Bosch sensors" and enable the sensors you want.

---

## POINTT API for Hourly Energy Data (CT200/TC100.2)

The EasyControl CT200 local API only provides **daily** energy totals. To get **real hourly** energy data (like the Bosch mobile app), you can enable the experimental POINTT cloud API.

### Why Use POINTT API?

| Feature | Local API | POINTT API |
|---------|-----------|------------|
| Data granularity | Daily totals | **Real hourly** |
| Energy Dashboard | Works, but inaccurate | **Accurate hourly stats** |
| Price correlation | Not possible | **Works correctly** |
| Internet required | No | Yes |

### Prerequisites

You need `uv` (Python package runner) and Playwright installed:

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Playwright browser (one-time setup)
uv run --with playwright python -m playwright install chromium
```

### Setup Steps

1. **Enable POINTT API** in integration options:
   - Go to **Settings → Devices & Services → Bosch**
   - Click **Configure**
   - Check **"POINTT cloud API for real hourly energy data"**
   - Select authentication method: **"Callback URL"**

2. **Run the authentication script**:
   ```bash
   cd /path/to/home-assistant-bosch-custom-component
   ./scripts/run_playwright_ha.sh
   ```

3. **Log in** with your Bosch/SingleKey-ID account in the browser window that opens

4. **Copy the callback URL** that appears after login

5. **Paste the URL** into Home Assistant and submit

The integration will exchange the code for tokens and start fetching hourly energy data automatically.

### Token Expiration

POINTT tokens expire periodically. When this happens:
- You'll see a **Repair** notification in Home Assistant
- Energy data will stop updating
- Re-run `./scripts/run_playwright_ha.sh` and paste the new callback URL

### Alternative: Direct Token Entry

If you prefer to manage tokens manually:

1. Run `./scripts/run_playwright.sh` (full OAuth flow)
2. Copy the ACCESS_TOKEN and REFRESH_TOKEN from the output
3. In HA options, choose **"Direct tokens"** and paste both values

---

## Integration Options

| Option | Default | Description |
|--------|---------|-------------|
| **Write energy data to HA statistics** | On | Required for Energy Dashboard. Writes external statistics with hourly granularity. |
| **Optimistic mode** | Off | Climate entity updates immediately without waiting for device confirmation. Enable if CT200 operation mode changes feel slow. |
| **POINTT cloud API** | Off | **(CT200 only)** Fetches real hourly energy data from Bosch cloud. Replaces local energy sensors with accurate cloud data. |

---

## Debugging

### Enable Debug Logging

Add to your `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.bosch: debug
    bosch_thermostat_client: debug
```

### Debug Scan

To scan your Bosch device for all available endpoints:

1. Go to **Developer Tools → Services**
2. Call `bosch.debug_scan`
3. Download the JSON from `<config>/www/bosch_scan.json`

---

## Troubleshooting

### POINTT API Issues

**"Token refresh failed: 400 - invalid_grant"**
- The refresh token has expired
- Re-run `./scripts/run_playwright_ha.sh` and paste the new callback URL

**"No hourly data returned"**
- Check if POINTT API is enabled in options
- Verify tokens are valid (check for repair notification)
- The POINTT API only provides ~3 days of hourly history

**Browser doesn't open for OAuth**
- Make sure Playwright is installed: `uv run --with playwright python -m playwright install chromium`
- Try running with full output: `uv run --with playwright --with playwright-stealth --with aiohttp python scripts/pointt_oauth_playwright.py --ha`

### Energy Dashboard Not Showing Data

1. Ensure "Write energy data to HA statistics" is enabled
2. Wait for the next update cycle (every hour at :06)
3. Check **Developer Tools → Statistics** for entries starting with `energy:` or `recording:`

---

## Architecture

For technical details on how the POINTT API integration works, see [docs/POINTT_API_ARCHITECTURE.md](docs/POINTT_API_ARCHITECTURE.md).

---

## Contributing

Issues and pull requests welcome!

When reporting issues:
- Attach a debug scan (`bosch.debug_scan` service)
- Include relevant log excerpts with debug logging enabled
- Specify your device model and HA version

---

## Credits

- Original component by [@pszafer](https://github.com/pszafer)
- POINTT API implementation based on research from [ha_bosch](https://github.com/CaseyRo/ha_bosch)

## License

This project is licensed under the MIT License.
