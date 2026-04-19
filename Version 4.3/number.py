from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    build_device_info,
    SETTING_BATTERY_PACKS,
    DEFAULT_BATTERY_PACKS,
    SETTING_PEAK_FACTOR,
    DEFAULT_PEAK_FACTOR,
    SETTING_VALLEY_FACTOR,
    DEFAULT_VALLEY_FACTOR,
    SETTING_VERY_CHEAP_PRICE,
    SETTING_SOC_MIN,
    DEFAULT_SOC_MIN,
    SETTING_SOC_MAX,
    DEFAULT_SOC_MAX,
    SETTING_MAX_CHARGE,
    DEFAULT_MAX_CHARGE,
    SETTING_MAX_DISCHARGE,
    DEFAULT_MAX_DISCHARGE,
    SETTING_EMERGENCY_SOC,
    DEFAULT_EMERGENCY_SOC,
    SETTING_EMERGENCY_CHARGE,
    DEFAULT_EMERGENCY_CHARGE,
    SETTING_PROFIT_MARGIN_PCT,
    DEFAULT_PROFIT_MARGIN_PCT,
    SETTING_VERY_EXPENSIVE_THRESHOLD,
    DEFAULT_VERY_EXPENSIVE_THRESHOLD,
    # PV-Forecast (v3.2)
    SETTING_DAYTIME_CONSUMPTION_W,
    DEFAULT_DAYTIME_CONSUMPTION_W,
    SETTING_NIGHTTIME_CONSUMPTION_W,
    DEFAULT_NIGHTTIME_CONSUMPTION_W,
    SETTING_PV_OPTIMISM_FACTOR,
    DEFAULT_PV_OPTIMISM_FACTOR,
    # Abendverbrauch (v4.3)
    SETTING_EVENING_CONSUMPTION_W,
    DEFAULT_EVENING_CONSUMPTION_W,
)

# Numerischer Entity-Default für very_cheap_price (0.0 = kein Filter).
# Bewusst verschieden von DEFAULT_VERY_CHEAP_PRICE = None in const.py,
# das als Coordinator-Sentinel für "Feature deaktiviert" dient.
_ENTITY_DEFAULT_VERY_CHEAP_PRICE = 0.0

_SETTING_DEFAULTS: dict[str, float] = {
    SETTING_BATTERY_PACKS:              DEFAULT_BATTERY_PACKS,
    SETTING_PEAK_FACTOR:                DEFAULT_PEAK_FACTOR,
    SETTING_VALLEY_FACTOR:              DEFAULT_VALLEY_FACTOR,
    SETTING_VERY_CHEAP_PRICE:           _ENTITY_DEFAULT_VERY_CHEAP_PRICE,
    SETTING_SOC_MIN:                    DEFAULT_SOC_MIN,
    SETTING_SOC_MAX:                    DEFAULT_SOC_MAX,
    SETTING_MAX_CHARGE:                 DEFAULT_MAX_CHARGE,
    SETTING_MAX_DISCHARGE:              DEFAULT_MAX_DISCHARGE,
    SETTING_EMERGENCY_SOC:              DEFAULT_EMERGENCY_SOC,
    SETTING_EMERGENCY_CHARGE:           DEFAULT_EMERGENCY_CHARGE,
    SETTING_PROFIT_MARGIN_PCT:          DEFAULT_PROFIT_MARGIN_PCT,
    SETTING_VERY_EXPENSIVE_THRESHOLD:   DEFAULT_VERY_EXPENSIVE_THRESHOLD,
    SETTING_DAYTIME_CONSUMPTION_W:      DEFAULT_DAYTIME_CONSUMPTION_W,
    SETTING_NIGHTTIME_CONSUMPTION_W:    DEFAULT_NIGHTTIME_CONSUMPTION_W,
    SETTING_PV_OPTIMISM_FACTOR:         DEFAULT_PV_OPTIMISM_FACTOR,
    SETTING_EVENING_CONSUMPTION_W:      DEFAULT_EVENING_CONSUMPTION_W,
}


@dataclass(frozen=True, kw_only=True)
class ZendureNumberEntityDescription(NumberEntityDescription):
    runtime_key: str


NUMBERS: tuple[ZendureNumberEntityDescription, ...] = (

    ZendureNumberEntityDescription(
        key=SETTING_BATTERY_PACKS,
        translation_key="battery_packs",
        runtime_key=SETTING_BATTERY_PACKS,
        native_min_value=1,
        native_max_value=10,
        native_step=1,
        mode="box",
    ),

    ZendureNumberEntityDescription(
        key=SETTING_PEAK_FACTOR,
        translation_key="peak_factor",
        runtime_key=SETTING_PEAK_FACTOR,
        native_min_value=1.0,
        native_max_value=2.5,
        native_step=0.01,
        mode="box",
        icon="mdi:chart-bell-curve",
    ),

    # -----------------------------------------------------
    # NEW: Valley Factor
    # -----------------------------------------------------

    ZendureNumberEntityDescription(
        key=SETTING_VALLEY_FACTOR,
        translation_key="valley_factor",
        runtime_key=SETTING_VALLEY_FACTOR,
        native_min_value=0.5,
        native_max_value=1.0,
        native_step=0.01,
        mode="box",
        icon="mdi:chart-bell-curve",
    ),

    # -----------------------------------------------------
    # NEW: Very Cheap Price
    # -----------------------------------------------------

    ZendureNumberEntityDescription(
        key=SETTING_VERY_CHEAP_PRICE,
        translation_key="very_cheap_price",
        runtime_key=SETTING_VERY_CHEAP_PRICE,
        native_min_value=0.0,
        native_max_value=1.0,
        native_step=0.01,
        native_unit_of_measurement="€/kWh",
        mode="box",
        icon="mdi:cash",
    ),

    ZendureNumberEntityDescription(
        key="soc_min",
        translation_key="soc_min",
        runtime_key="soc_min",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="%",
        mode="box",
        icon="mdi:battery-alert",
    ),
    ZendureNumberEntityDescription(
        key="soc_max",
        translation_key="soc_max",
        runtime_key="soc_max",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="%",
        mode="box",
        icon="mdi:battery-check",
    ),
    ZendureNumberEntityDescription(
        key="max_charge",
        translation_key="max_charge",
        runtime_key="max_charge",
        native_min_value=0,
        native_max_value=2400,
        native_step=10,
        native_unit_of_measurement="W",
        mode="box",
        icon="mdi:battery-arrow-up",
    ),
    ZendureNumberEntityDescription(
        key="max_discharge",
        translation_key="max_discharge",
        runtime_key="max_discharge",
        native_min_value=0,
        native_max_value=2400,
        native_step=10,
        native_unit_of_measurement="W",
        mode="box",
        icon="mdi:battery-arrow-down",
    ),
    ZendureNumberEntityDescription(
        key="emergency_charge",
        translation_key="emergency_charge",
        runtime_key="emergency_charge",
        native_min_value=0,
        native_max_value=2400,
        native_step=50,
        native_unit_of_measurement="W",
        mode="box",
        icon="mdi:flash-alert",
    ),
    ZendureNumberEntityDescription(
        key="emergency_soc",
        translation_key="emergency_soc",
        runtime_key="emergency_soc",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="%",
        mode="box",
        icon="mdi:alert-circle",
    ),
    ZendureNumberEntityDescription(
        key="profit_margin_pct",
        translation_key="profit_margin_pct",
        runtime_key="profit_margin_pct",
        native_min_value=0,
        native_max_value=1000,
        native_step=1,
        native_unit_of_measurement="%",
        mode="box",
        icon="mdi:chart-line",
    ),
    ZendureNumberEntityDescription(
        key="very_expensive_threshold",
        translation_key="very_expensive_threshold",
        runtime_key="very_expensive_threshold",
        native_min_value=0,
        native_max_value=2,
        native_step=0.01,
        native_unit_of_measurement="€/kWh",
        mode="box",
        icon="mdi:currency-eur",
    ),

    # --- PV-Forecast-basierte Nachtladung (v3.2) ---
    # Hinweis: pv_forecast_enabled wird als Switch-Entität verwaltet (switch.py)

    ZendureNumberEntityDescription(
        key=SETTING_DAYTIME_CONSUMPTION_W,
        translation_key="daytime_consumption_w",
        runtime_key=SETTING_DAYTIME_CONSUMPTION_W,
        native_min_value=0,
        native_max_value=2000,
        native_step=10,
        native_unit_of_measurement="W",
        mode="box",
        icon="mdi:weather-sunny",
    ),

    ZendureNumberEntityDescription(
        key=SETTING_NIGHTTIME_CONSUMPTION_W,
        translation_key="nighttime_consumption_w",
        runtime_key=SETTING_NIGHTTIME_CONSUMPTION_W,
        native_min_value=0,
        native_max_value=2000,
        native_step=10,
        native_unit_of_measurement="W",
        mode="box",
        icon="mdi:weather-night",
    ),

    ZendureNumberEntityDescription(
        key=SETTING_PV_OPTIMISM_FACTOR,
        translation_key="pv_optimism_factor",
        runtime_key=SETTING_PV_OPTIMISM_FACTOR,
        native_min_value=1.0,
        native_max_value=3.0,
        native_step=0.1,
        mode="box",
        icon="mdi:weather-sunny-alert",
    ),

    # --- Abendverbrauch (v4.3) ---
    ZendureNumberEntityDescription(
        key=SETTING_EVENING_CONSUMPTION_W,
        translation_key="evening_consumption_w",
        runtime_key=SETTING_EVENING_CONSUMPTION_W,
        native_min_value=0,
        native_max_value=2000,
        native_step=10,
        native_unit_of_measurement="W",
        mode="box",
        icon="mdi:weather-night-partly-cloudy",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        ZendureSmartFlowNumber(entry, coordinator, description)
        for description in NUMBERS
    ]

    add_entities(entities)

    # --- INITIALIZE RUNTIME SETTINGS ---
    # Always run: defensive __init__ may have pre-populated with native_min_value
    # instead of the proper defaults. entry.options wins if user has already saved.
    for ent in entities:
        key = ent.entity_description.runtime_key

        default_value = _SETTING_DEFAULTS.get(
            key,
            ent.entity_description.native_min_value,
        )

        coordinator.runtime_settings[key] = entry.options.get(
            key,
            default_value,
        )


class ZendureSmartFlowNumber(NumberEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator,
        description: ZendureNumberEntityDescription,
    ) -> None:
        self.entity_description = description
        self.coordinator = coordinator
        self._entry = entry

        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = build_device_info(entry.entry_id)

        # Defensive init
        if description.runtime_key not in coordinator.runtime_settings:
            coordinator.runtime_settings[description.runtime_key] = entry.options.get(
                description.runtime_key,
                description.native_min_value,
            )

    @property
    def native_value(self) -> float | int:
        value = float(
            self.coordinator.runtime_settings.get(
                self.entity_description.runtime_key, 0
            )
        )
        # Ganzzahligen Step → int zurückgeben, damit HA keine Nachkommastelle anzeigt
        step = self.entity_description.native_step
        if step is not None and step == int(step) and value == int(value):
            return int(value)
        return value

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.runtime_settings[self.entity_description.runtime_key] = float(value)

        self.hass.config_entries.async_update_entry(
            self._entry,
            options={
                **self._entry.options,
                self.entity_description.runtime_key: float(value),
            },
        )

        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
