(() => {
  "use strict";

  const SYSTEM_STATUS_URL = "./data/system_status.json";
  const SUPPORTED_MAJOR = 1;

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`${url} returned HTTP ${response.status}`);
    }
    return response.json();
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
      if (!latestCodes.has(code)) {
        throw new Error(`Region join-key missing from latest.json: ${code}`);
      }
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
    setText("map-legend-text", locked ? "Geography only · Risk output locked" : "Released public risk layer");
  }

  async function start() {
    const svg = document.getElementById("japan-map");
    const tooltip = document.getElementById("map-tooltip");
    setText("map-state", "Loading public data …");

    try {
      // system_status.json is authoritative for which public products may be loaded.
      const systemStatus = await fetchJson(SYSTEM_STATUS_URL);
      assertProduct(systemStatus, "LPZ_PUBLIC_SYSTEM_STATUS");

      const data = systemStatus.public_data || {};
      const [sourceHealth, latest, geojson] = await Promise.all([
        fetchJson(publicUrl(data.source_health_path)),
        fetchJson(publicUrl(data.latest_path)),
        fetchJson(publicUrl(data.geography_path)),
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

      renderStatus(systemStatus, sourceHealth);
      applyStatusValue("public-geometry-status", "ONLINE", "ok");
      setText("geometry-count", String(rendered));
      setText("map-state", `${rendered} regions · JSON-driven public state`);
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
