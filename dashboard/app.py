import ast
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.paths import RAW_DIR, PROCESSED_DIR, REPORTS_DIR

EVENT_KEY = "2026nyn2"
HOME_TEAM = "3158"

# Alliance-wide RP thresholds at regionals
ENERGIZED_FUEL    = 100
SUPERCHARGED_FUEL = 360
TRAVERSAL_TOWER   = 50

FILES = {
    "teams":      RAW_DIR / "gotham_2026_teams.csv",
    "scouting":   RAW_DIR / "scouting_datanyc.csv",
    "opr":        PROCESSED_DIR / "opr_tba_gotham.csv",
    "rankings":   PROCESSED_DIR / "rankings_tba_gotham.csv",
    "rank_pred":  PROCESSED_DIR / "ranking_predictions_tba_gotham.csv",
    "stats_pred": PROCESSED_DIR / "stats_prediction_tba_gotham.csv",
    "matches":    PROCESSED_DIR / "match_predictions_tba_gotham_slim.csv",
    "montecarlo": PROCESSED_DIR / f"monte_carlo_sim_{EVENT_KEY}.csv",
}
REPORT_DIRS = {
    "Gemini": (REPORTS_DIR / "gemini_reports", "gemini"),
    "GPT":    (REPORTS_DIR / "gpt_reports", "gpt"),
}
REPORT_SECTIONS = ["Performance Summary", "Autonomous", "Teleop", "Endgame", "Cycle Analysis",
                   "Strengths", "Weaknesses", "Match Strategy"]

# Internal column -> label, grouped the way the Rankings table shows them
COLUMN_GROUPS = {
    "Standings":   {"rank": "Rank", "record": "W-L-T", "rp": "RP", "ranking_score": "Ranking score"},
    "Power":       {"opr": "OPR", "dpr": "DPR", "ccwm": "CCWM"},
    "Predictions": {"tba_rank": "TBA pred rank", "tba_rp": "TBA pred RP", "mc_rank": "MC rank", "mc_rp": "MC RP"},
    "Scouting":    {"scouted": "Scouted matches", "auto_fuel": "Auto fuel", "teleop_fuel": "Teleop fuel",
                    "total_fuel": "Total fuel", "cycles": "Cycles", "fuel_per_cycle": "Fuel/cycle",
                    "tower": "Tower pts", "fouls": "Fouls", "points": "Points"},
    "AI":          {"tier_gemini": "Tier (Gemini)", "tier_gpt": "Tier (GPT)",
                    "profile_gemini": "Profile (Gemini)", "profile_gpt": "Profile (GPT)"},
}
LABELS = {col: label for group in COLUMN_GROUPS.values() for col, label in group.items()}
RANK_COLUMNS = ["rank", "rp", "tba_rank", "mc_rank", "mc_rp", "scouted"]
CHART_METRICS = ["opr", "dpr", "ccwm", "total_fuel", "auto_fuel", "teleop_fuel", "cycles",
                 "fuel_per_cycle", "tower", "points", "fouls", "rp", "mc_rp"]
MATCH_METRICS = {"teleop_fuel": "Teleop fuel", "auto_fuel": "Auto fuel", "teleop_cycles": "Cycles",
                 "tower": "Tower pts", "totalPoints": "Points", "fouls": "Fouls"}


# ── Load data ─────────────────────────────────────────────────────────────────
# Files are small, so read them on every rerun. New backend output shows up without a restart.

def read_csv(name, team_column=None, **kwargs):
    path = FILES[name]
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, **kwargs)
    if team_column:
        df["team"] = df[team_column].astype(str).str.replace("frc", "")
    return df


def event_group(event):
    """Sort the free-text event names scouts typed into Gotham, Practice, or Other events."""
    name = unicodedata.normalize("NFKD", str(event)).encode("ascii", "ignore").decode().lower()
    if "pract" in name or "test" in name:
        return "Practice"
    if "hali" in name or "hudson" in name:
        return "Other events"
    return "Gotham"


def load_scouting():
    df = read_csv("scouting", "teamNumber", engine="python", on_bad_lines="skip")
    if df.empty:
        return df
    numeric = ["auto_fuel", "auto_tower", "teleop_cycles", "teleop_fuel", "teleop_tower",
               "teleop_majorFoul", "teleop_minorFoul", "totalPoints"]
    df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")
    # Negative fouls are data entry errors
    df["negative_foul"] = (df["teleop_majorFoul"] < 0) | (df["teleop_minorFoul"] < 0)
    df["fouls"] = (df["teleop_majorFoul"] + df["teleop_minorFoul"]).where(~df["negative_foul"])
    df["tower"] = df["auto_tower"] + df["teleop_tower"]
    df["event_group"] = df["event"].map(event_group)
    df["match"] = df["event"].astype(str) + " #" + df["matchNumber"].astype(str)
    return df.sort_values("lastUpdated_seconds")


def parse_report(text):
    """Split a report into prose and JSON fields. fields is None when the JSON is missing or cut off."""
    found = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    prose = text[:found.start()] if found else text
    prose = prose.replace("PROSE REPORT:", "").replace("$", r"\$").strip().rstrip("-").strip()
    for section in REPORT_SECTIONS:
        prose = re.sub(rf"^{section}:", f"**{section}:**", prose, flags=re.MULTILINE)
    try:
        fields = json.loads(found.group(1)) if found else None
    except json.JSONDecodeError:
        fields = None
    return {"prose": prose, "fields": fields}


def load_reports():
    reports = {}
    for model, (folder, prefix) in REPORT_DIRS.items():
        reports[model] = {}
        for path in sorted(folder.glob(f"{prefix}_*.txt")):
            team = path.stem.replace(f"{prefix}_", "")
            reports[model][team] = parse_report(path.read_text(encoding="utf-8"))
    return reports


def build_team_table(data, scouting, reports):
    """One row per team at the event, from every source that has run so far."""
    teams = set()
    for name in ["rankings", "opr", "montecarlo"]:
        if not data[name].empty:
            teams |= set(data[name]["team"])
    table = pd.DataFrame({"team": sorted(teams, key=int)})
    if table.empty:
        return table

    def add(df, columns):
        nonlocal table
        if df.empty:
            for column in columns.values():
                table[column] = None
            return
        table = table.merge(df[["team", *columns]].rename(columns=columns), on="team", how="left")

    add(data["teams"].drop_duplicates("team"), {"nickname": "nickname"})

    rankings = data["rankings"]
    if not rankings.empty:
        rankings = rankings.copy()
        records = rankings["record"].map(ast.literal_eval)
        rankings["record"] = records.map(lambda r: f"{r['wins']}-{r['losses']}-{r['ties']}")
        rankings["rp"] = rankings["extra_stats"].map(lambda v: ast.literal_eval(v)[0])
        rankings["ranking_score"] = rankings["sort_orders"].map(lambda v: ast.literal_eval(v)[0])
    add(rankings, {"rank": "rank", "record": "record", "rp": "rp", "ranking_score": "ranking_score"})
    add(data["opr"], {"oprs": "opr", "dprs": "dpr", "ccwms": "ccwm"})
    add(data["rank_pred"], {"rank": "tba_rank", "ranking_points": "tba_rp"})
    add(data["montecarlo"], {"rank": "mc_rank", "total_rp": "mc_rp"})

    if scouting.empty:
        averages = pd.DataFrame()
    else:
        grouped = scouting.groupby("team")
        averages = grouped[["auto_fuel", "teleop_fuel", "teleop_cycles", "tower", "fouls", "totalPoints"]].mean().reset_index()
        averages["scouted"] = averages["team"].map(grouped.size())
        averages["total_fuel"] = averages["auto_fuel"] + averages["teleop_fuel"]
        averages["fuel_per_cycle"] = averages["teleop_fuel"] / averages["teleop_cycles"].where(averages["teleop_cycles"] > 0)
    add(averages, {"scouted": "scouted", "auto_fuel": "auto_fuel", "teleop_fuel": "teleop_fuel",
                   "total_fuel": "total_fuel", "teleop_cycles": "cycles", "fuel_per_cycle": "fuel_per_cycle",
                   "tower": "tower", "fouls": "fouls", "totalPoints": "points"})

    for model, suffix in [("Gemini", "gemini"), ("GPT", "gpt")]:
        def field(team, key):
            fields = reports[model].get(team, {}).get("fields") or {}
            value = fields.get(key)
            return None if value is None else str(value)
        table[f"tier_{suffix}"] = table["team"].map(lambda team: field(team, "tier"))
        table[f"profile_{suffix}"] = table["team"].map(lambda team: field(team, "cycle_profile"))

    for column in table.columns.difference(["team", "nickname", "record", *COLUMN_GROUPS["AI"]]):
        table[column] = pd.to_numeric(table[column], errors="coerce")
    table["scouted"] = table["scouted"].fillna(0)
    return table


def tidy(df):
    """Round decimals and keep rank-like columns as whole numbers for display."""
    df = df.round(1)
    for column in RANK_COLUMNS:
        if column in df.columns:
            df[column] = df[column].astype("Int64")
    return df


def fmt(value, digits=1):
    if value is None or pd.isna(value):
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}".removesuffix(".0")
    return str(value)


def team_label(row):
    return f"{row['team']} · {row['nickname']}" if pd.notna(row["nickname"]) else row["team"]


# ── Charts ────────────────────────────────────────────────────────────────────

def team_bars(df, metric, title):
    """Horizontal bars, best-to-worst, one per team."""
    return (
        alt.Chart(df.dropna(subset=[metric]))
        .mark_bar(cornerRadiusEnd=4, size=12)
        .encode(
            y=alt.Y("team:N", sort="-x", title=None, axis=alt.Axis(labelOverlap=False)),
            x=alt.X(f"{metric}:Q", title=title),
            tooltip=[alt.Tooltip("team:N", title="Team"), alt.Tooltip("nickname:N", title="Name"),
                     alt.Tooltip(f"{metric}:Q", title=title, format=".1f")],
        )
        .properties(height=alt.Step(20))
    )


def rank_scatter(df, predicted, title):
    """Real rank against predicted rank. Dots on the line were predicted exactly."""
    df = df.dropna(subset=["rank", predicted])
    top = int(max(df["rank"].max(), df[predicted].max()))
    line = alt.Chart(pd.DataFrame({"x": [1, top], "y": [1, top]})).mark_line(strokeDash=[4, 4], opacity=0.5).encode(x="x:Q", y="y:Q")
    dots = alt.Chart(df).mark_circle(size=90, opacity=0.9).encode(
        x=alt.X("rank:Q", title="Real rank", scale=alt.Scale(domain=[1, top])),
        y=alt.Y(f"{predicted}:Q", title=title, scale=alt.Scale(domain=[1, top])),
        tooltip=[alt.Tooltip("team:N", title="Team"), alt.Tooltip("nickname:N", title="Name"),
                 alt.Tooltip("rank:Q", title="Real rank"), alt.Tooltip(f"{predicted}:Q", title=title)],
    )
    return (line + dots).properties(height=420)


def match_bars(df, metric, title):
    """One bar per scouted match, oldest first."""
    return (
        alt.Chart(df)
        .mark_bar(cornerRadiusEnd=4, size=18)
        .encode(
            x=alt.X("match:N", sort=None, title=None, axis=alt.Axis(labelAngle=-40, labelLimit=240)),
            y=alt.Y(f"{metric}:Q", title=title),
            tooltip=[alt.Tooltip("match:N", title="Match"), alt.Tooltip(f"{metric}:Q", title=title)],
        )
        .properties(height=280)
    )


# ── Tabs ──────────────────────────────────────────────────────────────────────

def show_rankings(table, reports):
    filter_col, group_col = st.columns([1, 2])
    search = filter_col.text_input("Search team or name")
    options = [g for g in COLUMN_GROUPS if g != "AI" or any(reports.values())]
    groups = group_col.multiselect("Columns", options, default=options)
    scouted_only = st.toggle("Only teams with scouting data")

    rows = table
    if search:
        haystack = rows["team"] + " " + rows["nickname"].fillna("")
        rows = rows[haystack.str.contains(search, case=False, regex=False)]
    if scouted_only:
        rows = rows[rows["scouted"] > 0]

    columns = {col: label for group in groups for col, label in COLUMN_GROUPS[group].items()}
    view = tidy(rows[["team", "nickname", *columns]]).rename(columns={"team": "Team", "nickname": "Name", **columns})
    if "Rank" in view.columns:
        view = view.sort_values("Rank")
    st.caption(f"{len(view)} teams. Click a column header to sort.")
    st.dataframe(view, hide_index=True, width="stretch", height=min(38 + 35 * len(view), 560))

    bars_col, scatter_col = st.columns(2)
    with bars_col:
        metric = st.selectbox("Compare all teams by", CHART_METRICS, format_func=LABELS.get)
        if rows[metric].notna().any():
            st.altair_chart(team_bars(rows, metric, LABELS[metric]), width="stretch")
        else:
            st.info("No data for this metric yet.")
    with scatter_col:
        predicted = st.selectbox("Check predictions from", ["mc_rank", "tba_rank"], format_func=LABELS.get)
        if rows[["rank", predicted]].notna().all(axis=1).any():
            st.altair_chart(rank_scatter(rows, predicted, LABELS[predicted]), width="stretch")
            st.caption("Dots on the dashed line were predicted exactly.")
        else:
            st.info("Needs both real rankings and predictions.")


def show_ai_reports(team, reports):
    found = {model: reports[model][team] for model in reports if team in reports[model]}
    if not found:
        st.info("No AI reports for this team yet. Run `python -m pipeline.analysts`. Only the top 24 teams get one.")
        return

    for model, report in found.items():
        if report["fields"] is None:
            st.warning(f"The {model} report has no valid JSON, so it was probably cut off. Delete the file and re-run to regenerate it.")

    keys = []
    for report in found.values():
        keys += [key for key in (report["fields"] or {}) if key not in keys]
    if keys:
        def cell(report, key):
            value = (report["fields"] or {}).get(key)
            return "; ".join(map(str, value)) if isinstance(value, list) else fmt(value)
        comparison = pd.DataFrame({"Field": [key.replace("_", " ") for key in keys]})
        for model, report in found.items():
            comparison[model] = [cell(report, key) for key in keys]
        st.dataframe(comparison, hide_index=True, width="stretch", height=38 + 35 * len(comparison))

    for column, (model, report) in zip(st.columns(len(found)), found.items()):
        with column:
            st.markdown(f"#### {model} report")
            st.markdown(report["prose"])


def show_team(table, data, scouting, reports):
    labels = {row["team"]: team_label(row) for _, row in table.iterrows()}
    teams = list(labels)
    default = teams.index(HOME_TEAM) if HOME_TEAM in teams else 0
    team = st.selectbox("Team", teams, index=default, format_func=labels.get)
    row = table[table["team"] == team].iloc[0]

    st.subheader(labels[team])
    for items in [
        [("Rank", row["rank"]), ("W-L-T", row["record"]), ("RP", row["rp"]), ("MC rank", row["mc_rank"]), ("TBA pred rank", row["tba_rank"])],
        [("OPR", row["opr"]), ("DPR", row["dpr"]), ("CCWM", row["ccwm"]), ("MC RP", row["mc_rp"]), ("TBA pred RP", row["tba_rp"])],
    ]:
        for column, (label, value) in zip(st.columns(len(items)), items):
            column.metric(label, fmt(value))

    season = data["teams"][data["teams"]["team"] == team] if not data["teams"].empty else pd.DataFrame()
    if not season.empty:
        with st.expander("Season context"):
            info = season.iloc[0]
            st.dataframe(pd.DataFrame([{
                "Global OPR": info["global_opr"], "Global rank": info["global_rank"],
                "Last event": info["last_event"], "Last rank": info["last_rank"],
                "Last record": info["last_record"], "Avg pts": info["avg_pts"], "Event avg": info["event_avg"],
            }]), hide_index=True, width="stretch")

    st.markdown("### Scouting")
    matches = scouting[scouting["team"] == team] if not scouting.empty else pd.DataFrame()
    if matches.empty:
        st.info("No scouting data for this team with the current event filter.")
    else:
        items = [(LABELS[key], row[key]) for key in ["scouted", "auto_fuel", "teleop_fuel", "cycles", "fuel_per_cycle", "tower", "fouls", "points"]]
        for column, (label, value) in zip(st.columns(len(items)), items):
            column.metric(label, fmt(value))

        metric = st.selectbox("Per match", list(MATCH_METRICS), format_func=MATCH_METRICS.get)
        st.altair_chart(match_bars(matches, metric, MATCH_METRICS[metric]), width="stretch")

        columns = {"match": "Match", "event_group": "Group", "auto_fuel": "Auto fuel", "teleop_fuel": "Teleop fuel",
                   "teleop_cycles": "Cycles", "tower": "Tower pts", "fouls": "Fouls", "totalPoints": "Points", "comments": "Comments"}
        st.dataframe(matches[list(columns)].rename(columns=columns), hide_index=True, width="stretch",
                     column_config={"Comments": st.column_config.TextColumn(width="large")})

        comments = matches.dropna(subset=["comments"])
        with st.expander(f"Read all scout comments ({len(comments)})"):
            for _, match in comments.iterrows():
                st.markdown(f"**{match['match']}:** {match['comments']}")

    st.markdown("### TBA stat predictions")
    stats = data["stats_pred"][data["stats_pred"]["team"] == team] if not data["stats_pred"].empty else pd.DataFrame()
    if stats.empty:
        st.info("No stat predictions for this team yet.")
    else:
        view = stats[["level", "stat", "mean", "var"]].round(2).rename(columns={"level": "Level", "stat": "Stat", "mean": "Mean", "var": "Variance"})
        st.dataframe(view, hide_index=True, width="stretch")

    st.markdown("### AI reports")
    show_ai_reports(team, reports)


def show_compare(table, reports):
    labels = {row["team"]: team_label(row) for _, row in table.iterrows()}
    ranked = table.sort_values("rank")["team"].tolist()
    default = ([HOME_TEAM] if HOME_TEAM in ranked else []) + [t for t in ranked if t != HOME_TEAM][:2]
    picked = st.multiselect("Teams (pick three to test an alliance)", ranked, default=default, format_func=labels.get)
    if not picked:
        st.info("Pick at least one team.")
        return
    rows = table.set_index("team").loc[picked].reset_index()

    st.markdown("### Combined")
    fuel = rows["total_fuel"].sum()
    tower = rows["tower"].sum()
    metrics = [
        ("OPR", fmt(float(rows["opr"].sum()))),
        ("Cycles", fmt(float(rows["cycles"].sum()))),
        ("Fuel", fmt(float(fuel))),
        (f"Energized ({ENERGIZED_FUEL} fuel)", "Yes" if fuel >= ENERGIZED_FUEL else "No"),
        (f"Supercharged ({SUPERCHARGED_FUEL} fuel)", "Yes" if fuel >= SUPERCHARGED_FUEL else "No"),
        (f"Traversal ({TRAVERSAL_TOWER} tower)", "Yes" if tower >= TRAVERSAL_TOWER else "No"),
    ]
    for column, (label, value) in zip(st.columns(len(metrics)), metrics):
        column.metric(label, value)
    st.caption("Based on scouted averages under the current event filter. Teams with no scouting data count as zero.")

    st.markdown("### Side by side")
    columns = {col: label for group, cols in COLUMN_GROUPS.items()
               if group != "AI" or any(reports.values()) for col, label in cols.items()}
    grid = pd.DataFrame({"Metric": columns.values()})
    for _, row in rows.iterrows():
        grid[row["team"]] = [fmt(row[col]) for col in columns]
    st.dataframe(grid, hide_index=True, width="stretch", height=38 + 35 * len(grid))

    st.markdown("### Charts")
    metrics = ["opr", "total_fuel", "cycles", "tower"]
    for column, metric in zip(st.columns(len(metrics)), metrics):
        with column:
            if rows[metric].notna().any():
                st.altair_chart(team_bars(rows, metric, LABELS[metric]), width="stretch")


def match_sort_key(match_key):
    """qm2 before qm10, then semifinals, then finals."""
    code = match_key.split("_")[-1]
    numbers = [int(n) for n in re.findall(r"\d+", code)]
    level = re.match(r"[a-z]+", code).group()
    return ({"qm": 0, "ef": 1, "qf": 2, "sf": 3, "f": 4}.get(level, 5), numbers)


def show_matches(matches):
    if matches.empty:
        st.info("No match predictions yet. Run `python -m pipeline.base`.")
        return

    level_col, close_col = st.columns(2)
    levels = level_col.multiselect("Level", sorted(matches["level"].unique(), reverse=True), default=sorted(matches["level"].unique(), reverse=True))
    max_prob = close_col.slider("Only matches where the favorite's win chance is at most (%)", 50, 100, 100)

    rows = matches[matches["level"].isin(levels) & (matches["win_prob"] * 100 <= max_prob)]
    rows = rows.loc[sorted(rows.index, key=lambda i: match_sort_key(rows.at[i, "match_key"]))]

    view = pd.DataFrame({
        "Match": rows["match_key"].str.split("_").str[-1],
        "Level": rows["level"],
        "Favorite": rows["predicted_winner"],
        "Win chance %": (rows["win_prob"] * 100).round(1),
        "Red pred score": rows["red_score"].round(1),
        "Blue pred score": rows["blue_score"].round(1),
        "Margin": (rows["red_score"] - rows["blue_score"]).abs().round(1),
    })
    count_col, red_col, blue_col = st.columns(3)
    count_col.metric("Matches shown", len(view))
    red_col.metric("Red favored", int((view["Favorite"] == "red").sum()))
    blue_col.metric("Blue favored", int((view["Favorite"] == "blue").sum()))
    st.dataframe(view, hide_index=True, width="stretch", height=560)


def show_data_checks(data, scouting_all, table, reports):
    st.markdown("### Pipeline output")
    status = []
    for name, path in FILES.items():
        status.append({
            "File": str(path.relative_to(path.parents[2])),
            "Status": "Found" if path.exists() else "Missing",
            "Rows": len(data["scouting_all"] if name == "scouting" else data[name]) if path.exists() else None,
            "Last updated": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M") if path.exists() else None,
        })
    st.dataframe(pd.DataFrame(status), hide_index=True, width="stretch")

    st.markdown("### AI reports")
    for model, found in reports.items():
        cut_off = sorted((t for t, report in found.items() if report["fields"] is None), key=int)
        st.write(f"**{model}:** {len(found)} found, {len(cut_off)} cut off" + (f" ({', '.join(cut_off)})" if cut_off else ""))

    if scouting_all.empty:
        return

    st.markdown("### Scouting data")
    at_event = set(table["team"])
    unknown = scouting_all[~scouting_all["team"].isin(at_event)]
    if not unknown.empty:
        st.warning("Scouted teams that aren't at this event. These may be typos in the team number.")
        st.dataframe(unknown.groupby("team")["event"].agg(["count", lambda e: ", ".join(sorted(set(e)))])
                     .reset_index().set_axis(["Team", "Rows", "Events"], axis=1), hide_index=True, width="stretch")

    no_scouting = table.loc[~table["team"].isin(scouting_all["team"]), "team"].tolist()
    if no_scouting:
        st.write(f"**Teams at the event with no scouting data ({len(no_scouting)}):** {', '.join(no_scouting)}")

    duplicates = scouting_all[scouting_all.duplicated(["team", "documentId"], keep=False)]
    st.write(f"**Rows with a negative foul value (ignored in foul averages):** {int(scouting_all['negative_foul'].sum())}")
    st.write(f"**Rows repeating the same team and match:** {len(duplicates)}")
    if not duplicates.empty:
        with st.expander("Show repeated rows"):
            st.dataframe(duplicates[["team", "documentId", "auto_fuel", "teleop_fuel", "totalPoints", "comments"]]
                         .sort_values(["team", "documentId"]), hide_index=True, width="stretch")

    st.markdown("**How each event name was grouped**")
    st.dataframe(scouting_all.groupby(["event_group", "event"]).size().reset_index(name="Rows")
                 .rename(columns={"event_group": "Group", "event": "Event as typed"}), hide_index=True, width="stretch")


# ── App ───────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="FRC Scouting", layout="wide")

data = {
    "teams":      read_csv("teams", "team_number"),
    "opr":        read_csv("opr", "team_key"),
    "rankings":   read_csv("rankings", "team_key"),
    "rank_pred":  read_csv("rank_pred", "team"),
    "stats_pred": read_csv("stats_pred", "team"),
    "matches":    read_csv("matches"),
    "montecarlo": read_csv("montecarlo", "team"),
}
scouting_all = load_scouting()
data["scouting_all"] = scouting_all
reports = load_reports()

with st.sidebar:
    st.title("FRC Scouting")
    st.caption(f"Event {EVENT_KEY}")
    st.button("Reload data", width="stretch")
    scouting = scouting_all
    if not scouting_all.empty:
        groups = sorted(scouting_all["event_group"].unique())
        picked = st.multiselect("Scouting data from", groups, default=groups)
        scouting = scouting_all[scouting_all["event_group"].isin(picked)]
        st.caption(f"{len(scouting)} of {len(scouting_all)} scouted matches. AI reports were written from all of them, whatever this is set to.")

table = build_team_table(data, scouting, reports)

if table.empty:
    st.title("No pipeline output yet")
    st.info("Run these from the repo root, then press **Reload data**.")
    st.code("python -m pipeline.base\npython -m pipeline.montecarlo\npython -m pipeline.analysts", language="bash")
    st.stop()

rankings_tab, team_tab, compare_tab, matches_tab, checks_tab = st.tabs(["Rankings", "Team", "Compare", "Matches", "Data checks"])
with rankings_tab:
    show_rankings(table, reports)
with team_tab:
    show_team(table, data, scouting, reports)
with compare_tab:
    show_compare(table, reports)
with matches_tab:
    show_matches(data["matches"])
with checks_tab:
    show_data_checks(data, scouting_all, table, reports)
