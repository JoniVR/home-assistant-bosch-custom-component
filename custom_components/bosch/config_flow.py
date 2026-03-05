"""Config flow to configure esphome component."""
import logging

import voluptuous as vol
from bosch_thermostat_client import gateway_chooser
from bosch_thermostat_client.const import HTTP, XMPP
from bosch_thermostat_client.const.easycontrol import EASYCONTROL
from bosch_thermostat_client.const.ivt import IVT, IVT_MBLAN
from bosch_thermostat_client.const.nefit import NEFIT
from bosch_thermostat_client.exceptions import (
    DeviceException,
    EncryptionException,
    FirmwareException,
    UnknownDevice,
)
from homeassistant import config_entries
from homeassistant.core import callback

from homeassistant.const import CONF_ACCESS_TOKEN, CONF_ADDRESS, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import create_notification_firmware
from .const import (
    ACCESS_KEY,
    ACCESS_TOKEN,
    CONF_DEVICE_TYPE,
    CONF_PROTOCOL,
    DOMAIN,
    UUID,
)

DEVICE_TYPE = [NEFIT, IVT, EASYCONTROL, IVT_MBLAN]
PROTOCOLS = [HTTP, XMPP]


_LOGGER = logging.getLogger(__name__)


@config_entries.HANDLERS.register(DOMAIN)
class BoschFlowHandler(config_entries.ConfigFlow):
    """Handle a bosch config flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self):
        """Initialize Bosch flow."""
        self._choose_type = None
        self._host = None
        self._access_token = None
        self._password = None
        self._protocol = None
        self._device_type = None

    async def async_step_user(self, user_input=None):
        """Handle flow initiated by user."""
        return await self.async_step_choose_type(user_input)

    async def async_step_choose_type(self, user_input=None):
        """Choose if setup is for IVT, IVT/MBLAN, NEFIT or EASYCONTROL."""
        errors = {}
        if user_input is not None:
            self._choose_type = user_input[CONF_DEVICE_TYPE]
            if self._choose_type == IVT:
                return self.async_show_form(
                    step_id="protocol",
                    data_schema=vol.Schema(
                        {
                            vol.Required(CONF_PROTOCOL): vol.All(
                                vol.Upper, vol.In(PROTOCOLS)
                            ),
                        }
                    ),
                    errors=errors,
                )
            elif self._choose_type in (NEFIT, EASYCONTROL, IVT_MBLAN):
                return await self.async_step_protocol({CONF_PROTOCOL: XMPP})
        return self.async_show_form(
            step_id="choose_type",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_TYPE): vol.All(
                        vol.Upper, vol.In(DEVICE_TYPE)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_protocol(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._protocol = user_input[CONF_PROTOCOL]
            return self.async_show_form(
                step_id=f"{self._protocol.lower()}_config",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_ADDRESS): str,
                        vol.Required(CONF_ACCESS_TOKEN): str,
                        vol.Optional(CONF_PASSWORD): str,
                    }
                ),
                errors=errors,
            )
        return self.async_show_form(
            step_id="protocol",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PROTOCOL): vol.All(vol.Upper, vol.In(PROTOCOLS)),
                }
            ),
            errors=errors,
        )

    async def async_step_http_config(self, user_input=None):
        if user_input is not None:
            self._host = user_input[CONF_ADDRESS]
            self._access_token = user_input[CONF_ACCESS_TOKEN]
            self._password = user_input.get(CONF_PASSWORD)
            return await self.configure_gateway(
                device_type=self._choose_type,
                session=async_get_clientsession(self.hass, verify_ssl=False),
                session_type=self._protocol,
                host=self._host,
                access_token=self._access_token,
                password=self._password,
            )

    async def async_step_xmpp_config(self, user_input=None):
        if user_input is not None:
            self._host = user_input[CONF_ADDRESS]
            self._access_token = user_input[CONF_ACCESS_TOKEN]
            self._password = user_input.get(CONF_PASSWORD)
            if "127.0.0.1" in user_input[CONF_ADDRESS]:
                return await self.configure_gateway(
                    device_type=self._choose_type,
                    session=async_get_clientsession(self.hass, verify_ssl=False),
                    session_type=HTTP,
                    host=self._host,
                    access_token=self._access_token,
                    password=self._password,
                )
            return await self.configure_gateway(
                device_type=self._choose_type,
                session_type=self._protocol,
                host=self._host,
                access_token=self._access_token,
                password=self._password,
            )

    async def configure_gateway(
        self, device_type, session_type, host, access_token, password=None, session=None
    ):
        try:
            BoschGateway = gateway_chooser(device_type)
            device = BoschGateway(
                session_type=session_type,
                host=host,
                access_token=access_token,
                password=password,
                session=session,
            )
            try:
                uuid = await device.check_connection()
            except (FirmwareException, UnknownDevice) as err:
                create_notification_firmware(hass=self.hass, msg=err)
                uuid = device.uuid
            if uuid:
                await self.async_set_unique_id(uuid)
                self._abort_if_unique_id_configured()
        except (DeviceException, EncryptionException) as err:
            _LOGGER.error("Wrong IP or credentials at %s - %s", host, err)
            return self.async_abort(reason="faulty_credentials")
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Error connecting Bosch at %s - %s", host, err)
        else:
            _LOGGER.debug("Adding Bosch entry.")
            return self.async_create_entry(
                title=device.device_name or "Unknown model",
                data={
                    CONF_ADDRESS: device.host,
                    UUID: uuid,
                    ACCESS_KEY: device.access_key,
                    ACCESS_TOKEN: device.access_token,
                    CONF_DEVICE_TYPE: self._choose_type,
                    CONF_PROTOCOL: session_type,
                },
            )

    async def async_step_discovery(self, discovery_info=None):
        """Handle a flow discovery."""
        _LOGGER.debug("Discovered Bosch unit : %s", discovery_info)

    @staticmethod
    @callback
    def async_get_options_flow(entry: config_entries.ConfigEntry):
        """Get option flow."""
        return OptionsFlowHandler(entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow handler for new API."""

    def __init__(self, entry: config_entries.ConfigEntry):
        """Initialize option."""
        self.entry = entry

    async def async_step_init(self, user_input=None):
        """Display option dialog."""
        if user_input is not None:
            # If POINTT enabled, go to credentials step
            if user_input.get("experimental_pointt_api"):
                self._options = user_input
                return await self.async_step_pointt_credentials()
            return self.async_create_entry(title="", data=user_input)

        new_stats_api = self.entry.options.get("new_stats_api", False)
        optimistic_mode = self.entry.options.get("optimistic_mode", False)
        experimental_pointt = self.entry.options.get("experimental_pointt_api", False)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional("new_stats_api", default=new_stats_api): bool,
                    vol.Optional("optimistic_mode", default=optimistic_mode): bool,
                    vol.Optional("experimental_pointt_api", default=experimental_pointt): bool,
                }
            ),
        )

    async def async_step_pointt_credentials(self, user_input=None):
        """Handle POINTT API - choose authentication method."""
        # Store options for next step
        if not hasattr(self, "_options"):
            self._options = {}

        if user_input is not None:
            auth_method = user_input.get("pointt_auth_method", "callback")
            if auth_method == "tokens":
                return await self.async_step_pointt_tokens()
            else:
                return await self.async_step_pointt_callback()

        return self.async_show_form(
            step_id="pointt_credentials",
            data_schema=vol.Schema(
                {
                    vol.Required("pointt_auth_method", default="callback"): vol.In({
                        "callback": "Callback URL (recommended - use Playwright helper)",
                        "tokens": "Direct token input",
                    }),
                }
            ),
        )

    async def async_step_pointt_callback(self, user_input=None):
        """Handle POINTT API - accept callback URL from user."""
        errors = {}

        if user_input is not None:
            callback_url = user_input.get("pointt_callback_url", "")

            from .pointt_api import extract_code_from_callback, exchange_code_for_tokens, PointtAuthError
            from homeassistant.helpers.aiohttp_client import async_get_clientsession

            # Extract authorization code from callback URL
            code = extract_code_from_callback(callback_url)
            if not code:
                errors["base"] = "pointt_auth_failed"
            else:
                # Exchange code for tokens
                session = async_get_clientsession(self.hass)
                try:
                    tokens = await exchange_code_for_tokens(session, code)
                    # Success! Store tokens
                    data = {
                        **self._options,
                        "pointt_tokens": tokens,
                    }
                    return self.async_create_entry(title="", data=data)
                except PointtAuthError:
                    errors["base"] = "pointt_auth_failed"

        return self.async_show_form(
            step_id="pointt_callback",
            data_schema=vol.Schema(
                {
                    vol.Required("pointt_callback_url"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_pointt_tokens(self, user_input=None):
        """Handle POINTT API - direct token input."""
        errors = {}

        if user_input is not None:
            from datetime import datetime, timedelta, timezone

            access_token = user_input.get("pointt_access_token", "").strip()
            refresh_token = user_input.get("pointt_refresh_token", "").strip()

            if not access_token or not refresh_token:
                errors["base"] = "pointt_auth_failed"
            else:
                # Create token data structure
                # Assume token expires in 1 hour (will be refreshed automatically)
                expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
                tokens = {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": expires_at.isoformat(),
                }
                data = {
                    **self._options,
                    "pointt_tokens": tokens,
                }
                return self.async_create_entry(title="", data=data)

        return self.async_show_form(
            step_id="pointt_tokens",
            data_schema=vol.Schema(
                {
                    vol.Required("pointt_access_token"): str,
                    vol.Required("pointt_refresh_token"): str,
                }
            ),
            errors=errors,
        )
