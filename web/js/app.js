(() => {
  "use strict";

  const GEOJSON_URL = "./assets/japan_primary_subdivisions.geojson";

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

  async function start() {
    const svg = document.getElementById("japan-map");
    const tooltip = document.getElementById("map-tooltip");
    setText("map-state", "Loading public geometry …");

    try {
      const geojson = await fetchJson(GEOJSON_URL);
      if (!window.LPZMap || typeof window.LPZMap.render !== "function") {
        throw new Error("LPZ map renderer was not loaded.");
      }

      const rendered = window.LPZMap.render(svg, geojson, { tooltip });
      setText("geometry-count", String(rendered));
      setText("map-state", `${rendered} regions · display-only geometry`);
      setText("geometry-schema", geojson.schema_version || "—");
    } catch (error) {
      console.error(error);
      setText("map-state", "MAP LOAD FAILED");
      showError(`日本地図を読み込めませんでした: ${error.message}`);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
