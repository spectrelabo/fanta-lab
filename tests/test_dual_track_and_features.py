#!/usr/bin/env python3
"""
Test Agent — Verifica Risolutiva per fanta-lab v3.0
=====================================================
Testa tutti i fix critici, la Finestra Medica, l'architettura Dual-Track
e la robustezza dell'API.
"""
import json
import os
import sys
import time
import requests

BASE_URL = "http://localhost:5050"
PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []


def test(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((name, status, detail))
    print(f"  {status}  {name}" + (f"  ({detail})" if detail else ""))
    return condition


def main():
    print("\n" + "=" * 72)
    print("  TEST AGENT — fanta-lab v3.0 Dual-Track & Feature Verification")
    print("=" * 72 + "\n")

    # ── 1. Server Health ──────────────────────────────────────────────
    print("▸ 1. Server Health Check")
    try:
        r = requests.get(f"{BASE_URL}/api/players", timeout=10)
        test("Server risponde su /api/players", r.status_code == 200, f"status={r.status_code}")
        data = r.json()
        players = data.get("players", [])
        test("Players > 0", len(players) > 0, f"n={len(players)}")
    except Exception as e:
        test("Server raggiungibile", False, str(e))
        print("\n⛔ Server non raggiungibile. Assicurati che app.py sia in esecuzione su porta 5050.")
        sys.exit(1)

    # ── 2. Dual-Track API Settings ────────────────────────────────────
    print("\n▸ 2. Dual-Track Architecture — /api/settings")
    r_settings = requests.get(f"{BASE_URL}/api/settings")
    s_data = r_settings.json()
    test("GET /api/settings → status 200", r_settings.status_code == 200)
    test("Contiene 'app_env'", "app_env" in s_data, f"app_env={s_data.get('app_env')}")
    test("Contiene 'is_personal'", "is_personal" in s_data, f"is_personal={s_data.get('is_personal')}")

    # ── 3. Fasce per Macro-Ruolo ──────────────────────────────────────
    print("\n▸ 3. Fasce (Quantili per Macro-Ruolo P, D, C, A)")
    for role in ["P", "D", "C", "A"]:
        role_players = [p for p in players if p.get("role") == role]
        fasce = {1: 0, 2: 0, 3: 0, 4: 0}
        for p in role_players:
            f = p.get("fascia", 0)
            if f in fasce:
                fasce[f] += 1
        all_populated = all(v > 0 for v in fasce.values())
        test(
            f"Ruolo {role}: tutte le fasce 1-4 popolate",
            all_populated,
            f"F1={fasce[1]}, F2={fasce[2]}, F3={fasce[3]}, F4={fasce[4]}"
        )

    # Verifica specifica per portieri intermedi e top
    p_by_name = {p["player"]: p for p in players if p.get("role") == "P"}
    test("Portieri Top in Fascia 1 (Svilar, Vicario, Carnesecchi)",
         p_by_name.get("Svilar", {}).get("fascia") == 1 and p_by_name.get("Vicario", {}).get("fascia") == 1 and p_by_name.get("Carnesecchi", {}).get("fascia") == 1)
    test("Portieri Intermedi in Fascia 2 (Skorupski, De Gea, Falcone, Okoye)",
         p_by_name.get("Skorupski", {}).get("fascia") == 2 and p_by_name.get("De Gea", {}).get("fascia") == 2 and p_by_name.get("Falcone", {}).get("fascia") == 2 and p_by_name.get("Okoye", {}).get("fascia") == 2)
    test("Portieri Intermedi Minori in Fascia 3 (Muric, Bijlow, Stankovic)",
         p_by_name.get("Muric", {}).get("fascia") == 3 and p_by_name.get("Bijlow", {}).get("fascia") == 3 and p_by_name.get("Stankovic F.", {}).get("fascia") == 3)
    test("Portieri Riserva a 1-5 cr in Fascia 4",
         p_by_name.get("Di Gennaro", {}).get("fascia") == 4 and p_by_name.get("Gollini", {}).get("fascia") == 4)

    # ── 4. Medical Node (Finestra Medica) ─────────────────────────────
    print("\n▸ 4. Finestra Medica — Nodo 'medical' in /api/players")
    sample = players[0]
    med = sample.get("medical", {})
    test("Nodo 'medical' presente", "medical" in sample)
    test("medical.days_lost_3y è int", isinstance(med.get("days_lost_3y"), int))
    test("medical.injuries_count_3y è int", isinstance(med.get("injuries_count_3y"), int))
    test("medical.status in {safe, warning, danger}", med.get("status") in ("safe", "warning", "danger"), f"status={med.get('status')}")
    test("medical.status_badge non vuoto", len(med.get("status_badge", "")) > 0)
    test("medical.status_label non vuoto", len(med.get("status_label", "")) > 0)
    test("medical.dettaglio_infortuni è lista", isinstance(med.get("dettaglio_infortuni"), list))

    # Verify at least some players have injury data
    players_with_injuries = sum(1 for p in players if p.get("medical", {}).get("days_lost_3y", 0) > 0)
    test("Giocatori con giorni infortunio > 0", players_with_injuries > 10, f"n={players_with_injuries}")

    # ── 5. Understat Node ─────────────────────────────────────────────
    print("\n▸ 5. Volumi Offensivi — Nodo 'understat' in /api/players")
    us = sample.get("understat", {})
    test("Nodo 'understat' presente", "understat" in sample)
    for key in ["xg_per90", "npxg_per90", "xa_per90", "shots_per90", "delta_goals_xg"]:
        test(f"understat.{key} è numerico", isinstance(us.get(key), (int, float)), f"val={us.get(key)}")

    # ── 6. Quantiles Node ─────────────────────────────────────────────
    print("\n▸ 6. Profilo Quantilico — Nodo 'quantiles' in /api/players")
    q = sample.get("quantiles", {})
    test("Nodo 'quantiles' presente", "quantiles" in sample)
    for key in ["floor_p10", "expected_p50", "ceiling_p90", "spread"]:
        test(f"quantiles.{key} è numerico", isinstance(q.get(key), (int, float)), f"val={q.get(key)}")
    test("quantiles.profile_label presente", len(q.get("profile_label", "")) > 0)
    test("quantiles.profile_badge presente", len(q.get("profile_badge", "")) > 0)
    test("P10 <= P50 <= P90", q.get("floor_p10", 0) <= q.get("expected_p50", 0) <= q.get("ceiling_p90", 0))

    # ── 7. Tactical Presets — split_pct ───────────────────────────────
    print("\n▸ 7. Tactical Presets — split_pct presente")
    presets = data.get("tactical_presets", {})
    for pid, preset in presets.items():
        has_pct = "split_pct" in preset
        test(f"Preset '{pid}' ha split_pct", has_pct)
        if has_pct:
            pct_sum = sum(preset["split_pct"].values())
            test(f"Preset '{pid}' split_pct somma ~1.0", abs(pct_sum - 1.0) < 0.02, f"sum={pct_sum:.3f}")

    # ── 8. api_assign Robustness ──────────────────────────────────────
    print("\n▸ 8. /api/assign — Validazione Input Robusto")

    # Test assegnazione con giocatore inesistente
    r_assign = requests.post(f"{BASE_URL}/api/assign", json={
        "player": "GIOCATORE_INESISTENTE_XYZ_999",
        "team_id": 1,
        "price": 10
    })
    test("Assign giocatore inesistente → 404", r_assign.status_code == 404)

    # Test assegnazione senza nome
    r_no_name = requests.post(f"{BASE_URL}/api/assign", json={
        "player": "",
        "team_id": 1,
        "price": 10
    })
    test("Assign senza nome → 400", r_no_name.status_code == 400)

    # Test safe parsing di team_id e price non-int
    r_bad_input = requests.post(f"{BASE_URL}/api/assign", json={
        "player": players[0]["player"],
        "team_id": "abc",
        "price": "xyz"
    })
    # Should not crash (500), should handle gracefully
    test("Assign con input non-int non crasha (no 500)", r_bad_input.status_code != 500, f"status={r_bad_input.status_code}")

    # ── 9. /api/state Integrity ───────────────────────────────────────
    print("\n▸ 9. /api/state — Integrità Stato")
    r_state = requests.get(f"{BASE_URL}/api/state")
    test("/api/state → 200", r_state.status_code == 200)
    state_data = r_state.json()
    test("state contiene 'state'", "state" in state_data)
    test("state contiene 'scarcity'", "scarcity" in state_data)
    test("state contiene 'tactical_presets'", "tactical_presets" in state_data)
    test("state contiene 'market_index'", "market_index" in state_data)

    # Check scarcity has all roles
    scarcity = state_data.get("scarcity", {})
    for role in ["P", "D", "C", "A"]:
        test(f"Scarcity ha ruolo {role}", role in scarcity)

    # ── 10. HTML Endpoint ─────────────────────────────────────────────
    print("\n▸ 10. HTML Endpoint — Player Detail Drawer Presente")
    r_html = requests.get(f"{BASE_URL}/")
    test("GET / → 200", r_html.status_code == 200)
    html = r_html.text
    test("HTML contiene 'playerDetailDrawer'", "playerDetailDrawer" in html)
    test("HTML contiene 'openPlayerDetailDrawer'", "openPlayerDetailDrawer" in html)
    test("HTML contiene 'pdMedBadge' (Finestra Medica)", "pdMedBadge" in html)
    test("HTML contiene 'pdXg90' (Understat)", "pdXg90" in html)
    test("HTML contiene 'pdProfileBadge' (Quantiles)", "pdProfileBadge" in html)
    test("HTML contiene 'settingForceReset'", "settingForceReset" in html)
    test("HTML contiene 'ℹ️' dettaglio icona", "ℹ️" in html or "Dettaglio Giocatore" in html)

    # ── 11. Entity-First Retrieval (Thuram & Woltemade) ────────────────
    print("\n▸ 11. Entity-First Copilot Retrieval — Thuram & Woltemade")
    r_copilot_comp = requests.post(f"{BASE_URL}/api/ai_query", json={"prompt": "parlami di thuram e woltemade", "profile_id": 1}, timeout=25)
    test("POST /api/ai_query comparison → 200", r_copilot_comp.status_code == 200)
    comp_json = r_copilot_comp.json()
    test("Risposta confronto non vuota", bool(comp_json))
    comp_players = [p.get("name", "").lower() for p in comp_json.get("players", [])]
    test("Confronto contiene 'thuram'", any("thuram" in p for p in comp_players) or "thuram" in str(comp_json).lower())
    test("Confronto contiene 'woltemade'", any("woltemade" in p for p in comp_players) or "woltemade" in str(comp_json).lower())

    r_copilot_single = requests.post(f"{BASE_URL}/api/ai_query", json={"prompt": "chi è woltemade?", "profile_id": 1}, timeout=25)
    test("POST /api/ai_query single player → 200", r_copilot_single.status_code == 200)
    single_json = r_copilot_single.json()
    test("Single player Woltemade riconosciuto", "woltemade" in str(single_json).lower())

    # ── 12. Finestra Medica Drawer Fix ────────────────────────────────
    print("\n▸ 12. Finestra Medica Drawer — No cachedPlayers ReferenceError")
    test("Nessun 'cachedPlayers' non definito in HTML", "cachedPlayers" not in html)
    test("HTML contiene 'medical-badge'", "medical-badge" in html)
    test("Listone include badge medico integro/infortunato", "Finestra Medica:" in html)

    # ── 13. Slot-Based 'I Miei Target' Architecture ───────────────────
    print("\n▸ 13. 'I Miei Target' — Architettura a Slot per Ruolo & HUD Finanziario")
    test("HTML contiene 'targetRolesContainer'", "targetRolesContainer" in html)
    test("HTML contiene 'targetBudgetTotal'", "targetBudgetTotal" in html)
    test("HTML contiene 'targetEstSpendFair'", "targetEstSpendFair" in html)
    test("HTML contiene 'targetEstSpendMax'", "targetEstSpendMax" in html)
    test("HTML contiene 'targetEstRemaining'", "targetEstRemaining" in html)
    test("HTML contiene 'targetSlotsProgress'", "targetSlotsProgress" in html)
    test("HTML contiene 'assignPlayerToTargetSlot'", "assignPlayerToTargetSlot" in html)
    test("HTML contiene 'vacateTargetSlot'", "vacateTargetSlot" in html)
    test("HTML contiene 'toggleTargetSlotCandidates'", "toggleTargetSlotCandidates" in html)
    test("HTML contiene 'clearAllTargetSlots'", "clearAllTargetSlots" in html)

    # ── SUMMARY ───────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    passed = sum(1 for _, s, _ in results if s == PASS)
    failed = sum(1 for _, s, _ in results if s == FAIL)
    total = len(results)
    print(f"  RISULTATO: {passed}/{total} test superati  ({failed} falliti)")

    if failed == 0:
        print("  🎉 TUTTI I TEST SUPERATI — Le modifiche sono risolutive!")
    else:
        print("  ⚠️  ATTENZIONE — I seguenti test sono falliti:")
        for name, status, detail in results:
            if status == FAIL:
                print(f"     • {name}: {detail}")

    print("=" * 72 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
