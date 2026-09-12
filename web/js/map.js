(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const VIEW = Object.freeze({
    width: 1200,
    height: 760,
    padding: 28,
    minLon: 122.0,
    maxLon: 154.5,
    minLat: 20.0,
    maxLat: 46.5,
  });
  const MIN_SCALE = 1;
  const MAX_SCALE = 10;

  const state = {
    svg: null,
    viewport: null,
    rainImage: null,
    boundaryGroup: null,
    cityLayer: null,
    tooltip: null,
    onSelect: null,
    viewChangeHandler: null,
    cityLabelsVisible: true,
    cities: [],
    scale: 1,
    tx: 0,
    ty: 0,
    pointers: new Map(),
    dragLast: null,
    pinchStart: null,
    interactionsBound: false,
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
    if (geometry.type === "Polygon") return polygonPath(geometry.coordinates);
    if (geometry.type === "MultiPolygon") {
      return (geometry.coordinates || []).map(polygonPath).filter(Boolean).join("");
    }
    if (geometry.type === "GeometryCollection") {
      return (geometry.geometries || []).map(geometryPath).filter(Boolean).join("");
    }
    throw new Error(`Unsupported geometry type: ${geometry.type}`);
  }

  function featureDisplayName(feature) {
    const props = feature?.properties || {};
    return props.display_name_ja || props.name_ja || props.region_code || feature?.id || "名称未取得";
  }

  function positionTooltip(tooltip, event) {
    if (!tooltip || !event) return;
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
    if (name) name.textContent = featureDisplayName(feature);
    if (meta) {
      const raw = props.name_ja && props.display_name_ja && props.name_ja !== props.display_name_ja
        ? ` · JMA名称 ${props.name_ja}`
        : "";
      meta.textContent = `一次細分区域 ${props.region_code || feature.id || "—"}${raw}`;
    }
    tooltip.hidden = false;
    positionTooltip(tooltip, event);
  }

  function hideTooltip(tooltip) {
    if (tooltip) tooltip.hidden = true;
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function clientToView(clientX, clientY) {
    if (!state.svg) return { x: 0, y: 0 };
    const rect = state.svg.getBoundingClientRect();
    return {
      x: ((clientX - rect.left) / Math.max(1, rect.width)) * VIEW.width,
      y: ((clientY - rect.top) / Math.max(1, rect.height)) * VIEW.height,
    };
  }

  function refreshCityLabels() {
    if (!state.cityLayer) return;
    const scale = state.scale;
    for (const group of state.cityLayer.querySelectorAll(".reference-city")) {
      const minScale = Number(group.dataset.minScale || 1);
      const visible = state.cityLabelsVisible && scale + 1e-6 >= minScale;
      group.style.display = visible ? "block" : "none";
      if (!visible) continue;
      const circle = group.querySelector("circle");
      const text = group.querySelector("text");
      if (circle) {
        circle.setAttribute("r", String(3.0 / scale));
        circle.setAttribute("stroke-width", String(1.25 / scale));
      }
      if (text) {
        text.setAttribute("font-size", String(12.5 / scale));
        text.setAttribute("x", String(6.5 / scale));
        text.setAttribute("y", String(-5.5 / scale));
        text.setAttribute("stroke-width", String(2.7 / scale));
      }
    }
  }

  function notifyViewChange() {
    if (typeof state.viewChangeHandler === "function") {
      state.viewChangeHandler({ scale: state.scale, tx: state.tx, ty: state.ty });
    }
  }

  function applyTransform({ notify = true } = {}) {
    if (!state.viewport) return;
    state.viewport.setAttribute(
      "transform",
      `translate(${state.tx.toFixed(3)} ${state.ty.toFixed(3)}) scale(${state.scale.toFixed(5)})`
    );
    refreshCityLabels();
    if (notify) notifyViewChange();
  }

  function zoomAt(factor, point) {
    const next = clamp(state.scale * factor, MIN_SCALE, MAX_SCALE);
    if (Math.abs(next - state.scale) < 1e-6) return;
    const ratio = next / state.scale;
    state.tx = point.x - (point.x - state.tx) * ratio;
    state.ty = point.y - (point.y - state.ty) * ratio;
    state.scale = next;
    applyTransform();
  }

  function resetView() {
    state.scale = 1;
    state.tx = 0;
    state.ty = 0;
    state.dragLast = null;
    state.pinchStart = null;
    applyTransform();
  }

  function zoomIn() {
    zoomAt(1.45, { x: VIEW.width / 2, y: VIEW.height / 2 });
  }

  function zoomOut() {
    zoomAt(1 / 1.45, { x: VIEW.width / 2, y: VIEW.height / 2 });
  }

  function focusLonLat(lon, lat, scale = 5) {
    const p = project([lon, lat]);
    const next = clamp(Number(scale) || 5, MIN_SCALE, MAX_SCALE);
    state.scale = next;
    state.tx = VIEW.width / 2 - p[0] * next;
    state.ty = VIEW.height / 2 - p[1] * next;
    state.dragLast = null;
    state.pinchStart = null;
    applyTransform();
  }

  function focusFeature(feature, scale = 4.5) {
    const props = feature?.properties || {};
    const lon = Number(props.label_lon);
    const lat = Number(props.label_lat);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return false;
    focusLonLat(lon, lat, scale);
    return true;
  }

  function pointerDistance(a, b) {
    return Math.hypot(a.x - b.x, a.y - b.y);
  }

  function pointerCenter(a, b) {
    return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  }

  function beginPinch() {
    const points = Array.from(state.pointers.values());
    if (points.length < 2) return;
    const a = points[0];
    const b = points[1];
    const center = pointerCenter(a, b);
    state.pinchStart = {
      distance: Math.max(1, pointerDistance(a, b)),
      center,
      scale: state.scale,
      tx: state.tx,
      ty: state.ty,
      worldX: (center.x - state.tx) / state.scale,
      worldY: (center.y - state.ty) / state.scale,
    };
    state.dragLast = null;
  }

  function bindInteractions(svg) {
    if (state.interactionsBound) return;
    state.interactionsBound = true;

    svg.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        const point = clientToView(event.clientX, event.clientY);
        const factor = Math.exp(-event.deltaY * 0.0016);
        zoomAt(factor, point);
      },
      { passive: false }
    );

    svg.addEventListener("dblclick", (event) => {
      event.preventDefault();
      zoomAt(1.6, clientToView(event.clientX, event.clientY));
    });

    svg.addEventListener("pointerdown", (event) => {
      const point = clientToView(event.clientX, event.clientY);
      state.pointers.set(event.pointerId, point);
      try {
        svg.setPointerCapture(event.pointerId);
      } catch (_) {
        // Pointer capture is optional on older browsers.
      }
      if (state.pointers.size === 1) {
        state.dragLast = point;
        state.pinchStart = null;
      } else if (state.pointers.size === 2) {
        beginPinch();
      }
    });

    svg.addEventListener("pointermove", (event) => {
      if (!state.pointers.has(event.pointerId)) return;
      const point = clientToView(event.clientX, event.clientY);
      state.pointers.set(event.pointerId, point);

      if (state.pointers.size >= 2) {
        if (!state.pinchStart) beginPinch();
        const points = Array.from(state.pointers.values());
        const a = points[0];
        const b = points[1];
        const center = pointerCenter(a, b);
        const distance = Math.max(1, pointerDistance(a, b));
        const start = state.pinchStart;
        if (!start) return;
        const nextScale = clamp(start.scale * (distance / start.distance), MIN_SCALE, MAX_SCALE);
        state.scale = nextScale;
        state.tx = center.x - start.worldX * nextScale;
        state.ty = center.y - start.worldY * nextScale;
        applyTransform();
        return;
      }

      if (state.dragLast) {
        state.tx += point.x - state.dragLast.x;
        state.ty += point.y - state.dragLast.y;
        state.dragLast = point;
        applyTransform();
      }
    });

    const releasePointer = (event) => {
      state.pointers.delete(event.pointerId);
      if (state.pointers.size === 0) {
        state.dragLast = null;
        state.pinchStart = null;
      } else if (state.pointers.size === 1) {
        state.dragLast = Array.from(state.pointers.values())[0];
        state.pinchStart = null;
      } else {
        beginPinch();
      }
    };
    svg.addEventListener("pointerup", releasePointer);
    svg.addEventListener("pointercancel", releasePointer);
    svg.addEventListener("pointerleave", (event) => {
      if (event.pointerType === "mouse" && state.pointers.has(event.pointerId)) {
        releasePointer(event);
      }
    });
  }

  function buildBoundaryFragment(featureCollection) {
    if (!featureCollection || featureCollection.type !== "FeatureCollection") {
      throw new Error("Public geometry is not a GeoJSON FeatureCollection.");
    }
    const features = Array.isArray(featureCollection.features) ? featureCollection.features : [];
    if (!features.length) throw new Error("Public geometry contains no features.");

    const fragment = document.createDocumentFragment();
    let count = 0;
    for (const feature of features) {
      const d = geometryPath(feature.geometry);
      if (!d) continue;

      const path = document.createElementNS(SVG_NS, "path");
      const props = feature.properties || {};
      const code = props.region_code || String(feature.id || "");
      const name = featureDisplayName(feature);

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
        if (event.pointerType === "mouse") showTooltip(state.tooltip, feature, event);
      });
      path.addEventListener("pointermove", (event) => {
        if (event.pointerType === "mouse") positionTooltip(state.tooltip, event);
      });
      path.addEventListener("pointerleave", (event) => {
        path.classList.remove("is-active");
        if (event.pointerType === "mouse") hideTooltip(state.tooltip);
      });
      path.addEventListener("click", (event) => {
        path.classList.add("is-active");
        showTooltip(state.tooltip, feature, event);
        if (typeof state.onSelect === "function") state.onSelect(feature);
      });
      path.addEventListener("focus", () => path.classList.add("is-active"));
      path.addEventListener("blur", () => path.classList.remove("is-active"));

      fragment.appendChild(path);
      count += 1;
    }
    return { fragment, count };
  }

  function replaceGeometry(featureCollection) {
    if (!state.boundaryGroup) throw new Error("Map is not initialized.");
    const { fragment, count } = buildBoundaryFragment(featureCollection);
    state.boundaryGroup.replaceChildren(fragment);
    return count;
  }

  function renderCities(cities) {
    if (!state.cityLayer) return;
    state.cityLayer.replaceChildren();
    state.cities = Array.isArray(cities) ? cities : [];
    const fragment = document.createDocumentFragment();
    for (const city of state.cities) {
      const lon = Number(city.lon);
      const lat = Number(city.lat);
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
      const [x, y] = project([lon, lat]);
      const g = document.createElementNS(SVG_NS, "g");
      g.setAttribute("class", "reference-city");
      g.setAttribute("transform", `translate(${x.toFixed(2)} ${y.toFixed(2)})`);
      g.dataset.minScale = String(Number(city.min_scale) || 1);

      const circle = document.createElementNS(SVG_NS, "circle");
      circle.setAttribute("cx", "0");
      circle.setAttribute("cy", "0");
      const text = document.createElementNS(SVG_NS, "text");
      text.textContent = String(city.name_ja || "");
      text.setAttribute("paint-order", "stroke");
      text.setAttribute("stroke-linejoin", "round");
      g.append(circle, text);
      fragment.appendChild(g);
    }
    state.cityLayer.appendChild(fragment);
    refreshCityLabels();
  }

  function render(svg, featureCollection, options = {}) {
    if (!svg) throw new Error("Map SVG element is missing.");
    svg.setAttribute("viewBox", `0 0 ${VIEW.width} ${VIEW.height}`);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    svg.replaceChildren();

    state.tooltip = options.tooltip || null;
    state.onSelect = typeof options.onSelect === "function" ? options.onSelect : null;

    const viewport = document.createElementNS(SVG_NS, "g");
    viewport.setAttribute("class", "map-viewport");

    const rainImage = document.createElementNS(SVG_NS, "image");
    rainImage.setAttribute("class", "rain-layer");
    rainImage.setAttribute("x", String(VIEW.padding));
    rainImage.setAttribute("y", String(VIEW.padding));
    rainImage.setAttribute("width", String(VIEW.width - VIEW.padding * 2));
    rainImage.setAttribute("height", String(VIEW.height - VIEW.padding * 2));
    rainImage.setAttribute("preserveAspectRatio", "none");
    rainImage.setAttribute("pointer-events", "none");
    rainImage.style.display = "none";
    viewport.appendChild(rainImage);

    const boundaryGroup = document.createElementNS(SVG_NS, "g");
    boundaryGroup.setAttribute("class", "boundary-layer");
    viewport.appendChild(boundaryGroup);

    const cityLayer = document.createElementNS(SVG_NS, "g");
    cityLayer.setAttribute("class", "reference-city-layer");
    cityLayer.setAttribute("pointer-events", "none");
    viewport.appendChild(cityLayer);
    svg.appendChild(viewport);

    state.svg = svg;
    state.viewport = viewport;
    state.rainImage = rainImage;
    state.boundaryGroup = boundaryGroup;
    state.cityLayer = cityLayer;
    const rendered = replaceGeometry(featureCollection);
    resetView();
    bindInteractions(svg);
    return rendered;
  }

  function setRainFrame(url) {
    if (!state.rainImage) return;
    if (!url) {
      state.rainImage.removeAttribute("href");
      state.rainImage.style.display = "none";
      if (state.svg) state.svg.classList.remove("rain-active");
      return;
    }
    state.rainImage.setAttribute("href", url);
  }

  function setRainVisible(visible) {
    if (!state.rainImage) return;
    const show = Boolean(visible) && Boolean(state.rainImage.getAttribute("href"));
    state.rainImage.style.display = show ? "block" : "none";
    if (state.svg) state.svg.classList.toggle("rain-active", show);
  }

  function setBoundariesVisible(visible) {
    if (state.boundaryGroup) state.boundaryGroup.style.display = visible ? "block" : "none";
  }

  function setCityLabelsVisible(visible) {
    state.cityLabelsVisible = Boolean(visible);
    refreshCityLabels();
  }

  function setViewChangeHandler(handler) {
    state.viewChangeHandler = typeof handler === "function" ? handler : null;
    notifyViewChange();
  }

  window.LPZMap = Object.freeze({
    VIEW,
    render,
    replaceGeometry,
    renderCities,
    resetView,
    zoomIn,
    zoomOut,
    focusLonLat,
    focusFeature,
    currentScale: () => state.scale,
    setViewChangeHandler,
    setRainFrame,
    setRainVisible,
    setBoundariesVisible,
    setCityLabelsVisible,
  });
})();
