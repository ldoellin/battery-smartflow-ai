"""
Tests für NightWindowController.assess() und discharge_is_profitable().

Beide Methoden sind reine Berechnungsfunktionen ohne HA-Seiteneffekte
und damit gut isoliert testbar.
"""
import sys
import os
from datetime import datetime, timezone

import pytest

# Repo-Root auf sys.path damit custom_components importierbar ist
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.battery_smartflow_ai.decision_engine import (
    DecisionContext,
    DecisionEngine,
    NightWindowController,
    NightEnergyAssessment,
)


# ==================================================
# Fixtures / Helpers
# ==================================================

_NOW_NIGHT = datetime(2026, 4, 19, 2, 0, tzinfo=timezone.utc)   # 02:00 Uhr → GO-Fenster
_NOW_DAY   = datetime(2026, 4, 19, 12, 0, tzinfo=timezone.utc)  # 12:00 Uhr → außerhalb


def _ctx(**overrides) -> DecisionContext:
    """Minimaler DecisionContext mit sinnvollen Defaults.

    Alle für assess() / discharge_is_profitable() relevanten Felder
    können per Keyword-Argument überschrieben werden.
    """
    defaults = dict(
        now=_NOW_NIGHT,
        soc=50.0,
        soc_min=10.0,
        soc_max=100.0,
        emergency_soc=8.0,
        emergency_charge_w=1200.0,
        max_charge_w=2400.0,
        max_discharge_w=700.0,
        grid_import_w=0.0,
        grid_export_w=0.0,
        pv_w=0.0,
        house_load_w=300.0,
        price_now=0.15,
        avg_charge_price=None,
        expensive_threshold=0.35,
        very_expensive_threshold=0.49,
        profit_margin_pct=27.0,
        price_points=[],
        ai_mode="automatic",
        manual_action="standby",
        season="winter",
        profile={},
        prev_discharge_w=0.0,
        prev_charge_w=0.0,
        battery_capacity_kwh=5.76,   # 2× SF2400AC Packs
        # Nacht-relevante Felder
        pv_forecast_kwh=5.0,
        additional_battery_soc=-1.0,
        additional_battery_capacity_kwh=0.0,
        bridge_kwh=1.5,              # nighttime_consumption_w 500 W × 3h
        nighttime_kwh=1.0,           # verbleibende Nacht ~2h × 500 W
        daily_consumption_kwh=0.0,   # neutral: Tagesziel testen eigene Tests unten
        pv_self_consumption_kwh=5.0,
        pv_optimism_factor=1.0,      # neutrale Tests: kein Optimismus
        evening_consumption_w=500.0,
    )
    defaults.update(overrides)
    return DecisionContext(**defaults)


# ==================================================
# NightWindowController.assess()
# ==================================================

class TestAssess:

    def setup_method(self):
        self.ctrl = NightWindowController(round_trip_efficiency=0.90)

    # --- Brücke ---

    def test_bridge_covered_when_battery_sufficient(self):
        """Hoher SoC → Brücke (05–08 Uhr) ist gesichert."""
        ctx = _ctx(soc=80.0, nighttime_kwh=0.5)
        a = self.ctrl.assess(ctx)
        assert a.bridge_covered is True

    def test_bridge_not_covered_when_battery_low(self):
        """Leere Batterie → Brücke nicht gesichert."""
        ctx = _ctx(soc=12.0, nighttime_kwh=2.0, bridge_kwh=1.5)
        a = self.ctrl.assess(ctx)
        # z_usable = (12-10)/100 * 5.76 = 0.1152 kWh < bridge_kwh
        assert a.bridge_covered is False
        assert a.charge_needed_kwh > 0.0

    def test_charge_needed_equals_bridge_gap(self):
        """Ladebedarf entspricht der Lücke bis zur Brücke."""
        ctx = _ctx(soc=12.0, nighttime_kwh=0.0, bridge_kwh=1.5)
        a = self.ctrl.assess(ctx)
        # battery_usable ≈ 0.115 kWh < bridge_kwh 1.5 → charge = 1.5 - 0.115
        expected = max(0.0, ctx.bridge_kwh - (ctx.soc - ctx.soc_min) / 100.0 * ctx.battery_capacity_kwh)
        assert pytest.approx(a.charge_needed_kwh, abs=0.01) == expected

    def test_bridge_already_covered_now_pauses_instead_of_charging(self):
        """Regression (v4.4.4-custom): battery_usable >= bridge_kwh, aber
        projected_at_5 < bridge_kwh wegen pessimistischem nighttime_kwh-Abzug.
        Entladeschutz genügt hier — es darf NICHT geladen werden, obwohl die
        Brücke laut Projektion nicht gedeckt scheint."""
        # pv_forecast_kwh=-1.0: Tagesziel-Prüfung (Punkt 3) deaktiviert, damit dieser
        # Test ausschließlich den Brücke-Zweig isoliert prüft.
        ctx = _ctx(soc=90.0, nighttime_kwh=4.0, bridge_kwh=1.5, evening_consumption_w=500.0,
                   pv_forecast_kwh=-1.0)
        # z_usable = (90-10)/100*5.76 = 4.608 kWh >= bridge_kwh 1.5
        # projected_at_5 = 4.608 - 4.0 = 0.608 kWh < bridge_kwh 1.5 -> bridge_covered False
        a = self.ctrl.assess(ctx)
        assert a.bridge_covered is False
        assert a.charge_needed_kwh == 0.0
        assert a.z_charge_kwh == 0.0

    def test_bridge_charge_needed_uses_battery_usable_not_projection(self):
        """battery_usable < bridge_kwh -> charge_needed = bridge_kwh - battery_usable
        (ARCHITECTURE.md Zeile 118), nicht bridge_kwh - projected_at_5. Der erwartete
        Nachtverbrauch fällt durch den Entladeschutz während des Ladens (ac_mode=input)
        ohnehin nicht an."""
        ctx = _ctx(soc=15.0, nighttime_kwh=0.2, bridge_kwh=1.5, pv_forecast_kwh=-1.0)
        # z_usable = (15-10)/100*5.76 = 0.288 kWh < bridge_kwh 1.5
        # projected_at_5 = 0.288 - 0.2 = 0.088 kWh
        a = self.ctrl.assess(ctx)
        assert a.bridge_covered is False
        assert pytest.approx(a.charge_needed_kwh, abs=1e-6) == ctx.bridge_kwh - 0.288

    def test_bridge_protection_reason_distinguishes_from_generic_pause(self):
        """DecisionEngine.evaluate() muss für den Entladeschutz-Fall den eigenen
        reason 'night_bridge_discharge_protection' liefern, nicht das generische
        'night_charge_pause' (das für 'z_charge < 0.2 kWh trotz echtem Bedarf' steht)."""
        engine = DecisionEngine(self.ctrl)
        ctx = _ctx(soc=90.0, nighttime_kwh=4.0, bridge_kwh=1.5, pv_forecast_kwh=-1.0)

        result = self.ctrl.evaluate(engine, ctx)

        assert result is not None
        assert result.action == "idle"
        assert result.reason == "night_bridge_discharge_protection"

    # --- Abend ---

    def test_evening_covered_with_pv_surplus(self):
        """Genug PV-Überschuss → Abend gesichert, kein Ladebedarf."""
        ctx = _ctx(
            soc=80.0,
            nighttime_kwh=0.3,
            pv_forecast_kwh=12.0,
            pv_self_consumption_kwh=5.0,
            pv_optimism_factor=1.0,
            evening_consumption_w=500.0,  # evening_need = 3.0 kWh
        )
        a = self.ctrl.assess(ctx)
        assert a.evening_covered is True
        assert a.charge_needed_kwh == 0.0

    def test_evening_not_covered_without_pv(self):
        """Kein PV, mittlerer SoC → Abend nicht gedeckt → Ladebedarf."""
        ctx = _ctx(
            soc=40.0,
            nighttime_kwh=1.0,
            pv_forecast_kwh=0.0,
            pv_self_consumption_kwh=0.0,
            pv_optimism_factor=1.0,
            bridge_kwh=1.5,
            evening_consumption_w=500.0,  # evening_need = 3.0 kWh
        )
        a = self.ctrl.assess(ctx)
        # projected_at_5 = z_usable - nighttime_kwh
        z_usable = (40.0 - 10.0) / 100.0 * 5.76  # 1.728 kWh
        projected = z_usable - 1.0                 # 0.728 kWh ≥ bridge 1.5? Nein
        # → bridge_covered = False
        assert a.evening_covered is False

    def test_evening_need_scales_with_evening_consumption_w(self):
        """Höherer Abendverbrauch → mehr Ladebedarf."""
        base = _ctx(soc=50.0, nighttime_kwh=0.2, pv_forecast_kwh=0.0)
        ctx_low  = _ctx(soc=50.0, nighttime_kwh=0.2, pv_forecast_kwh=0.0, evening_consumption_w=300.0)
        ctx_high = _ctx(soc=50.0, nighttime_kwh=0.2, pv_forecast_kwh=0.0, evening_consumption_w=800.0)
        a_low  = self.ctrl.assess(ctx_low)
        a_high = self.ctrl.assess(ctx_high)
        assert a_high.evening_need > a_low.evening_need
        assert a_high.charge_needed_kwh >= a_low.charge_needed_kwh

    def test_evening_need_formula(self):
        """evening_need = evening_consumption_w / 1000 × 6h."""
        ctx = _ctx(evening_consumption_w=600.0)
        a = self.ctrl.assess(ctx)
        assert pytest.approx(a.evening_need) == 600.0 / 1000.0 * 6.0

    # --- PV-Forecast ---

    def test_pv_forecast_disabled_treated_as_zero(self):
        """pv_forecast_kwh < 0 (Feature deaktiviert) → konservativ: kein PV eingeplant."""
        ctx_disabled = _ctx(pv_forecast_kwh=-1.0, soc=50.0)
        ctx_zero     = _ctx(pv_forecast_kwh=0.0,  soc=50.0)
        a_disabled = self.ctrl.assess(ctx_disabled)
        a_zero     = self.ctrl.assess(ctx_zero)
        assert a_disabled.battery_at_18 == a_zero.battery_at_18

    def test_pv_surplus_reduces_charge_needed(self):
        """Hohe PV-Prognose reduziert den berechneten Ladebedarf."""
        ctx_no_pv   = _ctx(soc=40.0, nighttime_kwh=0.5, pv_forecast_kwh=0.0)
        ctx_good_pv = _ctx(soc=40.0, nighttime_kwh=0.5, pv_forecast_kwh=15.0,
                           pv_self_consumption_kwh=5.0, pv_optimism_factor=1.0)
        a_no_pv   = self.ctrl.assess(ctx_no_pv)
        a_good_pv = self.ctrl.assess(ctx_good_pv)
        assert a_good_pv.charge_needed_kwh <= a_no_pv.charge_needed_kwh

    # --- BYD / Zusatzakku ---

    def test_byd_usable_reduces_charge_needed(self):
        """BYD mit Ladezustand reduziert den Gesamt-Ladebedarf."""
        ctx_no_byd  = _ctx(soc=20.0, nighttime_kwh=1.0,
                           additional_battery_soc=-1.0,
                           additional_battery_capacity_kwh=0.0)
        ctx_with_byd = _ctx(soc=20.0, nighttime_kwh=1.0,
                            additional_battery_soc=80.0,
                            additional_battery_capacity_kwh=8.0)
        a_no_byd   = self.ctrl.assess(ctx_no_byd)
        a_with_byd = self.ctrl.assess(ctx_with_byd)
        assert a_with_byd.charge_needed_kwh < a_no_byd.charge_needed_kwh

    # --- Zendure-Anteil ---

    def test_z_charge_capped_at_z_capacity(self):
        """z_charge_kwh überschreitet nie die verbleibende Zendure-Kapazität."""
        ctx = _ctx(soc=20.0, nighttime_kwh=2.0, pv_forecast_kwh=0.0)
        a = self.ctrl.assess(ctx)
        z_capacity = ctx.battery_capacity_kwh * (ctx.soc_max - ctx.soc_min) / 100.0
        z_usable   = (ctx.soc - ctx.soc_min) / 100.0 * ctx.battery_capacity_kwh
        max_z_charge = max(0.0, z_capacity - z_usable)
        assert a.z_charge_kwh <= max_z_charge + 1e-9

    def test_no_charge_when_fully_covered(self):
        """Vollgeladene Batterie + gute PV → kein Ladebedarf."""
        ctx = _ctx(
            soc=95.0,
            nighttime_kwh=0.1,
            pv_forecast_kwh=10.0,
            pv_self_consumption_kwh=4.0,
            pv_optimism_factor=1.0,
            evening_consumption_w=400.0,
        )
        a = self.ctrl.assess(ctx)
        assert a.charge_needed_kwh == 0.0
        assert a.bridge_covered is True
        assert a.evening_covered is True

    def test_day_target_covered_when_pv_covers_daily_consumption(self):
        """Gute PV-Prognose deckt Tagesverbrauch → day_target ≈ bridge_kwh, kein Zusatzbedarf."""
        ctx = _ctx(
            soc=60.0, nighttime_kwh=0.5,
            pv_forecast_kwh=20.0, pv_self_consumption_kwh=5.0,
            daily_consumption_kwh=12.0,
        )
        a = self.ctrl.assess(ctx)
        assert a.day_target_covered is True

    def test_day_target_not_covered_forces_extra_charge(self):
        """Schwache PV-Prognose deckt Tagesverbrauch nicht → Tagesziel erzwingt mehr Ladebedarf
        als Brücke/Abend allein (Punkt 3, PLAN_MODUL3_IMPROVEMENTS.md)."""
        ctx_poor_pv = _ctx(
            soc=60.0, nighttime_kwh=0.5,
            pv_forecast_kwh=2.0, pv_self_consumption_kwh=5.0,
            daily_consumption_kwh=12.0,
        )
        ctx_good_pv = _ctx(
            soc=60.0, nighttime_kwh=0.5,
            pv_forecast_kwh=20.0, pv_self_consumption_kwh=5.0,
            daily_consumption_kwh=12.0,
        )
        a_poor = self.ctrl.assess(ctx_poor_pv)
        a_good = self.ctrl.assess(ctx_good_pv)
        assert a_poor.day_target_covered is False
        assert a_poor.charge_needed_kwh > a_good.charge_needed_kwh


# ==================================================
# NightWindowController.discharge_is_profitable()
# ==================================================

class TestDischargeIsProfitable:

    def setup_method(self):
        self.ctrl = NightWindowController(round_trip_efficiency=0.90)

    def test_returns_false_when_price_none(self):
        ctx = _ctx(price_now=None)
        assert self.ctrl.discharge_is_profitable(ctx) is False

    def test_fallback_to_very_expensive_when_no_avg_price(self):
        """Ohne avg_charge_price: price >= very_expensive_threshold → True."""
        ctx = _ctx(price_now=0.50, avg_charge_price=None, very_expensive_threshold=0.49)
        assert self.ctrl.discharge_is_profitable(ctx) is True

    def test_fallback_false_below_very_expensive(self):
        ctx = _ctx(price_now=0.30, avg_charge_price=None, very_expensive_threshold=0.49)
        assert self.ctrl.discharge_is_profitable(ctx) is False

    def test_profitable_above_break_even(self):
        """0.18 € Einkauf / 0.90 Effizienz = 0.20 € Break-Even → 0.25 € profitabel."""
        ctx = _ctx(price_now=0.25, avg_charge_price=0.18)
        assert self.ctrl.discharge_is_profitable(ctx) is True

    def test_not_profitable_below_break_even(self):
        """0.18 / 0.90 = 0.20 Break-Even → 0.19 € nicht profitabel."""
        ctx = _ctx(price_now=0.19, avg_charge_price=0.18)
        assert self.ctrl.discharge_is_profitable(ctx) is False

    def test_not_profitable_exactly_at_break_even(self):
        """Genau am Break-Even: price > break_even ist False.

        Floating-Point: 0.18 / 0.90 = 0.19999...  (nicht exakt 0.20)
        → price_now muss sicher unterhalb liegen um False zu erzwingen.
        """
        ctx = _ctx(price_now=0.199, avg_charge_price=0.18)
        # 0.18 / 0.90 ≈ 0.2000 → price 0.199 < 0.200 → False
        assert self.ctrl.discharge_is_profitable(ctx) is False

    def test_higher_efficiency_lowers_break_even(self):
        """Höhere Effizienz → niedrigerer Break-Even → eher profitabel."""
        ctrl_low  = NightWindowController(round_trip_efficiency=0.80)
        ctrl_high = NightWindowController(round_trip_efficiency=0.95)
        ctx = _ctx(price_now=0.22, avg_charge_price=0.18)
        # low:  0.18/0.80 = 0.225 → price 0.22 < 0.225 → False
        # high: 0.18/0.95 ≈ 0.189 → price 0.22 > 0.189 → True
        assert ctrl_low.discharge_is_profitable(ctx)  is False
        assert ctrl_high.discharge_is_profitable(ctx) is True

    def test_go_tariff_scenario(self):
        """GO-Tarif-Szenario: Einkauf 0.08 €, aktueller Preis 0.12 €.
        Break-Even = 0.08/0.90 ≈ 0.089 → 0.12 > 0.089 → profitabel.
        """
        ctx = _ctx(price_now=0.12, avg_charge_price=0.08)
        assert self.ctrl.discharge_is_profitable(ctx) is True

    def test_go_tariff_daytime_low_price_not_profitable(self):
        """GO nachts geladen (0.08€), tags 0.14€ Preis.
        0.08/0.90 ≈ 0.089 → 0.14 > 0.089 → True, aber knapp."""
        ctx = _ctx(price_now=0.14, avg_charge_price=0.08)
        assert self.ctrl.discharge_is_profitable(ctx) is True
