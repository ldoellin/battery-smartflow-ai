# Architektur — Battery SmartFlow AI (Custom Fork)

Dieses Dokument beschreibt die interne Architektur der Integration, insbesondere die
Zusammenarbeit zwischen `decision_engine.py` und `coordinator.py`.

---

## Überblick

```
coordinator.py          decision_engine.py
──────────────          ──────────────────
Sensor-Lesen            DecisionContext
Zustand verwalten  ───► Rule-Chain evaluieren  ───► DecisionResult
Setpoints setzen  ◄───  (Zendure)
BYD-Modus setzen        (BYD via _manage_byd_night_charge)
```

**Prinzip:** Der Coordinator sammelt alle Sensorwerte, baut einen `DecisionContext` auf und
übergibt ihn der Engine. Die Engine gibt ein `DecisionResult` zurück, das der Coordinator
auf Zendure anwendet. BYD wird separat gesteuert (eigene Zustandsmaschine, da BYD kein
Watt-basiertes Setpoint-Interface hat).

---

## Decision Engine — Rule-Chain

Regeln werden der Reihe nach ausgewertet. Die erste Regel, die ein Ergebnis liefert,
gewinnt. Nachfolgende Regeln werden nicht mehr evaluiert.

| Prio | Regel | Bedingung / Zweck |
|------|-------|-------------------|
| 1 | `EmergencyRule` | SoC kritisch niedrig → Notladung |
| 2 | `PeakRule` | Hoher Strompreis + kein PV-Überschuss + kein Export → Entladen |
| 3 | `ArbitrageRule` | Günstig kaufen / teuer verkaufen (Arbitrage) |
| 4 | `PlanningRule` | Vorausplanung: billigstes Ladefenster im Tagesverlauf |
| 5 | `NightChargeRule` | 0–5 Uhr UTC: Mindestkapazität für Morgenstunden sichern |
| 6 | `ValleyBoostRule` | Winter: Günstigster Nachtstrom → Laden |
| 7 | `PvRule` | PV-Überschuss → Laden |
| 8 | `SummerRule` | Sommermodus: Hauslast aus Batterie decken |
| 9 | `ManualRule` | Manuell gesetzter Modus (constant_discharge, charge, etc.) |

### Gemeinsame Guards (alle Entladeregeln)

- `_byd_blocks_discharge()` — BYD lädt gerade → kein Zendure-Entladen
- `_wallbox_blocks_discharge()` — Wallbox aktiv + Schalter ein → kein Entladen
- `_bridge_reserve_blocks_discharge()` — Kapazität ≤ Brückenreserve → kein Entladen
- `_is_real_export()` — Netto-Export > 100 W → kein Entladen (PeakRule, ArbitrageRule, SummerRule)

### PV-first Guard (PeakRule, ArbitrageRule)

```python
if ctx.soc < ctx.soc_max and engine._delta_charge(ctx) > 0:
    return None  # PV lädt → kein Entladen
```

---

## NightChargeRule — Strategie (0–5 Uhr UTC)

### Drei Zeitabschnitte

| Zeitraum | Verbrauchsrate | Variable |
|----------|---------------|----------|
| Jetzt → 05:00 | `nighttime_consumption_w` | `ctx.nighttime_kwh` (dynamisch) |
| 05:00 → 08:00 | `nighttime_consumption_w` | `ctx.bridge_kwh` = `nighttime_w × 3h` |
| 08:00 → 18:00 | `daytime_consumption_w` | `ctx.pv_self_consumption_kwh` = `daytime_w × 10h` |

### Zielwerte

```python
morning_need = min(total_max,
    ctx.bridge_kwh + max(0, ctx.pv_self_consumption_kwh - ctx.pv_forecast_kwh))

total_need = min(total_max,
    ctx.nighttime_kwh + morning_need)

battery_usable = z_usable + byd_usable
```

`morning_need` enthält bewusst **kein** `nighttime_kwh`: Nach dem Laden pausiert die
Entladung bis 05:00 Uhr, der Nachtverbrauch (0–5 Uhr) wird direkt aus dem Netz gedeckt
— zum gleichen Preis, ohne den Umweg über Batterie.

### Dreistufige Entscheidungslogik

| Bedingung | Aktion | Grund |
|-----------|--------|-------|
| `battery_usable ≥ total_need` | `return None` → ManualRule entscheidet | Kapazität reicht für alles |
| `battery_usable ≥ morning_need` | `return idle` | Entladung pausieren, Vorrat schützen |
| `z_charge ≥ 0.2 kWh` | `return charge` | Defizit → minimal laden |
| `z_charge < 0.2 kWh` | `return idle` | Defizit klein → BYD deckt Rest, Zendure pausiert |

---

## BYD-Steuerung — `_manage_byd_night_charge`

BYD hat kein Watt-Setpoint-Interface, daher steuert der Coordinator BYD direkt über
Modi (`charge` / `pause` / `stop`) als separate Zustandsmaschine.

### Funktionsweise

Wird bei **jedem Coordinator-Zyklus** (10 s) aufgerufen, wenn PV-Nachtladen aktiv.

```
charge_needed = max(0, morning_need - total_avail)        # gleiche Formel wie NightChargeRule
effective_z_charge = z_charge  wenn Zendure lädt  sonst 0
byd_charge = max(0, charge_needed - effective_z_charge)   # BYD ergänzt was Zendure nicht schafft
```

`_ZENDURE_CHARGING_REASONS` bestimmt, ob Zendure als „ladend" gilt:
```python
{"night_charge_go_window", "planning_latest_start", "valley_boost_charge",
 "manual_charge", "emergency_latched_charge", "pv_surplus_charge"}
```

`night_charge_pause` ist bewusst **nicht** enthalten: wenn Zendure pausiert, übernimmt
BYD das verbleibende Defizit vollständig.

### Zustandsübergänge

```
byd_charge > 0.5 kWh  →  BYD-Modus: charge
Ziel erreicht         →  BYD-Modus: stop   (oder pause wenn byd_usable ≤ bridge_kwh)
byd_usable ≤ bridge   →  BYD-Modus: pause  (Brückenreserve schützen)
05:00 Uhr UTC         →  Fenster-Ende: Modus zurücksetzen
```

---

## Coordinator — Ablauf pro Zyklus (10 s)

```
1. Sensoren lesen
2. DecisionContext aufbauen
3. _engine.evaluate(ctx)         → decision
4. _manage_byd_night_charge()    → BYD-Modus setzen
5. SoC-Limit-Guards anwenden     → decision ggf. überschreiben
6. _last_decision_reason speichern  ← NACH Schritt 5 (wichtig!)
7. Zendure-Setpoints anwenden
8. Dashboard-Sensoren aktualisieren
```

**Wichtig:** `_last_decision_reason` wird erst nach allen Modifikationen (Schritt 5) gespeichert,
damit `_manage_byd_night_charge` im nächsten Zyklus den tatsächlichen Zustand sieht.

---

## Zwei verschiedene Planungshorizonte

| Funktion | Formel | Horizont | Zweck |
|----------|--------|----------|-------|
| `NightChargeRule` | `morning_need` (bridge + Tagesdefizit) | 0–18 Uhr | Nacht-Ladeentscheidung |
| `_calc_pv_aware_zendure_target_soc` | `bridge + nighttime_kwh + daily - pv` | 24 h | Tages-Ziel-SoC für Planung |

Die Tagesplanungsfunktion verwendet den vollen 24h-Horizont (inkl. `nighttime_kwh` für den
Folgeabend), weil sie entscheidet, wie voll Zendure tagsüber geladen werden soll.
Die NightChargeRule blickt dagegen nur auf die nächsten Stunden bis 18:00 Uhr.

---

## `_delta_charge` / `_delta_discharge` (PID-Regler)

`power_controller.py` stellt zwei Hilfsfunktionen bereit:

- `_delta_charge(ctx)` — positiv wenn PV-Überschuss vorhanden (Ladung sinnvoll)
- `_delta_discharge(ctx)` — Entladeleistung, die Netz-Import auf `TARGET_IMPORT_W` hält

Export-Guard: `_is_real_export()` prüft ob Netto-Export > 100 W. Verhindert, dass
Regelungen versehentlich Batterie → Netz pumpen (Einspeisevergütung ≪ Bezugspreis).

---

## Manuelle Modi (`ai_mode = "manual"`)

| `manual_action` | Verhalten |
|----------------|-----------|
| `constant_discharge` | Zendure entlädt konstant unter Hauslast. NightChargeRule kann überschreiben (Priorität 5 > ManualRule 9). |
| `charge` | Manuelles Laden. NightChargeRule greift nicht ein. |
| `discharge` | Manuelles Entladen. NightChargeRule greift nicht ein. |
| `standby` | Kein Laden/Entladen. NightChargeRule darf überschreiben. |

---

## Wichtige Konstanten

| Konstante | Wert | Bedeutung |
|-----------|------|-----------|
| `_EXPORT_THRESHOLD_W` | 100 W | Mindest-Export für `_is_real_export()` |
| `night_charge_pause` min | 0.2 kWh | Unter diesem z_charge: pausieren statt laden |
| `bridge_kwh` default | ≈ 0.9 kWh | `nighttime_w × 3h` (bei 300 W Standard) |
| GO-Fenster | 0–5 Uhr UTC | NightChargeRule aktiv |
