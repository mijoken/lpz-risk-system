(() => {
  "use strict";

  const SYSTEM_STATUS_URL = "./data/system_status.json";
  const RAIN_MANIFEST_URL = "./data/rain/latest.json";
  const MAP_MANIFEST_URL = "./assets/map/manifest.json";
  const F4_RESEARCH_URL = "./data/research/f4_archived_identity_summary.json";
  const F4_LIVE_RESEARCH_URL = "./data/research/f4_live_geographic_research.geojson";
  const REFERENCE_CITIES_URL = "./data/reference_cities.json";
  const SUPPORTED_MAJOR = 1;

  let rainState = null;
  let rainTimer = null;
  let mapManifest = null;
  let referenceCities = [];
  let regionSearchFeatures = [];
  let latestProduct = null;
  let f4LiveResearch = null;
  let activeLodId = null;
  let lodRequestToken = 0;
  const lodCache = new Map();

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
    return response.json();
  }

  async function fetchOptionalJson(url) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (response.status === 404) return null;
      if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
      return response.json();
    } catch (error) {
      console.warn("Optional public product unavailable", url, error);
      return null;
    }
  }

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  function showError(message) {
    const box = document.getElementById("map-error");
    if (!box) return;
    box.hidden = false;
    box.textContent = message;
  }

  function assertProduct(obj, product) {
    if (!obj || typeof obj !== "object" || obj.product !== product) {
      throw new Error(`Unexpected public product; expected ${product}.`);
    }
    const version = String(obj.schema_version || "");
    const major = Number(version.split(".")[0]);
    if (!Number.isInteger(major) || major !== SUPPORTED_MAJOR) {
      throw new Error(`Unsupported ${product} schema version: ${version || "missing"}`);
    }
  }

  function publicUrl(path) {
    const value = String(path || "");
    if (!value || value.includes("://") || value.includes("..") || value.startsWith("/")) {
      throw new Error(`Unsafe public data path: ${value || "missing"}`);
    }
    return `./${value}`;
  }

  function assertLockedRiskInvariant(systemStatus, latest) {
    const systemAllowed = systemStatus.scientific_release?.risk_engine_allowed === true;
    const latestAllowed = latest.release?.risk_engine_allowed === true;
    if (systemAllowed !== latestAllowed) {
      throw new Error("Risk release state mismatch between system_status.json and latest.json.");
    }
    if (!systemAllowed) {
      for (const region of latest.regions || []) {
        if (region.risk !== null) {
          throw new Error(`Locked public data contains non-null risk: ${region.region_code}`);
        }
        if (region.display_state === "RISK_AVAILABLE") {
          throw new Error(`Locked public data contains RISK_AVAILABLE: ${region.region_code}`);
        }
      }
    }
  }

  function assertRegionJoin(latest, geojson) {
    const latestCodes = new Set((latest.regions || []).map((row) => String(row.region_code || "")));
    const geometryCodes = new Set(
      (geojson.features || []).map((feature) =>
        String(feature?.properties?.region_code || feature?.id || "")
      )
    );
    if (latestCodes.size !== geometryCodes.size) {
      throw new Error(`Region count mismatch: latest=${latestCodes.size}, geometry=${geometryCodes.size}`);
    }
    for (const code of geometryCodes) {
      if (!latestCodes.has(code)) throw new Error(`Region join-key missing from latest.json: ${code}`);
    }
  }

  function applyStatusValue(id, text, tone) {
    const node = document.getElementById(id);
    if (!node) return;
    node.textContent = text;
    node.classList.remove("value-ok", "value-wait", "value-locked");
    if (tone === "ok") node.classList.add("value-ok");
    else if (tone === "locked") node.classList.add("value-locked");
    else node.classList.add("value-wait");
  }

  function formatJst(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value || "—";
    return new Intl.DateTimeFormat("ja-JP", {
      timeZone: "Asia/Tokyo",
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date) + " JST";
  }

  function ageMinutes(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    return Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
  }

  function haversineKm(lon1, lat1, lon2, lat2) {
    const rad = Math.PI / 180;
    const p1 = Number(lat1) * rad;
    const p2 = Number(lat2) * rad;
    const dLat = (Number(lat2) - Number(lat1)) * rad;
    const dLon = (Number(lon2) - Number(lon1)) * rad;
    const a = Math.sin(dLat / 2) ** 2
      + Math.cos(p1) * Math.cos(p2) * Math.sin(dLon / 2) ** 2;
    return 6371.0088 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(Math.max(0, 1 - a)));
  }

  function bearingDegrees(lon1, lat1, lon2, lat2) {
    const rad = Math.PI / 180;
    const y = Math.sin((Number(lon2) - Number(lon1)) * rad) * Math.cos(Number(lat2) * rad);
    const x = Math.cos(Number(lat1) * rad) * Math.sin(Number(lat2) * rad)
      - Math.sin(Number(lat1) * rad) * Math.cos(Number(lat2) * rad)
        * Math.cos((Number(lon2) - Number(lon1)) * rad);
    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
  }

  function directionJa(degrees) {
    const dirs = ["北", "北東", "東", "南東", "南", "南西", "西", "北西"];
    return dirs[Math.round(Number(degrees) / 45) % 8];
  }

  function nearestReferenceCity(lon, lat) {
    let best = null;
    for (const city of referenceCities) {
      const cityLon = Number(city.lon);
      const cityLat = Number(city.lat);
      if (!Number.isFinite(cityLon) || !Number.isFinite(cityLat)) continue;
      const distanceKm = haversineKm(cityLon, cityLat, lon, lat);
      if (!best || distanceKm < best.distanceKm) {
        best = {
          city,
          distanceKm,
          bearing: bearingDegrees(cityLon, cityLat, lon, lat),
        };
      }
    }
    return best;
  }

  function assertF4LiveResearch(doc) {
    assertProduct(doc, "LPZ_F4_LIVE_RESEARCH_ENVELOPES");
    if (doc.research_only !== true
        || doc.validated_forecast !== false
        || doc.risk_engine_allowed !== false
        || doc.official_risk_output !== false
        || doc.lpz_forecast_generated !== false
        || doc.probability_generated !== false
        || doc.severity_generated !== false
        || doc.coverage !== "SELECTED_FIXED_MOSAIC_NOT_NATIONWIDE") {
      throw new Error("F4 live research lock or coverage contract mismatch.");
    }
    const features = Array.isArray(doc.features) ? doc.features : [];
    if (Number(doc.feature_count) !== features.length) {
      throw new Error("F4 live feature count mismatch.");
    }
    for (const feature of features) {
      const props = feature?.properties || {};
      const lead = Number(props.lead_from_as_of_minutes);
      if (feature?.geometry?.type !== "Polygon"
          || props.kind !== "PROJECTED_RESEARCH_GEOGRAPHIC_ENVELOPE"
          || (lead !== 15 && lead !== 30)
          || props.research_only !== true
          || props.risk_engine_allowed !== false
          || props.lpz_forecast_generated !== false
          || props.probability !== null
          || props.severity !== null
          || props.intensity !== null
          || props.exact_precipitation_contour !== false) {
        throw new Error("F4 live feature violates research-only contract.");
      }
    }
  }

  function resetF4LiveSelection() {
    setText("f4-live-area", "候補域を地図で選択");
    setText("f4-live-center", "—");
    setText("f4-live-scale", "—");
    setText("f4-live-target", "—");
    setText("f4-live-lead", "—");
    setText("f4-live-object", "—");
  }

  function renderF4LiveSelection(feature) {
    const props = feature?.properties || {};
    const centroid = props.projected_centroid_lon_lat;
    const lon = Number(Array.isArray(centroid) ? centroid[0] : NaN);
    const lat = Number(Array.isArray(centroid) ? centroid[1] : NaN);

    let areaText = "位置参照なし";
    if (Number.isFinite(lon) && Number.isFinite(lat)) {
      const nearest = nearestReferenceCity(lon, lat);
      if (nearest) {
        const city = nearest.city;
        const base = `${city.prefecture_ja || ""} ${city.name_ja || ""}`.trim();
        areaText = nearest.distanceKm < 12
          ? `${base}付近`
          : `${base}の${directionJa(nearest.bearing)} 約${Math.round(nearest.distanceKm)}km`;
      } else {
        areaText = "参照都市なし";
      }
      setText("f4-live-center", `${lat.toFixed(3)}°N, ${lon.toFixed(3)}°E`);
    } else {
      setText("f4-live-center", "—");
    }

    const areaKm2 = Number(props.observed_approx_area_km2);
    setText("f4-live-area", areaText);
    setText("f4-live-scale", Number.isFinite(areaKm2) ? `${areaKm2.toFixed(1)} km²` : "—");
    setText("f4-live-target", formatJst(props.target_valid_time_utc));
    setText(
      "f4-live-lead",
      Number.isFinite(Number(props.lead_from_as_of_minutes))
        ? `${Number(props.lead_from_as_of_minutes)}分先（as-of基準）`
        : "—"
    );
    setText("f4-live-object", String(props.research_object_id || "—"));
  }

  function setupF4LiveResearch(doc) {
    const toggle = document.getElementById("f4-live-layer-toggle");
    const disable = (status, summary) => {
      f4LiveResearch = null;
      window.LPZMap.setResearchEnvelopes(null);
      window.LPZMap.setResearchVisible(false);
      if (toggle) {
        toggle.checked = false;
        toggle.disabled = true;
      }
      applyStatusValue("f4-live-status", status, "wait");
      setText("f4-live-summary", summary);
      resetF4LiveSelection();
      updateMapLegend();
    };

    if (!doc) {
      disable("NOT PUBLISHED", "最新のF4-4研究候補域は公開されていません。");
      return;
    }

    try {
      assertF4LiveResearch(doc);
    } catch (error) {
      console.warn("F4 live research contract error", error);
      disable("CONTRACT ERROR", "F4-4研究候補域の公開契約に不一致があるため表示を停止しました。");
      return;
    }

    if (doc.status !== "AVAILABLE" || !doc.features.length) {
      const label = doc.status === "STALE_SUPPRESSED" ? "STALE SUPPRESSED" : doc.status || "UNAVAILABLE";
      const summary = doc.status === "STALE_SUPPRESSED"
        ? "候補域が古いため自動的に非表示にしました。"
        : "現在の最新研究slotには表示可能な短時間候補域がありません。";
      disable(label, summary);
      return;
    }

    f4LiveResearch = doc;
    const rendered = window.LPZMap.setResearchEnvelopes(doc);
    window.LPZMap.setResearchVisible(true);
    if (rendered !== doc.feature_count) {
      disable("RENDER ERROR", "F4-4候補域の描画件数が公開データと一致しません。");
      return;
    }

    if (toggle) {
      toggle.disabled = false;
      toggle.checked = true;
    }
    applyStatusValue("f4-live-status", "RESEARCH ONLY", "wait");
    setText(
      "f4-live-summary",
      `${doc.projected_object_count}対象 · ${doc.feature_count}候補域 · as-of ${formatJst(doc.source_as_of_utc)} · 固定モザイク範囲のみ`
    );
    resetF4LiveSelection();
    updateMapLegend();
  }

  function renderStatus(systemStatus, sourceHealth) {
    const release = systemStatus.scientific_release || {};
    const pipeline = systemStatus.pipeline || {};
    const locked = release.risk_engine_allowed !== true;

    applyStatusValue(
      "live-source-status",
      sourceHealth.overall_status,
      sourceHealth.overall_status === "PASS" ? "ok" : "wait"
    );
    applyStatusValue(
      "prediction-status",
      release.state === "RELEASED" ? "RELEASED" : "VALIDATION PENDING",
      release.state === "RELEASED" ? "ok" : "wait"
    );
    applyStatusValue("risk-status", locked ? "LOCKED" : "ACTIVE", locked ? "locked" : "ok");

    const imerg = (sourceHealth.sources || []).find(
      (source) => source.source_id === "nasa_earthdata_imerg"
    );
    const imergProbe = String(imerg?.probe_status || "UNKNOWN");
    if (imergProbe === "AVAILABLE_ACTION_REQUIRED") {
      applyStatusValue("imerg-status", "AVAILABLE", "ok");
    } else if (imergProbe === "EXPECTED_PENDING") {
      applyStatusValue("imerg-status", "WAITING", "wait");
    } else {
      applyStatusValue("imerg-status", imergProbe, "wait");
    }

    setText("pipeline-status", pipeline.state || "UNKNOWN");
    setText("public-data-time", systemStatus.generated_at_utc || "—");
    setText(
      "scientific-state-text",
      `2025 confirmatory validation: ${release.validation_status || "UNKNOWN"}. ` +
        `${release.reason || "The public scientific release state is locked."}`
    );
    setText("release-badge", locked ? "PUBLIC PREVIEW · RISK LOCKED" : "PUBLIC RELEASE");

    const riskToggle = document.getElementById("risk-layer-toggle");
    if (riskToggle) {
      riskToggle.checked = false;
      riskToggle.disabled = true;
    }
  }

  function renderF4ArchivedResearch(report) {
    const badge = document.getElementById("f4-research-state");
    const stats = document.getElementById("f4-research-stats");
    const horizons = document.getElementById("f4-research-horizons");
    const breakdown = document.getElementById("f4-research-breakdown");
    const footnote = document.getElementById("f4-research-footnote");
    if (!badge || !stats || !horizons || !breakdown || !footnote) return;
    const c = report?.counts;
    const category = report?.no_continuous_match_association_categories;
    const h = report?.horizons_from_as_of_minutes;
    if (report?.product !== "LPZ_F4_ARCHIVED_RESEARCH_PUBLIC_SUMMARY"
        || report?.schema_version !== "1.0.0"
        || report?.risk_engine_allowed !== false
        || report?.lpz_forecast_generated !== false
        || report?.archived_research_only !== true
        || report?.source_run_id !== "35564667965"
        || report?.target_run_id !== "35565907043"
        || !c || !category || !h) {
      badge.textContent = "CONTRACT ERROR";
      footnote.textContent = "F4研究データの契約に不一致があります。数値を表示しません。";
      return;
    }
    const number = (value) => Number.isInteger(value) && value >= 0 ? String(value) : "—";
    const statRows = [
      ["F3研究対象", c.source_research_objects],
      ["短時間移動の予測対象", c.projected_objects],
      ["比較可能な予測", c.comparable_projections],
      ["継続追跡成立", c.identity_matched_projections],
      ["追跡不成立", c.identity_unresolved_projections],
      ["同時刻の比較先なし", c.no_exact_comparable_target],
    ];
    stats.replaceChildren();
    for (const [label, value] of statRows) {
      const node = document.createElement("div");
      node.className = "research-stat";
      const name = document.createElement("span");
      name.textContent = label;
      const metric = document.createElement("strong");
      metric.textContent = number(value);
      node.append(name, metric);
      stats.append(node);
    }
    horizons.replaceChildren();
    for (const lead of ["15", "30"]) {
      const row = h[lead];
      if (!row || !Number.isInteger(row.identity_matched_count)) continue;
      const node = document.createElement("div");
      node.className = "research-horizon";
      const title = document.createElement("h3");
      title.textContent = lead + "分先 · 観測降雨域中心の位置誤差";
      const matched = document.createElement("span");
      matched.textContent = "継続追跡成立 " + number(row.identity_matched_count) + " 件";
      const distance = document.createElement("strong");
      distance.textContent = Number.isFinite(row.motion_median_km)
        ? row.motion_median_km.toFixed(2) + " km" : "—";
      const compare = document.createElement("span");
      compare.textContent = "移動なしの誤差中央値: "
        + (Number.isFinite(row.persistence_median_km)
          ? row.persistence_median_km.toFixed(2) + " km" : "—");
      node.append(title, matched, distance, compare);
      horizons.append(node);
    }
    breakdown.replaceChildren();
    const title = document.createElement("h3");
    title.textContent = "追跡不成立の最初の5分間 · 観測形状の診断";
    const list = document.createElement("ul");
    const categories = [
      ["重なり候補なし", category.NO_RECORDED_OVERLAP_CANDIDATE],
      ["合流候補あり", category.MERGE_CANDIDATE],
      ["分裂・合流両候補あり", category.SPLIT_AND_MERGE_CANDIDATES],
      ["分裂候補あり", category.SPLIT_CANDIDATE],
    ];
    for (const [label, value] of categories) {
      if (!value) continue;
      const item = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = label;
      const count = document.createElement("strong");
      count.textContent = number(value) + " 件";
      item.append(name, count);
      list.append(item);
    }
    breakdown.append(title, list);
    badge.textContent = "ARCHIVED · RESEARCH ONLY";
    footnote.textContent = "取得済みArtifact " + report.source_run_id + " / "
      + report.target_run_id + " の遡及評価。"
      + " 30 mm/hの観測降雨域に関するアルゴリズム上の追跡であり、"
      + "線状降水帯発生予測・確率・危険度・公式発表ではありません。"
      + " 対応候補なしは降雨域の消滅を意味しません。位置誤差は継続追跡が成立した少数例のみです。";
  }

  async function setupF4ArchivedResearch() {
    try {
      const report = await fetchOptionalJson(F4_RESEARCH_URL);
      if (!report) {
        setText("f4-research-state", "NOT PUBLISHED");
        setText("f4-research-footnote", "検証済みF4研究要約が未公開です。現在の降雨・予報データから研究値を補いません。");
        return;
      }
      renderF4ArchivedResearch(report);
    } catch (error) {
      console.warn("Archived F4 research unavailable", error);
      setText("f4-research-state", "UNAVAILABLE");
      setText("f4-research-footnote", "研究成果を読み込めませんでした。実況降水・リスク表示には影響しません。");
    }
  }

  function stopRainPlayback() {
    if (rainTimer !== null) {
      window.clearInterval(rainTimer);
      rainTimer = null;
    }
    const button = document.getElementById("rain-play");
    if (button) button.textContent = "▶ 再生";
  }

  function renderRainLegend(manifest) {
    const root = document.getElementById("rain-legend");
    if (!root) return;
    root.replaceChildren();
    for (const entry of manifest.legend || []) {
      const item = document.createElement("span");
      item.className = "rain-legend-item";
      const swatch = document.createElement("i");
      const rgb = Array.isArray(entry.rgb) ? entry.rgb : [255, 255, 255];
      swatch.style.background = `rgb(${rgb.join(",")})`;
      const label = document.createElement("span");
      label.textContent = entry.label || "";
      item.append(swatch, label);
      root.appendChild(item);
    }
  }

  function updateMapLegend() {
    const rainToggle = document.getElementById("rain-layer-toggle");
    const researchToggle = document.getElementById("f4-live-layer-toggle");
    const rainOn = Boolean(rainToggle?.checked && rainState?.frames?.length);
    const researchOn = Boolean(researchToggle?.checked && f4LiveResearch?.features?.length);
    const lod = activeLodId ? ` · ${activeLodId} detail` : "";
    const layers = [];
    if (rainOn) layers.push("実況降水（表示用加工）");
    if (researchOn) layers.push("F4短時間研究候補域（未検証）");
    layers.push(`JMA一次細分区域${lod}`);
    setText("map-legend-text", `${layers.join(" + ")} · LPZ Risk locked`);
  }

  function setRainFrame(index) {
    if (!rainState || !Array.isArray(rainState.frames) || !rainState.frames.length) return;
    const safe = Math.max(0, Math.min(rainState.frames.length - 1, Number(index) || 0));
    const frame = rainState.frames[safe];
    rainState.currentIndex = safe;
    window.LPZMap.setRainFrame(publicUrl(frame.image_path));

    const toggle = document.getElementById("rain-layer-toggle");
    window.LPZMap.setRainVisible(toggle ? toggle.checked : true);
    const slider = document.getElementById("rain-frame-slider");
    if (slider) slider.value = String(safe);

    const age = ageMinutes(frame.valid_time_utc);
    setText(
      "rain-time",
      `${formatJst(frame.valid_time_utc)}${age === null ? "" : ` · 約${age}分前`}`
    );
    updateMapLegend();
  }

  function startRainPlayback() {
    if (!rainState?.frames?.length || rainState.frames.length < 2) return;
    stopRainPlayback();
    const button = document.getElementById("rain-play");
    if (button) button.textContent = "■ 停止";
    rainTimer = window.setInterval(() => {
      const next = (rainState.currentIndex + 1) % rainState.frames.length;
      setRainFrame(next);
    }, 900);
  }

  function setupRain(manifest) {
    const toggle = document.getElementById("rain-layer-toggle");
    const slider = document.getElementById("rain-frame-slider");
    const play = document.getElementById("rain-play");

    if (!manifest || manifest.product !== "LPZ_PUBLIC_RAIN_OVERLAY" || !manifest.frames?.length) {
      rainState = null;
      if (toggle) {
        toggle.checked = false;
        toggle.disabled = true;
      }
      if (slider) slider.disabled = true;
      if (play) play.disabled = true;
      applyStatusValue("rain-layer-status", manifest?.status || "UNAVAILABLE", "wait");
      setText("rain-time", "実況降水データなし");
      window.LPZMap.setRainFrame(null);
      updateMapLegend();
      return;
    }

    assertProduct(manifest, "LPZ_PUBLIC_RAIN_OVERLAY");
    rainState = {
      ...manifest,
      currentIndex: Number.isInteger(manifest.latest_index)
        ? manifest.latest_index
        : manifest.frames.length - 1,
    };
    renderRainLegend(manifest);
    applyStatusValue(
      "rain-layer-status",
      manifest.status,
      manifest.status === "AVAILABLE" ? "ok" : "wait"
    );

    if (toggle) {
      toggle.disabled = false;
      toggle.checked = true;
      toggle.addEventListener("change", () => {
        window.LPZMap.setRainVisible(toggle.checked);
        updateMapLegend();
      });
    }
    if (slider) {
      slider.disabled = false;
      slider.min = "0";
      slider.max = String(manifest.frames.length - 1);
      slider.step = "1";
      slider.addEventListener("input", () => {
        stopRainPlayback();
        setRainFrame(Number(slider.value));
      });
    }
    if (play) {
      play.disabled = manifest.frames.length < 2;
      play.addEventListener("click", () => {
        if (rainTimer === null) startRainPlayback();
        else stopRainPlayback();
      });
    }
    setRainFrame(rainState.currentIndex);
  }

  function featureDisplayName(feature) {
    const props = feature?.properties || {};
    return props.display_name_ja || props.name_ja || props.region_code || feature?.id || "—";
  }

  function renderRegionSelection(feature) {
    const props = feature?.properties || {};
    const code = props.region_code || feature?.id || "—";
    setText("selected-location-name", featureDisplayName(feature));
    setText(
      "selected-location-meta",
      `JMA一次細分区域 ${code}${props.name_ja ? ` · JMA名称「${props.name_ja}」` : ""}`
    );
  }

  function renderCitySelection(city) {
    setText("selected-location-name", `${city.prefecture_ja || ""} ${city.name_ja || ""}`.trim());
    setText("selected-location-meta", "地図参照用の主要都市アンカー · 科学計算には使用しません");
  }

  function normalizeSearch(value) {
    return String(value || "").trim().toLocaleLowerCase("ja-JP").replace(/\s+/g, "");
  }

  function setupSearch() {
    const form = document.getElementById("map-search-form");
    const input = document.getElementById("map-search-input");
    const feedback = document.getElementById("map-search-feedback");
    if (!form || !input) return;

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const q = normalizeSearch(input.value);
      if (!q) return;

      const city = referenceCities.find((row) => {
        const values = [row.name_ja, row.prefecture_ja, `${row.prefecture_ja || ""}${row.name_ja || ""}`];
        return values.some((value) => normalizeSearch(value).includes(q));
      });
      if (city) {
        window.LPZMap.focusLonLat(Number(city.lon), Number(city.lat), 5.2);
        renderCitySelection(city);
        if (feedback) feedback.textContent = `${city.prefecture_ja || ""} ${city.name_ja}へ移動しました。`;
        return;
      }

      const feature = regionSearchFeatures.find((row) => {
        const props = row?.properties || {};
        const values = [
          props.display_name_ja,
          props.name_ja,
          props.parent_name_ja,
          props.region_code,
          `${props.parent_name_ja || ""}${props.name_ja || ""}`,
        ];
        return values.some((value) => normalizeSearch(value).includes(q));
      });
      if (feature && window.LPZMap.focusFeature(feature, 4.7)) {
        renderRegionSelection(feature);
        if (feedback) feedback.textContent = `${featureDisplayName(feature)}へ移動しました。`;
        return;
      }

      if (feedback) feedback.textContent = `「${input.value.trim()}」は現在の地図参照データでは見つかりませんでした。`;
    });
  }

  function desiredLod(scale) {
    const rows = Array.isArray(mapManifest?.lods) ? mapManifest.lods : [];
    if (!rows.length) return null;
    const s = Number(scale) || 1;
    return rows.find((row) => {
      const min = Number(row.min_scale ?? 1);
      const max = row.max_scale === null || row.max_scale === undefined ? Infinity : Number(row.max_scale);
      return s >= min && s < max;
    }) || rows[rows.length - 1];
  }

  async function switchLodForScale(scale) {
    const target = desiredLod(scale);
    if (!target || target.id === activeLodId) return;
    const token = ++lodRequestToken;
    let geo = lodCache.get(target.id);
    if (!geo) {
      geo = await fetchJson(publicUrl(target.path));
      if (token !== lodRequestToken) return;
      if (latestProduct) assertRegionJoin(latestProduct, geo);
      lodCache.set(target.id, geo);
    }
    if (token !== lodRequestToken) return;

    const count = window.LPZMap.replaceGeometry(geo);
    if (count !== 142) throw new Error(`LOD ${target.id} rendered ${count} regions, expected 142.`);
    activeLodId = target.id;
    regionSearchFeatures = Array.isArray(geo.features) ? geo.features : regionSearchFeatures;
    setText("geometry-schema", `${geo.schema_version || "—"} · ${target.id}`);
    setText("map-state", `${count} regions · ${target.id} detail · interactive public map`);
    updateMapLegend();
  }

  function setupReferenceCities(doc) {
    if (!doc || doc.product !== "LPZ_PUBLIC_REFERENCE_CITIES" || !Array.isArray(doc.cities)) {
      referenceCities = [];
      const toggle = document.getElementById("city-layer-toggle");
      if (toggle) {
        toggle.checked = false;
        toggle.disabled = true;
      }
      return;
    }
    referenceCities = doc.cities;
    window.LPZMap.renderCities(referenceCities);
  }

  function bindMapControls() {
    document.getElementById("map-reset")?.addEventListener("click", () => window.LPZMap.resetView());
    document.getElementById("map-zoom-in")?.addEventListener("click", () => window.LPZMap.zoomIn());
    document.getElementById("map-zoom-out")?.addEventListener("click", () => window.LPZMap.zoomOut());

    const boundaryToggle = document.getElementById("boundary-layer-toggle");
    if (boundaryToggle) {
      boundaryToggle.checked = true;
      boundaryToggle.addEventListener("change", () => {
        window.LPZMap.setBoundariesVisible(boundaryToggle.checked);
      });
    }

    const cityToggle = document.getElementById("city-layer-toggle");
    if (cityToggle) {
      cityToggle.checked = true;
      cityToggle.addEventListener("change", () => {
        window.LPZMap.setCityLabelsVisible(cityToggle.checked);
      });
    }

    const researchToggle = document.getElementById("f4-live-layer-toggle");
    if (researchToggle) {
      researchToggle.addEventListener("change", () => {
        window.LPZMap.setResearchVisible(researchToggle.checked);
        updateMapLegend();
      });
    }
  }

  async function start() {
    setupF4ArchivedResearch();
    const svg = document.getElementById("japan-map");
    const tooltip = document.getElementById("map-tooltip");
    setText("map-state", "Loading public data …");

    try {
      const systemStatus = await fetchJson(SYSTEM_STATUS_URL);
      assertProduct(systemStatus, "LPZ_PUBLIC_SYSTEM_STATUS");

      const data = systemStatus.public_data || {};
      const [sourceHealth, latest, geojson, rainManifest, optionalMapManifest, citiesDoc, f4LiveDoc] = await Promise.all([
        fetchJson(publicUrl(data.source_health_path)),
        fetchJson(publicUrl(data.latest_path)),
        fetchJson(publicUrl(data.geography_path)),
        fetchOptionalJson(RAIN_MANIFEST_URL),
        fetchOptionalJson(MAP_MANIFEST_URL),
        fetchOptionalJson(REFERENCE_CITIES_URL),
        fetchOptionalJson(F4_LIVE_RESEARCH_URL),
      ]);

      assertProduct(sourceHealth, "LPZ_PUBLIC_SOURCE_HEALTH");
      assertProduct(latest, "LPZ_PUBLIC_LATEST");
      assertLockedRiskInvariant(systemStatus, latest);
      assertRegionJoin(latest, geojson);
      latestProduct = latest;

      if (!window.LPZMap || typeof window.LPZMap.render !== "function") {
        throw new Error("LPZ map renderer was not loaded.");
      }

      const rendered = window.LPZMap.render(svg, geojson, {
        tooltip,
        onSelect: renderRegionSelection,
        onResearchSelect: renderF4LiveSelection,
      });
      const expected = Number(latest.map?.region_count);
      if (Number.isInteger(expected) && rendered !== expected) {
        throw new Error(`Rendered region count mismatch: rendered=${rendered}, latest=${expected}`);
      }

      mapManifest = optionalMapManifest?.product === "LPZ_PUBLIC_MAP_GEOMETRY_MANIFEST"
        ? optionalMapManifest
        : null;
      activeLodId = geojson.lod || mapManifest?.default_lod || null;
      regionSearchFeatures = Array.isArray(geojson.features) ? geojson.features : [];
      if (activeLodId) lodCache.set(activeLodId, geojson);

      bindMapControls();
      setupReferenceCities(citiesDoc);
      setupF4LiveResearch(f4LiveDoc);
      setupSearch();
      renderStatus(systemStatus, sourceHealth);
      setupRain(rainManifest);
      applyStatusValue("public-geometry-status", "ONLINE", "ok");
      setText("geometry-count", String(rendered));
      setText("map-state", `${rendered} regions · ${activeLodId || "single"} detail · interactive public map`);
      setText("geometry-schema", `${geojson.schema_version || "—"}${activeLodId ? ` · ${activeLodId}` : ""}`);

      window.LPZMap.setViewChangeHandler(({ scale }) => {
        switchLodForScale(scale).catch((error) => {
          console.warn("LOD switch failed; keeping current geometry", error);
          setText("map-search-feedback", "詳細地図の切替に失敗したため、現在の地図精度を維持しています。");
        });
      });
      updateMapLegend();
    } catch (error) {
      console.error(error);
      applyStatusValue("public-geometry-status", "FAILED", "locked");
      setText("map-state", "PUBLIC DATA LOAD FAILED");
      showError(`公開データを読み込めませんでした: ${error.message}`);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
