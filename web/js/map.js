(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const VIEW = {
    width: 1200,
    height: 760,
    padding: 28,
    minLon: 122.0,
    maxLon: 154.5,
    minLat: 20.0,
    maxLat: 46.5,
  };

  const toRad = (deg) => (deg * Math.PI) / 180;
  const mercatorY = (lat) => Math.log(Math.tan(Math.PI / 4 + toRad(lat) / 2));
  const mercMin = mercatorY(VIEW.minLat);
  const mercMax = mercatorY(VIEW.maxLat);

  function project(coord) {
    const lon = Number(coord[0]);
    const lat = Number(coord[1]);
    const usableW = VIEW.width - VIEW.padding * 2;
    const usableH = VIEW.height - VIEW.padding * 2;
    const x = VIEW.padding + ((lon - VIEW.minLon) / (VIEW.maxLon - VIEW.minLon)) * usableW;
    const my = mercatorY(lat);
    const y = VIEW.padding + ((mercMax - my) / (mercMax - mercMin)) * usableH;
    return [x, y];
  }

  function ringPath(ring) {
    if (!Array.isArray(ring) || ring.length < 4) return "";
    const first = project(ring[0]);
    const parts = [`M${first[0].toFixed(2)},${first[1].toFixed(2)}`];
    for (let i = 1; i < ring.length; i += 1) {
      const p = project(ring[i]);
      parts.push(`L${p[0].toFixed(2)},${p[1].toFixed(2)}`);
    }
    parts.push("Z");
    return parts.join("");
  }

  function polygonPath(polygon) {
    if (!Array.isArray(polygon)) return "";
    return polygon.map(ringPath).filter(Boolean).join("");
  }

  function geometryPath(geometry) {
    if (!geometry || typeof geometry !== "object") return "";
    if (geometry.type === "Polygon") {
      return polygonPath(geometry.coordinates);
    }
    if (geometry.type === "MultiPolygon") {
      return (geometry.coordinates || []).map(polygonPath).filter(Boolean).join("");
    }
    if (geometry.type === "GeometryCollection") {
      return (geometry.geometries || []).map(geometryPath).filter(Boolean).join("");
    }
    throw new Error(`Unsupported geometry type: ${geometry.type}`);
  }

  function positionTooltip(tooltip, event) {
    const margin = 14;
    const maxX = window.innerWidth - tooltip.offsetWidth - 18;
    const maxY = window.innerHeight - tooltip.offsetHeight - 18;
    const left = Math.min(event.clientX + margin, Math.max(8, maxX));
    const top = Math.min(event.clientY + margin, Math.max(8, maxY));
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }

  function showTooltip(tooltip, feature, event) {
    if (!tooltip) return;
    const props = feature.properties || {};
    const name = tooltip.querySelector("strong");
    const meta = tooltip.querySelector("span");
    if (name) name.textContent = props.name_ja || "名称未取得";
    if (meta) meta.textContent = `JMA一次細分区域 ${props.region_code || feature.id || "—"}`;
    tooltip.hidden = false;
    positionTooltip(tooltip, event);
  }

  function hideTooltip(tooltip) {
    if (tooltip) tooltip.hidden = true;
  }

  function render(svg, featureCollection, options = {}) {
    if (!svg) throw new Error("Map SVG element is missing.");
    if (!featureCollection || featureCollection.type !== "FeatureCollection") {
      throw new Error("Public geometry is not a GeoJSON FeatureCollection.");
    }

    const features = Array.isArray(featureCollection.features)
      ? featureCollection.features
      : [];
    if (!features.length) throw new Error("Public geometry contains no features.");

    svg.setAttribute("viewBox", `0 0 ${VIEW.width} ${VIEW.height}`);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    svg.replaceChildren();

    const fragment = document.createDocumentFragment();
    const tooltip = options.tooltip || null;

    for (const feature of features) {
      const d = geometryPath(feature.geometry);
      if (!d) continue;

      const path = document.createElementNS(SVG_NS, "path");
      const props = feature.properties || {};
      const code = props.region_code || String(feature.id || "");
      const name = props.name_ja || code || "JMA一次細分区域";

      path.setAttribute("d", d);
      path.setAttribute("class", "region");
      path.setAttribute("fill-rule", "evenodd");
      path.setAttribute("clip-rule", "evenodd");
      path.setAttribute("tabindex", "0");
      path.setAttribute("role", "button");
      path.setAttribute("aria-label", `${name} ${code}`.trim());
      path.dataset.regionCode = code;

      path.addEventListener("pointerenter", (event) => {
        path.classList.add("is-active");
        showTooltip(tooltip, feature, event);
      });
      path.addEventListener("pointermove", (event) => positionTooltip(tooltip, event));
      path.addEventListener("pointerleave", () => {
        path.classList.remove("is-active");
        hideTooltip(tooltip);
      });
      path.addEventListener("focus", () => path.classList.add("is-active"));
      path.addEventListener("blur", () => path.classList.remove("is-active"));

      fragment.appendChild(path);
    }

    svg.appendChild(fragment);
    return svg.querySelectorAll(".region").length;
  }

  window.LPZMap = Object.freeze({ render });
})();
