/* 逆・血統ビーム PWA — vanilla JS, ビルドツールなし (v2: core/watch/除外) */
(() => {
  "use strict";

  // ?sample=empty|nosale でサンプル状態を切替 (表示確認用)
  const SAMPLE = new URLSearchParams(location.search).get("sample");
  const DATA_DIR = SAMPLE ? `data/samples/${SAMPLE}` : "data";

  const BET_YEN = 500; // 収支グラフの1点あたり換算額 (実運用のベット額)

  const EXCL_LABELS = { long_layoff: "休", small: "小", extend: "延" };
  const EXCL_DESC = {
    long_layoff: "休=休養121日以上",
    small: "小=馬体重440kg以下",
    extend: "延=前走比+200m以上の延長",
  };

  const $ = (id) => document.getElementById(id);
  const state = {
    candidates: null,
    picks: null,
    meta: null,
    tab: null,          // "sat" | "sun" | "results"
    expanded: new Set(), // 展開中カードの race_id:horse_number
    pnlYear: null       // 収支グラフの表示年
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
        rows.push({
          race, cand, pick,
          tier: pick?.tier ?? null,
          // 除外理由: picks(当日馬体重で再判定済み) > candidates(前走値の仮判定)
          excl: pick?.excluded_reason ?? cand.excluded_reason ?? [],
          formMissing: pick?.form_missing ?? cand.form_missing ?? false,
        });
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

    const coreUp = upcoming.filter((r) => r.tier === "core");
    const watchUp = upcoming.filter((r) => r.tier === "watch");
    const otherUp = upcoming.filter((r) => r.tier == null);

    const heroSlot = $("hero-slot");
    const list = $("card-list");
    heroSlot.innerHTML = "";
    list.innerHTML = "";

    // 推奨(core)ゼロの日は「該当なし」を大きく (watchもない場合)
    $("empty-state").hidden = !(rows.length === 0 ||
      (released && coreUp.length === 0 && watchUp.length === 0 && finished.length === 0));

    if (coreUp.length > 0) {
      heroSlot.appendChild(card(coreUp[0], { hero: true, released }));
      for (const r of coreUp.slice(1)) list.appendChild(card(r, { released }));
    }

    // watch層(30-50倍) — coreの下に控えめ表示
    const watchSection = $("watch-section");
    const watchList = $("watch-list");
    watchList.innerHTML = "";
    watchSection.hidden = watchUp.length === 0;
    for (const r of watchUp) watchList.appendChild(card(r, { released, watch: true }));

    // オッズ未発売: 除外以外の候補を発売待ちバッジ付きで表示 (エラーにしない)
    const outband = $("outband-details");
    const outList = $("outband-list");
    outList.innerHTML = "";
    const excludedUp = otherUp.filter((r) => r.excl.length > 0);
    const bandOutUp = otherUp.filter((r) => r.excl.length === 0);
    if (!released && otherUp.length > 0) {
      $("empty-state").hidden = true;
      for (const r of bandOutUp) list.appendChild(card(r, { released }));
      if (excludedUp.length > 0) {
        outband.hidden = false;
        $("outband-summary").textContent = `候補(除外) ${excludedUp.length}頭`;
        for (const r of excludedUp) outList.appendChild(card(r, { released, outband: true }));
      } else {
        outband.hidden = true;
      }
    } else if (otherUp.length > 0) {
      outband.hidden = false;
      $("outband-summary").textContent =
        `候補(帯外${bandOutUp.length}・除外${excludedUp.length})`;
      for (const r of bandOutUp) outList.appendChild(card(r, { released, outband: true }));
      for (const r of excludedUp) outList.appendChild(card(r, { released, outband: true }));
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
      (opts.watch ? " watch-card" : "") +
      (opts.outband ? " outband-card" : "") +
      (opts.finished ? " finished-card" : "");

    const odds = pick?.odds_win;
    let oddsHtml;
    if (odds != null) {
      if (row.tier === "core") {
        oddsHtml = `<span class="odds-badge tier-core">単勝 ${odds.toFixed(1)}倍</span>`;
      } else if (row.tier === "watch") {
        oddsHtml = `<span class="odds-badge tier-watch">単勝 ${odds.toFixed(1)}倍<span class="watch-tag">参考</span></span>`;
      } else {
        oddsHtml = `<span class="odds-badge">単勝 ${odds.toFixed(1)}倍</span>`;
      }
    } else {
      oddsHtml = `<span class="odds-badge waiting">オッズ発売待ち</span>`;
    }

    const exclBadges = row.excl.map((r) =>
      `<span class="excl-badge" title="${EXCL_DESC[r] || r}">${EXCL_LABELS[r] || "?"}</span>`
    ).join("");
    const formChip = row.formMissing
      ? `<span class="chip sub">前走情報なし</span>` : "";

    const cd = opts.finished ? "" : countdownHtml(race);
    const warnChip = race.chukyo_warning
      ? `<span class="chip warn">中京は効き弱(検証済)</span>` : "";
    const tierChip = row.tier === "core"
      ? `<span class="chip">コア帯10-30倍</span>`
      : row.tier === "watch" ? `<span class="chip">参考帯30-50倍</span>` : "";
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
        <span class="horse-number">${cand.horse_number}</span><span class="horse-name">${esc(cand.horse_name)}</span>${exclBadges}
      </div>
      <div class="odds-line">${oddsHtml}</div>
      <div class="chips">
        <span class="chip">父${esc(cand.sire_name)}=日本型</span>
        <span class="chip">${race.distance}m=非根幹</span>
        ${tierChip}
        ${formChip}
        ${warnChip}
      </div>
      ${expanded ? detailHtml(row) : ""}`;

    el.addEventListener("click", (ev) => {
      if (ev.target.closest("a")) return; // リンクは素通し
      if (state.expanded.has(key)) state.expanded.delete(key);
      else state.expanded.add(key);
      render();
    });
    return el;
  }

  function detailHtml(row) {
    const core = state.meta?.core || {};
    const years = core.by_year || {};
    const perf = Object.keys(years).sort()
      .map((y) => `${y.slice(2)}:${Math.round(years[y].win_roi_pct)}%`).join(" → ");
    const ci = core.ci95 ? `95%CI ${core.ci95[0]}-${core.ci95[1]}%` : "";
    const exclNote = row.excl.length > 0
      ? `<p class="detail-note">除外理由: ${row.excl.map((r) => EXCL_DESC[r] || r).join(" / ")}</p>` : "";
    const watchNote = row.tier === "watch"
      ? `<p class="detail-note">参考: 30-50倍はデータ希薄のため購入対象外</p>` : "";
    return `<div class="card-detail">
      <p class="perf-line">コア帯実績 ${perf || "--"} ${ci ? `(${ci})` : ""}</p>
      <p class="detail-note">※10-50倍全体では2025年98%と100%割れの年もある。過去実績は将来を保証しない。</p>
      ${exclNote}${watchNote}
      <a class="nk-link" target="_blank" rel="noopener"
         href="https://race.netkeiba.com/race/shutuba.html?race_id=${row.race.race_id}">netkeibaで出馬表を見る</a>
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
    const core = meta.core || {};
    const years = core.by_year || {};
    const rows = Object.keys(years).sort().map((y) => {
      const v = years[y];
      const cls = v.win_roi_pct >= 100 ? ` class="roi-good"` : "";
      return `<tr><td>${y}年</td><td>${v.n.toLocaleString()}</td><td${cls}>${v.win_roi_pct.toFixed(1)}%</td></tr>`;
    }).join("");
    const ci = core.ci95 ? `${core.ci95[0]}-${core.ci95[1]}%` : "--";
    body.innerHTML = `
      <table class="results-table">
        <thead><tr><th>年</th><th>n</th><th>回収率</th></tr></thead>
        <tbody>${rows}
          <tr><td>コア計</td><td>${core.n?.toLocaleString() || "--"}</td>
              <td class="roi-good">${core.win_roi_pct?.toFixed(1) || "--"}%</td></tr>
        </tbody>
      </table>
      <p class="results-note">コア帯 = 芝・非根幹・父日本型・中京千直除外・ネガ3除外後の単勝10-30倍
      (${meta.db_span?.join(" 〜 ") || ""})。ブートストラップ95%CI ${ci}、P(&gt;100%)=${core.p_gt_100 ?? "--"}。</p>
      <p class="results-note">参考帯(30-50倍): n=${meta.watch?.n?.toLocaleString() || "--"} /
      ${meta.watch?.win_roi_pct || "--"}%(2025年${meta.watch?.worst_year_roi_pct ?? 38.5}%など年次ブレ大・購入対象外)。
      10-50倍全体: n=${meta.full?.n?.toLocaleString() || "--"} / ${meta.full?.win_roi_pct || "--"}%。</p>
      ${streakHtml(meta)}${pnlSectionHtml(meta)}`;
    wirePnlChart(body, meta);
  }

  // ─── 連敗状況・累積収支グラフ (コア=推奨のみ) ───

  function streakHtml(meta) {
    const s = meta.streak;
    if (!s) return "";
    const rate = meta.core?.win_rate_pct;
    const asof = s.asof ? s.asof.slice(5).replace("-", "/") : "--";
    const lastWin = s.last_win_date ? s.last_win_date.slice(5).replace("-", "/") : "--";
    return `<h2 class="section-title">連敗状況(コア・検証データ 〜${asof})</h2>
      <div class="streak-card">
        <div class="streak-main">現在 <strong>${s.current}連敗</strong> 中</div>
        <div class="streak-sub">最終勝利 ${lastWin} / 過去最長 ${s.longest}連敗${
          rate ? ` / 勝率${rate}%(約${Math.round(100 / rate)}頭に1頭)` : ""}</div>
        <div class="streak-sub">勝率${rate ?? "--"}%ではこの規模の連敗は想定内。判断はkill-switch基準で。</div>
      </div>`;
  }

  function pnlSectionHtml(meta) {
    const pnl = meta.pnl_by_year;
    if (!pnl) return "";
    const years = Object.keys(pnl).sort();
    if (!state.pnlYear || !years.includes(state.pnlYear)) {
      state.pnlYear = years[years.length - 1];
    }
    const btns = years.map((y) =>
      `<button type="button" class="pnl-year" data-pnl-year="${y}"
        aria-pressed="${y === state.pnlYear}">${y}</button>`).join("");
    return `<h2 class="section-title">累積収支カーブ(コアのみ・1点${BET_YEN}円換算)</h2>
      <div class="pnl-years">${btns}</div>
      <div class="pnl-card">
        <div id="pnl-svg-wrap"></div>
        <div id="pnl-readout" class="streak-sub">グラフをなぞると各時点の収支を表示</div>
      </div>`;
  }

  function wirePnlChart(body, meta) {
    const wrap = body.querySelector("#pnl-svg-wrap");
    if (!wrap) return;
    for (const b of body.querySelectorAll("[data-pnl-year]")) {
      b.addEventListener("click", () => {
        state.pnlYear = b.dataset.pnlYear;
        renderResults();
      });
    }
    const series = (meta.pnl_by_year[state.pnlYear] || []).map((v) => v * BET_YEN / 100);
    if (series.length < 2) { wrap.innerHTML = ""; return; }

    const W = 320, H = 150, padL = 6, padR = 6, padT = 16, padB = 8;
    const lo = Math.min(0, ...series), hi = Math.max(0, ...series);
    const x = (i) => padL + (i / (series.length - 1)) * (W - padL - padR);
    const y = (v) => padT + ((hi - v) / (hi - lo || 1)) * (H - padT - padB);
    const pts = series.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const last = series[series.length - 1];
    const endAnchor = last >= (hi + lo) / 2 ? y(last) + 14 : y(last) - 6;
    wrap.innerHTML = `
      <svg id="pnl-svg" viewBox="0 0 ${W} ${H}" role="img"
           aria-label="${state.pnlYear}年のコア累積収支カーブ">
        <line x1="${padL}" y1="${y(0)}" x2="${W - padR}" y2="${y(0)}"
              stroke="var(--line)" stroke-width="1"/>
        <text x="${padL}" y="${padT - 5}" class="pnl-text">${fmtYen(hi)}</text>
        <text x="${padL}" y="${H - 1}" class="pnl-text">${lo < 0 ? fmtYen(lo) : ""}</text>
        <polyline points="${pts}" fill="none" stroke="var(--accent)"
                  stroke-width="2" stroke-linejoin="round"/>
        <text x="${x(series.length - 1)}" y="${endAnchor}" text-anchor="end"
              class="pnl-text pnl-end">${fmtYen(last)}</text>
        <circle id="pnl-dot" r="4" fill="var(--accent)" stroke="var(--card)"
                stroke-width="2" visibility="hidden"/>
      </svg>`;

    // なぞり読み取り (ホバー非依存: タッチ/マウス両対応)
    const svg = wrap.querySelector("#pnl-svg");
    const dot = wrap.querySelector("#pnl-dot");
    const readout = body.querySelector("#pnl-readout");
    const show = (ev) => {
      const rect = svg.getBoundingClientRect();
      const px = ((ev.clientX - rect.left) / rect.width) * W;
      const i = Math.max(0, Math.min(series.length - 1,
        Math.round(((px - padL) / (W - padL - padR)) * (series.length - 1))));
      dot.setAttribute("cx", x(i));
      dot.setAttribute("cy", y(series[i]));
      dot.setAttribute("visibility", "visible");
      readout.textContent = `${i + 1}頭目: ${fmtYen(series[i])}(${state.pnlYear}年)`;
    };
    svg.addEventListener("pointerdown", show);
    svg.addEventListener("pointermove", (ev) => {
      if (ev.pressure > 0 || ev.pointerType === "mouse") show(ev);
    });
  }

  function fmtYen(v) {
    const n = Math.round(v);
    return (n >= 0 ? "+" : "−") + Math.abs(n).toLocaleString() + "円";
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
