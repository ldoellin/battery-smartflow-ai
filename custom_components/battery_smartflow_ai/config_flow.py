from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_SOC_ENTITY,
    CONF_PV_ENTITY,
    CONF_BATTERY_AC_POWER_ENTITY,
    CONF_ADDITIONAL_BATTERY_CHARGE_ENTITY,
    CONF_ADDITIONAL_BATTERY_DISCHARGE_ENTITY,
    CONF_WALLBOX_POWER_ENTITY,
    CONF_PRICE_EXPORT_ENTITY,
    CONF_PRICE_NOW_ENTITY,
    CONF_AC_MODE_ENTITY,
    CONF_INPUT_LIMIT_ENTITY,
    CONF_OUTPUT_LIMIT_ENTITY,
    CONF_GRID_MODE,
    CONF_GRID_POWER_ENTITY,
    CONF_GRID_IMPORT_ENTITY,
    CONF_GRID_EXPORT_ENTITY,
    GRID_MODE_NONE,
    GRID_MODE_SINGLE,
    GRID_MODE_SPLIT,
    CONF_DEVICE_PROFILE,
    DEFAULT_DEVICE_PROFILE,
    CONF_SOC_LIMIT_ENTITY,
    CONF_PACK_CAPACITY_KWH,
    DEFAULT_PACK_CAPACITY_KWH,
    CONF_PROFILE_OVERRIDES,
    CONF_INSTALLED_PV_WP,
    DEFAULT_INSTALLED_PV_WP,
    # PV-Forecast (v3.2)
    CONF_PV_FORECAST_ENTITY,
    CONF_PV_DAILY_YIELD_ENTITY,
    CONF_ADDITIONAL_BATTERY_SOC_ENTITY,
    CONF_ADDITIONAL_BATTERY_CAPACITY_KWH,
    CONF_ADDITIONAL_BATTERY_MODE_ENTITY,
    CONF_ADDITIONAL_BATTERY_POWER_ENTITY,
    CONF_ADDITIONAL_BATTERY_CHARGE_MODE,
    CONF_ADDITIONAL_BATTERY_STOP_MODE,
    CONF_ADDITIONAL_BATTERY_PAUSE_MODE,
    DEFAULT_ADDITIONAL_BATTERY_CAPACITY_KWH,
)

from .device_profiles import DEVICE_PROFILES, PROFILE_OVERRIDE_FIELDS


class ZendureSmartFlowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Battery SmartFlow AI."""

    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._user_input = dict(user_input)
            return await self.async_step_grid()

        return self.async_show_form(
            step_id="user",
            data_schema=self._base_schema(),
        )

    async def async_step_grid(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        grid_mode = self._user_input.get(CONF_GRID_MODE, GRID_MODE_NONE)

        if user_input is not None:
            self._user_input.update(user_input)

            if grid_mode == GRID_MODE_SPLIT:
                if (
                    not user_input.get(CONF_GRID_IMPORT_ENTITY)
                    or not user_input.get(CONF_GRID_EXPORT_ENTITY)
                ):
                    errors["base"] = "grid_split_missing"

            if not self._user_input.get(CONF_PRICE_EXPORT_ENTITY):
                self._user_input.pop(CONF_PRICE_EXPORT_ENTITY, None)

            if not self._user_input.get(CONF_PRICE_NOW_ENTITY):
                self._user_input.pop(CONF_PRICE_NOW_ENTITY, None)

            if not self._user_input.get(CONF_SOC_LIMIT_ENTITY):
                self._user_input.pop(CONF_SOC_LIMIT_ENTITY, None)

            if not self._user_input.get(CONF_ADDITIONAL_BATTERY_CHARGE_ENTITY):
                self._user_input.pop(CONF_ADDITIONAL_BATTERY_CHARGE_ENTITY, None)

            if not self._user_input.get(CONF_ADDITIONAL_BATTERY_DISCHARGE_ENTITY):
                self._user_input.pop(CONF_ADDITIONAL_BATTERY_DISCHARGE_ENTITY, None)

            if not self._user_input.get(CONF_WALLBOX_POWER_ENTITY):
                self._user_input.pop(CONF_WALLBOX_POWER_ENTITY, None)

            if not self._user_input.get(CONF_PV_FORECAST_ENTITY):
                self._user_input.pop(CONF_PV_FORECAST_ENTITY, None)

            if not self._user_input.get(CONF_PV_DAILY_YIELD_ENTITY):
                self._user_input.pop(CONF_PV_DAILY_YIELD_ENTITY, None)

            if not self._user_input.get(CONF_ADDITIONAL_BATTERY_SOC_ENTITY):
                self._user_input.pop(CONF_ADDITIONAL_BATTERY_SOC_ENTITY, None)

            if not self._user_input.get(CONF_ADDITIONAL_BATTERY_MODE_ENTITY):
                self._user_input.pop(CONF_ADDITIONAL_BATTERY_MODE_ENTITY, None)

            if not self._user_input.get(CONF_ADDITIONAL_BATTERY_POWER_ENTITY):
                self._user_input.pop(CONF_ADDITIONAL_BATTERY_POWER_ENTITY, None)

            if grid_mode != GRID_MODE_SINGLE:
                self._user_input.pop(CONF_GRID_POWER_ENTITY, None)

            if grid_mode != GRID_MODE_SPLIT:
                self._user_input.pop(CONF_GRID_IMPORT_ENTITY, None)
                self._user_input.pop(CONF_GRID_EXPORT_ENTITY, None)

            if not errors:
                return self.async_create_entry(
                    title="Battery SmartFlow AI",
                    data=self._user_input,
                )

        return self.async_show_form(
            step_id="grid",
            data_schema=self._grid_schema(grid_mode),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            self._user_input = dict(entry.data)
            self._user_input.update(user_input)
            return await self.async_step_reconfigure_grid()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._base_schema(entry),
        )

    async def async_step_reconfigure_grid(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        grid_mode = self._user_input.get(CONF_GRID_MODE, GRID_MODE_NONE)

        if user_input is not None:
            cleaned = dict(self._user_input)
            cleaned.update(user_input)

            if grid_mode != GRID_MODE_SINGLE:
                cleaned.pop(CONF_GRID_POWER_ENTITY, None)

            if grid_mode != GRID_MODE_SPLIT:
                cleaned.pop(CONF_GRID_IMPORT_ENTITY, None)
                cleaned.pop(CONF_GRID_EXPORT_ENTITY, None)

            if grid_mode == GRID_MODE_SPLIT:
                if (
                    not cleaned.get(CONF_GRID_IMPORT_ENTITY)
                    or not cleaned.get(CONF_GRID_EXPORT_ENTITY)
                ):
                    errors["base"] = "grid_split_missing"

            if not cleaned.get(CONF_PRICE_EXPORT_ENTITY):
                cleaned.pop(CONF_PRICE_EXPORT_ENTITY, None)

            if not cleaned.get(CONF_PRICE_NOW_ENTITY):
                cleaned.pop(CONF_PRICE_NOW_ENTITY, None)

            if not cleaned.get(CONF_SOC_LIMIT_ENTITY):
                cleaned.pop(CONF_SOC_LIMIT_ENTITY, None)

            if not cleaned.get(CONF_ADDITIONAL_BATTERY_CHARGE_ENTITY):
                cleaned.pop(CONF_ADDITIONAL_BATTERY_CHARGE_ENTITY, None)

            if not cleaned.get(CONF_ADDITIONAL_BATTERY_DISCHARGE_ENTITY):
                cleaned.pop(CONF_ADDITIONAL_BATTERY_DISCHARGE_ENTITY, None)

            if not cleaned.get(CONF_WALLBOX_POWER_ENTITY):
                cleaned.pop(CONF_WALLBOX_POWER_ENTITY, None)

            if not cleaned.get(CONF_PV_FORECAST_ENTITY):
                cleaned.pop(CONF_PV_FORECAST_ENTITY, None)

            if not cleaned.get(CONF_PV_DAILY_YIELD_ENTITY):
                cleaned.pop(CONF_PV_DAILY_YIELD_ENTITY, None)

            if not cleaned.get(CONF_ADDITIONAL_BATTERY_SOC_ENTITY):
                cleaned.pop(CONF_ADDITIONAL_BATTERY_SOC_ENTITY, None)

            if not cleaned.get(CONF_ADDITIONAL_BATTERY_MODE_ENTITY):
                cleaned.pop(CONF_ADDITIONAL_BATTERY_MODE_ENTITY, None)

            if not cleaned.get(CONF_ADDITIONAL_BATTERY_POWER_ENTITY):
                cleaned.pop(CONF_ADDITIONAL_BATTERY_POWER_ENTITY, None)

            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=cleaned,
                    reason="reconfigure_success",
                )

        return self.async_show_form(
            step_id="reconfigure_grid",
            data_schema=self._grid_schema(grid_mode, entry),
            errors=errors,
        )

    @classmethod
    def async_get_options_flow(cls, config_entry: config_entries.ConfigEntry):
        return ZendureSmartFlowOptionsFlow()

    def _base_schema(
        self,
        entry: config_entries.ConfigEntry | None = None,
    ) -> vol.Schema:
        def _val(key: str):
            if entry:
                return entry.data.get(key)
            return None

        schema: dict[Any, Any] = {}

        schema[
            vol.Required(
                CONF_DEVICE_PROFILE,
                default=_val(CONF_DEVICE_PROFILE) or DEFAULT_DEVICE_PROFILE,
            )
        ] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {
                        "value": key,
                        "label": DEVICE_PROFILES[key].get("label", key),
                    }
                    for key in DEVICE_PROFILES
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )

        schema[
            vol.Required(CONF_SOC_ENTITY, default=_val(CONF_SOC_ENTITY))
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")
        )

        soc_limit_val = _val(CONF_SOC_LIMIT_ENTITY)
        if soc_limit_val:
            schema[
                vol.Optional(CONF_SOC_LIMIT_ENTITY, default=soc_limit_val)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )
        else:
            schema[
                vol.Optional(CONF_SOC_LIMIT_ENTITY)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )

        schema[
            vol.Required(
                CONF_PACK_CAPACITY_KWH,
                default=_val(CONF_PACK_CAPACITY_KWH) or DEFAULT_PACK_CAPACITY_KWH,
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.1,
                max=20.0,
                step=0.01,
                mode=selector.NumberSelectorMode.BOX,
            )
        )

        schema[
            vol.Optional(
                CONF_INSTALLED_PV_WP,
                default=_val(CONF_INSTALLED_PV_WP) or DEFAULT_INSTALLED_PV_WP,
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=50000,
                step=10,
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="Wp",
            )
        )

        schema[
            vol.Required(CONF_PV_ENTITY, default=_val(CONF_PV_ENTITY))
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")
        )

        schema[
            vol.Required(
                CONF_BATTERY_AC_POWER_ENTITY,
                default=_val(CONF_BATTERY_AC_POWER_ENTITY),
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")
        )

        additional_battery_val = _val(CONF_ADDITIONAL_BATTERY_CHARGE_ENTITY)
        if additional_battery_val:
            schema[
                vol.Optional(
                    CONF_ADDITIONAL_BATTERY_CHARGE_ENTITY,
                    default=additional_battery_val,
                )
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )
        else:
            schema[
                vol.Optional(CONF_ADDITIONAL_BATTERY_CHARGE_ENTITY)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )

        additional_battery_discharge_val = _val(CONF_ADDITIONAL_BATTERY_DISCHARGE_ENTITY)
        if additional_battery_discharge_val:
            schema[
                vol.Optional(
                    CONF_ADDITIONAL_BATTERY_DISCHARGE_ENTITY,
                    default=additional_battery_discharge_val,
                )
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )
        else:
            schema[
                vol.Optional(CONF_ADDITIONAL_BATTERY_DISCHARGE_ENTITY)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )

        wallbox_val = _val(CONF_WALLBOX_POWER_ENTITY)
        if wallbox_val:
            schema[
                vol.Optional(
                    CONF_WALLBOX_POWER_ENTITY,
                    default=wallbox_val,
                )
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )
        else:
            schema[
                vol.Optional(CONF_WALLBOX_POWER_ENTITY)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )

        # --- PV-Forecast-basierte Nachtladung (v3.2) ---

        pv_forecast_val = _val(CONF_PV_FORECAST_ENTITY)
        if pv_forecast_val:
            schema[
                vol.Optional(CONF_PV_FORECAST_ENTITY, default=pv_forecast_val)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )
        else:
            schema[
                vol.Optional(CONF_PV_FORECAST_ENTITY)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )

        pv_yield_val = _val(CONF_PV_DAILY_YIELD_ENTITY)
        if pv_yield_val:
            schema[
                vol.Optional(CONF_PV_DAILY_YIELD_ENTITY, default=pv_yield_val)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )
        else:
            schema[
                vol.Optional(CONF_PV_DAILY_YIELD_ENTITY)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )

        byd_soc_val = _val(CONF_ADDITIONAL_BATTERY_SOC_ENTITY)
        if byd_soc_val:
            schema[
                vol.Optional(CONF_ADDITIONAL_BATTERY_SOC_ENTITY, default=byd_soc_val)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )
        else:
            schema[
                vol.Optional(CONF_ADDITIONAL_BATTERY_SOC_ENTITY)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )

        schema[
            vol.Optional(
                CONF_ADDITIONAL_BATTERY_CAPACITY_KWH,
                default=_val(CONF_ADDITIONAL_BATTERY_CAPACITY_KWH)
                or DEFAULT_ADDITIONAL_BATTERY_CAPACITY_KWH,
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.0,
                max=200.0,
                step=0.1,
                mode=selector.NumberSelectorMode.BOX,
            )
        )

        byd_mode_val = _val(CONF_ADDITIONAL_BATTERY_MODE_ENTITY)
        if byd_mode_val:
            schema[
                vol.Optional(CONF_ADDITIONAL_BATTERY_MODE_ENTITY, default=byd_mode_val)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="input_select")
            )
        else:
            schema[
                vol.Optional(CONF_ADDITIONAL_BATTERY_MODE_ENTITY)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="input_select")
            )

        byd_power_val = _val(CONF_ADDITIONAL_BATTERY_POWER_ENTITY)
        if byd_power_val:
            schema[
                vol.Optional(CONF_ADDITIONAL_BATTERY_POWER_ENTITY, default=byd_power_val)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="input_number")
            )
        else:
            schema[
                vol.Optional(CONF_ADDITIONAL_BATTERY_POWER_ENTITY)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="input_number")
            )

        schema[
            vol.Optional(
                CONF_ADDITIONAL_BATTERY_CHARGE_MODE,
                default=_val(CONF_ADDITIONAL_BATTERY_CHARGE_MODE) or "Laden",
            )
        ] = selector.TextSelector()

        schema[
            vol.Optional(
                CONF_ADDITIONAL_BATTERY_STOP_MODE,
                default=_val(CONF_ADDITIONAL_BATTERY_STOP_MODE) or "Automatik",
            )
        ] = selector.TextSelector()

        schema[
            vol.Optional(
                CONF_ADDITIONAL_BATTERY_PAUSE_MODE,
                default=_val(CONF_ADDITIONAL_BATTERY_PAUSE_MODE) or "Pause",
            )
        ] = selector.TextSelector()

        price_export_val = _val(CONF_PRICE_EXPORT_ENTITY)
        if price_export_val:
            schema[
                vol.Optional(CONF_PRICE_EXPORT_ENTITY, default=price_export_val)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )
        else:
            schema[
                vol.Optional(CONF_PRICE_EXPORT_ENTITY)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )

        price_now_val = _val(CONF_PRICE_NOW_ENTITY)
        if price_now_val:
            schema[
                vol.Optional(CONF_PRICE_NOW_ENTITY, default=price_now_val)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )
        else:
            schema[
                vol.Optional(CONF_PRICE_NOW_ENTITY)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )

        schema[
            vol.Required(CONF_AC_MODE_ENTITY, default=_val(CONF_AC_MODE_ENTITY))
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="select")
        )

        schema[
            vol.Required(
                CONF_INPUT_LIMIT_ENTITY,
                default=_val(CONF_INPUT_LIMIT_ENTITY),
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="number")
        )

        schema[
            vol.Required(
                CONF_OUTPUT_LIMIT_ENTITY,
                default=_val(CONF_OUTPUT_LIMIT_ENTITY),
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="number")
        )

        schema[
            vol.Required(
                CONF_GRID_MODE,
                default=_val(CONF_GRID_MODE) or GRID_MODE_SINGLE,
            )
        ] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {"value": GRID_MODE_NONE, "label": "Kein Netzsensor"},
                    {"value": GRID_MODE_SINGLE, "label": "Ein Sensor (+ / −)"},
                    {
                        "value": GRID_MODE_SPLIT,
                        "label": "Zwei Sensoren (Bezug & Einspeisung)",
                    },
                ]
            )
        )

        return vol.Schema(schema)

    def _grid_schema(
        self,
        grid_mode: str,
        entry: config_entries.ConfigEntry | None = None,
    ) -> vol.Schema:
        def _val(key: str):
            if entry:
                return entry.data.get(key)
            return None

        schema: dict[Any, Any] = {}

        if grid_mode == GRID_MODE_SINGLE:
            schema[
                vol.Required(
                    CONF_GRID_POWER_ENTITY,
                    default=_val(CONF_GRID_POWER_ENTITY),
                )
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )

        if grid_mode == GRID_MODE_SPLIT:
            schema[
                vol.Required(
                    CONF_GRID_IMPORT_ENTITY,
                    default=_val(CONF_GRID_IMPORT_ENTITY),
                )
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )
            schema[
                vol.Required(
                    CONF_GRID_EXPORT_ENTITY,
                    default=_val(CONF_GRID_EXPORT_ENTITY),
                )
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )

        return vol.Schema(schema)


class ZendureSmartFlowOptionsFlow(config_entries.OptionsFlow):
    """Options flow for profile overrides and expert settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        profile_key = (
            self.config_entry.options.get(CONF_DEVICE_PROFILE)
            or self.config_entry.data.get(CONF_DEVICE_PROFILE)
            or DEFAULT_DEVICE_PROFILE
        )
        profile = DEVICE_PROFILES.get(
            profile_key,
            DEVICE_PROFILES[DEFAULT_DEVICE_PROFILE],
        )
        current_overrides = self.config_entry.options.get(CONF_PROFILE_OVERRIDES, {})
        if not isinstance(current_overrides, dict):
            current_overrides = {}

        if user_input is not None:
            merged_options = dict(self.config_entry.options)

            installed_pv_wp = user_input.get(
                CONF_INSTALLED_PV_WP,
                self.config_entry.options.get(
                    CONF_INSTALLED_PV_WP,
                    self.config_entry.data.get(
                        CONF_INSTALLED_PV_WP,
                        DEFAULT_INSTALLED_PV_WP,
                    ),
                ),
            )

            profile_overrides: dict[str, float] = {}
            for key in PROFILE_OVERRIDE_FIELDS:
                value = user_input.get(key)
                if value is None:
                    continue
                try:
                    profile_overrides[key] = float(value)
                except (TypeError, ValueError):
                    continue

            merged_options[CONF_INSTALLED_PV_WP] = float(installed_pv_wp)
            merged_options[CONF_PROFILE_OVERRIDES] = profile_overrides

            return self.async_create_entry(
                title="",
                data=merged_options,
            )

        options_schema = vol.Schema(
            {
                vol.Optional("TARGET_IMPORT_W"): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0,
                        max=300.0,
                        step=5.0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="W",
                    )
                ),
                vol.Optional("DEADBAND_W"): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0,
                        max=200.0,
                        step=5.0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="W",
                    )
                ),
                vol.Optional("EXPORT_GUARD_W"): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0,
                        max=300.0,
                        step=5.0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="W",
                    )
                ),
                vol.Optional("KP_UP"): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.10,
                        max=2.00,
                        step=0.01,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional("KP_DOWN"): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.10,
                        max=2.00,
                        step=0.01,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional("MAX_STEP_UP"): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=50.0,
                        max=2000.0,
                        step=10.0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="W",
                    )
                ),
                vol.Optional("MAX_STEP_DOWN"): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=50.0,
                        max=2000.0,
                        step=10.0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="W",
                    )
                ),
                vol.Optional("KEEPALIVE_MIN_DEFICIT_W"): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0,
                        max=200.0,
                        step=5.0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="W",
                    )
                ),
                vol.Optional("KEEPALIVE_MIN_OUTPUT_W"): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0,
                        max=300.0,
                        step=5.0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="W",
                    )
                ),
                vol.Optional("SOC_DISCHARGE_RESUME_MARGIN"): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0,
                        max=15.0,
                        step=0.5,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="%",
                    )
                ),
            }
        )

        suggested_values = {
            CONF_INSTALLED_PV_WP: self.config_entry.options.get(
                CONF_INSTALLED_PV_WP,
                self.config_entry.data.get(
                    CONF_INSTALLED_PV_WP,
                    DEFAULT_INSTALLED_PV_WP,
                ),
            ),
            "TARGET_IMPORT_W": current_overrides.get(
                "TARGET_IMPORT_W",
                profile.get("TARGET_IMPORT_W"),
            ),
            "DEADBAND_W": current_overrides.get(
                "DEADBAND_W",
                profile.get("DEADBAND_W"),
            ),
            "EXPORT_GUARD_W": current_overrides.get(
                "EXPORT_GUARD_W",
                profile.get("EXPORT_GUARD_W"),
            ),
            "KP_UP": current_overrides.get("KP_UP", profile.get("KP_UP")),
            "KP_DOWN": current_overrides.get("KP_DOWN", profile.get("KP_DOWN")),
            "MAX_STEP_UP": current_overrides.get(
                "MAX_STEP_UP",
                profile.get("MAX_STEP_UP"),
            ),
            "MAX_STEP_DOWN": current_overrides.get(
                "MAX_STEP_DOWN",
                profile.get("MAX_STEP_DOWN"),
            ),
            "KEEPALIVE_MIN_DEFICIT_W": current_overrides.get(
                "KEEPALIVE_MIN_DEFICIT_W",
                profile.get("KEEPALIVE_MIN_DEFICIT_W"),
            ),
            "KEEPALIVE_MIN_OUTPUT_W": current_overrides.get(
                "KEEPALIVE_MIN_OUTPUT_W",
                profile.get("KEEPALIVE_MIN_OUTPUT_W"),
            ),
            "SOC_DISCHARGE_RESUME_MARGIN": current_overrides.get(
                "SOC_DISCHARGE_RESUME_MARGIN",
                profile.get("SOC_DISCHARGE_RESUME_MARGIN"),
            ),
        }

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                options_schema,
                suggested_values,
            ),
        )
