# Hey mfs, this is where the llms come in and give judgement
# Gemini and Chat
# Are ya ready kids? Aye Aye Captain!
import pandas as pd
import numpy as np
import json
import re
import os
import time
from dotenv import load_dotenv
from openai import OpenAI
from google import genai
from google.genai import types as genai_types
from buldteamdatafunc import build_team_data

load_dotenv()
print("imports done")

# ── Keys ──────────────────────────────────────────────────────────────────────

GEMINI_KEY    = os.getenv("GEMINI_KEY")
OPENAI_KEY    = os.getenv("OPENAI_KEY")

class FRCEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        if pd.isna(obj):
            return None
        return super(FRCEncoder, self).default(obj)

# ── Analyst prompt ────────────────────────────────────────────────────────────

ANALYST_PROMPT = """
You are an expert FRC scouting analyst for the 2026 game REBUILT. You will receive statistical and observational data for a single team from the 2026 Gotham Regional. Your job is to produce a structured scouting report for both alliance selection and match strategy purposes.

REBUILT SCORING CONTEXT:

FUEL (balls shot into the HUB) scores 1 point each, but ONLY when the HUB is active. The HUB alternates active/inactive between alliances based on who scored more fuel in AUTO. Fuel scored in an inactive HUB scores zero. AUTO fuel output is a critical strategic variable.

TOWER (climb) has three levels: Level 1 = 15pts in AUTO, 10pts in teleop. Level 2 = 20pts teleop only. Level 3 = 30pts teleop only. Teams that climb in AUTO score 15pts AND potentially shift hub control. Most teams disregard tower do to it not being meta.

RP thresholds at regionals: ENERGIZED = 100 fuel total, SUPERCHARGED = 360 fuel total (alliance-wide), TRAVERSAL = 50 tower points total.

CYCLES = complete fuel retrieval loops: travel to field center -> collect balls -> return -> shoot. High fuel + low cycles = high-capacity shooter. High cycles + moderate fuel = high-frequency runner. These are distinct alliance profiles. A high-capacity shooter needs a high-frequency runner alongside them. Two high-capacity shooters may bottleneck on ball supply.

If foul values are negative, ignore them — data entry error.

---

TEAM DATA:
{team_data}

---

Return EXACTLY this structure. No added sections, no skipped sections.

PROSE REPORT:

Team {team_number}

Performance Summary: Overall scoring output, ranking context, consistency signal from standard deviation.

Autonomous: Fuel scored in auto, tower climb attempts, HUB control impact.

Teleop: Cycle profile, fuel output per match, HUB timing awareness from comments.

Endgame: Tower level attempted, success rate, points contributed. Flag L1 vs L2/L3 gap.

Cycle Analysis: Compare teleop_fuel vs avg_cycles to categorize robot. State alliance role.

Strengths: 3 concrete strengths backed by data.

Weaknesses: 3 concrete weaknesses backed by data.

Match Strategy: How to play WITH and AGAINST this team.

---

```json
{{
  "team": "{team_number}",
  "opr": null,
  "dpr": null,
  "ccwm": null,
  "rank": null,
  "record": null,
  "avg_total_points": null,
  "score_std_dev": null,
  "auto_fuel_avg": null,
  "auto_tower": null,
  "teleop_fuel_avg": null,
  "teleop_tower_level": null,
  "climb_success_rate": null,
  "avg_cycles": null,
  "fuel_per_cycle": null,
  "cycle_profile": null,
  "tier": null,
  "alliance_role": null,
  "contributes_to_energized_rp": null,
  "contributes_to_supercharged_rp": null,
  "contributes_to_traversal_rp": null,
  "red_flags": [],
  "strengths": [],
  "weaknesses": []
}}
```
"""

def build_analyst_prompt(team_number: str) -> str:
    data = build_team_data(team_number)
    # ADD THE 'cls=FRCEncoder' PART HERE:
    data_str = json.dumps(data, indent=2, cls=FRCEncoder, ensure_ascii=False)
    return ANALYST_PROMPT.format(team_data=data_str, team_number=team_number)

def analyze_team_gemini(team_number: str) -> str:
    prompt = build_analyst_prompt(team_number)
    client = genai.Client(api_key=GEMINI_KEY)
    contents = [genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=prompt)])]
    config = genai_types.GenerateContentConfig(
        thinking_config=genai_types.ThinkingConfig(thinking_level="LOW"),
        max_output_tokens=1500,
    )
    print(f"\n{'='*60}\nGEMINI ANALYSIS — Team {team_number}\n{'='*60}\n")
    response = ""
    for chunk in client.models.generate_content_stream(model="gemini-1.5-flash-8b", contents=contents, config=config):
        if chunk.text:
            print(chunk.text, end="", flush=True)
            response += chunk.text
    return response


def analyze_team_gpt(team_number: str) -> str:
    prompt = build_analyst_prompt(team_number)
    client = OpenAI(api_key=OPENAI_KEY)
    print(f"\n{'='*60}\nGPT ANALYSIS — Team {team_number}\n{'='*60}\n")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1500,
    )
    result = response.choices[0].message.content
    print(result)
    return result


def extract_json_from_report(report: str) -> str:
    match = re.search(r"```json\s*(.*?)\s*```", report, re.DOTALL)
    return match.group(1) if match else "{}"


def run_full_pipeline(team_list: list, delay: int = 5):
    os.makedirs("gemini_reports", exist_ok=True)
    os.makedirs("gpt_reports",    exist_ok=True)


    completed, failed = 0, []

    for i, team in enumerate(team_list):
        print(f"\n[{i+1}/{len(team_list)}] Processing team {team}...")
        final_path = f"final_reports/final_{team}.txt"

        if os.path.exists(final_path):
            print(f"  Already complete, skipping.")
            completed += 1
            continue

        try:
            # Gemini
            gemini_path = f"gemini_reports/gemini_{team}.txt"
            if os.path.exists(gemini_path):
                gemini_report = open(gemini_path, "r", encoding="utf-8").read()
                print("  Gemini loaded from file.")
            else:
                gemini_report = analyze_team_gemini(team)
                open(gemini_path, "w", encoding="utf-8").write(gemini_report)
                time.sleep(delay)

            # GPT
            gpt_path = f"gpt_reports/gpt_{team}.txt"
            if os.path.exists(gpt_path):
                gpt_report = open(gpt_path, "r", encoding="utf-8").read()
                print("  GPT loaded from file.")
            else:
                gpt_report = analyze_team_gpt(team)
                open(gpt_path, "w", encoding="utf-8").write(gpt_report)
                time.sleep(delay)

        except Exception as e:
            print(f"\n  Team {team} FAILED: {e}")
            failed.append(team)

    print(f"\n{'='*60}\nPIPELINE COMPLETE\nCompleted: {completed}\nFailed: {len(failed)}")
    if failed:
        print(f"Failed teams: {failed}\nRe-run to retry.")
    print("="*60)


if __name__ == "__main__":
    TOP_24 = [
        "1796", "4027", "694", "8267", "4122", "8398",
        "3158", "1156", "2869", "358", "4571", "9030",
        "7840", "8011", "3950", "10262", "1880", "8739",
        "6880", "7551", "334", "2875", "7272", "10045"
    ]
    run_full_pipeline(TOP_24, delay=5)
    # Combine gemini + gpt reports side by side into one txt
    files = sorted([f for f in os.listdir("gemini_reports") if f.endswith(".txt")])
    combined = ""

    for filename in files:
        team = filename.replace("gemini_", "").replace(".txt", "")
        gemini_path = f"gemini_reports/gemini_{team}.txt"
        gpt_path    = f"gpt_reports/gpt_{team}.txt"

        combined += f"\n{'='*60}\nTEAM {team}\n{'='*60}\n"

        if os.path.exists(gemini_path):
            combined += f"\n--- GEMINI ---\n{open(gemini_path).read()}\n"
        if os.path.exists(gpt_path):
            combined += f"\n--- GPT ---\n{open(gpt_path).read()}\n"

    with open("all_reports.txt", "w", encoding="utf-8") as f:
        f.write(combined)

    print(f"Combined {len(files)} teams into all_reports.txt")

    FINAL_DIR   = "final_reports"
    OUTPUT_FILE = "all_final_reports.txt"
 
    files = sorted([f for f in os.listdir(FINAL_DIR) if f.endswith(".txt")])
 
    combined = ""
    for filename in files:
        team = filename.replace("final_", "").replace(".txt", "")
        with open(os.path.join(FINAL_DIR, filename), "r", encoding="utf-8") as f:
            content = f.read()
        combined += f"\n{'='*60}\nTEAM {team}\n{'='*60}\n{content}\n"
 
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(combined)
    print(f"Combined {len(files)} reports into {OUTPUT_FILE}")


 