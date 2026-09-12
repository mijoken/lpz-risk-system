(() => {
  "use strict";

  const SYSTEM_STATUS_URL = "./data/system_status.json";
  const RAIN_MANIFEST_URL = "./data/rain/latest.json";
  const SUPPORTED_MAJOR = 1;
  let rainState = null;
  let rainTimer = null;

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
      riskToggle.disabled = locked || true; // reserved until a released risk renderer exists
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
    const rainOn = Boolean(rainToggle?.checked && rainState?.frames?.length);
    setText(
      "map-legend-text",
      rainOn
        ? "実況降水（表示用加工） + JMA一次細分区域 · LPZ Risk locked"
        : "JMA一次細分区域 · LPZ Risk locked"
    );
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
  }

  async function start() {
    const svg = document.getElementById("japan-map");
    const tooltip = document.getElementById("map-tooltip");
    setText("map-state", "Loading public data …");

    try {
      const systemStatus = await fetchJson(SYSTEM_STATUS_URL);
      assertProduct(systemStatus, "LPZ_PUBLIC_SYSTEM_STATUS");

      const data = systemStatus.public_data || {};
      const [sourceHealth, latest, geojson, rainManifest] = await Promise.all([
        fetchJson(publicUrl(data.source_health_path)),
        fetchJson(publicUrl(data.latest_path)),
        fetchJson(publicUrl(data.geography_path)),
        fetchOptionalJson(RAIN_MANIFEST_URL),
      ]);

      assertProduct(sourceHealth, "LPZ_PUBLIC_SOURCE_HEALTH");
      assertProduct(latest, "LPZ_PUBLIC_LATEST");
      assertLockedRiskInvariant(systemStatus, latest);
      assertRegionJoin(latest, geojson);

      if (!window.LPZMap || typeof window.LPZMap.render !== "function") {
        throw new Error("LPZ map renderer was not loaded.");
      }

      const rendered = window.LPZMap.render(svg, geojson, { tooltip });
      const expected = Number(latest.map?.region_count);
      if (Number.isInteger(expected) && rendered !== expected) {
        throw new Error(`Rendered region count mismatch: rendered=${rendered}, latest=${expected}`);
      }

      bindMapControls();
      renderStatus(systemStatus, sourceHealth);
      setupRain(rainManifest);
      applyStatusValue("public-geometry-status", "ONLINE", "ok");
      setText("geometry-count", String(rendered));
      setText("map-state", `${rendered} regions · interactive public map`);
      setText("geometry-schema", geojson.schema_version || "—");
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
