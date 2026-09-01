#!/usr/bin/env python3
"""
STAGE 7 — Formatted Multi-Sheet Auction Spreadsheet Generator.

Generates a formatted, multi-tab Excel workbook containing:
  - FULL ROSTER LIST (All active players ranked by Composite Score & Fair Value)
  - POSITIONAL TABS (Goalkeepers, Defenders, Midfielders, Forwards)
  - AUCTION COLUMN LEGEND (Detailed analytical guide for every metric)

Output:
  - data/analisi_fantacalcio_completa.xlsx
"""

import os, sys, warnings
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

warnings.filterwarnings("ignore")

DISPLAY_COLS = [
    "player", "role", "role_mantra", "team", "Prezzo_Consigliato_Cr",
    "prezzo_fair_1000", "surplus_value_cr", "score_composito",
    "predicted_pts_p50", "predicted_pts_p10", "predicted_pts_p90", "pts_volatility_spread",
    "vorp_points", "mv_media_3y", "mv_std", "mv_trend", "availability",
    "xg_media_3y", "xa_media_3y", "offensive_index",
    "giorni_infortunio_3y", "n_infortuni_3y", "infortunio_grave", "malus_infortuni",
    "NN_MV_Atteso", "NN_FV_Atteso", "Prob_Bonus_Ge_8_%", "Prob_Picco_Ge_10_%",
    "Clean_Sheet_%", "FVM_1000"
]

COL_RENAME = {
    "player": "Player", "role": "Role", "role_mantra": "Mantra Role",
    "team": "Team", "Prezzo_Consigliato_Cr": "Official Price (Cr)",
    "prezzo_fair_1000": "Fair Price 1000 (Cr)", "surplus_value_cr": "Surplus Value (Cr)",
    "score_composito": "Composite Score",
    "predicted_pts_p50": "Expected Pts (P50)", "predicted_pts_p10": "Floor Pts (P10)",
    "predicted_pts_p90": "Ceiling Pts (P90)", "pts_volatility_spread": "Pts Volatility Spread",
    "vorp_points": "VORP Points",
    "mv_media_3y": "3y Weighted Rating", "mv_std": "Rating Volatility (Std)",
    "mv_trend": "Rating Trend", "availability": "Availability %",
    "xg_media_3y": "3y xG Average", "xa_media_3y": "3y xA Average",
    "offensive_index": "Team Offensive Index",
    "giorni_infortunio_3y": "Days Lost 3y", "n_infortuni_3y": "Injury Count 3y",
    "infortunio_grave": "Severe Injury Flag", "malus_infortuni": "Injury Malus",
    "NN_MV_Atteso": "Expected Baseline Rating", "NN_FV_Atteso": "Expected Fantavote",
    "Prob_Bonus_Ge_8_%": "Prob Bonus >= 8 %", "Prob_Picco_Ge_10_%": "Prob Peak >= 10 %",
    "Clean_Sheet_%": "Clean Sheet %", "FVM_1000": "FVM (out of 1000)"
}

LEGENDA = [
    ("Composite Score", "Risk-adjusted synthetic performance index (0.00 - 1.00) balancing ratings, xG, consistency, and physical availability."),
    ("Official Price (Cr)", "Official list quotation baseline."),
    ("Fair Price 1000 (Cr)", "Mathematical rational auction valuation computed via VORP (Value Over Replacement Player) on a 1000 credit scale."),
    ("Surplus Value (Cr)", "Market inefficiency indicator (Fair Price minus Official Price). Positive values denote undervalued targets; negative values denote overhyped traps."),
    ("Expected Pts (P50)", "Projected median total season fantasy points from Quantile Gradient Boosting regression."),
    ("Floor Pts (P10)", "10th percentile conservative floor points projection (pessimistic scenario)."),
    ("Ceiling Pts (P90)", "90th percentile high-upside ceiling points projection (optimistic scenario)."),
    ("Pts Volatility Spread", "Difference between Ceiling and Floor (P90 - P10). High values indicate boom-or-bust volatile profiles."),
    ("VORP Points", "Value Over Replacement Player: fantasy points produced above the waiver-wire replacement baseline for that position."),
    ("3y Weighted Rating", "Historical pure average rating weighted across the last 3 seasons (3x recent, 2x previous, 1x oldest)."),
    ("Rating Volatility (Std)", "Standard deviation of match ratings. Low (<0.20) indicates rock-solid reliability; high (>0.50) indicates erratic swings."),
    ("Rating Trend", "Multi-year regression slope. Positive values indicate improving trajectories; negative values denote performance decline."),
    ("Availability %", "Percentage of rated league appearances over 38 matchdays."),
    ("3y xG Average", "Three-season average of Expected Goals from Understat."),
    ("3y xA Average", "Three-season average of Expected Assists from Understat."),
    ("Team Offensive Index", "Team offensive power rating factor (0.90 - 1.10)."),
    ("Days Lost 3y", "Total days missed due to injury/illness over the last 3 seasons (Transfermarkt)."),
    ("Injury Count 3y", "Number of verified medical absence events over the last 3 years."),
    ("Severe Injury Flag", "1 = Yes, 0 = No (at least one continuous absence event >= 60 days)."),
    ("Injury Malus", "Physical fragility index (0.00 = Ironman, 1.00 = Extremely Fragile). Deducts up to -15% from Composite Score."),
    ("Expected Baseline Rating", "Model-projected pure match rating baseline."),
    ("Expected Fantavote", "Total expected fantasy rating including goal/assist bonuses."),
    ("Prob Bonus >= 8 %", "Estimated probability density of scoring a fantasy rating >= 8.0 in a single matchday."),
    ("Prob Peak >= 10 %", "Estimated probability density of recording an explosive peak performance (rating >= 10.0)."),
    ("Clean Sheet %", "Percentage of fixtures completed with zero goals conceded."),
    ("FVM (out of 1000)", "Official market valuation in thousandths.")
]


def generate_excel(df, output_path=None):
    output_path = output_path or config.OUTPUT_EXCEL
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    role_fills = {
        "P": PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid"),
        "D": PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid"),
        "C": PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid"),
        "A": PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid"),
    }
    border_thin = Border(
        left=Side(style='thin', color='D9D9D9'), right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'), bottom=Side(style='thin', color='D9D9D9')
    )
    align_center = Alignment(horizontal="center", vertical="center")
    align_left   = Alignment(horizontal="left", vertical="center")
    align_right  = Alignment(horizontal="right", vertical="center")

    available_cols = [c for c in DISPLAY_COLS if c in df.columns]

    def format_sheet(ws, df_subset):
        df_sub = df_subset[available_cols].rename(columns=COL_RENAME)
        headers = list(df_sub.columns)
        ws.append(headers)

        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = align_center
            cell.border = border_thin

        for r_idx, row in enumerate(df_sub.itertuples(index=False), start=2):
            role_val = row[1]
            fill_bg = role_fills.get(role_val, PatternFill(fill_type=None))
            for c_idx, val in enumerate(row, start=1):
                cell = ws.cell(row=r_idx, column=c_idx)
                if pd.isna(val) or val is None:
                    cell.value = "-"
                    cell.alignment = align_center
                elif isinstance(val, (float, np.floating)):
                    col_name = headers[c_idx - 1]
                    if "%" in col_name or "Availability" in col_name:
                        cell.value = val
                        cell.number_format = '0.0%' if val <= 1.0 else '0.0'
                    elif "Score" in col_name or "Trend" in col_name or "Malus" in col_name:
                        cell.value = round(val, 4)
                        cell.number_format = '0.0000'
                    else:
                        cell.value = round(val, 2)
                        cell.number_format = '0.00'
                    cell.alignment = align_right
                elif isinstance(val, (int, np.integer)):
                    cell.value = int(val)
                    cell.alignment = align_right
                else:
                    cell.value = str(val)
                    cell.alignment = align_left if c_idx in [1, 4] else align_center
                if c_idx == 2:
                    cell.fill = fill_bg
                cell.border = border_thin

        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    format_sheet(wb.create_sheet(title="FULL ROSTER LIST"), df)
    format_sheet(wb.create_sheet(title="GOALKEEPERS"), df[df["role"] == "P"])
    format_sheet(wb.create_sheet(title="DEFENDERS"), df[df["role"] == "D"])
    format_sheet(wb.create_sheet(title="MIDFIELDERS"), df[df["role"] == "C"])
    format_sheet(wb.create_sheet(title="FORWARDS"), df[df["role"] == "A"])

    ws_leg = wb.create_sheet(title="COLUMN LEGEND")
    ws_leg.append(["Metric Column", "Analytical Meaning & Auction Strategy Guide"])
    ws_leg.cell(row=1, column=1).fill = header_fill
    ws_leg.cell(row=1, column=1).font = header_font
    ws_leg.cell(row=1, column=2).fill = header_fill
    ws_leg.cell(row=1, column=2).font = header_font
    for r_idx, (col_name, desc) in enumerate(LEGENDA, start=2):
        c1 = ws_leg.cell(row=r_idx, column=1, value=col_name)
        c2 = ws_leg.cell(row=r_idx, column=2, value=desc)
        c1.font = Font(name="Calibri", size=11, bold=True)
        c1.alignment = align_left
        c2.alignment = align_left
        c1.border = border_thin
        c2.border = border_thin
    ws_leg.column_dimensions['A'].width = 28
    ws_leg.column_dimensions['B'].width = 110

    wb.save(output_path)
    print(f"  Workbook exported: {output_path}")


def main():
    print("=" * 60)
    print("  STAGE 7 — EXCEL WORKBOOK GENERATION")
    print("=" * 60)

    df = pd.read_csv(config.DATASET_FINALE_CSV)
    print(f"  Exporting {len(df)} players to formatted spreadsheet...")
    generate_excel(df)
    print("  STAGE 7 COMPLETED.\n")


if __name__ == "__main__":
    main()
