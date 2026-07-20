/* 逆・血統ビーム PWA — vanilla JS, ビルドツールなし */
(() => {
  "use strict";

  // ?sample=empty|nosale でサンプル状態を切替 (表示確認用)
  const SAMPLE = new URLSearchParams(location.search).get("sample");
  const DATA_DIR = SAMPLE ? `data/samples/${SAMPLE}` : "data";

  const $ = (id) => document.getElementById(id);
  const state = {
    candidates: null,
    picks: null,
    meta: null,
    tab: null,          // "sat" | "sun" | "results"
    expanded: new Set() // 展開中カードの race_id:horse_number
  };

  // ─── データ取得 ───
  async function fetchJson(name, bust) {
    const url = `${DATA_DIR}/${name}${bust ? `?t=${Date.now()}` : ""}`;
    const resp = await fetch(url, { cache: bust ? "reload" : "default" });
    if (!resp.ok) throw new Error(`${name}: ${resp.status}`);
    return resp.json();
  }

  async function loadAll(bust = false) {
    const spinner = $("spinner");
    spinner.hidden = false;
    try {
      const [candidates, picks, meta] = await Promise.all([
        fetchJson("candidates.json", bust),
        fetchJson("picks.json", bust).catch(() => null),
        fetchJson("meta.json", bust).catch(() => null),
      ]);
      state.candidates = candidates;
      state.picks = picks;
      state.meta = meta;
      if (!state.tab) state.tab = defaultTab();
      render();
    } catch (e) {
      // 圏外かつキャッシュなし
      $("card-list").innerHTML =
        `<div class="empty-state"><p class="empty-main">データを取得できません</p>
         <p class="empty-sub">電波のある場所で再読み込みしてください</p></div>`;
    } finally {
      spinner.hidden = true;
    }
  }

  function defaultTab() {
    const days = state.candidates?.weekend || [];
    const today = jstToday();
    if (days[1] && today >= days[1]) return "sun";
    return "sat";
  }

  function jstNow() {
    return new Date(Date.now() + (9 * 60 + new Date().getTimezoneOffset()) * 60000);
  }
  function jstToday() {
    const d = jstNow();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  // ─── 結合・分類 ───
  function pickFor(raceId, horseNumber) {
    return (state.picks?.picks || []).find(
      (p) => p.race_id === raceId && p.horse_number === horseNumber) || null;
  }

  function oddsReleased() {
    return (state.picks?.picks || []).some((p) => p.odds_win != null);
  }

  function postDate(race) {
    // race.date "YYYY-MM-DD" + post_time "HH:MM" はJST
    if (!race.post_time) return null;
    return new Date(`${race.date}T${race.post_time}:00+09:00`);
  }

  function rowsForDay(dateStr) {
    const rows = [];
    for (const race of state.candidates?.races || []) {
      if (race.date !== dateStr) continue;
      for (const cand of race.candidates) {
        const pick = pickFor(race.race_id, cand.horse_number);
        rows.push({ race, cand, pick, inBand: !!pick?.in_band });
      }
    }
    rows.sort((a, b) => (a.race.post_time || "99:99").localeCompare(b.race.post_time || "99:99"));
    return rows;
  }

  // ─── 描画 ───
  function render() {
    renderTopbar();
    renderTabs();
    const isResults = state.tab === "results";
    $("view-day").hidden = isResults;
    $("view-results").hidden = !isResults;
    if (isResults) renderResults();
    else renderDay();
  }

  function renderTopbar() {
    const asof = state.picks?.odds_asof;
    $("odds-asof").textContent = asof ? `${asof}時点` : "オッズ未取得";
    const note = $("stale-note");
    const updated = state.picks?.updated_at;
    if (updated && jstToday() > updated.slice(0, 10)) {
      // 当日より古いpicks = スタレ表示
      note.textContent = `⚠ 表示中のオッズは ${updated.slice(5, 10).replace("-", "/")} ${asof} 時点のものです`;
      note.hidden = false;
    } else {
      note.hidden = true;
    }
  }

  function renderTabs() {
    const days = state.candidates?.weekend || [];
    $("tab-sat").textContent = days[0] ? `土 ${Number(days[0].slice(8, 10))}日` : "土";
    $("tab-sun").textContent = days[1] ? `日 ${Number(days[1].slice(8, 10))}日` : "日";
    for (const [id, key] of [["tab-sat", "sat"], ["tab-sun", "sun"], ["tab-results", "results"]]) {
      $(id).setAttribute("aria-pressed", String(state.tab === key));
    }
  }

  function renderDay() {
    const days = state.candidates?.weekend || [];
    const dateStr = state.tab === "sun" ? days[1] : days[0];
    const rows = rowsForDay(dateStr);
    const released = oddsReleased();

    // postDate は+09:00付き絶対時刻なので現在時刻との直接比較でよい
    const finished = rows.filter((r) => postDate(r.race) && postDate(r.race) < new Date());
    const upcoming = rows.filter((r) => !finished.includes(r));

    const picksUp = upcoming.filter((r) => r.inBand);
    const outUp = upcoming.filter((r) => !r.inBand);

    const heroSlot = $("hero-slot");
    const list = $("card-list");
    heroSlot.innerHTML = "";
    list.innerHTML = "";

    $("empty-state").hidden = !(rows.length === 0 || (released && picksUp.length === 0 && finished.length === 0));

    if (picksUp.length > 0) {
      heroSlot.appendChild(card(picksUp[0], { hero: true, released }));
      for (const r of picksUp.slice(1)) list.appendChild(card(r, { released }));
    }

    // オッズ未発売: 候補を発売待ちバッジ付きで表示 (エラーにしない)
    const outband = $("outband-details");
    const outList = $("outband-list");
    outList.innerHTML = "";
    if (!released && outUp.length > 0) {
      $("empty-state").hidden = true;
      for (const r of outUp) list.appendChild(card(r, { released }));
      outband.hidden = true;
    } else if (outUp.length > 0) {
      outband.hidden = false;
      $("outband-summary").textContent = `候補(帯外) ${outUp.length}頭`;
      for (const r of outUp) outList.appendChild(card(r, { released, outband: true }));
    } else {
      outband.hidden = true;
    }

    const finSection = $("finished-section");
    const finList = $("finished-list");
    finList.innerHTML = "";
    finSection.hidden = finished.length === 0;
    for (const r of finished) finList.appendChild(card(r, { released, finished: true }));
  }

  function card(row, opts = {}) {
    const { race, cand, pick } = row;
    const key = `${race.race_id}:${cand.horse_number}`;
    const el = document.createElement("button");
    el.type = "button";
    el.className = "race-card" +
      (opts.hero ? " hero" : "") +
      (opts.outband ? " outband-card" : "") +
      (opts.finished ? " finished-card" : "");

    const odds = pick?.odds_win;
    let oddsHtml;
    if (odds != null) {
      oddsHtml = `<span class="odds-badge${row.inBand ? " in-band" : ""}">単勝 ${odds.toFixed(1)}倍</span>`;
    } else {
      oddsHtml = `<span class="odds-badge waiting">オッズ発売待ち</span>`;
    }

    const cd = opts.finished ? "" : countdownHtml(race);
    const warnChip = race.chukyo_warning
      ? `<span class="chip warn">中京は効き弱(検証済)</span>` : "";
    const expanded = state.expanded.has(key);

    el.innerHTML = `
      ${opts.hero ? `<div class="hero-label">次の推奨</div>` : ""}
      <div class="card-line1">
        <span class="race-time">${race.post_time || "--:--"}</span>
        <span class="race-place">${race.venue_name}${race.race_number}R</span>
        <span class="race-cond">${race.surface}${race.distance}</span>
        ${cd}
      </div>
      <div class="horse-line">
        <span class="horse-number">${cand.horse_number}</span><span class="horse-name">${esc(cand.horse_name)}</span>
      </div>
      <div class="odds-line">${oddsHtml}</div>
      <div class="chips">
        <span class="chip">父${esc(cand.sire_name)}=日本型</span>
        <span class="chip">${race.distance}m=非根幹</span>
        <span class="chip">10-50倍帯</span>
        ${warnChip}
      </div>
      ${expanded ? detailHtml(race) : ""}`;

    el.addEventListener("click", (ev) => {
      if (ev.target.closest("a")) return; // リンクは素通し
      if (state.expanded.has(key)) state.expanded.delete(key);
      else state.expanded.add(key);
      render();
    });
    return el;
  }

  function detailHtml(race) {
    const years = state.meta?.by_year || {};
    const perf = Object.keys(years).sort()
      .map((y) => `${y.slice(2)}:${years[y].win_roi_pct.toFixed(1)}%`).join(" → ");
    return `<div class="card-detail">
      <p class="perf-line">年別実績 ${perf || "--"}</p>
      <a class="nk-link" target="_blank" rel="noopener"
         href="https://race.netkeiba.com/race/shutuba.html?race_id=${race.race_id}">netkeibaで出馬表を見る</a>
    </div>`;
  }

  function countdownHtml(race) {
    const pd = postDate(race);
    if (!pd) return "";
    const mins = Math.floor((pd - new Date()) / 60000);
    if (mins < 0) return "";
    if (mins >= 600) return "";
    const h = Math.floor(mins / 60), m = mins % 60;
    const text = h > 0 ? `あと${h}時間${m}分` : `あと${m}分`;
    return `<span class="countdown${mins <= 30 ? " urgent" : ""}">${text}</span>`;
  }

  function renderResults() {
    const meta = state.meta;
    const body = $("results-body");
    if (!meta) { body.innerHTML = `<p class="results-note">meta.json 未取得</p>`; return; }
    const years = meta.by_year || {};
    const rows = Object.keys(years).sort().map((y) => {
      const v = years[y];
      const cls = v.win_roi_pct >= 100 ? ` class="roi-good"` : "";
      return `<tr><td>${y}年</td><td>${v.n.toLocaleString()}</td><td${cls}>${v.win_roi_pct.toFixed(1)}%</td></tr>`;
    }).join("");
    body.innerHTML = `
      <table class="results-table">
        <thead><tr><th>年</th><th>n</th><th>回収率</th></tr></thead>
        <tbody>${rows}
          <tr><td>帯内計</td><td>${meta.band?.n?.toLocaleString() || "--"}</td>
              <td class="roi-good">${meta.band?.win_roi_pct?.toFixed(1) || "--"}%</td></tr>
        </tbody>
      </table>
      <p class="results-note">対象: 芝・非根幹距離・父日本型・単勝10-50倍帯 (${meta.db_span?.join(" 〜 ") || ""})。
      全オッズ帯では n=${meta.all?.n?.toLocaleString() || "--"} / ${meta.all?.win_roi_pct || "--"}%。</p>`;
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ─── イベント ───
  function setTab(tab) {
    state.tab = tab;
    render();
  }
  $("tab-sat").addEventListener("click", () => setTab("sat"));
  $("tab-sun").addEventListener("click", () => setTab("sun"));
  $("tab-results").addEventListener("click", () => setTab("results"));
  $("tab-refresh").addEventListener("click", () => loadAll(true));
  $("refresh-btn").addEventListener("click", () => loadAll(true));

  // 発走時刻の経過を1分ごとに反映
  setInterval(() => { if (state.candidates && state.tab !== "results") render(); }, 60000);

  // ─── Service Worker ───
  if ("serviceWorker" in navigator && !SAMPLE) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }

  loadAll();
})();
