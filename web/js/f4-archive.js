(() => {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const W = 1200, H = 760, P = 28;
  const BOUNDS = {west: 122, east: 154.5, south: 20, north: 46.5};

  const svg = document.getElementById("f4-map");
  const status = document.getElementById("f4-status");
  const slotSelect = document.getElementById("f4-slot");
  const leadSelect = document.getElementById("f4-lead");
  const focusButton = document.getElementById("f4-focus");
  const fieldMotionFocusButton = document.getElementById("f4-field-motion-focus");
  const fieldMotionToggle = document.getElementById("f4-field-motion-toggle");
  const pointToggle = document.getElementById("f4-point-toggle");
  const fieldMotionMeta = document.getElementById("f4-field-motion-meta");
  const legacyListSection = document.getElementById("f4-legacy-list-section");

  let data = null;
  let fieldMotionData = null;
  let bySlot = new Map();
  let cities = [];
  let scale = 1, tx = 0, ty = 0;
  let viewport = null, fieldMotionLayer = null, legacyLayer = null, pan = null;
  let selectedLegacyId = null, selectedFieldMotionId = null;
  let selectedMarkers = new Map();

  const rad = Math.PI / 180;
  const merc = lat => Math.log(Math.tan(Math.PI / 4 + lat * rad / 2));
  const minY = merc(BOUNDS.south), maxY = merc(BOUNDS.north);

  const point = ([lon, lat]) => [
    P + (lon - BOUNDS.west) / (BOUNDS.east - BOUNDS.west) * (W - 2 * P),
    P + (maxY - merc(lat)) / (maxY - minY) * (H - 2 * P),
  ];

  const el = (tag, attrs = {}, title = "") => {
    const node = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    if (title) {
      const t = document.createElementNS(NS, "title");
      t.textContent = title;
      node.append(t);
    }
    return node;
  };

  const jst = str => new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(str)) + " JST";

  const valid = c => Array.isArray(c) && c.length === 2
    && Number.isFinite(c[0]) && Number.isFinite(c[1])
    && c[0] >= -180 && c[0] <= 180 && c[1] >= -90 && c[1] <= 90;

  const geoPath = geometry => {
    const ringPath = ring => ring.map((coord, i) => {
      const [x, y] = point(coord);
      return (i ? "L" : "M") + x.toFixed(2) + " " + y.toFixed(2);
    }).join(" ") + "Z";
    if (geometry.type === "Polygon") return geometry.coordinates.map(ringPath).join(" ");
    if (geometry.type === "MultiPolygon") {
      return geometry.coordinates.map(polygon => polygon.map(ringPath).join(" ")).join(" ");
    }
    return "";
  };

  const km = (a, b) => {
    const r = Math.PI / 180;
    const dLat = (b[1] - a[1]) * r;
    const dLon = (b[0] - a[0]) * r;
    const h = Math.sin(dLat / 2) ** 2
      + Math.cos(a[1] * r) * Math.cos(b[1] * r) * Math.sin(dLon / 2) ** 2;
    return 12742.0176 * Math.asin(Math.min(1, Math.sqrt(h)));
  };

  const nearestCity = coord => {
    if (!cities.length) return null;
    return cities.map(c => ({...c, distance: km(coord, [c.lon, c.lat])}))
      .sort((a, b) => a.distance - b.distance)[0];
  };

  const regionName = coord => {
    const city = nearestCity(coord);
    return city
      ? city.name_ja + "の中心から約" + city.distance.toFixed(0)
        + " km（方位・影響地域ではありません）"
      : "参考都市データなし";
  };

  const formatArea = area => Number.isFinite(Number(area))
    ? Number(area).toLocaleString("ja-JP", {maximumFractionDigits: 1}) + " km²"
    : "未取得";

  function renderDetailCards(rows, noteText) {
    const detail = document.getElementById("f4-selected");
    detail.replaceChildren();
    for (const [label, value] of rows) {
      const card = document.createElement("div");
      card.className = "archive-detail-card";
      const caption = document.createElement("span");
      caption.textContent = label;
      const strong = document.createElement("strong");
      strong.textContent = value;
      card.append(caption, strong);
      detail.append(card);
    }
    if (noteText) {
      const note = document.createElement("p");
      note.className = "archive-detail-note";
      note.textContent = noteText;
      detail.append(note);
    }
  }

  function updateArrowHead(path) {
    const x = Number(path.dataset.endX);
    const y = Number(path.dataset.endY);
    const ux = Number(path.dataset.ux);
    const uy = Number(path.dataset.uy);
    if (![x, y, ux, uy].every(Number.isFinite)) return;
    const head = 8 / Math.max(1, scale);
    const wing = 4.5 / Math.max(1, scale);
    const bx = x - ux * head;
    const by = y - uy * head;
    const lx = bx - uy * wing;
    const ly = by + ux * wing;
    const rx = bx + uy * wing;
    const ry = by - ux * wing;
    path.setAttribute("d",
      "M" + lx + "," + ly + " L" + x + "," + y + " L" + rx + "," + ry
    );
  }

  function zoomTransform() {
    viewport.setAttribute("transform", "translate(" + tx + " " + ty + ") scale(" + scale + ")");

    for (const circle of viewport.querySelectorAll(".f4-origin")) {
      circle.setAttribute("r", String(9 / scale));
    }
    for (const circle of viewport.querySelectorAll(".f4-end")) {
      circle.setAttribute("r", String(4 / scale));
    }
    for (const label of viewport.querySelectorAll(".f4-origin-number")) {
      label.setAttribute("font-size", String(10 / scale));
    }
    for (const arrow of viewport.querySelectorAll(".f4-arrow-head")) updateArrowHead(arrow);

    const placed = [];
    for (const g of viewport.querySelectorAll(".f4-city")) {
      const circle = g.querySelector("circle");
      const label = g.querySelector("text");
      const baseX = Number(g.dataset.x);
      const baseY = Number(g.dataset.y);
      const screenX = baseX * scale + tx;
      const screenY = baseY * scale + ty;
      const minScale = Number(g.dataset.minScale || 1);

      if (circle) {
        circle.setAttribute("r", String(2.3 / scale));
        circle.setAttribute("stroke-width", String(1 / scale));
      }
      if (!label) continue;

      label.setAttribute("font-size", String(12 / scale));
      label.setAttribute("stroke-width", String(2.6 / scale));
      label.setAttribute("x", String(baseX + 5 / scale));
      label.setAttribute("y", String(baseY - 5 / scale));

      const width = Math.max(28, String(label.textContent || "").length * 12 + 10);
      const visible = scale >= minScale
        && screenX >= 0 && screenX <= W - width
        && screenY >= 18 && screenY <= H - 8;
      const overlaps = placed.some(box =>
        screenX < box.x + box.w + 8 && screenX + width > box.x - 8
        && screenY - 16 < box.y + 7 && screenY + 7 > box.y - 16
      );
      const show = visible && !overlaps;
      label.style.display = show ? "" : "none";
      if (show) placed.push({x: screenX, y: screenY, w: width});
    }
  }

  function zoomTo(lon, lat, desired = 5) {
    const [x, y] = point([lon, lat]);
    scale = Math.min(20, Math.max(1, desired));
    tx = W / 2 - x * scale;
    ty = H / 2 - y * scale;
    zoomTransform();
  }

  function selectLegacy(origin, prediction) {
    selectedLegacyId = String(origin.properties.research_object_id || "");
    selectedFieldMotionId = null;

    for (const path of fieldMotionLayer.querySelectorAll(".f4-field-motion.is-selected")) {
      path.classList.remove("is-selected");
    }
    for (const [id, marker] of selectedMarkers) {
      marker.setAttribute("aria-pressed", String(id === selectedLegacyId));
    }
    for (const button of document.querySelectorAll("#f4-object-list button")) {
      button.setAttribute("aria-pressed", String(button.dataset.objectId === selectedLegacyId));
    }

    const o = origin.geometry.coordinates;
    const p = prediction?.geometry.coordinates || null;
    const target = prediction?.properties.target_valid_time_utc;
    const observation = origin.properties.observation_valid_time_utc;
    const elapsed = target ? Math.round((new Date(target) - new Date(observation)) / 60000) : null;
    const rows = [
      ["レイヤー", "旧F4観測中心＋等速位置外挿"],
      ["観測地点の目安", regionName(o)],
      ["観測時刻", jst(observation)],
      ["観測中心", "北緯" + o[1].toFixed(4) + "°／東経" + o[0].toFixed(4) + "°"],
      ["30 mm/h以上の観測域の概算面積", formatArea(origin.properties.observed_approx_area_km2)],
    ];
    if (origin.properties.observed_boundary_truncated) {
      rows.push(["観測範囲", "解析範囲の端で切れています。面積は全域を表さない可能性があります。"]);
    }
    if (p) {
      rows.push(
        ["研究用外挿先", jst(target)],
        ["外挿中心", "北緯" + p[1].toFixed(4) + "°／東経" + p[0].toFixed(4) + "°"],
        ["観測からの経過", elapsed + "分（15/30分は研究用基準時刻から）"],
        ["中心からの直線距離", "約" + km(o, p).toFixed(1) + " km"]
      );
    }
    renderDetailCards(
      rows,
      "旧F4の表示です。実際の降雨域輪郭・予測雨量・線状降水帯発生確率を表しません。"
    );
  }

  function selectFieldMotion(feature, path) {
    selectedFieldMotionId = String(feature.properties.research_object_id || "");
    selectedLegacyId = null;

    for (const marker of selectedMarkers.values()) marker.setAttribute("aria-pressed", "false");
    for (const button of document.querySelectorAll("#f4-object-list button")) {
      button.setAttribute("aria-pressed", "false");
    }
    for (const other of fieldMotionLayer.querySelectorAll(".f4-field-motion.is-selected")) {
      other.classList.remove("is-selected");
    }
    path.classList.add("is-selected");

    const props = feature.properties || {};
    const centroid = props.projected_centroid_lon_lat;
    const coord = valid(centroid) ? centroid : null;
    const rows = [
      ["レイヤー", "保存済みLucas–Kanade短時間研究予測"],
      ["F4-9D判定", String(fieldMotionData.terminal_decision || "PENDING")],
      ["研究as-of", jst(fieldMotionData.source_as_of_utc)],
      ["予測対象時刻", jst(props.target_valid_time_utc)],
      ["リードタイム", String(props.lead_from_as_of_minutes) + "分先（as-of基準）"],
      ["研究オブジェクト", String(props.research_object_id || "—")],
      ["予測域の概算面積", formatArea(props.projected_approx_area_km2)],
    ];
    if (coord) {
      rows.push(
        ["予測中心", "北緯" + coord[1].toFixed(4) + "°／東経" + coord[0].toFixed(4) + "°"],
        ["位置の目安", regionName(coord)]
      );
    }
    renderDetailCards(
      rows,
      "保存済みの過去予測です。現在の予報ではなく、線状降水帯の発生確率・危険度・警報を表しません。"
    );
  }

  function renderFieldMotionLayer() {
    fieldMotionLayer.replaceChildren();
    if (!fieldMotionData || !fieldMotionToggle.checked) return;

    const lead = Number(leadSelect.value);
    const features = (fieldMotionData.features || []).filter(feature =>
      feature?.properties?.kind === "FIELD_MOTION_RESEARCH_ENVELOPE"
      && Number(feature.properties.lead_from_as_of_minutes) === lead
    );

    for (const feature of features) {
      const d = geoPath(feature.geometry);
      if (!d) continue;
      const path = el("path", {
        d,
        "class": "f4-field-motion f4-field-motion-" + lead,
        "fill-rule": "evenodd",
        "clip-rule": "evenodd",
        tabindex: "0",
        role: "button",
        "aria-label": "保存済みLucas–Kanade研究予測 " + lead + "分先",
      });
      path.dataset.objectId = String(feature.properties.research_object_id || "");
      const activate = event => {
        event?.stopPropagation();
        selectFieldMotion(feature, path);
      };
      path.addEventListener("click", activate);
      path.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate(event);
        }
      });
      if (path.dataset.objectId === selectedFieldMotionId) path.classList.add("is-selected");
      fieldMotionLayer.append(path);
    }

    if (fieldMotionMeta) {
      fieldMotionMeta.innerHTML =
        "<strong>紫色アーカイブ</strong> · as-of " + jst(fieldMotionData.source_as_of_utc)
        + " · " + fieldMotionData.projected_component_count + "対象 · "
        + fieldMotionData.feature_count + "保存済み予測域 · F4-9D "
        + String(fieldMotionData.terminal_decision || "PENDING");
    }
    document.getElementById("f4-context").textContent =
      "紫：Lucas–Kanade保存済み予測 " + lead + "分先を表示中。"
      + "現在の予報ではありません。";
  }

  function renderLegacyLayer() {
    legacyLayer.replaceChildren();
    selectedMarkers = new Map();
    const list = document.getElementById("f4-object-list");
    list.replaceChildren();

    if (!pointToggle.checked) {
      if (legacyListSection) legacyListSection.hidden = true;
      return;
    }
    if (legacyListSection) legacyListSection.hidden = false;

    const slot = slotSelect.value;
    const lead = Number(leadSelect.value);
    const rows = bySlot.get(slot) || [];
    const origins = rows.filter(f => f.properties.kind === "OBSERVED_ORIGIN");
    const ends = new Map(rows.filter(f =>
      f.properties.kind === "RESEARCH_POINT_EXTRAPOLATION"
      && Number(f.properties.lead_from_as_of_minutes) === lead
    ).map(f => [f.properties.research_object_id, f]));

    origins.forEach((origin, index) => {
      const future = ends.get(origin.properties.research_object_id);
      if (!future) return;
      const o = point(origin.geometry.coordinates);
      const p = point(future.geometry.coordinates);
      const name = "旧F4観測対象" + (index + 1) + "・" + regionName(origin.geometry.coordinates);
      const dx = p[0] - o[0], dy = p[1] - o[1], len = Math.hypot(dx, dy);

      legacyLayer.append(el("path", {
        d: "M" + o[0] + "," + o[1] + " L" + p[0] + "," + p[1],
        "class": "f4-arrow",
      }, name + "の研究用外挿"));

      if (len > 5) {
        const arrow = el("path", {"class": "f4-arrow-head"});
        arrow.dataset.endX = String(p[0]);
        arrow.dataset.endY = String(p[1]);
        arrow.dataset.ux = String(dx / len);
        arrow.dataset.uy = String(dy / len);
        legacyLayer.append(arrow);
      }

      legacyLayer.append(el("circle", {
        cx: p[0], cy: p[1], r: 4, "class": "f4-end",
      }, lead + "分先の研究用外挿"));

      const marker = el("circle", {
        cx: o[0], cy: o[1], r: 9, "class": "f4-origin",
        tabindex: "0", role: "button", "aria-pressed": "false", "aria-label": name,
      }, name);
      const number = el("text", {x: o[0], y: o[1], "class": "f4-origin-number"});
      number.textContent = String(index + 1);

      const activate = () => {
        selectLegacy(origin, future);
        zoomTo(origin.geometry.coordinates[0], origin.geometry.coordinates[1], 9);
      };
      marker.addEventListener("click", activate);
      marker.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
        }
      });

      legacyLayer.append(marker, number);
      selectedMarkers.set(String(origin.properties.research_object_id || ""), marker);

      const button = document.createElement("button");
      button.type = "button";
      button.dataset.objectId = String(origin.properties.research_object_id || "");
      button.setAttribute("aria-pressed", "false");
      button.textContent = (index + 1) + ". " + regionName(origin.geometry.coordinates)
        + " ／ 観測中心 " + origin.geometry.coordinates[1].toFixed(3) + "°N, "
        + origin.geometry.coordinates[0].toFixed(3) + "°E ／ 面積 "
        + formatArea(origin.properties.observed_approx_area_km2);
      button.addEventListener("click", activate);
      list.append(button);
    });

    if (!list.children.length) list.textContent = "この時刻の旧F4対象はありません。";
    document.getElementById("f4-context").textContent =
      "旧F4観測：" + jst(slot) + " ／ " + lead + "分先外挿を表示中。";
  }

  function renderAll() {
    renderFieldMotionLayer();
    renderLegacyLayer();
    zoomTransform();
  }

  function focusLegacy() {
    const rows = bySlot.get(slotSelect.value) || [];
    const origins = rows.filter(f => f.properties.kind === "OBSERVED_ORIGIN");
    if (!origins.length) return;
    const lon = origins.reduce((sum, f) => sum + f.geometry.coordinates[0], 0) / origins.length;
    const lat = origins.reduce((sum, f) => sum + f.geometry.coordinates[1], 0) / origins.length;
    zoomTo(lon, lat, 5);
  }

  function fieldMotionBounds(features) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

    for (const feature of features) {
      const geometry = feature?.geometry;
      if (!geometry || geometry.type !== "Polygon") continue;

      for (const ring of geometry.coordinates || []) {
        for (const coord of ring || []) {
          if (!valid(coord)) continue;
          const [x, y] = point(coord);
          minX = Math.min(minX, x);
          minY = Math.min(minY, y);
          maxX = Math.max(maxX, x);
          maxY = Math.max(maxY, y);
        }
      }
    }

    if (![minX, minY, maxX, maxY].every(Number.isFinite)) return null;
    return {minX, minY, maxX, maxY};
  }

  function focusFieldMotion() {
    if (!fieldMotionData) return;

    const lead = Number(leadSelect.value);
    const features = (fieldMotionData.features || []).filter(feature =>
      feature?.properties?.kind === "FIELD_MOTION_RESEARCH_ENVELOPE"
      && Number(feature.properties.lead_from_as_of_minutes) === lead
    );
    if (!features.length) return;

    const bounds = fieldMotionBounds(features);
    if (!bounds) return;

    // Fit the actual archived purple polygon extent into the archive map.
    // This is deliberately tighter than the live-map national overview.
    const paddingX = 105;
    const paddingY = 82;
    const width = Math.max(1, bounds.maxX - bounds.minX);
    const height = Math.max(1, bounds.maxY - bounds.minY);
    const fitX = (W - paddingX * 2) / width;
    const fitY = (H - paddingY * 2) / height;
    const desired = Math.min(12, Math.max(2.5, Math.min(fitX, fitY)));

    const centerX = (bounds.minX + bounds.maxX) / 2;
    const centerY = (bounds.minY + bounds.maxY) / 2;

    scale = desired;
    tx = W / 2 - centerX * scale;
    ty = H / 2 - centerY * scale;
    zoomTransform();
  }

  function bindZoomPan() {
    svg.addEventListener("wheel", event => {
      event.preventDefault();
      const r = svg.getBoundingClientRect();
      const x = (event.clientX - r.left) * W / r.width;
      const y = (event.clientY - r.top) * H / r.height;
      const next = Math.min(20, Math.max(1, scale * Math.exp(-event.deltaY * .0016)));
      const ratio = next / scale;
      tx = x - (x - tx) * ratio;
      ty = y - (y - ty) * ratio;
      scale = next;
      zoomTransform();
    }, {passive: false});

    svg.addEventListener("pointerdown", event => {
      pan = {x: event.clientX, y: event.clientY};
    });
    svg.addEventListener("pointermove", event => {
      if (!pan) return;
      const r = svg.getBoundingClientRect();
      tx += (event.clientX - pan.x) * W / r.width;
      ty += (event.clientY - pan.y) * H / r.height;
      pan = {x: event.clientX, y: event.clientY};
      zoomTransform();
    });
    for (const type of ["pointerup", "pointercancel", "pointerleave"]) {
      svg.addEventListener(type, () => { pan = null; });
    }
  }

  function validateFieldMotion(doc) {
    if (doc?.product !== "LPZ_F4_FIELD_MOTION_RESEARCH"
        || !["AVAILABLE", "ARCHIVED"].includes(doc.status)
        || doc.model_id !== "LUCAS_KANADE_SEMILAGRANGIAN"
        || doc.research_only !== true
        || doc.validated_forecast !== false
        || doc.production_integration_enabled !== false
        || doc.risk_engine_allowed !== false
        || doc.lpz_forecast_generated !== false
        || doc.feature_count !== doc.features.length) {
      throw Error("Lucas–Kanade保存済み研究データ契約不一致");
    }
    if (doc.features.some(feature =>
      feature?.geometry?.type !== "Polygon"
      || feature?.properties?.kind !== "FIELD_MOTION_RESEARCH_ENVELOPE"
      || ![15, 30].includes(Number(feature.properties.lead_from_as_of_minutes))
    )) {
      throw Error("Lucas–Kanade保存済み研究geometry不一致");
    }
  }

  async function start() {
    try {
      const [dataResponse, motionResponse, mapResponse, cityResponse] = await Promise.all([
        fetch("./data/research/f4_archived_geographic_research.geojson", {cache: "no-store"}),
        fetch("./data/research/f4_field_motion_research.geojson", {cache: "no-store"}),
        fetch("./assets/japan_primary_subdivisions.geojson", {cache: "no-store"}),
        fetch("./data/reference_cities.json", {cache: "no-store"}),
      ]);
      if (!dataResponse.ok || !motionResponse.ok || !mapResponse.ok || !cityResponse.ok) {
        throw Error("地理データの取得失敗");
      }

      data = await dataResponse.json();
      fieldMotionData = await motionResponse.json();
      const map = await mapResponse.json();
      const cityDoc = await cityResponse.json();

      if (cityDoc.product !== "LPZ_PUBLIC_REFERENCE_CITIES"
          || cityDoc.scientific_input_allowed !== false
          || !Array.isArray(cityDoc.cities)) {
        throw Error("参考都市データ契約不一致");
      }
      cities = cityDoc.cities.filter(c => Number.isFinite(c.lon) && Number.isFinite(c.lat));

      if (data.product !== "LPZ_F4_ARCHIVED_GEOGRAPHIC_RESEARCH"
          || data.archived_research_only !== true
          || data.risk_engine_allowed !== false
          || data.lpz_forecast_generated !== false
          || data.radar_coverage !== "SELECTED_FIXED_MOSAIC_NOT_NATIONWIDE"
          || data.source_run_id !== "35564667965"
          || data.feature_count !== data.features.length
          || map.type !== "FeatureCollection") {
        throw Error("旧F4研究データ契約または出典不一致");
      }
      if (data.features.some(f =>
        !["OBSERVED_ORIGIN", "RESEARCH_POINT_EXTRAPOLATION", "RESEARCH_POINT_MOTION_ARROW"]
          .includes(f.properties.kind)
        || (f.geometry.type === "Point" && !valid(f.geometry.coordinates))
        || (f.geometry.type === "LineString" && f.geometry.coordinates.some(c => !valid(c)))
      )) {
        throw Error("旧F4位置または研究表示種別が不正");
      }

      validateFieldMotion(fieldMotionData);

      bySlot = new Map();
      for (const feature of data.features) {
        const key = feature.properties.source_slot_utc;
        if (!bySlot.has(key)) bySlot.set(key, []);
        bySlot.get(key).push(feature);
      }

      viewport = el("g", {"class": "f4-map-viewport"});
      const boundaries = el("g", {"class": "f4-boundaries"});
      for (const feature of map.features || []) {
        const d = geoPath(feature.geometry);
        if (d) boundaries.append(el("path", {d, "class": "f4-boundary", "fill-rule": "evenodd"}));
      }
      viewport.append(boundaries);

      fieldMotionLayer = el("g", {"class": "f4-field-motion-layer"});
      legacyLayer = el("g", {"class": "f4-research-layer"});
      viewport.append(fieldMotionLayer, legacyLayer);

      const cityLayer = el("g", {"class": "f4-cities", "pointer-events": "none"});
      for (const city of cities) {
        const [x, y] = point([city.lon, city.lat]);
        const g = el("g", {"class": "f4-city"});
        g.dataset.x = String(x);
        g.dataset.y = String(y);
        g.dataset.minScale = String(Number(city.min_scale) || 1);
        g.append(el("circle", {cx: x, cy: y, r: 2.3}));
        const label = el("text", {x: x + 5, y: y - 5});
        label.textContent = city.name_ja;
        g.append(label);
        cityLayer.append(g);
      }
      viewport.append(cityLayer);
      svg.replaceChildren(viewport);

      const slots = [...bySlot.keys()].sort();
      if (!slots.length) throw Error("旧F4観測時刻がありません");
      slotSelect.replaceChildren();
      for (const slot of slots) {
        const option = document.createElement("option");
        option.value = slot;
        option.textContent = jst(slot);
        slotSelect.append(option);
      }
      slotSelect.value = slots[slots.length - 1];

      slotSelect.disabled = false;
      leadSelect.disabled = false;
      focusButton.disabled = false;
      fieldMotionFocusButton.disabled = false;
      fieldMotionToggle.disabled = false;
      pointToggle.disabled = false;

      slotSelect.addEventListener("change", () => {
        renderLegacyLayer();
        if (pointToggle.checked) focusLegacy();
        zoomTransform();
      });
      leadSelect.addEventListener("change", () => {
        selectedFieldMotionId = null;
        selectedLegacyId = null;
        renderAll();
      });
      focusButton.addEventListener("click", focusLegacy);
      fieldMotionFocusButton.addEventListener("click", focusFieldMotion);
      fieldMotionToggle.addEventListener("change", () => {
        renderFieldMotionLayer();
        zoomTransform();
      });
      pointToggle.addEventListener("change", () => {
        renderLegacyLayer();
        zoomTransform();
      });

      bindZoomPan();
      renderAll();
      focusFieldMotion();

      status.textContent =
        "紫：保存済みLucas–Kanade " + fieldMotionData.projected_component_count
        + "対象・" + fieldMotionData.feature_count + "予測域"
        + " ／ 旧F4固定archive run " + data.source_run_id
        + " ／ ライブ更新ではありません";

      if (location.hash === "#field-motion") focusFieldMotion();
    } catch (error) {
      console.error(error);
      status.textContent = "表示できません：" + error.message;
      if (fieldMotionMeta) fieldMotionMeta.textContent = "表示できません：" + error.message;
    }
  }

  start();
})();
