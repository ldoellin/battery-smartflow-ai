# Changelog — Battery SmartFlow AI

## v4.4.5-custom (2026-07-23)

### Fix — Konfiguriertes Peak-Schutzfenster (15-20 Uhr) wurde bei vorhandenen Preisdaten ignoriert

**Problem:** `grid_protect_active`/`top_hours` (Netzbezugsschutz-Rationierung, Modul 3)
wurden bei vorhandenen Preisdaten ausschließlich aus `very_expensive_threshold`
abgeleitet — das über `SETTING_PEAK_PROTECT_START`/`SETTING_PEAK_PROTECT_END`
konfigurierte Zeitfenster (Default 15-20 Uhr) galt nur als Fallback **ohne**
Preisdaten und wurde komplett ignoriert, sobald eine Preisreihe vorlag. Unterschreitet
der Preis innerhalb von 15-20 Uhr kurz die `very_expensive`-Schwelle (z.B. ein
Preis-Einbruch mitten im teuren Fenster), wurde diese Stunde nicht mitgezählt —
der Akku hätte in genau dieser Stunde ungeschützt sein können.

**Fix:** Das konfigurierte Fenster gilt jetzt zusätzlich als Mindest-Garantie:
`top_hours = max(preisgetriebene_top_hours, restliche_stunden_im_konfigurierten_fenster)`.
Die preisgetriebene Erkennung kann den Schutz weiterhin über 20 Uhr hinaus
verlängern, falls die Preise dort noch teuer sind — das Fenster hebt den Schutz
nur an, nie ab. **Files:** `coordinator.py`.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>

---

## v4.4.4-custom (2026-07-23)

### Bugfix — Entladeschutz-Fall in `NightWindowController.assess()` fehlte (Regression)

**Problem:** ARCHITECTURE.md dokumentiert für Schritt 1 (Brücke 05–08 Uhr) zwei Fälle
für `projected_at_5 < bridge_kwh`: bei `battery_usable >= bridge_kwh` genügt reiner
Entladeschutz (`idle`, kein Laden), erst bei `battery_usable < bridge_kwh` wird
tatsächlich geladen. Der Code kannte nur noch den zweiten Fall — `charge_needed`
wurde immer aus dem pessimistischen `projected_at_5` berechnet (das den erwarteten
Nachtverbrauch bereits abzieht), auch wenn der aktuelle Stand die Brücke längst
gedeckt hätte. Ergebnis: unnötiges Nachladen, obwohl reines Pausieren (Zendure/BYD
entladen ohnehin nicht, `ac_mode=input`) ausgereicht hätte. Diese Fallunterscheidung
war vor einigen Wochen vorhanden und ist bei einem Refactoring versehentlich entfernt
worden.

**Fix:** `assess()` prüft `battery_usable >= ctx.bridge_kwh` vor der
`projected_at_5`-Rechnung und setzt `charge_needed = 0.0`, falls die Brücke bereits
gedeckt ist. `_apply_constraints()` gibt für diesen Fall den eigenen reason
`night_bridge_discharge_protection` zurück (statt des generischen
`night_charge_pause`), damit er im Rule-Trace-Debug-Log von "z_charge < 0.2 kWh trotz
echtem Bedarf" unterscheidbar ist. Zusätzlich wurde der Nachbar-Zweig
(`battery_usable < bridge_kwh`) von `charge_needed = bridge_kwh - projected_at_5` auf
`charge_needed = bridge_kwh - battery_usable` umgestellt (ARCHITECTURE.md Zeile 118)
— der erwartete Nachtverbrauch fällt durch den Entladeschutz während des Ladens
(`ac_mode=input`) ohnehin nicht an, die alte Formel lud daher unnötig mehr.
**Files:** `decision_engine.py`.

**Test:** `tests/test_night_window_controller.py` deckt beide Zweige (Entladeschutz
vs. echter Ladebedarf) sowie den unveränderten `bridge_covered=True`-Fall ab —
erster automatisierter Test im Projekt.

---

## v4.4.3-custom (2026-07-22)

### Bugfix — BYD ignorierte das neue Tagesziel (Anschluss an v4.4.2-custom)

**Problem:** `BydNightChargeManager._decide_byd_mode()` pausierte BYD nur bei
`bridge_covered=False`, nicht bei `day_target_covered=False` (dem in v4.4.2-custom
eingeführten, umfassenderen Tagesziel inkl. Peak-Fenster ab 15 Uhr). Beobachtet in
der Nacht 21.→22.07.: Zendure lud korrekt gegen das eingebrochene PV-Forecast nach,
BYD blieb aber auf `bridge_covered=True` hängen (Brücke allein war gedeckt) und lief
auf eigener Automatik weiter, statt zu pausieren.

**Fix:** `_calc_targets()` gibt jetzt zusätzlich `day_target_covered` zurück,
`_decide_byd_mode()` bekommt es als Parameter und pausiert BYD bei
`not bridge_covered or not day_target_covered`. **Files:** `byd_manager.py`.

Zendure-Priorität vor BYD (`z_charge = min(gap, need)`, `byd = max(0, need - z_charge)`,
BUG-004) und Brücken-Schutz auch im manuellen Modus (BUG-013) waren bereits korrekt
implementiert — kein Fix nötig, siehe DEBUG_NOTES.md.

---

## v4.4.2-custom (2026-07-21)

### Feature — Nachtladung deckt Peak-Fenster ab 15 Uhr vor (Punkt 3, PLAN_MODUL3_IMPROVEMENTS.md)

**Problem:** `NightWindowController` lud im GO-Fenster (0–5 Uhr) bisher nur bis
`bridge_kwh` (Brücke 05–08) + `evening_need` (18–24 Uhr). Reichte die
PV-Prognose nicht für den restlichen Tag inkl. Preis-Peak (15–20 Uhr), musste
`PlanningRule` danach zu einem teureren Tagespreis nachladen (beobachtet:
Nachladung im 5–7-Uhr-Fenster zu 0,224 €/kWh statt im 0,104-€/kWh-GO-Fenster).

**Fix:** Neue Modulfunktion `_pv_aware_day_target_kwh` (dieselbe Formel wie
`DecisionEngine._calc_pv_aware_zendure_target_soc`, jetzt aus beiden Stellen
aufgerufen statt dupliziert). `NightWindowController.assess()` prüft zusätzlich
das PV-bewusste Tagesziel (`day_target_covered`, neues Feld in
`NightEnergyAssessment`) und lädt im GO-Fenster nach, falls die PV-Prognose den
Tagesverbrauch nicht deckt. Bei ausreichender PV-Prognose ≈ `bridge_kwh` →
kein Effekt auf bestehendes Verhalten.

`_apply_constraints()`: `needs_charge` berücksichtigt jetzt zusätzlich
`day_target_covered`.

Kein neuer Schalter — hängt am bestehenden PV-Forecast-Feature
(`pv_forecast_kwh < 0` → deaktiviert wie zuvor).

---

## v4.4.1-custom (2026-06-26)

### Bugfix

**30W Deadband für `_byd_blocks_discharge` (decision_engine.py)**
`_byd_blocks_discharge` blockierte Zendure-Entladung bei jedem BYD-Ladewert > 0 W —
also auch bei Messrauschen und Restwerten direkt nach dem Pausieren der BYD.
Schwellwert analog zu `_byd_blocks_charge` (120 W) auf 30 W angehoben.
Praktische Auswirkung: Manual constant_discharge startet jetzt sofort nach dem
BYD-Pause-Befehl, ohne auf das vollständige Abklingen der Leistung warten zu müssen.

---

## v4.4.0 (2026-06-11)

### Stabilität — P1-Fixes aus Code Review (REVIEW_REPORT.md)

**Flash-Schonung: Store-Save entkoppelt (I1)**
`_persist` wurde bisher bei jedem 10-s-Zyklus auf `.storage` geschrieben (~8 600
Writes/Tag). Jetzt verzögertes Speichern via `Store.async_delay_save` (60 s,
gebündelt); sofortiges Speichern nur noch bei Moduswechsel und Shutdown
(`async_shutdown` flusht). Der Store schreibt offene Saves bei HA-Stop automatisch.

**Latenter Crash im Preis-Parser behoben (S1)**
`dt_util.replace(dt, tzinfo=tz)` existiert nicht in `homeassistant.util.dt` —
naive Zeitstempel in Preisdaten hätten einen AttributeError und damit
Unavailability aller Entities ausgelöst. Korrigiert zu `dt.replace(tzinfo=tz)`.

**Setpoint-Setter: Cache nur bei Erfolg (S3)**
`last_set_mode/input_w/output_w` wurden vor dem Service-Call gesetzt
(`blocking=False`, keine Fehlerbehandlung) — fehlgeschlagene Kommandos wurden
nie wiederholt. Jetzt `blocking=True` mit try/except; bei Fehler bleibt der
Cache alt → automatischer Retry im nächsten Zyklus. Redundantes Überschreiben
von `last_set_output_w` in `_apply_setpoints` entfernt.

**Fehler-Isolation im Update-Zyklus (S2)**
Preis-Parsing, BYD-Nachtlade-Update und Profit-Tracking sind einzeln
abgesichert und degradieren (Zyklus läuft weiter, `engine_health` zeigt
Preisprobleme an), statt alle ~30 Entities unavailable zu schalten.
Unerwartete Fehler werden jetzt mit Traceback geloggt (`_LOGGER.exception`).

**BYD-Leistungs-Call abgesichert (S4)**
`input_number.set_value` in `byd_manager.update()` analog `_set_mode` mit
try/except; Cache-Update nur bei Erfolg.

**Moduswechsel sofort persistiert (S6)**
ai_mode/manual_action/season_override werden bei Auswahl sofort gespeichert —
ein Neustart ≤10 s nach Umschalten verliert den Modus nicht mehr.

**Single-Instance-Schutz im Config Flow (S7)**
unique_id aus der AC-Mode-Entität + `_abort_if_unique_id_configured`, plus
Daten-Vergleich für Alt-Einträge ohne unique_id. Verhindert zwei Einträge,
die dasselbe Zendure-Gerät gegeneinander steuern. Abort-Übersetzungen in
de/en/fr/strings.json ergänzt.

**Robustes Config-Parsing (S9)**
`_get_battery_capacity()` nutzt `_to_float` statt ungeschütztem `float()` —
kein Setup-Crash mehr bei korruptem `pack_capacity_kwh`.

---

## v4.3.2 (2026-06-08)

### Übernahme aus offiziellem PalmManiac-Branch

**Hauslast-Berechnung bei AC-Ladung (PalmManiac 4.0.6)**
Bei AC-Ladung der Zendure-Batterie wurde die Ladeleistung über `grid_import`
fälschlich als zusätzlicher Hausverbrauch gewertet. Korrigiert durch Abzug von
`battery_charge_w` in [coordinator.py](custom_components/battery_smartflow_ai/coordinator.py)
`_read_sensors()`. Betrifft alle abgeleiteten Entscheidungen während aktiver
AC-Netzladung.

**DB-Wachstum durch große Sensor-Attribute (PalmManiac 4.2.0-Beta2)**
Bisher wurde der vollständige interne `details`-Dict an alle ~25 Sensoren als
`extra_state_attributes` gehängt. Bei 10-s-Updates ließ das die Home-Assistant-
Recorder-DB unnötig schnell wachsen. Nur noch `device_profile` bekommt eine
gekürzte Profil-/Diagnoseübersicht.

**Stabile Zeitstempel (PalmManiac 4.2.0-Beta2)**
`next_action_time` wird nicht mehr bei jedem Regelzyklus auf die aktuelle
Uhrzeit gesetzt, sondern nur beim Start einer Aktion. Helper `_stable_iso_minute`
rundet zusätzlich auf volle Minuten, um Sekunden-Jitter im Recorder zu vermeiden.

---

## v4.3.1 (2026-04-19)

### Refactoring — Code-Qualität (kein Verhaltens-Änderung für Endnutzer)

**NightWindowController 4-Layer-Architektur**
`evaluate()` ist jetzt in vier klar getrennte Schichten aufgeteilt:

1. `assess()` — reine Energiebilanz (Physik, keine Seiteneffekte)
2. `_apply_constraints()` — Energie-Constraints (Emergency, bridge/evening-Ladebedarf)
3. `_apply_system_guards()` — Geräte-Koordination (Wallbox, BYD, BYD-Zyklus-Flags)
4. `_apply_policy()` — Strategie (Manual, Auto-Entladen, Idle) — keine Guard-Aufrufe

Korrekturen im Rahmen des Refactorings:
- Wallbox-Guard hat in `_apply_system_guards` Priorität vor BYD-Guard — stellt ursprüngliches
  Verhalten (Output-Modus halten bei aktiver Wallbox) korrekt wieder her
- `night_charge_required` / `night_charge_active` aus `_apply_constraints` in
  `_apply_system_guards` verschoben (BYD-Systemzustand ≠ Energie-Physik)
- `_bridge_reserve_blocks_discharge()` im NWC-Pfad als mathematisch redundant
  identifiziert und entfernt (`bridge_covered = True` impliziert `bridge_reserve = False`)

**Unit Tests — NightWindowController**
21 Tests für `assess()` und `discharge_is_profitable()` in `tests/test_night_controller.py`.
Pytest läuft lokal ohne HA-Installation (direkte `importlib`-Loader in `conftest.py`).

---

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
