"""Regression tests for service gateway lookup, without a full HA install."""
from __future__ import annotations

import ast
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest


DOMAIN = "bosch"
GATEWAY_ENTRY = "BoschGatewayEntry"


def load_gateway_lookup(registry):
    """Execute the actual lookup function with only its HA boundary replaced."""
    path = Path(__file__).parents[1] / "custom_components/bosch/services.py"
    tree = ast.parse(path.read_text())
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "find_gateway_entry"
    )
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), function],
        type_ignores=[],
    )
    namespace = {
        "ConfigEntry": SimpleNamespace,
        "DOMAIN": DOMAIN,
        "BOSCH_GATEWAY_ENTRY": GATEWAY_ENTRY,
        "dr": SimpleNamespace(async_get=lambda hass: registry),
        "_LOGGER": logging.getLogger(__name__),
    }
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace["find_gateway_entry"]


class GatewayLookupTests(unittest.TestCase):
    def setUp(self):
        self.entry = SimpleNamespace(entry_id="entry-1", domain=DOMAIN)
        self.gateway = SimpleNamespace(device_id=self.entry.entry_id)
        self.registry = SimpleNamespace(
            async_get=lambda device_id: SimpleNamespace(config_entries=["entry-1"])
        )
        self.lookup = load_gateway_lookup(self.registry)
        self.hass = SimpleNamespace(
            data={DOMAIN: {"gateway-1": {GATEWAY_ENTRY: self.gateway}}},
            config_entries=SimpleNamespace(async_get_entry=lambda entry_id: self.entry),
        )

    def test_token_refresh_metadata_is_not_a_gateway(self):
        """Token reload suppression must not break GET/refresh/PUT services."""
        self.hass.data[DOMAIN]["options_signature"] = {"entry-1": {"optimistic_mode": False}}
        self.assertEqual(self.lookup(self.hass, ["thermostat-device"]), [self.gateway])

    def test_normal_gateway_lookup_is_preserved(self):
        self.assertEqual(self.lookup(self.hass, ["thermostat-device"]), [self.gateway])

    def test_unloaded_gateway_returns_no_targets(self):
        self.hass.data[DOMAIN] = {"options_signature": {}}
        self.assertEqual(self.lookup(self.hass, ["thermostat-device"]), [])


if __name__ == "__main__":
    unittest.main()
