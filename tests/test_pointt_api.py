from __future__ import annotations

import ast
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from zoneinfo import ZoneInfo


def load_pointt_api():
    """Load pointt_api.py without requiring a full Home Assistant install."""
    aiohttp = types.ModuleType("aiohttp")
    setattr(aiohttp, "ClientSession", object)
    setattr(aiohttp, "ClientTimeout", lambda **_: None)
    sys.modules["aiohttp"] = aiohttp

    homeassistant = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    setattr(core, "HomeAssistant", object)
    helpers = types.ModuleType("homeassistant.helpers")
    issue_registry = types.ModuleType("homeassistant.helpers.issue_registry")
    setattr(issue_registry, "IssueSeverity", types.SimpleNamespace(ERROR="error"))
    setattr(issue_registry, "async_create_issue", lambda *args, **kwargs: None)
    setattr(issue_registry, "async_delete_issue", lambda *args, **kwargs: None)
    setattr(helpers, "issue_registry", issue_registry)
    setattr(homeassistant, "core", core)
    setattr(homeassistant, "helpers", helpers)
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.issue_registry"] = issue_registry

    path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "bosch"
        / "pointt_api.py"
    )
    spec = importlib.util.spec_from_file_location("bosch_pointt_api_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pointt_api = load_pointt_api()


class ParseHourlyDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = pointt_api.PointtEnergyClient.__new__(
            pointt_api.PointtEnergyClient
        )
        self.client._local_timezone = ZoneInfo("Europe/Brussels")

    def test_summer_local_hour_is_converted_to_utc(self) -> None:
        rows = self.client._parse_hourly_data(
            [{"d": "30-08-2026", "h": "8", "gCh": 1.2, "gHw": 0.3}]
        )

        self.assertEqual(rows[0]["datetime"], datetime(2026, 8, 30, 6, tzinfo=timezone.utc))

    def test_winter_local_hour_is_converted_to_utc(self) -> None:
        rows = self.client._parse_hourly_data(
            [{"d": "05-03-2026", "h": "6", "gCh": 1.2, "gHw": 0.3}]
        )

        self.assertEqual(rows[0]["datetime"], datetime(2026, 3, 5, 5, tzinfo=timezone.utc))

    def test_nonexistent_spring_forward_hour_is_skipped(self) -> None:
        rows = self.client._parse_hourly_data(
            [{"d": "29-03-2026", "h": "2", "gCh": 1.2, "gHw": 0.3}]
        )

        self.assertEqual(rows, [])

    def test_ambiguous_fall_back_hour_is_rejected_regardless_of_order(self) -> None:
        entries = [
            {"d": "25-10-2026", "h": "2", "gCh": 1.0, "gHw": 0.1},
            {"d": "25-10-2026", "h": "2", "gCh": 2.0, "gHw": 0.2},
        ]

        for ordered_entries in (entries, list(reversed(entries))):
            with self.subTest(ordered_entries=ordered_entries):
                rows = self.client._parse_hourly_data(ordered_entries)
                self.assertEqual(rows, [])

    def test_invalid_duplicate_does_not_block_later_valid_entry(self) -> None:
        valid = {"d": "30-08-2026", "h": "8", "gCh": 1.2, "gHw": 0.3}
        invalid_entries = [
            {"d": "30-08-2026", "h": "8", "gCh": "bad", "gHw": 0.0},
            {"d": "30-08-2026", "h": "8"},
        ]

        for invalid in invalid_entries:
            with self.subTest(invalid=invalid):
                rows = self.client._parse_hourly_data([invalid, valid])
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["ch"], 1.2)
                self.assertEqual(rows[0]["hw"], 0.3)


class RecorderApiUsageTests(unittest.TestCase):
    def test_pointt_import_does_not_write_recorder_entity_statistics(self) -> None:
        """POINTT imports must not mutate Recorder-owned entity statistics."""
        energy_source = (
            Path(__file__).parents[1]
            / "custom_components"
            / "bosch"
            / "sensor"
            / "energy.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("_import_pointt_entity_statistics", energy_source)
        self.assertNotIn("async_import_statistics", energy_source)

    def test_statistics_period_query_uses_statistic_id_set(self) -> None:
        """Match the Home Assistant statistics_during_period signature."""
        helper_source = (
            Path(__file__).parents[1]
            / "custom_components"
            / "bosch"
            / "sensor"
            / "statistic_helper.py"
        ).read_text(encoding="utf-8")

        tree = ast.parse(helper_source)
        period_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "async_add_executor_job"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "statistics_during_period"
        ]

        self.assertEqual(len(period_calls), 1)
        self.assertIsInstance(period_calls[0].args[4], ast.Set)


if __name__ == "__main__":
    unittest.main()
