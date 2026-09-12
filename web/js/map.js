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
  const MAX_SCALE = 8;

  const state = {
    svg: null,
    viewport: null,
    rainImage: null,
    boundaryGroup: null,
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
    if (name) name.textContent = props.name_ja || "名称未取得";
    if (meta) meta.textContent = `JMA一次細分区域 ${props.region_code || feature.id || "—"}`;
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

  function applyTransform() {
    if (!state.viewport) return;
    state.viewport.setAttribute(
      "transform",
      `translate(${state.tx.toFixed(3)} ${state.ty.toFixed(3)}) scale(${state.scale.toFixed(5)})`
    );
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
        const nextScale = clamp(
          start.scale * (distance / start.distance),
          MIN_SCALE,
          MAX_SCALE
        );
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

    const tooltip = options.tooltip || null;
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
    const fragment = document.createDocumentFragment();

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
        if (event.pointerType === "mouse") showTooltip(tooltip, feature, event);
      });
      path.addEventListener("pointermove", (event) => {
        if (event.pointerType === "mouse") positionTooltip(tooltip, event);
      });
      path.addEventListener("pointerleave", (event) => {
        path.classList.remove("is-active");
        if (event.pointerType === "mouse") hideTooltip(tooltip);
      });
      path.addEventListener("click", (event) => {
        path.classList.add("is-active");
        showTooltip(tooltip, feature, event);
      });
      path.addEventListener("focus", () => path.classList.add("is-active"));
      path.addEventListener("blur", () => path.classList.remove("is-active"));

      fragment.appendChild(path);
    }

    boundaryGroup.appendChild(fragment);
    viewport.appendChild(boundaryGroup);
    svg.appendChild(viewport);

    state.svg = svg;
    state.viewport = viewport;
    state.rainImage = rainImage;
    state.boundaryGroup = boundaryGroup;
    resetView();
    bindInteractions(svg);
    return boundaryGroup.querySelectorAll(".region").length;
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
    if (state.boundaryGroup) {
      state.boundaryGroup.style.display = visible ? "block" : "none";
    }
  }

  window.LPZMap = Object.freeze({
    VIEW,
    render,
    resetView,
    zoomIn,
    zoomOut,
    setRainFrame,
    setRainVisible,
    setBoundariesVisible,
  });
})();
