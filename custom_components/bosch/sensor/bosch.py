"""Bosch regular sensor."""
from ..const import SIGNAL_SENSOR_UPDATE_BOSCH
from .base import BoschBaseSensor


class BoschSensor(BoschBaseSensor):
    """Representation of a Bosch sensor."""

    signal = SIGNAL_SENSOR_UPDATE_BOSCH
    _domain_name = "Sensors"

    @property
    def device_name(self):
        """Return device name for grouping in HA."""
        # Use parent_id if available for more specific grouping
        if self._bosch_object and self._bosch_object.parent_id:
            return f"Bosch {self._bosch_object.parent_id}"
        return "Bosch sensors"
