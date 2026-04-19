from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Literal, Optional

from .power_controller import PowerController, PowerContext
from .const import MANUAL_CONST_DISCHARGE

_LOGGER = logging.getLogger(__name__)


# --------------------------------------------------
# TYPES
# --------------------------------------------------

AiMode = Literal["automatic", "summer", "winter", "manual"]
ZendureMode = Literal["input", "output"]
ActionType = Literal["idle", "charge", "discharge", "emergency"]


@dataclass
class PricePoint:
    start: datetime
    end: datetime
    price: float


@dataclass
class DecisionContext:
    now: datetime

    soc: float
    soc_min: float
    soc_max: float

    emergency_soc: float
    emergency_charge_w: float

    max_charge_w: float
    max_discharge_w: float

    grid_import_w: float
    grid_export_w: float
    pv_w: float
    house_load_w: float

    price_now: Optional[float]
    avg_charge_price: Optional[float]
    expensive_threshold: float
    very_expensive_threshold: float
    profit_margin_pct: float
    price_points: List[PricePoint]

    ai_mode: AiMode
    manual_action: Optional[str]
    season: Literal["winter", "summer"]

    profile: dict
    prev_discharge_w: float
    prev_charge_w: float

    battery_capacity_kwh: float

    # Zusatzakku + Wallbox Koordination
    additional_battery_charge_w: float = 0.0
    additional_battery_discharge_w: float = 0.0
    wallbox_active_w: float = 0.0
    wallbox_block_enabled: bool = True   # Entladung bei Schnellladen verhindern (Schalter)

    # --- Planning tuning ---
    peak_factor: float = 1.35
    valley_factor: float = 0.85
    very_cheap_price: Optional[float] = None

    # --- PV-Forecast-basierte Nachtladung (v3.2) ---
    pv_forecast_kwh: float = -1.0             # -1 = Feature deaktiviert / Sensor unavailable
    additional_battery_soc: float = -1.0      # -1 = kein Zusatzakku konfiguriert
    additional_battery_capacity_kwh: float = 0.0
    daily_consumption_kwh: float = 12.0
    bridge_kwh: float = 1.5
    nighttime_kwh: float = 0.0                # Hausverbrauch bis 05:00 (0 tagsüber)
    pv_self_consumption_kwh: float = 5.0      # PV direkt Hausverbrauch tagsüber (nicht in Batterie)
    pv_optimism_factor: float = 1.5           # Skalierung P10→optimistisch für Nachtlade-Mengenkalkulation
    evening_consumption_w: float = 500.0      # Abendverbrauch 18–24 Uhr in W (v4.3, ersetzt bridge_kwh×2)
    night_charge_required: bool = False   # Ladebedarf ≥ 0.2 kWh (aus letztem BYD-Zyklus)
    night_charge_active: bool = False     # BYD lädt gerade aktiv (aus letztem BYD-Zyklus)


@dataclass(frozen=True)
class DecisionResult:
    action: ActionType
    ac_mode: ZendureMode
    charge_w: float
    discharge_w: float
    reason: str
    target_soc: Optional[float] = None


@dataclass
class NightEnergyAssessment:
    """Energiebilanz für das GO-Fenster (00–05 Uhr).

    Einzige Quelle der Wahrheit für Nacht-Energieberechnungen.
    Wird vom NightWindowController berechnet und an BydNightChargeManager
    weitergegeben — keine doppelte Implementierung mehr.
    """
    bridge_covered: bool       # projected_at_5 >= bridge_kwh
    evening_covered: bool      # battery_at_18 >= evening_need
    charge_needed_kwh: float   # Gesamtladebedarf (Zendure + BYD)
    z_charge_kwh: float        # Zendures Anteil am Ladebedarf
    # Diagnose
    projected_at_5: float = 0.0
    battery_at_18: float = 0.0
    evening_need: float = 0.0


# ==================================================
# RULE BASE
# ==================================================

class BaseRule:
    def evaluate(
        self,
        engine: "DecisionEngine",
        ctx: DecisionContext,
    ) -> Optional[DecisionResult]:
        raise NotImplementedError


# ==================================================
# RULES
# ==================================================

class EmergencyRule(BaseRule):
    def evaluate(self, engine, ctx):
        if ctx.soc <= ctx.emergency_soc:
            return DecisionResult(
                action="emergency",
                ac_mode="input",
                charge_w=min(ctx.max_charge_w, ctx.emergency_charge_w),
                discharge_w=0.0,
                reason="emergency_latched_charge",
            )
        return None


class PeakRule(BaseRule):
    def evaluate(self, engine, ctx):
        if engine._byd_blocks_discharge(ctx) or engine._wallbox_blocks_discharge(ctx):
            return None
        if engine._bridge_reserve_blocks_discharge(ctx):
            return None
        if ctx.soc < ctx.soc_max and engine._delta_charge(ctx) > 0:
            return None
        if engine._is_real_export(ctx):
            return None
        if (
            ctx.soc > ctx.soc_min + 5
            and ctx.ai_mode in ("automatic", "winter", "summer")
        ):
            if engine._detect_adaptive_peak(ctx):
                discharge_w = engine._delta_discharge(ctx)
                return DecisionResult(
                    action="discharge",
                    ac_mode="output",
                    charge_w=0.0,
                    discharge_w=discharge_w,
                    reason="adaptive_peak_discharge",
                )

            if (
                ctx.price_now is not None
                and ctx.price_now >= ctx.very_expensive_threshold
            ):
                discharge_w = engine._delta_discharge(ctx)
                return DecisionResult(
                    action="discharge",
                    ac_mode="output",
                    charge_w=0.0,
                    discharge_w=discharge_w,
                    reason="very_expensive_force_discharge",
                )
        return None


class PlanningRule(BaseRule):
    def evaluate(self, engine, ctx):
        if engine._byd_blocks_charge(ctx):
            return None
        return engine._planning_result





class PvRule(BaseRule):
    def evaluate(self, engine, ctx):
        if ctx.ai_mode == "manual":
            return None
        if engine._byd_blocks_charge(ctx):
            return None
        # Nicht auf Laden wechseln wenn Zendure gerade entladen hat.
        # Kurzer Export durch eigene Entladung ist kein PV-Überschuss-Signal.
        if ctx.prev_discharge_w > 0:
            return None
        # Wenn wir gerade aktiv planen zu laden,
        # soll PV diese Entscheidung nicht überschreiben
        if engine._planning_result is not None:
            return None

        if ctx.soc < ctx.soc_max:
            charge_w = engine._delta_charge(ctx)

            if charge_w > 0:
                return DecisionResult(
                    action="charge",
                    ac_mode="input",
                    charge_w=charge_w,
                    discharge_w=0.0,
                    reason="pv_surplus_charge",
                )

        return None


class SummerRule(BaseRule):
    def evaluate(self, engine, ctx):
        if (
            engine._byd_blocks_discharge(ctx)
            or engine._wallbox_blocks_discharge(ctx)
            or engine._bridge_reserve_blocks_discharge(ctx)
        ):
            return None
        if (
            ctx.ai_mode == "summer"
            or (ctx.ai_mode == "automatic" and ctx.season == "summer")
        ):
            if ctx.soc > ctx.soc_min:
                # _delta_discharge() übernimmt den Exportschutz via EXPORT_GUARD:
                # Net-Export > 100W → aggressive Kürzung auf 0W
                # Net-Export 0–100W → Entladung bleibt stabil (kein Reset)
                discharge_w = engine._delta_discharge(ctx)
                if discharge_w > 0:
                    return DecisionResult(
                        action="discharge",
                        ac_mode="output",
                        charge_w=0.0,
                        discharge_w=discharge_w,
                        reason="summer_cover_deficit",
                    )
        return None


class ManualRule(BaseRule):
    def evaluate(self, engine, ctx):
        if ctx.ai_mode != "manual":
            return None

        if ctx.manual_action == "charge":
            return DecisionResult(
                action="charge",
                ac_mode="input",
                charge_w=ctx.max_charge_w,
                discharge_w=0.0,
                reason="manual_charge",
            )

        if ctx.manual_action == MANUAL_CONST_DISCHARGE:
            # Wallbox lädt → discharge_w=0, Zendure bleibt im Output-Modus aber gibt nichts ab.
            # Kein Moduswechsel auf idle. max_discharge_w Einstellung bleibt erhalten.
            # Im GO-Fenster (00–05h) übernimmt NightWindowController — falls er None zurückgibt
            # (constant_discharge pass-through), greift diese Regel.
            if engine._wallbox_blocks_discharge(ctx):
                return DecisionResult(
                    action="discharge",
                    ac_mode="output",
                    charge_w=0.0,
                    discharge_w=0.0,
                    reason="manual_constant_discharge",
                )
            # BYD lädt → kein Entladen (verhindert Energiekreis: BYD lädt, Zendure entlädt)
            # Brückenreserve fast erreicht → Entladung stoppen (Schutz für Morgenstunden)
            if engine._byd_blocks_discharge(ctx) or engine._bridge_reserve_blocks_discharge(ctx):
                return DecisionResult(
                    action="idle",
                    ac_mode="input",
                    charge_w=0.0,
                    discharge_w=0.0,
                    reason="manual_idle",
                )
            return DecisionResult(
                action="discharge",
                ac_mode="output",
                charge_w=0.0,
                discharge_w=float(ctx.max_discharge_w),
                reason="manual_constant_discharge",
            )

        if ctx.manual_action == "discharge":
            if (
                engine._byd_blocks_discharge(ctx)
                or engine._wallbox_blocks_discharge(ctx)
                or engine._bridge_reserve_blocks_discharge(ctx)
            ):
                return DecisionResult(
                    action="idle",
                    ac_mode="input",
                    charge_w=0.0,
                    discharge_w=0.0,
                    reason="manual_idle",
                )
            discharge_w = engine._delta_discharge(ctx)
            return DecisionResult(
                action="discharge",
                ac_mode="output",
                charge_w=0.0,
                discharge_w=discharge_w,
                reason="manual_discharge",
            )

        return DecisionResult(
            action="idle",
            ac_mode="input",
            charge_w=0.0,
            discharge_w=0.0,
            reason="manual_idle",
        )


# ==================================================
# NIGHT WINDOW CONTROLLER
# ==================================================

class NightWindowController:
    """Steuert alle Entscheidungen im GO-Fenster (00–05 Uhr).

    Ersetzt NightChargeRule als eigenständiger Controller.
    DecisionEngine delegiert das 00–05-Fenster vollständig hierher.

    Vorbereitet für EnWG 14a Modul 3:
    - round_trip_efficiency aus Geräteprofil
    - discharge_is_profitable() berechnet Break-Even nach Wandlungsverlusten
    - Laden vs. Entladen vs. Idle an einem Ort entschieden
    """

    def __init__(self, round_trip_efficiency: float = 0.90) -> None:
        self._round_trip_efficiency = round_trip_efficiency
        self.last_assessment: Optional[NightEnergyAssessment] = None

    # --------------------------------------------------
    # Energiebilanz — einzige Implementierung dieser Logik
    # --------------------------------------------------

    def assess(self, ctx: DecisionContext) -> NightEnergyAssessment:
        pv_forecast = max(0.0, ctx.pv_forecast_kwh)  # < 0 = deaktiviert → konservativ 0

        z_usable   = max(0.0, (ctx.soc - ctx.soc_min) / 100.0 * ctx.battery_capacity_kwh)
        z_capacity = ctx.battery_capacity_kwh * (ctx.soc_max - ctx.soc_min) / 100.0
        byd_usable = (
            max(0.0, ctx.additional_battery_soc / 100.0 * ctx.additional_battery_capacity_kwh)
            if ctx.additional_battery_soc >= 0 else 0.0
        )
        total_capacity = z_capacity + ctx.additional_battery_capacity_kwh
        battery_usable = z_usable + byd_usable

        projected_at_5 = battery_usable - ctx.nighttime_kwh
        pv_surplus = max(
            0.0,
            pv_forecast * ctx.pv_optimism_factor - ctx.pv_self_consumption_kwh,
        )
        evening_need   = ctx.evening_consumption_w / 1000.0 * 6.0  # 18–24 Uhr = 6h
        bridge_covered = projected_at_5 >= ctx.bridge_kwh

        if bridge_covered:
            battery_at_08 = projected_at_5 - ctx.bridge_kwh
            battery_at_18 = min(total_capacity, battery_at_08 + pv_surplus)
            evening_covered = battery_at_18 >= evening_need
        else:
            battery_at_18   = 0.0
            evening_covered = False

        if not bridge_covered:
            charge_needed = (
                0.0 if battery_usable >= ctx.bridge_kwh
                else max(0.0, ctx.bridge_kwh - battery_usable)
            )
        elif not evening_covered:
            charge_needed = max(0.0, evening_need - battery_at_18)
        else:
            charge_needed = 0.0

        z_charge = min(max(0.0, z_capacity - z_usable), charge_needed)

        return NightEnergyAssessment(
            bridge_covered=bridge_covered,
            evening_covered=evening_covered,
            charge_needed_kwh=charge_needed,
            z_charge_kwh=z_charge,
            projected_at_5=projected_at_5,
            battery_at_18=battery_at_18,
            evening_need=evening_need,
        )

    # --------------------------------------------------
    # Fenster-Ownership
    # --------------------------------------------------

    def is_active(self, ctx: DecisionContext) -> bool:
        """True wenn der Controller das GO-Fenster ownt.

        False wenn ManualRule übernehmen soll:
        ai_mode == 'manual' + manual_action in {'charge', 'discharge'}.
        In diesem Fall gibt evaluate() None zurück — ManualRule greift.
        """
        if not (0 <= ctx.now.hour < 5):
            return False
        if ctx.ai_mode == "manual" and ctx.manual_action not in (
            "", "standby", "constant_discharge"
        ):
            return False
        return True

    # --------------------------------------------------
    # Profitabilitätsprüfung (EnWG 14a Modul 3 vorbereitet)
    # --------------------------------------------------

    def discharge_is_profitable(self, ctx: DecisionContext) -> bool:
        """True wenn Entladen nach Wandlungsverlusten profitabel ist.

        Break-Even = avg_charge_price / round_trip_efficiency.
        Entladen lohnt sich nur wenn price_now > Break-Even.

        Fallback ohne avg_charge_price: price_now >= very_expensive_threshold
        (entspricht dem früheren PeakRule-Verhalten für das 00–05-Fenster).

        Relevant für EnWG 14a Modul 3: bekannte Niedertarif-Einkaufspreise
        machen den Break-Even-Vergleich besonders wichtig.
        """
        if ctx.price_now is None:
            return False
        if ctx.avg_charge_price is None:
            return ctx.price_now >= ctx.very_expensive_threshold
        break_even = ctx.avg_charge_price / self._round_trip_efficiency
        return ctx.price_now > break_even

    # --------------------------------------------------
    # Hauptentscheidung
    # --------------------------------------------------

    def evaluate(
        self,
        engine: "DecisionEngine",
        ctx: DecisionContext,
    ) -> Optional[DecisionResult]:
        """Entscheidung für das GO-Fenster (00–05 Uhr).

        Gibt None zurück wenn ManualRule übernehmen soll (manual + charge/discharge).
        In allen anderen Fällen: immer ein vollständiges DecisionResult.

        4-Layer-Ablauf:
            1. assess()               — Energiebilanz (reine Physik, keine Seiteneffekte)
            2. _apply_constraints()   — Energie-Constraints (Emergency, Ladebedarf)
            3. _apply_system_guards() — Geräte-Koordination (BYD, Wallbox)
            4. _apply_policy()        — Strategie (Entladen, Manual, Idle)
        """
        # Manuelles Laden/Entladen: ManualRule übernimmt
        if ctx.ai_mode == "manual" and ctx.manual_action not in (
            "", "standby", "constant_discharge"
        ):
            return None

        self.last_assessment = self.assess(ctx)

        decision = self._apply_constraints(engine, ctx, self.last_assessment)
        if decision is not None:
            return decision

        decision = self._apply_system_guards(engine, ctx)
        if decision is not None:
            return decision

        return self._apply_policy(engine, ctx, self.last_assessment)

    def _apply_constraints(
        self,
        engine: "DecisionEngine",
        ctx: DecisionContext,
        a: NightEnergyAssessment,
    ) -> Optional[DecisionResult]:
        """Energie-Constraints — physikgetrieben, nicht-verhandelbar.

        Gibt ein DecisionResult zurück wenn ein Constraint greift,
        sonst None (weiter zu _apply_system_guards).

        Constraints (in Priorität):
            1. Emergency              — Notladung
            2. Ladebedarf vorhanden   — Laden oder Pause (getrieben durch bridge/evening)
            3. BYD-Systemzustand      — Zendure halten bis BYD-Zyklus abgeschlossen
        """
        # 1. Emergency hat absolute Priorität — auch im Nachtfenster
        if ctx.soc <= ctx.emergency_soc:
            return DecisionResult(
                action="emergency", ac_mode="input",
                charge_w=min(ctx.max_charge_w, ctx.emergency_charge_w),
                discharge_w=0.0,
                reason="emergency_latched_charge",
            )

        # 2. Energie-Physik: Brücke oder Abend nicht gedeckt → Laden erforderlich
        needs_charge = not a.bridge_covered or not a.evening_covered
        if needs_charge:
            # Lade-Guard: BYD entlädt gerade → kein Energiekreislauf (Charge-Constraint)
            if engine._byd_blocks_charge(ctx):
                return DecisionResult(
                    action="idle", ac_mode="input",
                    charge_w=0.0, discharge_w=0.0,
                    reason="night_charge_byd_discharging",
                )
            if ctx.max_charge_w <= 0:
                return DecisionResult(
                    action="idle", ac_mode="input",
                    charge_w=0.0, discharge_w=0.0,
                    reason="night_charge_no_capacity",
                )
            if a.z_charge_kwh >= 0.2:
                return DecisionResult(
                    action="charge", ac_mode="input",
                    charge_w=ctx.max_charge_w, discharge_w=0.0,
                    reason="night_charge_go_window",
                )
            return DecisionResult(
                action="idle", ac_mode="input",
                charge_w=0.0, discharge_w=0.0,
                reason="night_charge_pause",
            )

        # 3. BYD-Systemzustand: lädt noch oder Ladebedarf aus letztem Zyklus
        if ctx.night_charge_required or ctx.night_charge_active:
            return DecisionResult(
                action="idle", ac_mode="input",
                charge_w=0.0, discharge_w=0.0,
                reason="night_charge_pause",
            )

        return None  # kein Energie-Constraint aktiv → System-Guards prüfen

    def _apply_system_guards(
        self,
        engine: "DecisionEngine",
        ctx: DecisionContext,
    ) -> Optional[DecisionResult]:
        """Geräte-Koordinations-Guards — verhindert Entladen bei System-Konflikten.

        Wird nur erreicht wenn _apply_constraints None zurückgab (Batterie sicher,
        kein Ladebedarf). Trennt Geräte-Koordinationslogik von Energie-Physik und Strategie.

        Guards (in Priorität):
            1. BYD lädt  → kein Entladen (Energie-Loop verhindern)
            2. Wallbox   → Entladen auf 0 W drosseln (Output-Modus halten, kein Netzstrom)
        """
        if engine._byd_blocks_discharge(ctx):
            return DecisionResult(
                action="idle", ac_mode="input",
                charge_w=0.0, discharge_w=0.0,
                reason="night_guard_byd_charging",
            )
        if engine._wallbox_blocks_discharge(ctx):
            # Output-Modus halten, aber nichts abgeben — kein Moduswechsel auf idle
            return DecisionResult(
                action="discharge", ac_mode="output",
                charge_w=0.0, discharge_w=0.0,
                reason="night_guard_wallbox",
            )
        return None  # keine Guards aktiv → Policy entscheidet

    def _apply_policy(
        self,
        engine: "DecisionEngine",
        ctx: DecisionContext,
        a: NightEnergyAssessment,
    ) -> DecisionResult:
        """Strategie — wird nur erreicht wenn Constraints und Guards nicht gegriffen haben.

        Keine Guard-Aufrufe hier — Trennung zwischen Strategie und Geräte-Koordination.

        Policies (in Priorität):
            1. Manual constant_discharge — Entladen auf max_discharge_w, kein Profit-Check
            2. Auto profitable discharge — Entladen wenn Break-Even überschritten
            3. Idle                      — kein Eingriff nötig
        """
        # 1. Manual constant_discharge: Guards bereits durch _apply_system_guards abgedeckt
        if ctx.ai_mode == "manual" and ctx.manual_action == MANUAL_CONST_DISCHARGE:
            return DecisionResult(
                action="discharge", ac_mode="output",
                charge_w=0.0, discharge_w=float(ctx.max_discharge_w),
                reason="manual_constant_discharge",
            )

        # 2. Auto: Entladen wenn nach Wandlungsverlusten profitabel
        if (
            ctx.soc > ctx.soc_min + 5
            and self.discharge_is_profitable(ctx)
        ):
            discharge_w = engine._delta_discharge(ctx)
            if discharge_w > 0:
                return DecisionResult(
                    action="discharge", ac_mode="output",
                    charge_w=0.0, discharge_w=discharge_w,
                    reason="night_discharge_profitable",
                )

        # 3. Kein Eingriff nötig
        return DecisionResult(
            action="idle", ac_mode="input",
            charge_w=0.0, discharge_w=0.0,
            reason="night_no_intervention_needed",
        )


# ==================================================
# ENGINE
# ==================================================

class DecisionEngine:
    def __init__(self, night_controller: NightWindowController) -> None:
        self._night_controller = night_controller
        self._rules = [
            EmergencyRule(),
            PeakRule(),
            PlanningRule(),
            PvRule(),
            SummerRule(),
            ManualRule(),
        ]
        self._planning_result: Optional[DecisionResult] = None  # per-cycle cache

    # -------------------------------------------------
    # Helper methods
    # -------------------------------------------------

    _EXPORT_THRESHOLD_W: float = 100.0

    def _is_real_export(self, ctx: DecisionContext) -> bool:
        """True wenn Netto-Export > 100W (Zähler exportiert signifikant ins Netz)."""
        net = ctx.grid_import_w - ctx.grid_export_w
        return net < -self._EXPORT_THRESHOLD_W

    def _byd_blocks_discharge(self, ctx: DecisionContext) -> bool:
        """BYD lädt → Zendure darf nicht entladen (Energie-Loop verhindern)."""
        return float(ctx.additional_battery_charge_w or 0.0) > 0.0

    def _byd_blocks_charge(self, ctx: DecisionContext) -> bool:
        """BYD entlädt → Zendure darf nicht laden (Energie-Loop verhindern).
        Schwellwert 120 W filtert kurze Lastimpulse und Messrauschen heraus."""
        return float(ctx.additional_battery_discharge_w or 0.0) > 120.0

    def _wallbox_blocks_discharge(self, ctx: DecisionContext) -> bool:
        """Wallbox lädt → Zendure darf nicht entladen (nur wenn Schalter aktiv)."""
        if not ctx.wallbox_block_enabled:
            return False
        return float(ctx.wallbox_active_w or 0.0) > 0.0

    def _bridge_reserve_blocks_discharge(self, ctx: DecisionContext) -> bool:
        """Safety-Guard: Im GO-Fenster (00–05 Uhr lokal) kein Entladen wenn
        kombinierte Kapazität ≤ bridge_kwh — Brückenzeit (05–08 Uhr) wäre nicht mehr
        abdeckbar. NightChargeRule greift bei vorgelagerter Gefährdung bereits ein."""
        if not (0 <= ctx.now.hour < 5):
            return False
        z_usable = max(0.0, (ctx.soc - ctx.soc_min) / 100.0 * ctx.battery_capacity_kwh)
        byd_usable = (
            max(0.0, ctx.additional_battery_soc / 100.0 * ctx.additional_battery_capacity_kwh)
            if ctx.additional_battery_soc >= 0 and ctx.additional_battery_capacity_kwh > 0
            else 0.0
        )
        return (z_usable + byd_usable) <= ctx.bridge_kwh

    def _compute_base_price(self, prices: List[float]) -> float:
        avg_price = sum(prices) / len(prices)
        median_price = statistics.median(prices)
        return min(avg_price, median_price)

    def _compute_peak_threshold(self, prices: List[float], peak_factor: float) -> float:
        base_price = self._compute_base_price(prices)
        return base_price * peak_factor

    def _compute_valley_threshold(self, prices: List[float], valley_factor: float) -> float:
        base_price = self._compute_base_price(prices)
        return base_price * valley_factor

    # -------------------------------------------------
    # Delta delegation
    # -------------------------------------------------

    def _to_power_ctx(self, ctx: DecisionContext) -> PowerContext:
        return PowerContext(
            soc=ctx.soc,
            soc_min=ctx.soc_min,
            soc_max=ctx.soc_max,
            max_charge_w=ctx.max_charge_w,
            max_discharge_w=ctx.max_discharge_w,
            grid_import_w=ctx.grid_import_w,
            grid_export_w=ctx.grid_export_w,
            prev_discharge_w=ctx.prev_discharge_w,
            prev_charge_w=ctx.prev_charge_w,
            profile=ctx.profile,
        )

    def _delta_discharge(self, ctx: DecisionContext) -> float:
        return PowerController.delta_discharge(self._to_power_ctx(ctx))

    def _delta_charge(self, ctx: DecisionContext) -> float:
        return PowerController.delta_charge(self._to_power_ctx(ctx))

    # -------------------------------------------------
    # Peak detection
    # -------------------------------------------------

    def _detect_adaptive_peak(self, ctx: DecisionContext) -> bool:
        if not ctx.price_points or ctx.price_now is None:
            return False

        prices = [p.price for p in ctx.price_points]
        if not prices:
            return False

        threshold = self._compute_peak_threshold(prices, ctx.peak_factor)

        # Normal peak detection
        if ctx.price_now >= threshold:
            return True

        # ------------------------------------------------
        # Early spike detection
        # ------------------------------------------------
        future_slots = sorted(
            [p for p in ctx.price_points if p.start > ctx.now],
            key=lambda p: p.start,
        )

        for slot in future_slots:
            minutes_ahead = (slot.start - ctx.now).total_seconds() / 60

            if minutes_ahead > 60:
                break

            if slot.price >= threshold * 1.15:
                return True

        return False

    # -------------------------------------------------
    # PV-Forecast-basierte Ziel-SoC-Berechnung (v3.2)
    # -------------------------------------------------

    def _calc_pv_aware_zendure_target_soc(self, ctx: DecisionContext) -> Optional[float]:
        """Berechnet den PV-bewussten Zendure-Ziel-SoC.

        Gibt None zurück wenn:
        - Feature deaktiviert (pv_forecast_kwh < 0)
        - Sensor nicht verfügbar

        Formeln:
            z_usable    = max(0; (soc - soc_min) / 100 × battery_capacity_kwh)
            byd_usable  = max(0; additional_battery_soc / 100 × additional_battery_capacity_kwh)
            z_capacity  = battery_capacity_kwh × (soc_max - soc_min) / 100
            total_max   = z_capacity + additional_battery_capacity_kwh
            _pv_for_battery = max(0; pv_forecast_kwh - pv_self_consumption_kwh)
            target_total = min(total_max; bridge_kwh + nighttime_kwh + max(0; daily_consumption_kwh - _pv_for_battery))
            charge_needed = max(0; target_total - (z_usable + byd_usable))
            z_charge    = min(z_capacity - z_usable; charge_needed)
            z_target_soc = min(soc_max; soc + z_charge / battery_capacity_kwh × 100)

        Hinweis: Verwendet den vollen Tages-/Nachthorizont (inkl. nighttime_kwh) für
        die Tagesplanung (adaptive_planning). NightChargeRule verwendet projected_at_5
        und battery_at_18 statt dieses SoC-Zielwerts.
        """
        if ctx.pv_forecast_kwh < 0:
            return None  # Feature deaktiviert oder Sensor unavailable

        z_usable = max(0.0, (ctx.soc - ctx.soc_min) / 100.0 * ctx.battery_capacity_kwh)

        byd_usable = 0.0
        if ctx.additional_battery_soc >= 0 and ctx.additional_battery_capacity_kwh > 0:
            byd_usable = max(0.0, ctx.additional_battery_soc / 100.0 * ctx.additional_battery_capacity_kwh)

        total_avail = z_usable + byd_usable

        z_capacity = ctx.battery_capacity_kwh * (ctx.soc_max - ctx.soc_min) / 100.0
        total_max = z_capacity + ctx.additional_battery_capacity_kwh

        _pv_for_battery = max(0.0, ctx.pv_forecast_kwh - ctx.pv_self_consumption_kwh)
        target_total = min(
            total_max,
            ctx.bridge_kwh + ctx.nighttime_kwh + max(0.0, ctx.daily_consumption_kwh - _pv_for_battery),
        )

        charge_needed = max(0.0, target_total - total_avail)
        z_charge = min(max(0.0, z_capacity - z_usable), charge_needed)

        z_target_soc = min(
            ctx.soc_max,
            ctx.soc + z_charge / ctx.battery_capacity_kwh * 100.0,
        )
        return round(z_target_soc, 1)

    # -------------------------------------------------
    # Adaptive planning
    # -------------------------------------------------

    def _evaluate_adaptive_planning(self, ctx: DecisionContext) -> Optional[DecisionResult]:
        if (
            ctx.ai_mode not in ("automatic", "winter", "summer")
            or not ctx.price_points
            or ctx.price_now is None
            or ctx.battery_capacity_kwh <= 0
            or ctx.max_charge_w <= 0
        ):
            return None

        # PV-aware effective_soc_max: ersetzt ctx.soc_max wenn Feature aktiv
        effective_soc_max = ctx.soc_max
        pv_target = self._calc_pv_aware_zendure_target_soc(ctx)
        if pv_target is not None:
            effective_soc_max = pv_target

        # Guard: Bereits am Ziel? (0.1% Toleranz gegen Float-Rundung)
        if ctx.soc >= effective_soc_max - 0.1:
            return None

        prices = [p.price for p in ctx.price_points]
        if not prices:
            return None

        # ------------------------------------------------
        # Optional absolute cheap price filter
        # ------------------------------------------------
        if ctx.very_cheap_price is not None and ctx.price_now > ctx.very_cheap_price:
            return None

        # ------------------------------------------------
        # Valley factor check
        # ------------------------------------------------
        valley_threshold = self._compute_valley_threshold(prices, ctx.valley_factor)

        if ctx.price_now > valley_threshold:
            return None

        # ------------------------------------------------
        # Peak detection
        # ------------------------------------------------
        peak_threshold = self._compute_peak_threshold(prices, ctx.peak_factor)

        peak_slots = [p for p in ctx.price_points if p.price >= peak_threshold]
        future_peaks = [p for p in peak_slots if p.start > ctx.now]

        if not future_peaks:
            return None

        # ------------------------------------------------
        # Expected peak price
        # ------------------------------------------------
        expected_peak_price = max(p.price for p in future_peaks)

        # ------------------------------------------------
        # Profitability check
        # ------------------------------------------------
        min_profit_factor = 1 + (ctx.profit_margin_pct / 100)
        required_peak_price = ctx.price_now * min_profit_factor

        if expected_peak_price < required_peak_price:
            return None

        next_peak = min(p.start for p in future_peaks)

        # ------------------------------------------------
        # Detect second peak (multi-peak protection)
        # ------------------------------------------------
        future_peaks_sorted = sorted(future_peaks, key=lambda p: p.start)
        second_peak = future_peaks_sorted[1].start if len(future_peaks_sorted) >= 2 else None

        soc_gap_pct = max(0.0, effective_soc_max - ctx.soc)
        required_kwh = ctx.battery_capacity_kwh * (soc_gap_pct / 100.0)

        # ------------------------------------------------
        # Multi-peak protection
        # ------------------------------------------------
        if second_peak is not None:
            hours_between_peaks = (second_peak - next_peak).total_seconds() / 3600.0

            # Wenn Peaks sehr dicht sind -> mehr Energie reservieren
            if hours_between_peaks < 6:
                required_kwh *= 1.4

        charge_power_kw = ctx.max_charge_w / 1000.0
        if charge_power_kw <= 0:
            return None

        hours_needed = required_kwh / charge_power_kw
        hours_needed = max(hours_needed * 1.10, 0.25)

        latest_start = next_peak - timedelta(hours=hours_needed)

        # ------------------------------------------------
        # Smart cheapest charging window
        # ------------------------------------------------
        future_prices = [
            p for p in ctx.price_points
            if ctx.now <= p.start <= next_peak
        ]

        if future_prices:
            energy_per_slot = charge_power_kw * 0.25  # 15 Minuten

            if energy_per_slot > 0:
                required_slots = max(1, math.ceil(required_kwh / energy_per_slot))

                cheapest_slots = sorted(
                    future_prices,
                    key=lambda p: p.price,
                )[:required_slots]

                if not cheapest_slots:
                    return None

                cheapest_prices = [p.price for p in cheapest_slots]

                if ctx.price_now > max(cheapest_prices):
                    return None

        # ------------------------------------------------
        # Latest start trigger
        # ------------------------------------------------
        if ctx.now >= latest_start:
            return DecisionResult(
                action="charge",
                ac_mode="input",
                charge_w=ctx.max_charge_w,
                discharge_w=0.0,
                reason="planning_latest_start",
                target_soc=effective_soc_max,
            )

        return None

    # -------------------------------------------------
    # MAIN EVALUATION
    # -------------------------------------------------

    def evaluate(self, ctx: DecisionContext) -> DecisionResult:
        try:
            if not self._night_controller.is_active(ctx):
                self._night_controller.last_assessment = None
                self._planning_result = self._evaluate_adaptive_planning(ctx)
            else:
                result = self._night_controller.evaluate(self, ctx)
                if result is not None:
                    _LOGGER.debug(
                        "NightWindowController → %s (%s)", result.action, result.reason,
                    )
                    return result
                # is_active() filtert manual pass-through — sollte nicht eintreten
                _LOGGER.debug("NightWindowController → pass (manual override)")
                self._planning_result = self._evaluate_adaptive_planning(ctx)

            for rule in self._rules:
                result = rule.evaluate(self, ctx)
                if result is not None:
                    _LOGGER.debug(
                        "Rule %s → %s (%s)",
                        rule.__class__.__name__, result.action, result.reason,
                    )
                    return result
                _LOGGER.debug("Rule %s → pass", rule.__class__.__name__)

            _LOGGER.debug("All rules passed → idle")
            return DecisionResult(
                action="idle",
                ac_mode="input",
                charge_w=0.0,
                discharge_w=0.0,
                reason="idle",
            )
        finally:
            self._planning_result = None
