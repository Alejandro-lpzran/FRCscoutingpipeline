// FRC Scouting dashboard. Reads one JSON file made by `python -m pipeline.export`.
//
// How it's organized:
//   1. Config      labels and column groups
//   2. State       the loaded JSON, plus the scouting filter applied to it
//   3. Helpers     fmt, escapeHtml, sortableTable, statCards, barChart, rankScatter, proseHtml
//   4. Views       one function per tab; each fills #view
//   5. Router      reads the #hash in the URL and shows that tab
//
// The pattern every view follows: set view.innerHTML with empty placeholder <div>s, then fill the
// placeholders that need click handlers (tables) with replaceChildren(sortableTable(...)).

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
const TEXT_COLUMNS = ["nickname", "record", "tier_gemini", "tier_gpt", "profile_gemini", "profile_gpt"];
const WHOLE_NUMBERS = new Set(["rank", "rp", "tba_rank", "mc_rank", "scouted"]);
const CHART_METRICS = ["opr", "dpr", "ccwm", "total_fuel", "auto_fuel", "teleop_fuel", "cycles",
                       "fuel_per_cycle", "tower", "points", "fouls", "rp", "mc_rp"];

// Per-match scouting columns, as they appear in DATA.scouting
const MATCH_METRICS = { teleop_fuel: "Teleop fuel", auto_fuel: "Auto fuel", teleop_cycles: "Cycles",
                        tower: "Tower pts", totalPoints: "Points", fouls: "Fouls" };
const MODELS = { gemini: "Gemini", gpt: "GPT" };
const REPORT_SECTIONS = ["Performance Summary", "Autonomous", "Teleop", "Endgame", "Cycle Analysis",
                         "Strengths", "Weaknesses", "Match Strategy"];
// qm2 before qm10, then quarterfinals, semifinals, finals
const LEVEL_ORDER = { qm: 0, ef: 1, qf: 2, sf: 3, f: 4 };

// ── 2. State ─────────────────────────────────────────────────────────────────

// The loaded JSON. Views read from it; nothing writes to it after load.
let DATA = null;

// The export averages scouting over Gotham matches only. The filter bar can pick other event groups,
// so the page redoes those averages here. Views read TEAMS and SCOUTING instead of DATA.teams and DATA.scouting.
let TEAMS = [];
let SCOUTING = [];
let pickedGroups = null;   // Set of event groups to keep. null until the first load

// Selections that should survive switching tabs
let pickedTeam = null;     // Team tab
let compareTeams = null;   // Compare tab

function mean(rows, key) {
  const values = rows.map(r => r[key]).filter(v => v !== null && v !== undefined);
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
}

// Same math as build_team_table in pipeline/export.py
function scoutingAverages(rows) {
  const avg = {
    scouted:     rows.length,
    auto_fuel:   mean(rows, "auto_fuel"),
    teleop_fuel: mean(rows, "teleop_fuel"),
    cycles:      mean(rows, "teleop_cycles"),
    tower:       mean(rows, "tower"),
    fouls:       mean(rows, "fouls"),
    points:      mean(rows, "totalPoints"),
  };
  avg.total_fuel = avg.auto_fuel !== null && avg.teleop_fuel !== null ? avg.auto_fuel + avg.teleop_fuel : null;
  avg.fuel_per_cycle = avg.teleop_fuel !== null && avg.cycles > 0 ? avg.teleop_fuel / avg.cycles : null;
  return avg;
}

function applyScoutingFilter() {
  SCOUTING = DATA.scouting.filter(r => pickedGroups.has(r.event_group));
  TEAMS = DATA.teams.map(t => ({ ...t, ...scoutingAverages(SCOUTING.filter(r => r.team === t.team)) }));
  const count = document.getElementById("filter-count");
  if (count) count.textContent = `${SCOUTING.length} of ${DATA.scouting.length} scouted matches. ` +
                                 "AI reports only use Gotham matches, whatever this is set to.";
}

// The "Scouting data from" bar under the tabs. Changing it re-averages and redraws the current tab.
function renderFilterBar() {
  const bar = document.getElementById("filterbar");
  const groups = [...new Set(DATA.scouting.map(r => r.event_group))].sort();
  if (pickedGroups === null) pickedGroups = new Set(groups.filter(g => g === "Gotham"));
  bar.hidden = !groups.length;
  bar.innerHTML = `
    <span class="muted">Scouting data from</span>
    ${groups.map(g => `<label class="chip"><input type="checkbox" value="${escapeHtml(g)}"
      ${pickedGroups.has(g) ? "checked" : ""}> ${escapeHtml(g)}</label>`).join("")}
    <span class="muted" id="filter-count"></span>`;
  bar.querySelectorAll("input").forEach(input => input.addEventListener("change", () => {
    pickedGroups = new Set([...bar.querySelectorAll("input:checked")].map(i => i.value));
    applyScoutingFilter();
    route();
  }));
}

// ── 3. Helpers ───────────────────────────────────────────────────────────────

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

// Numbers to display text. null/undefined become a dash.
function fmt(value, column, digits = 1) {
  if (value === null || value === undefined || value === "") return "–";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value !== "number") return String(value);
  if (WHOLE_NUMBERS.has(column)) return String(Math.round(value));
  return Number.isInteger(value) ? String(value) : value.toFixed(digits);
}

function isHome(team) {
  return team === DATA.meta.home_team;
}

function teamLabel(row) {
  return row.nickname ? `${row.team} · ${row.nickname}` : row.team;
}

// Sort helper: real rank first, teams without a rank at the end
function byRank(a, b) {
  return (a.rank ?? Infinity) - (b.rank ?? Infinity);
}

function notice(text, kind = "") {
  return `<div class="notice ${kind}">${text}</div>`;
}

// A table you can sort by clicking headers.
//   rows:    array of objects
//   columns: { key: "Label" }   (keys that look like numbers get reordered by JS, so prefix them)
//   opts.sortKey, opts.ascending: starting sort. Without sortKey, rows keep the order given
//   opts.textColumns: keys to left-align
//   opts.wrapColumns: keys whose long text wraps instead of stretching the table
//   opts.digits:      { key: decimals } for columns that need more than 1
//   opts.cellClass:   (key, row) => extra CSS class for a cell
// Returns an element (not a string) because it needs click handlers.
function sortableTable(rows, columns, opts = {}) {
  const textColumns = new Set([...(opts.textColumns || []), ...(opts.wrapColumns || [])]);
  const wrapColumns = new Set(opts.wrapColumns || []);
  const digits = opts.digits || {};
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
        const text = fmt(row[key], key, digits[key]);
        const classes = [textColumns.has(key) ? "text" : "", wrapColumns.has(key) ? "wrap" : "",
                         text === "–" ? "empty" : "", opts.cellClass ? opts.cellClass(key, row) : ""];
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

// A row of stat cards. items: [[label, text, extraClass?], ...]
function statCards(items) {
  return `<div class="stats">${items.map(([label, text, cls = ""]) => `
    <div class="stat"><div class="label">${escapeHtml(label)}</div>
    <div class="value ${cls}">${escapeHtml(text)}</div></div>`).join("")}</div>`;
}

// Stat cards for some columns of one team row
function teamStats(row, keys) {
  return statCards(keys.map(key => [LABELS[key], fmt(row[key], key)]));
}

// Horizontal bars. Pure HTML/CSS, no chart library.
//   opts.label:  row => text on the left (default: team number)
//   opts.sort:   false keeps the given order instead of best first
//   opts.labelWidth: CSS width of the label column, for labels longer than a team number
function barChart(rows, metric, opts = {}) {
  const label = opts.label || (r => r.team);
  const withValues = rows.filter(r => r[metric] !== null && r[metric] !== undefined);
  if (opts.sort !== false) withValues.sort((a, b) => b[metric] - a[metric]);
  if (!withValues.length) return notice("No data for this metric yet.");
  const max = Math.max(...withValues.map(r => Math.abs(r[metric]))) || 1;
  const bars = withValues.map(r => `
    <div class="bar-row ${!opts.label && isHome(r.team) ? "home" : ""}" title="${escapeHtml(r.nickname || "")}">
      <span class="name">${escapeHtml(label(r))}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${(Math.abs(r[metric]) / max) * 100}%"></div></div>
      <span class="num">${fmt(r[metric], metric)}</span>
    </div>`).join("");
  return `<div class="bars" style="--label-width: ${opts.labelWidth || "56px"}">${bars}</div>`;
}

// Real rank (x) against a predicted rank (y), drawn as plain SVG.
// Rank 1 is the bottom-left corner. Dots on the dashed diagonal were predicted exactly.
function rankScatter(rows, predicted) {
  const points = rows.filter(r => r.rank != null && r[predicted] != null)
                     .sort((a, b) => isHome(a.team) - isHome(b.team));   // home team drawn last, on top
  if (!points.length) return notice("Needs both real rankings and predictions.");

  const size = 420, pad = 40;
  const top = Math.max(...points.flatMap(r => [r.rank, r[predicted]]));
  // Rank to pixels. SVG y grows downward, so y flips x.
  const x = rank => pad + ((rank - 1) / Math.max(top - 1, 1)) * (size - 2 * pad);
  const y = rank => size - x(rank);

  const ticks = [1];
  for (let t = 5; t <= top; t += 5) ticks.push(t);
  const grid = ticks.map(t => `
    <line class="grid-line" x1="${x(t)}" y1="${pad}" x2="${x(t)}" y2="${size - pad}"/>
    <line class="grid-line" x1="${pad}" y1="${y(t)}" x2="${size - pad}" y2="${y(t)}"/>
    <text class="tick" x="${x(t)}" y="${size - pad + 16}" text-anchor="middle">${t}</text>
    <text class="tick" x="${pad - 8}" y="${y(t) + 4}" text-anchor="end">${t}</text>`).join("");
  const dots = points.map(r => `
    <circle class="dot ${isHome(r.team) ? "home" : ""}" cx="${x(r.rank)}" cy="${y(r[predicted])}" r="6">
      <title>${escapeHtml(teamLabel(r))}\nReal rank ${r.rank}, ${LABELS[predicted]} ${r[predicted]}</title>
    </circle>`).join("");

  return `
    <svg class="scatter" viewBox="0 0 ${size} ${size}" role="img" aria-label="Real rank against ${LABELS[predicted]}">
      ${grid}
      <line class="diagonal" x1="${x(1)}" y1="${y(1)}" x2="${x(top)}" y2="${y(top)}"/>
      ${dots}
      <text class="axis-title" x="${size / 2}" y="${size - 6}" text-anchor="middle">Real rank</text>
      <text class="axis-title" transform="translate(12 ${size / 2}) rotate(-90)" text-anchor="middle">${LABELS[predicted]}</text>
    </svg>`;
}

// AI report prose to HTML: "Section:" starts get bolded, "- " lines become a list, every other line a paragraph.
function proseHtml(text) {
  const sections = new RegExp(`^(${REPORT_SECTIONS.join("|")}):`);
  let html = "", inList = false;
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const bullet = line.startsWith("- ");
    if (bullet && !inList) html += "<ul>";
    if (!bullet && inList) html += "</ul>";
    inList = bullet;
    const content = escapeHtml(bullet ? line.slice(2) : line).replace(sections, "<strong>$1:</strong>");
    html += bullet ? `<li>${content}</li>` : `<p>${content}</p>`;
  }
  return html + (inList ? "</ul>" : "");
}

// One value from a report's JSON fields as display text
function fieldText(value) {
  return Array.isArray(value) ? value.join("; ") : fmt(value);
}

// "qm10" -> [0, 10], "sf2m1" -> [3, 2, 1]. Compare those lists to put matches in play order.
function matchSortKey(code) {
  const level = (code.match(/^[a-z]+/) || [""])[0];
  return [LEVEL_ORDER[level] ?? 5, ...(code.match(/\d+/g) || []).map(Number)];
}

function compareMatches(a, b) {
  const x = matchSortKey(a), y = matchSortKey(b);
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    if (x[i] !== y[i]) return x[i] - y[i];
  }
  return x.length - y.length;
}

// ── 4. Views ─────────────────────────────────────────────────────────────────

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

    <h2>Monte Carlo ranking</h2>
    <p class="muted">Rank gap is real rank minus MC rank. Positive means the team finished worse than simulated.
      The simulation only models win and Energized RP, so compare ranks rather than RP totals.</p>
    <div id="mc"></div>

    <div class="grid" style="margin-top: 24px">
      <div class="card">
        <div class="controls">
          <h3 style="margin: 0">Compare all teams by</h3>
          <select id="metric">${CHART_METRICS.map(m => `<option value="${m}">${LABELS[m]}</option>`).join("")}</select>
        </div>
        <div id="chart"></div>
      </div>
      <div class="card">
        <div class="controls">
          <h3 style="margin: 0">Check predictions from</h3>
          <select id="predicted">
            <option value="mc_rank">${LABELS.mc_rank}</option>
            <option value="tba_rank">${LABELS.tba_rank}</option>
          </select>
        </div>
        <div id="scatter"></div>
        <p class="muted">Dots on the dashed line were predicted exactly. Hover a dot to see the team.</p>
      </div>
    </div>`;

  function update() {
    const search = view.querySelector("#search").value.toLowerCase();
    const scoutedOnly = view.querySelector("#scouted-only").checked;
    const picked = [...view.querySelectorAll(".controls input[value]:checked")].map(i => i.value);

    const rows = TEAMS.filter(t =>
      `${t.team} ${t.nickname || ""}`.toLowerCase().includes(search) &&
      (!scoutedOnly || t.scouted > 0));

    const columns = { team: "Team", nickname: "Name" };
    picked.forEach(g => Object.assign(columns, COLUMN_GROUPS[g]));

    view.querySelector("#count").textContent = `${rows.length} teams. Click a column header to sort.`;
    view.querySelector("#table").replaceChildren(
      sortableTable(rows, columns, { sortKey: "rank", textColumns: TEXT_COLUMNS }));

    const simulated = rows.filter(r => r.mc_rank !== null)
                          .map(r => ({ ...r, gap: r.rank !== null ? r.rank - r.mc_rank : null }));
    const mc = view.querySelector("#mc");
    if (simulated.length) {
      mc.replaceChildren(sortableTable(simulated,
        { mc_rank: "MC rank", team: "Team", nickname: "Name", mc_rp: "MC RP", rank: "Real rank", rp: "Real RP", gap: "Rank gap" },
        { sortKey: "mc_rank", textColumns: ["team", "nickname"], digits: { mc_rp: 2 } }));
    } else {
      mc.innerHTML = notice("No Monte Carlo results to show. Run <code>python -m pipeline.montecarlo</code>.");
    }

    view.querySelector("#chart").innerHTML = barChart(rows, view.querySelector("#metric").value);
    view.querySelector("#scatter").innerHTML = rankScatter(rows, view.querySelector("#predicted").value);
  }

  view.querySelectorAll("input, select").forEach(input => input.addEventListener("input", update));
  update();
}

function showTeam(view) {
  const teams = [...TEAMS].sort((a, b) => Number(a.team) - Number(b.team));
  if (!teams.some(t => t.team === pickedTeam)) {
    pickedTeam = teams.some(t => isHome(t.team)) ? DATA.meta.home_team : teams[0].team;
  }
  const row = teams.find(t => t.team === pickedTeam);
  const season = DATA.season[pickedTeam];
  const matches = SCOUTING.filter(r => r.team === pickedTeam);
  const comments = matches.filter(r => r.comments);
  const stats = DATA.stats_pred.filter(r => r.team === pickedTeam);

  view.innerHTML = `
    <div class="controls">
      <select id="team">${teams.map(t => `<option value="${t.team}" ${t.team === pickedTeam ? "selected" : ""}>
        ${escapeHtml(teamLabel(t))}</option>`).join("")}</select>
    </div>
    <h2>${escapeHtml(teamLabel(row))}</h2>
    ${teamStats(row, ["rank", "record", "rp", "mc_rank", "tba_rank", "opr", "dpr", "ccwm", "mc_rp", "tba_rp"])}
    ${season ? `<details class="card"><summary>Season context</summary><div id="season"></div></details>` : ""}

    <h2>Scouting</h2>
    ${matches.length ? `
      ${teamStats(row, ["scouted", "auto_fuel", "teleop_fuel", "cycles", "fuel_per_cycle", "tower", "fouls", "points"])}
      <div class="card" style="margin-top: 12px">
        <div class="controls">
          <h3 style="margin: 0">Per match</h3>
          <select id="match-metric">${Object.entries(MATCH_METRICS).map(([key, label]) =>
            `<option value="${key}">${label}</option>`).join("")}</select>
        </div>
        <div id="match-chart"></div>
      </div>
      <div id="matches" style="margin-top: 12px"></div>
      <details class="card">
        <summary>Read all scout comments (${comments.length})</summary>
        ${comments.map(m => `<p><strong>${escapeHtml(m.match)}:</strong> ${escapeHtml(m.comments)}</p>`).join("")}
      </details>`
    : notice("No scouting data for this team with the current event filter.")}

    <h2>TBA stat predictions</h2>
    <div id="stats"></div>

    <h2>AI reports</h2>
    <div id="reports"></div>`;

  view.querySelector("#team").addEventListener("change", e => {
    pickedTeam = e.target.value;
    showTeam(view);
  });

  if (season) {
    view.querySelector("#season").replaceChildren(sortableTable([season], {
      global_opr: "Global OPR", global_rank: "Global rank", last_event: "Last event", last_rank: "Last rank",
      last_record: "Last record", avg_pts: "Avg pts", event_avg: "Event avg",
    }, { textColumns: ["last_event", "last_record"] }));
  }

  if (matches.length) {
    const select = view.querySelector("#match-metric");
    const drawChart = () => {
      // Oldest match first. The export already sorted rows by when they were scouted.
      view.querySelector("#match-chart").innerHTML =
        barChart(matches, select.value, { label: r => r.match, sort: false, labelWidth: "140px" });
    };
    select.addEventListener("input", drawChart);
    drawChart();

    view.querySelector("#matches").replaceChildren(sortableTable(matches, {
      match: "Match", event_group: "Group", auto_fuel: "Auto fuel", teleop_fuel: "Teleop fuel",
      teleop_cycles: "Cycles", tower: "Tower pts", fouls: "Fouls", totalPoints: "Points", comments: "Comments",
    }, { textColumns: ["event_group"], wrapColumns: ["comments"] }));
  }

  const statsBox = view.querySelector("#stats");
  if (stats.length) {
    statsBox.replaceChildren(sortableTable(stats, { level: "Level", stat: "Stat", mean: "Mean", var: "Variance" },
      { textColumns: ["stat"], digits: { mean: 2, var: 2 } }));
  } else {
    statsBox.innerHTML = notice("No stat predictions for this team yet.");
  }

  showReports(view.querySelector("#reports"), pickedTeam);
}

// AI reports for one team: a warning per cut-off report, the JSON fields side by side, then the prose.
function showReports(box, team) {
  const found = Object.entries(DATA.reports).filter(([, reports]) => reports[team])
                      .map(([model, reports]) => ({ model, name: MODELS[model] || model, ...reports[team] }));
  if (!found.length) {
    box.innerHTML = notice("No AI reports for this team yet. Run <code>python -m pipeline.analysts</code>. " +
                           "Only the top 24 teams get one.");
    return;
  }

  const warnings = found.filter(r => !r.fields).map(r => notice(
    `The ${r.name} report has no valid JSON, so it was probably cut off. Delete the file and re-run to regenerate it.`, "warn"));
  box.innerHTML = `
    ${warnings.join("")}
    <div id="fields" style="margin: 12px 0"></div>
    <div class="grid">${found.map(r => `
      <div class="card prose"><h3 style="margin-top: 0">${r.name} report</h3>${proseHtml(r.prose)}</div>`).join("")}
    </div>`;

  const keys = [...new Set(found.flatMap(r => Object.keys(r.fields || {})))];
  if (keys.length) {
    const rows = keys.map(key => Object.assign({ field: key.replaceAll("_", " ") },
      ...found.map(r => ({ [r.model]: fieldText((r.fields || {})[key]) }))));
    const columns = Object.assign({ field: "Field" }, ...found.map(r => ({ [r.model]: r.name })));
    box.querySelector("#fields").replaceChildren(
      sortableTable(rows, columns, { wrapColumns: found.map(r => r.model) }));
  }
}

function showCompare(view) {
  const ranked = [...TEAMS].sort(byRank);
  if (compareTeams === null) {
    // Default: the home team plus the two best-ranked others
    const home = ranked.filter(t => isHome(t.team)).map(t => t.team);
    compareTeams = [...home, ...ranked.filter(t => !isHome(t.team)).slice(0, 2).map(t => t.team)];
  }
  const rows = compareTeams.map(team => TEAMS.find(t => t.team === team)).filter(Boolean);
  const available = ranked.filter(t => !compareTeams.includes(t.team));

  view.innerHTML = `
    <div class="controls">
      <span class="muted">Teams (pick three to test an alliance)</span>
      ${rows.map(r => `<button type="button" class="chip picked" data-team="${r.team}"
        title="Remove">${escapeHtml(teamLabel(r))} ✕</button>`).join("")}
      <select id="add">
        <option value="">Add team…</option>
        ${available.map(t => `<option value="${t.team}">${escapeHtml(teamLabel(t))}</option>`).join("")}
      </select>
    </div>
    <div id="result"></div>`;

  view.querySelectorAll("button[data-team]").forEach(button => button.addEventListener("click", () => {
    compareTeams = compareTeams.filter(team => team !== button.dataset.team);
    showCompare(view);
  }));
  view.querySelector("#add").addEventListener("change", e => {
    if (!e.target.value) return;
    compareTeams = [...compareTeams, e.target.value];
    showCompare(view);
  });

  const result = view.querySelector("#result");
  if (!rows.length) {
    result.innerHTML = notice("Pick at least one team.");
    return;
  }

  // Missing values count as zero, so a team with no scouting adds nothing
  const sum = key => rows.reduce((total, r) => total + (r[key] ?? 0), 0);
  const fuel = sum("total_fuel"), tower = sum("tower");
  const t = DATA.meta.thresholds;
  const clears = ok => [ok ? "Yes" : "No", ok ? "good" : "warn"];

  const hasAI = Object.values(DATA.reports).some(found => Object.keys(found).length);
  const metrics = Object.assign({}, ...Object.entries(COLUMN_GROUPS)
    .filter(([group]) => group !== "AI" || hasAI).map(([, columns]) => columns));
  const charts = ["opr", "total_fuel", "cycles", "tower"];

  result.innerHTML = `
    <h2>Combined</h2>
    ${statCards([
      ["OPR", fmt(sum("opr"))],
      ["Cycles", fmt(sum("cycles"))],
      ["Fuel", fmt(fuel)],
      [`Energized (${t.energized_fuel} fuel)`, ...clears(fuel >= t.energized_fuel)],
      [`Supercharged (${t.supercharged_fuel} fuel)`, ...clears(fuel >= t.supercharged_fuel)],
      [`Traversal (${t.traversal_tower} tower)`, ...clears(tower >= t.traversal_tower)],
    ])}
    <p class="muted" style="margin-top: 8px">Based on scouted averages under the current event filter.
      Teams with no scouting data count as zero.</p>

    <h2>Side by side</h2>
    <div id="side-by-side"></div>

    <h2>Charts</h2>
    <div class="grid">${charts.map(metric => `
      <div class="card"><h3 style="margin-top: 0">${LABELS[metric]}</h3>${barChart(rows, metric)}</div>`).join("")}
    </div>`;

  // Metrics as rows, one column per team. Team keys get a "t" prefix so JS keeps them in picked order.
  const grid = Object.entries(metrics).map(([key, label]) =>
    Object.assign({ metric: label }, ...rows.map(r => ({ [`t${r.team}`]: fmt(r[key], key) }))));
  const columns = Object.assign({ metric: "Metric" }, ...rows.map(r => ({ [`t${r.team}`]: r.team })));
  result.querySelector("#side-by-side").replaceChildren(sortableTable(grid, columns));
}

function showMatches(view) {
  if (!DATA.matches.length) {
    view.innerHTML = notice("No match predictions yet. Run <code>python -m pipeline.base</code>.");
    return;
  }
  const levels = [...new Set(DATA.matches.map(m => m.level))].sort().reverse();

  view.innerHTML = `
    <div class="controls">
      ${levels.map(l => `<label class="chip"><input type="checkbox" value="${escapeHtml(l)}" checked> ${escapeHtml(l)}</label>`).join("")}
      <label class="chip">Favorite's win chance at most
        <input type="range" id="max-prob" min="50" max="100" value="100"> <span id="max-prob-text"></span></label>
    </div>
    <div id="counts"></div>
    <div id="table" style="margin-top: 12px"></div>`;

  function update() {
    const picked = new Set([...view.querySelectorAll("input[value]:checked")].map(i => i.value));
    const maxProb = Number(view.querySelector("#max-prob").value);
    view.querySelector("#max-prob-text").textContent = `${maxProb}%`;

    const rows = DATA.matches
      .filter(m => picked.has(m.level) && m.win_prob * 100 <= maxProb)
      .sort((a, b) => compareMatches(a.code, b.code))
      .map(m => ({
        code: m.code,
        level: m.level,
        favorite: m.predicted_winner,
        win_chance: m.win_prob * 100,
        red_score: m.red_score,
        blue_score: m.blue_score,
        margin: Math.abs(m.red_score - m.blue_score),
      }));

    view.querySelector("#counts").innerHTML = statCards([
      ["Matches shown", String(rows.length)],
      ["Red favored", String(rows.filter(r => r.favorite === "red").length)],
      ["Blue favored", String(rows.filter(r => r.favorite === "blue").length)],
    ]);
    view.querySelector("#table").replaceChildren(sortableTable(rows, {
      code: "Match", level: "Level", favorite: "Favorite", win_chance: "Win chance %",
      red_score: "Red pred score", blue_score: "Blue pred score", margin: "Margin",
    }, { textColumns: ["level", "favorite"], cellClass: (key, row) => key === "favorite" ? row.favorite : "" }));
  }

  view.querySelectorAll("input").forEach(input => input.addEventListener("input", update));
  update();
}

function showChecks(view) {
  const checks = DATA.checks;
  const hasScouting = "event_groups" in checks;

  view.innerHTML = `
    <h2>Pipeline output</h2>
    <div id="files"></div>

    <h2>AI reports</h2>
    ${Object.entries(checks.reports).map(([model, status]) => `
      <p><strong>${MODELS[model] || model}:</strong> ${status.found} found, ${status.cut_off.length} cut off
      ${status.cut_off.length ? `(${status.cut_off.join(", ")})` : ""}</p>`).join("")}

    ${hasScouting ? `
      <h2>Scouting data</h2>
      ${checks.unknown_teams.length ? `
        ${notice("Scouted teams that aren't at this event. These may be typos in the team number.", "warn")}
        <div id="unknown" style="margin: 12px 0"></div>` : ""}
      ${checks.unscouted_teams.length ? `
        <p><strong>Teams at the event with no scouting data (${checks.unscouted_teams.length}):</strong>
        ${checks.unscouted_teams.join(", ")}</p>` : ""}
      <p><strong>Rows with a negative foul value (ignored in foul averages):</strong> ${checks.negative_foul_rows}</p>
      ${checks.duplicate_rows ? `
        <p><strong>Rows repeating the same team and match:</strong> ${checks.duplicate_rows.length}</p>
        ${checks.duplicate_rows.length ? `
          <details class="card"><summary>Show repeated rows</summary><div id="duplicates"></div></details>` : ""}` : ""}
      <h3>How each event name was grouped</h3>
      <div id="event-groups"></div>` : ""}`;

  view.querySelector("#files").replaceChildren(sortableTable(
    checks.files.map(f => ({ ...f, status: f.found ? "Found" : "Missing", updated: f.updated?.replace("T", " ") })),
    { file: "File", status: "Status", rows: "Rows", updated: "Last updated" },
    { textColumns: ["status", "updated"], cellClass: (key, row) => key === "status" && !row.found ? "warn" : "" }));

  if (!hasScouting) return;
  if (checks.unknown_teams.length) {
    view.querySelector("#unknown").replaceChildren(sortableTable(
      checks.unknown_teams.map(u => ({ ...u, events: u.events.join(", ") })),
      { team: "Team", rows: "Rows", events: "Events" }, { textColumns: ["events"] }));
  }
  if (checks.duplicate_rows?.length) {
    view.querySelector("#duplicates").replaceChildren(sortableTable(checks.duplicate_rows, {
      team: "Team", documentId: "Match ID", auto_fuel: "Auto fuel", teleop_fuel: "Teleop fuel",
      totalPoints: "Points", comments: "Comments",
    }, { textColumns: ["documentId"], wrapColumns: ["comments"] }));
  }
  view.querySelector("#event-groups").replaceChildren(sortableTable(checks.event_groups,
    { event_group: "Group", event: "Event as typed", rows: "Rows" }, { textColumns: ["event"] }));
}

// ── 5. Router ────────────────────────────────────────────────────────────────

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
  renderFilterBar();
  applyScoutingFilter();
  route();
}

window.addEventListener("hashchange", route);
document.getElementById("reload").addEventListener("click", load);
load();
