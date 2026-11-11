// FRC Scouting dashboard. Reads one JSON file made by `python -m pipeline.export`.
//
// How it's organized:
//   1. Config      labels and column groups
//   2. Helpers     fmt, escapeHtml, h (builds HTML), sortableTable, barChart
//   3. Views       one function per tab; each returns an HTML string or fills #view
//   4. Router      reads the #hash in the URL and shows that tab
//
// Rankings is fully built as the example. The other tabs are stubs with TODO lists.

const DATA_URL = "../data/processed/dashboard.json";

// ── 1. Config ────────────────────────────────────────────────────────────────

const COLUMN_GROUPS = {
  Standings:   { rank: "Rank", record: "W-L-T", rp: "RP", ranking_score: "Ranking score" },
  Power:       { opr: "OPR", dpr: "DPR", ccwm: "CCWM" },
  Predictions: { tba_rank: "TBA pred rank", tba_rp: "TBA pred RP", mc_rank: "MC rank", mc_rp: "MC RP" },
  Scouting:    { scouted: "Scouted", auto_fuel: "Auto fuel", teleop_fuel: "Teleop fuel", total_fuel: "Total fuel",
                 cycles: "Cycles", fuel_per_cycle: "Fuel/cycle", tower: "Tower pts", fouls: "Fouls", points: "Points" },
  AI:          { tier_gemini: "Tier (Gemini)", tier_gpt: "Tier (GPT)",
                 profile_gemini: "Profile (Gemini)", profile_gpt: "Profile (GPT)" },
};
const LABELS = Object.assign({}, ...Object.values(COLUMN_GROUPS));
const WHOLE_NUMBERS = new Set(["rank", "rp", "tba_rank", "mc_rank", "scouted"]);
const CHART_METRICS = ["opr", "dpr", "ccwm", "total_fuel", "auto_fuel", "teleop_fuel", "cycles",
                       "fuel_per_cycle", "tower", "points", "fouls", "rp", "mc_rp"];

// The loaded JSON lives here. Views read from it; nothing writes to it after load.
let DATA = null;

// ── 2. Helpers ───────────────────────────────────────────────────────────────

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

// Numbers to display text. null/undefined become a dash.
function fmt(value, column) {
  if (value === null || value === undefined || value === "") return "–";
  if (typeof value !== "number") return String(value);
  if (WHOLE_NUMBERS.has(column)) return String(Math.round(value));
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function isHome(team) {
  return team === DATA.meta.home_team;
}

function notice(text, kind = "") {
  return `<div class="notice ${kind}">${text}</div>`;
}

// A table you can sort by clicking headers.
//   rows:    array of objects
//   columns: { key: "Label" }
//   opts.textColumns: keys to left-align
// Returns an element (not a string) because it needs click handlers.
function sortableTable(rows, columns, opts = {}) {
  const textColumns = new Set(opts.textColumns || []);
  let sortKey = opts.sortKey || null;
  let ascending = opts.ascending ?? true;

  const wrap = document.createElement("div");
  wrap.className = "table-wrap";

  function render() {
    const sorted = [...rows];
    if (sortKey) {
      sorted.sort((a, b) => {
        const x = a[sortKey], y = b[sortKey];
        if (x === null || x === undefined) return 1;   // empty cells always at the bottom
        if (y === null || y === undefined) return -1;
        const order = typeof x === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true });
        return ascending ? order : -order;
      });
    }
    const head = Object.entries(columns).map(([key, label]) => {
      const classes = [textColumns.has(key) ? "text" : "", key === sortKey ? (ascending ? "sorted-asc" : "sorted-desc") : ""];
      return `<th data-key="${key}" class="${classes.join(" ")}">${escapeHtml(label)}</th>`;
    }).join("");
    const body = sorted.map(row => {
      const cells = Object.keys(columns).map(key => {
        const text = fmt(row[key], key);
        const classes = [textColumns.has(key) ? "text" : "", text === "–" ? "empty" : ""];
        return `<td class="${classes.join(" ")}">${escapeHtml(text)}</td>`;
      }).join("");
      return `<tr class="${isHome(row.team) ? "home" : ""}">${cells}</tr>`;
    }).join("");
    wrap.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;

    wrap.querySelectorAll("th").forEach(th => th.addEventListener("click", () => {
      const key = th.dataset.key;
      ascending = key === sortKey ? !ascending : true;
      sortKey = key;
      render();
    }));
  }

  render();
  return wrap;
}

// Horizontal bars, best first. Pure HTML/CSS, no chart library.
function barChart(rows, metric) {
  const withValues = rows.filter(r => r[metric] !== null && r[metric] !== undefined)
                         .sort((a, b) => b[metric] - a[metric]);
  if (!withValues.length) return notice("No data for this metric yet.");
  const max = Math.max(...withValues.map(r => Math.abs(r[metric]))) || 1;
  const bars = withValues.map(r => `
    <div class="bar-row ${isHome(r.team) ? "home" : ""}" title="${escapeHtml(r.nickname || "")}">
      <span class="name">${escapeHtml(r.team)}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${(Math.abs(r[metric]) / max) * 100}%"></div></div>
      <span class="num">${fmt(r[metric], metric)}</span>
    </div>`).join("");
  return `<div class="bars">${bars}</div>`;
}

// ── 3. Views ─────────────────────────────────────────────────────────────────

// Fully built. Use this as the pattern for the other tabs.
function showRankings(view) {
  const hasAI = Object.values(DATA.reports).some(found => Object.keys(found).length);
  const groups = Object.keys(COLUMN_GROUPS).filter(g => g !== "AI" || hasAI);

  view.innerHTML = `
    <div class="controls">
      <input type="search" id="search" placeholder="Search team or name">
      ${groups.map(g => `<label class="chip"><input type="checkbox" value="${g}" checked> ${g}</label>`).join("")}
      <label class="chip"><input type="checkbox" id="scouted-only"> Only scouted teams</label>
    </div>
    <p class="muted" id="count"></p>
    <div id="table"></div>
    <div class="grid" style="margin-top: 24px">
      <div class="card">
        <div class="controls">
          <h3 style="margin: 0">Compare all teams by</h3>
          <select id="metric">${CHART_METRICS.map(m => `<option value="${m}">${LABELS[m]}</option>`).join("")}</select>
        </div>
        <div id="chart"></div>
      </div>
      <div class="card">
        <h3 style="margin-top: 0">Monte Carlo vs real rank</h3>
        <!-- TODO (you): a scatter plot, real rank on x, MC rank on y, dashed diagonal line.
             Plain <svg> works: one <circle> per team, cx/cy scaled from rank to pixels. -->
        ${notice("Scatter plot goes here.")}
      </div>
    </div>`;

  function update() {
    const search = view.querySelector("#search").value.toLowerCase();
    const scoutedOnly = view.querySelector("#scouted-only").checked;
    const picked = [...view.querySelectorAll(".controls input[value]:checked")].map(i => i.value);

    const rows = DATA.teams.filter(t =>
      `${t.team} ${t.nickname || ""}`.toLowerCase().includes(search) &&
      (!scoutedOnly || t.scouted > 0));

    const columns = { team: "Team", nickname: "Name" };
    picked.forEach(g => Object.assign(columns, COLUMN_GROUPS[g]));

    view.querySelector("#count").textContent = `${rows.length} teams. Click a column header to sort.`;
    view.querySelector("#table").replaceChildren(
      sortableTable(rows, columns, { sortKey: "rank", textColumns: ["nickname", "record", "tier_gemini", "tier_gpt", "profile_gemini", "profile_gpt"] }));
    view.querySelector("#chart").innerHTML = barChart(rows, view.querySelector("#metric").value);
  }

  view.querySelectorAll("input, select").forEach(input => input.addEventListener("input", update));
  update();
}

function showTeam(view) {
  view.innerHTML = `
    <h2>Team</h2>
    ${notice(`TODO (you). What the old Streamlit tab had:
      <ul>
        <li>A team picker (&lt;select&gt;), defaulting to ${DATA.meta.home_team}</li>
        <li>Stat cards: Rank, W-L-T, RP, MC rank, TBA pred rank, OPR, DPR, CCWM, MC RP, TBA pred RP.
            Use <code>.stats</code> and <code>.stat</code> from style.css</li>
        <li>Season context from <code>DATA.season[team]</code></li>
        <li>Scouting: averages, a per-match bar chart, a table of matches, all comments.
            Rows are in <code>DATA.scouting</code>, filter by <code>team</code></li>
        <li>TBA stat predictions from <code>DATA.stats_pred</code></li>
        <li>AI reports: <code>DATA.reports.gemini[team]</code> and <code>.gpt[team]</code>, each with
            <code>prose</code> and <code>fields</code>. Show fields side by side, then both reports.
            If <code>fields</code> is null the report was cut off, so warn about it</li>
      </ul>`)}`;
}

function showCompare(view) {
  view.innerHTML = `
    <h2>Compare</h2>
    ${notice(`TODO (you). Pick up to three teams to test an alliance:
      <ul>
        <li>Combined OPR, cycles, fuel</li>
        <li>Whether the alliance clears each RP threshold in <code>DATA.meta.thresholds</code></li>
        <li>A side-by-side table, metrics as rows and teams as columns</li>
        <li>Small bar charts for OPR, total fuel, cycles, tower (<code>barChart</code> works on any rows)</li>
      </ul>
      Later this is where the neural net's win probability goes.`)}`;
}

function showMatches(view) {
  view.innerHTML = `
    <h2>Matches</h2>
    ${notice(`TODO (you). From <code>DATA.matches</code>:
      <ul>
        <li>Filters: level (qual/playoff) and "favorite's win chance at most X%" to find close matches</li>
        <li>Counts: matches shown, red favored, blue favored</li>
        <li>Table: match <code>code</code>, level, favorite, win chance %, red and blue predicted score, margin.
            Color the favorite with <code>--red</code> / <code>--blue</code></li>
        <li>Sort qm2 before qm10: <code>localeCompare</code> with <code>{ numeric: true }</code> does this</li>
      </ul>`)}`;
}

function showChecks(view) {
  view.innerHTML = `
    <h2>Data checks</h2>
    ${notice(`TODO (you). Everything is in <code>DATA.checks</code>:
      <ul>
        <li><code>files</code>: which pipeline outputs exist, row counts, last updated</li>
        <li><code>reports</code>: AI reports found and cut off, per model</li>
        <li><code>unknown_teams</code>: scouted teams not at the event (likely typos)</li>
        <li><code>unscouted_teams</code>, <code>negative_foul_rows</code>, <code>duplicate_rows</code>, <code>event_groups</code></li>
      </ul>`)}`;
}

// ── 4. Router ────────────────────────────────────────────────────────────────

const VIEWS = { rankings: showRankings, team: showTeam, compare: showCompare, matches: showMatches, checks: showChecks };

function route() {
  const name = location.hash.slice(1) in VIEWS ? location.hash.slice(1) : "rankings";
  document.querySelectorAll("#tabs a").forEach(a => a.classList.toggle("active", a.hash === `#${name}`));
  const view = document.getElementById("view");
  if (!DATA) return;
  if (!DATA.teams.length) {
    view.innerHTML = notice(`No pipeline output yet. From the repo root, run:
      <pre>python -m pipeline.base\npython -m pipeline.montecarlo\npython -m pipeline.analysts\npython -m pipeline.export</pre>`);
    return;
  }
  VIEWS[name](view);
}

async function load() {
  const view = document.getElementById("view");
  try {
    const response = await fetch(DATA_URL, { cache: "no-store" });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    DATA = await response.json();
  } catch (error) {
    view.innerHTML = notice(`Couldn't load <code>${DATA_URL}</code> (${escapeHtml(error.message)}).
      Run <code>python -m pipeline.export</code>, and serve the repo root, not the web folder:
      <pre>python -m http.server 8000</pre> then open <a href="http://localhost:8000/web/">localhost:8000/web/</a>`, "warn");
    return;
  }
  const generated = new Date(DATA.meta.generated_at).toLocaleString();
  document.getElementById("event-line").textContent = `Event ${DATA.meta.event_key} · data from ${generated}`;
  route();
}

window.addEventListener("hashchange", route);
document.getElementById("reload").addEventListener("click", load);
load();
