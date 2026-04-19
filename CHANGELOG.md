# Changelog — Battery SmartFlow AI

## v4.3.0 (2026-04-19)

### Neue Features — Transparenz & Observability

**Night-Assessment Sensoren (Punkt 1)**
Vier neue Sensoren machen die Nacht-Energiebilanz des `NightWindowController` sichtbar:
- `sensor.battery_smartflow_ai_night_assessment_projected_at_5` — projizierter Energievorrat bei 05:00 (kWh)
- `sensor.battery_smartflow_ai_night_assessment_battery_at_18` — projizierter Energievorrat bei 18:00 (kWh)
- `sensor.battery_smartflow_ai_night_assessment_charge_needed_kwh` — Gesamtladebedarf dieser Nacht (kWh)
- `sensor.battery_smartflow_ai_night_break_even_price` — Break-Even-Preis für Entladung (`avg_charge_price / round_trip_efficiency`) in €/kWh; `None` wenn noch kein avg_charge_price vorliegt

Außerhalb des 00–05-Fensters zeigen alle vier Sensoren `None` (kein Assessment aktiv).

**Season Override (Punkt 5)**
Neue Select-Entity `select.battery_smartflow_ai_jahreszeit_override` (`auto` / `summer` / `winter`).
Im `auto`-Modus (Default) läuft die bisherige Auto-Detection unverändert. Bei `summer` oder `winter`
wird `_season_detection()` übersprungen und der Wert direkt als `ctx.season` verwendet —
ohne `ai_mode` wechseln zu müssen. Der Override überlebt HA-Neustarts (gespeichert in `runtime_mode`
→ `_persist`). Motiviert durch beobachtetes Flattern zwischen `summer`/`winter` an Übergangstagen.

**Abendverbrauch konfigurierbar (Punkt 4)**
Neue Number-Entity `number.battery_smartflow_ai_evening_consumption_w` (0–2000 W, Schritt 50 W,
Default 500 W). Ersetzt die hardcodierte Formel `bridge_kwh × 2.0` in `NightWindowController.assess()`.
Der Wert beschreibt den Hausverbrauch von 18–24 Uhr (6h); `evening_need = evening_consumption_w / 1000 × 6`.
Default 500 W ergibt 3,0 kWh — identisch zum bisherigen Verhalten, kein Breaking Change.

**Tägliches Profit-Tracking (Punkt 2)**
Neuer Sensor `sensor.battery_smartflow_ai_profit_today_eur` zeigt den Arbitrage-Gewinn
des laufenden Tages. Wird täglich um Mitternacht auf 0 zurückgesetzt (Datumsprüfung in
`_track_profit()`). Der kumulierte Gesamt-Sensor `profit_eur` bleibt unverändert.

---

## v4.2.0 (2026-04-18)

### Refactoring — Code-Qualität (kein Verhaltens-Änderung)

**`NightWindowController.is_active()` — explizite Fenster-Ownership**
Die Nacht-Bedingung (00–05 Uhr + Modus-Check) ist jetzt in einer eigenen
Methode `is_active(ctx)` gekapselt. `DecisionEngine.evaluate()` ruft sie
auf und ist dadurch deutlich schlanker. Die Logik ist isoliert und testbar.

**`BydNightChargeManager.update()` aufgesplittet**
Der 90-Zeilen-Monolith wurde in drei Hilfsmethoden zerlegt:
- `_calc_targets()` — berechnet Lade-Ziele aus Assessment und SoC-Snapshot
- `_decide_byd_mode()` — bestimmt Ziel-Modus, aktualisiert State-Flags
- `_persist_night_plan()` — schreibt Nachtplan in `_persist`

**`_CycleState`-Dataclass + `_async_update_data()` aufgesplittet**
Der 300-Zeilen-Monolith `_async_update_data()` in `coordinator.py` wurde in
8 fokussierte Methoden zerlegt. `_CycleState` fasst alle Sensor-Werte und
abgeleiteten Größen eines Zyklus zusammen und wird durch die Methoden
durchgereicht — keine losen Variablen mehr zwischen den Abschnitten:
- `_sensor_invalid_payload()` — Frühausstieg bei fehlenden Pflichtsensoren
- `_read_sensors(now)` — liest alle Sensoren, gibt `_CycleState` zurück
- `_build_decision_context(state)` — baut `DecisionContext` aus `_CycleState`
- `_apply_soc_guards(decision, state)` — BMS-Limit- und Hysterese-Guards
- `_track_profit(decision, state)` — Profit-Tracking für Laden und Entladen
- `_apply_setpoints(decision, now)` — schreibt Zendure-Sollwerte
- `_build_response_payload(ctx, decision, state, ...)` — baut Coordinator-Payload
- `_async_update_data()` — schlanker Orchestrator (~20 Zeilen)

**Bool-Flags korrigiert**
`runtime_settings` ist jetzt `dict[str, Any]` statt `dict[str, float]`.
`pv_forecast_enabled` und `wallbox_block_enabled` werden mit `bool()`
ausgewertet statt `float() >= 1.0`, was der tatsächlichen Semantik entspricht.

---

## v4.1.0 (2026-04-18)

### Refactoring — Code-Qualität (kein Verhaltens-Änderung)

**`DecisionResult` ist jetzt immutable (`frozen=True`)**
Direkte Attribut-Mutationen nach `engine.evaluate()` wurden durch
`dataclasses.replace()` ersetzt. Die drei Guards (`soc_limit_upper`,
`soc_limit_lower`, `soc_min_resume_block`) in `coordinator.py` erzeugen
jetzt explizit neue Objekte statt das Ergebnis still zu überschreiben.
Debugging und Nachvollziehbarkeit werden dadurch deutlich einfacher.

**`build_device_info()` — zentrale Device-Metadaten**
Statt den identischen Device-Info-Block in `sensor.py`, `number.py`,
`select.py` und `switch.py` je einzeln zu pflegen, gibt es jetzt einen
einzigen Helper in `const.py`. Eine Änderung (z.B. `sw_version`) wirkt
sich automatisch auf alle Entities aus.

**`_SETTING_DEFAULTS`-Dict in `number.py`**
Die 15-gliedrige `if/elif`-Chain für Setting-Defaults beim Setup wurde
durch ein Dict-Lookup ersetzt. Neue Settings müssen nur noch an einer
Stelle (im Dict) eingetragen werden.

**Version-Konsistenz hergestellt**
`const.py` und `manifest.json` zeigten unterschiedliche Versionsnummern
(`3.6.0-custom` vs. `4.0.0-custom`). Beide sind jetzt auf `4.1.0-custom`
synchronisiert.

---

## v4.0.0 (2026-04-17)

Initiale Version des Custom Forks.
Einführung von `NightWindowController`, `BydNightChargeManager`,
PV-Forecast-basierter Nachtladung, Season Detection und
`NightEnergyAssessment` als Single Source of Truth.
