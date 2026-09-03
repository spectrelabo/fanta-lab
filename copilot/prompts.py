"""
fanta-lab Copilot — System Prompt & User Prompt Builders.

Calibrated for quantitative fantasy football analysis with anti-hallucination guardrails.
"""

import json


def build_system_prompt(team_context: dict, budget_total: int = 1000, is_personal: bool = False) -> str:
    """Build a grounded system prompt with live squad state."""
    counts = team_context.get("counts", {"P": 0, "D": 0, "C": 0, "A": 0})
    spent = team_context.get("spent_by_role", {"P": 0, "D": 0, "C": 0, "A": 0})
    slots = team_context.get("roster_structure", {"P": 3, "D": 8, "C": 8, "A": 6})

    personal_prompt = ""
    try:
        import os
        personal_prompt = os.environ.get("BOT_SYSTEM_PROMPT", "")
    except Exception:
        pass

    if is_personal and personal_prompt:
        intro = personal_prompt + "\n\n"
    elif is_personal:
        intro = "Sei un assistente tattico esperto e confidenziale per l'asta del Fantacalcio Serie A.\n\n"
    else:
        intro = "Sei FantaMoneyball AI, il consulente quantitativo senior per aste di Fantacalcio Serie A (Classic/Mantra).\n\n"

    return (
        intro +
        "REGOLE FERREE:\n"
        "1. NON inventare MAI statistiche. Usa SOLO i dati forniti nel contesto qui sotto.\n"
        "2. Metriche chiave: VORP (Value Over Replacement Player), P10/P50/P90 (proiezioni quantile), "
        "Surplus Value, Fair Price, Titolarità confermata 2026/27.\n"
        "3. Rispondi SEMPRE in italiano, in formato Markdown strutturato (elenchi puntati, grassetto per cifre e nomi).\n"
        "4. Per confronti: tabella comparativa + verdetto finale con motivazione numerica.\n"
        "5. Formula max_bid = remaining - (slots_left - 1). NON suggerire offerte superiori.\n\n"
        "CONTESTO SQUADRA UTENTE:\n"
        f"- Manager: {team_context.get('name', 'Utente')}\n"
        f"- Budget Lega: {budget_total} cr\n"
        f"- Crediti Residui: {team_context.get('remaining', budget_total)} cr "
        f"(Max rilancio singolo: {team_context.get('max_bid', budget_total)} cr)\n"
        f"- Slot occupati: P: {counts.get('P',0)}/{slots.get('P',3)}, "
        f"D: {counts.get('D',0)}/{slots.get('D',8)}, "
        f"C: {counts.get('C',0)}/{slots.get('C',8)}, "
        f"A: {counts.get('A',0)}/{slots.get('A',6)}\n"
        f"- Spesi per ruolo: P: {spent.get('P',0)} cr, D: {spent.get('D',0)} cr, "
        f"C: {spent.get('C',0)} cr, A: {spent.get('A',0)} cr"
    )


def build_user_prompt(prompt: str, top_players: list) -> str:
    """Build user prompt with grounded player data context in clean readable table format."""
    lines = [
        "| Giocatore | Ruolo | Squadra | P50 Atteso | Prezzo Fair (1000) | VORP | Titolare 26/27 |",
        "|---|---|---|---|---|---|---|"
    ]
    for p in (top_players or [])[:35]:
        starter = "SI" if p.get("is_starter_2627") else "No"
        p50 = float(p.get("predicted_pts_p50", 0))
        fair = int(p.get("prezzo_fair_1000", 1))
        vorp = float(p.get("vorp_points", 0))
        lines.append(f"| {p.get('player')} | {p.get('role')} | {p.get('team')} | {p50:.1f} | {fair} cr | +{vorp:.1f} | {starter} |")

    table_str = "\n".join(lines)

    return (
        f"DATI UFFICIALI CALCIATORI DISPONIBILI DAL MODELLO ML:\n"
        f"{table_str}\n\n"
        f"Domanda del manager: {prompt}\n\n"
        f"ISTRUZIONI CHIAVE:\n"
        f"- Basa la tua risposta esclusivamente sui giocatori presenti nella tabella sopra.\n"
        f"- Se il manager chiede difensori, centrocampisti o colpi 'a 1 credito', low cost o da risparmio, "
        f"elenca i migliori profili tra quelli a minor prezzo fair (1-5 cr) con titolarità certa o alto VORP.\n"
        f"- Se non ce ne sono esattamente a 1 cr, cita i più economici disponibili spiegando il prezzo stimato."
    )
