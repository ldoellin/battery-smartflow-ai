from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

from .const import (
    DEFAULT_PV_DAILY_YIELD_FALLBACK_KWH,
    DEFAULT_PV_FORECAST_ENABLED,
    SETTING_PV_FORECAST_ENABLED,
)
from .decision_engine import DecisionContext, NightEnergyAssessment
from .utils import _to_float

if TYPE_CHECKING:
    from .coordinator import SelectedEntities

_LOGGER = logging.getLogger(__name__)



class BydNightChargeManager:
    """Steuert BYD-Nachtladung und PV-Forecast-Fallback.

    Eigenständige Zustandsmaschine für:
    - Nachtladen im GO-Fenster (00:00–05:00 Lokalzeit)
    - PV-Tagesertrag Rolling-History als Solcast-Fallback

    Wird vom Coordinator instanziiert und bei jedem Zyklus via update() aufgerufen.
    _persist wird als Referenz übergeben — Coordinator bleibt alleiniger Owner
    von Load/Save.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entities: SelectedEntities,
        persist: dict[str, Any],
        runtime_settings: dict[str, Any],
        charge_mode: str,
        stop_mode: str,
        pause_mode: str,
    ) -> None:
        self.hass = hass
        self.entities = entities
        self._persist = persist            # Referenz auf coordinator._persist
        self._runtime_settings = runtime_settings  # Referenz auf coordinator.runtime_settings
        self._charge_mode = charge_mode
        self._stop_mode = stop_mode
        self._pause_mode = pause_mode

        # State-Flags (werden vom Coordinator via _load/_save persistiert)
        self.night_active: bool = False
        self.discharge_paused: bool = False
        # Log-Dedup: Fehler beim Leistungs-Setzen nur einmal loggen bis zum nächsten Erfolg
        self._power_set_failed: bool = False

    # --------------------------------------------------
    # PV-Forecast Fallback
    # --------------------------------------------------

    def update_pv_yield_history(self) -> None:
        """Speichert PV-Tagesertrag bei Sonnenuntergang (sun.sun → below_horizon).

        Erkennt die Flanke above_horizon → below_horizon und speichert den aktuellen
        Tagesertrag in einer Rolling-History der letzten 3 Tage.
        """
        if not self.entities.pv_daily_yield:
            return

        sun_state = self._state("sun.sun")
        last_sun_state = self._persist.get("pv_yield_last_sun_state")

        # Flanke: above_horizon → below_horizon
        if last_sun_state == "above_horizon" and sun_state == "below_horizon":
            raw = self._state(self.entities.pv_daily_yield)
            val = _to_float(raw, None)
            if val is not None and val > 0:
                history: list = list(self._persist.get("pv_yield_history", []))
                history.append(float(val))
                self._persist["pv_yield_history"] = history[-3:]
                _LOGGER.info(
                    "SmartFlow PV-Yield: Tagesertrag %.1f kWh gespeichert (History: %s)",
                    val,
                    self._persist["pv_yield_history"],
                )

        if sun_state in ("above_horizon", "below_horizon"):
            self._persist["pv_yield_last_sun_state"] = sun_state

    def get_pv_forecast_kwh(self) -> float:
        """Gibt PV-Forecast-Wert zurück.

        Priorität:
        1. Solcast-Sensor (wenn verfügbar)
        2. Rolling-Average der letzten 1–3 Tageserträge
        3. Hardcoded Default (25 kWh)

        Gibt -1.0 zurück wenn Feature deaktiviert.
        """
        pv_forecast_enabled = bool(
            self._runtime_settings.get(SETTING_PV_FORECAST_ENABLED, DEFAULT_PV_FORECAST_ENABLED)
        )

        if not pv_forecast_enabled:
            return -1.0

        # Primär: Solcast-Sensor
        if self.entities.pv_forecast:
            raw = self._state(self.entities.pv_forecast)
            val = _to_float(raw, None)
            if val is not None:
                return float(val)

        # Fallback: Rolling-Average der letzten Tage
        history: list = self._persist.get("pv_yield_history", [])
        if history:
            avg = sum(history) / len(history)
            _LOGGER.debug(
                "SmartFlow PV-Forecast Fallback: %.1f kWh (avg von %d Tag(en))",
                avg,
                len(history),
            )
            return avg

        # Hard-Default
        _LOGGER.debug(
            "SmartFlow PV-Forecast Fallback: %.1f kWh (default, keine History)",
            DEFAULT_PV_DAILY_YIELD_FALLBACK_KWH,
        )
        return DEFAULT_PV_DAILY_YIELD_FALLBACK_KWH

    # --------------------------------------------------
    # Nachtlade-Zustandsmaschine
    # --------------------------------------------------

    async def async_reset(self) -> None:
        """Erzwingt Sicherheitsstopp unabhängig vom Nachtfenster (z.B. bei Switch-off).

        Gleiches Verhalten wie der Fenster-Sicherheitsstopp in update(), aber
        von außen (Coordinator) auslösbar statt an das GO-Fenster gebunden.
        """
        self._persist.pop("night_soc_snapshot", None)
        if self.night_active:
            _LOGGER.info("SmartFlow Nachtladen: PV-Nachtladung deaktiviert – BYD → %s", self._stop_mode)
            await self._set_mode(self._stop_mode)
            self.night_active = False
        if self.discharge_paused:
            _LOGGER.info("SmartFlow Nachtladen: PV-Nachtladung deaktiviert – Entladepause aufheben → %s", self._stop_mode)
            await self._set_mode(self._stop_mode)
            self.discharge_paused = False

    async def update(
        self,
        ctx: DecisionContext,
        now: datetime,
        assessment: NightEnergyAssessment | None = None,
    ) -> None:
        """Steuert BYD-Ladung während des GO-Günstigfensters (00:00–05:00 Lokalzeit).

        Wird bei jedem Coordinator-Zyklus (10s) aufgerufen wenn Feature aktiv.
        Schreibt nur bei Zustandswechsel (Modus-Änderung) auf HA-Entitäten.
        """
        # Außerhalb des Nacht-Fensters: Sicherheitsstopp falls noch aktiv + Pause aufheben
        if not (0 <= now.hour < 5):
            self._persist.pop("night_soc_snapshot", None)
            if self.night_active:
                _LOGGER.info("SmartFlow Nachtladen: Fenster 05:00 überschritten – BYD → %s", self._stop_mode)
                await self._set_mode(self._stop_mode)
                self.night_active = False
            if self.discharge_paused:
                _LOGGER.info("SmartFlow Nachtladen: 05:00 – Entladepause aufheben → %s", self._stop_mode)
                await self._set_mode(self._stop_mode)
                self.discharge_paused = False
            return

        # Nur in Betriebsmodi, in denen auch NightChargeRule aktiv ist.
        if ctx.ai_mode not in ("automatic", "winter", "summer", "manual"):
            if self.night_active:
                _LOGGER.info(
                    "SmartFlow Nachtladen: Modus wechselte zu %s während GO-Fenster – BYD → %s",
                    ctx.ai_mode, self._stop_mode,
                )
                await self._set_mode(self._stop_mode)
                self.night_active = False
            if self.discharge_paused:
                _LOGGER.info(
                    "SmartFlow Nachtladen: Modus wechselte zu %s – Entladepause aufheben → %s",
                    ctx.ai_mode, self._stop_mode,
                )
                await self._set_mode(self._stop_mode)
                self.discharge_paused = False
            return

        # Ohne konfigurierte BYD-Steuerentität: keine Aktion
        if not self.entities.additional_battery_mode:
            return

        (byd_target_soc, z_target_soc, byd_charge, bridge_covered, day_target_covered,
         current_byd_soc, byd_actual_kwh, zendure_actual_kwh, z_charge) = self._calc_targets(ctx, assessment)

        current_mode = self._state(self.entities.additional_battery_mode)

        night_status, mode_to_set = self._decide_byd_mode(
            byd_charge=byd_charge,
            bridge_covered=bridge_covered,
            day_target_covered=day_target_covered,
            current_mode=current_mode,
            byd_target_soc=byd_target_soc,
            current_byd_soc=current_byd_soc,
            z_charge=z_charge,
        )
        if mode_to_set is not None:
            await self._set_mode(mode_to_set)

        byd_power_w: int | None = None
        if night_status == "charging":
            remaining_h = max(0.25, 5.0 - now.hour - now.minute / 60.0)
            byd_power_w = int(min(3600, max(500, round(byd_charge / remaining_h * 10) * 100)))

            if current_mode != self._charge_mode:
                _LOGGER.info(
                    "SmartFlow Nachtladen: BYD %.1fkWh laden → Ziel %.0f%%, %dW (%s bleibt)",
                    byd_charge, byd_target_soc, byd_power_w, f"{remaining_h:.1f}h",
                )
                await self._set_mode(self._charge_mode)

            if self.entities.additional_battery_power:
                _last_pw = self._persist.get("last_set_byd_power_w")
                _last_ts = self._persist.get("last_set_byd_power_ts")
                _elapsed = (now.timestamp() - _last_ts) if _last_ts is not None else float("inf")
                if byd_power_w != _last_pw and _elapsed >= 300:
                    try:
                        await self.hass.services.async_call(
                            "input_number",
                            "set_value",
                            {"entity_id": self.entities.additional_battery_power, "value": byd_power_w},
                        )
                        self._persist["last_set_byd_power_w"] = byd_power_w
                        self._persist["last_set_byd_power_ts"] = now.timestamp()
                        self._power_set_failed = False
                    except Exception as err:  # noqa: BLE001
                        if not self._power_set_failed:
                            self._power_set_failed = True
                            _LOGGER.error(
                                "SmartFlow BYD: Leistung %d W konnte nicht gesetzt werden: %s",
                                byd_power_w, err,
                            )
            self.night_active = True

        self._persist_night_plan(
            now=now,
            night_status=night_status,
            ctx=ctx,
            byd_target_soc=byd_target_soc,
            z_target_soc=z_target_soc,
            byd_actual_kwh=byd_actual_kwh,
            zendure_actual_kwh=zendure_actual_kwh,
            byd_power_w=byd_power_w,
        )

    def _calc_targets(
        self,
        ctx: DecisionContext,
        assessment: NightEnergyAssessment | None,
    ) -> tuple[float, float, float, bool, bool, float, float, float, float]:
        """Berechnet Lade-Ziele aus Assessment und SoC-Snapshot.

        Returns (byd_target_soc, z_target_soc, byd_charge, bridge_covered,
                 day_target_covered, current_byd_soc, byd_actual_kwh,
                 zendure_actual_kwh, z_charge).
        """
        charge_needed      = assessment.charge_needed_kwh   if assessment else 0.0
        z_charge           = assessment.z_charge_kwh        if assessment else 0.0
        bridge_covered     = assessment.bridge_covered      if assessment else True
        day_target_covered = assessment.day_target_covered  if assessment else True
        byd_charge     = max(0.0, charge_needed - z_charge)

        current_byd_soc = ctx.additional_battery_soc if ctx.additional_battery_soc >= 0 else 0.0

        if "night_soc_snapshot" not in self._persist:
            self._persist["night_soc_snapshot"] = {"byd": current_byd_soc, "zendure": ctx.soc}
        _snap = self._persist["night_soc_snapshot"]
        byd_actual_kwh = (
            max(0.0, (current_byd_soc - _snap["byd"]) / 100.0 * ctx.additional_battery_capacity_kwh)
            if ctx.additional_battery_capacity_kwh > 0 else 0.0
        )
        zendure_actual_kwh = max(0.0, (ctx.soc - _snap["zendure"]) / 100.0 * ctx.battery_capacity_kwh)

        byd_target_soc = current_byd_soc
        if ctx.additional_battery_capacity_kwh > 0:
            byd_target_soc = min(
                100.0,
                current_byd_soc + byd_charge / ctx.additional_battery_capacity_kwh * 100.0,
            )

        z_target_soc = ctx.soc
        if ctx.battery_capacity_kwh > 0:
            z_target_soc = min(ctx.soc_max, ctx.soc + z_charge / ctx.battery_capacity_kwh * 100.0)

        return (byd_target_soc, z_target_soc, byd_charge, bridge_covered,
                day_target_covered, current_byd_soc, byd_actual_kwh, zendure_actual_kwh, z_charge)

    def _decide_byd_mode(
        self,
        byd_charge: float,
        bridge_covered: bool,
        day_target_covered: bool,
        current_mode: str,
        byd_target_soc: float,
        current_byd_soc: float,
        z_charge: float,
    ) -> tuple[str, str | None]:
        """Bestimmt (night_status, mode_to_set).

        mode_to_set ist None wenn kein Moduswechsel nötig.
        Aktualisiert self.night_active und self.discharge_paused.
        """
        if current_byd_soc >= byd_target_soc - 0.5 or byd_charge < 0.5:
            was_night_active = self.night_active
            self.night_active = False

            if z_charge >= 0.2:
                byd_already_charging = current_mode == self._charge_mode
                if not byd_already_charging and current_mode != self._pause_mode:
                    _LOGGER.info(
                        "SmartFlow Nachtladen: Zendure lädt noch (%.2f kWh) → BYD pausieren", z_charge,
                    )
                    self.discharge_paused = True
                    return "discharge_paused", self._pause_mode
                return "discharge_paused", None

            if not bridge_covered or not day_target_covered:
                byd_already_charging = current_mode == self._charge_mode
                if not byd_already_charging and current_mode != self._pause_mode:
                    _LOGGER.info(
                        "SmartFlow Nachtladen: %s (Assessment) → %s",
                        "Brücke nicht gesichert" if not bridge_covered else "Tagesziel (Peak ab 15 Uhr) nicht gesichert",
                        self._pause_mode,
                    )
                    self.discharge_paused = True
                    return "discharge_paused", self._pause_mode
                return "discharge_paused", None

            if current_mode in (self._charge_mode, self._pause_mode):
                if was_night_active or self.discharge_paused:
                    _LOGGER.info(
                        "SmartFlow Nachtladen: BYD Ziel %.0f%% erreicht (aktuell %.0f%%) → %s",
                        byd_target_soc, current_byd_soc, self._stop_mode,
                    )
                    self.discharge_paused = False
                    return "goal_reached" if byd_charge >= 0.5 else "no_need", self._stop_mode
            return "goal_reached" if byd_charge >= 0.5 else "no_need", None

        return "charging", None

    def _persist_night_plan(
        self,
        now: datetime,
        night_status: str,
        ctx: DecisionContext,
        byd_target_soc: float,
        z_target_soc: float,
        byd_actual_kwh: float,
        zendure_actual_kwh: float,
        byd_power_w: int | None,
    ) -> None:
        """Schreibt night_plan in _persist."""
        self._persist["night_plan"] = {
            "status": night_status,
            "pv_kwh": round(ctx.pv_forecast_kwh, 2),
            "byd_ziel_soc": round(byd_target_soc, 1),
            "byd_laden_kwh": round(byd_actual_kwh, 2),
            "byd_leistung_w": (
                byd_power_w if byd_power_w is not None
                else self._persist.get("night_plan", {}).get("byd_leistung_w")
            ),
            "zendure_ziel_soc": round(z_target_soc, 1),
            "zendure_laden_kwh": round(zendure_actual_kwh, 2),
            "timestamp": now.strftime("%H:%M %d.%m.%Y"),
        }

    async def _set_mode(self, mode: str) -> None:
        """Schreibt BYD-Steuermodus auf input_select (nur wenn Entität konfiguriert)."""
        if not self.entities.additional_battery_mode:
            return
        _LOGGER.debug("SmartFlow BYD: setze Modus → %s (Entität: %s)", mode, self.entities.additional_battery_mode)
        try:
            await self.hass.services.async_call(
                "input_select",
                "select_option",
                {
                    "entity_id": self.entities.additional_battery_mode,
                    "option": mode,
                },
                blocking=False,
            )
            _LOGGER.debug("SmartFlow BYD: Modus %s erfolgreich gesetzt", mode)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("SmartFlow BYD: Modus %s konnte nicht gesetzt werden: %s", mode, err)

    # --------------------------------------------------
    # Helper
    # --------------------------------------------------

    def _state(self, entity_id: str | None) -> Any:
        """Liest HA-Sensor-State (None wenn nicht konfiguriert oder unavailable)."""
        if not entity_id:
            return None
        st = self.hass.states.get(entity_id)
        return st.state if st else None
