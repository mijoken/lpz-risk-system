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
  let data, bySlot, scale = 1, tx = 0, ty = 0;
  let viewport, pan = null;
  const rad = Math.PI / 180;
  const merc = lat => Math.log(Math.tan(Math.PI / 4 + lat * rad / 2));
  const minY = merc(BOUNDS.south), maxY = merc(BOUNDS.north);
  const point = ([lon,lat]) => [
    P + (lon - BOUNDS.west) / (BOUNDS.east - BOUNDS.west) * (W - 2 * P),
    P + (maxY - merc(lat)) / (maxY - minY) * (H - 2 * P),
  ];
  const el = (tag, attrs = {}, title = "") => {
    const node = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    if (title) {
      const t = document.createElementNS(NS, "title"); t.textContent = title; node.append(t);
    }
    return node;
  };
  const jst = str => new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(str)) + " JST";
  const valid = c => Array.isArray(c) && c.length === 2
    && Number.isFinite(c[0]) && Number.isFinite(c[1])
    && c[0] >= -180 && c[0] <= 180 && c[1] >= -90 && c[1] <= 90;
  const zoomTransform = () => viewport.setAttribute("transform", `translate(${tx} ${ty}) scale(${scale})`);
  const zoomTo = (lon, lat, desired = 5) => {
    const [x,y] = point([lon,lat]); scale = desired;
    tx = W / 2 - x * scale; ty = H / 2 - y * scale; zoomTransform();
  };
  const geoPath = geometry => {
    const ringPath = ring => ring.map((coord,i) => {
      const [x,y] = point(coord);
      return (i ? "L" : "M") + x.toFixed(2) + " " + y.toFixed(2);
    }).join(" ") + "Z";
    if (geometry.type === "Polygon") return geometry.coordinates.map(ringPath).join(" ");
    if (geometry.type === "MultiPolygon") return geometry.coordinates.map(
      polygon => polygon.map(ringPath).join(" ")).join(" ");
    return "";
  };
  function select(feature, prediction) {
    const o = feature.geometry.coordinates;
    const p = prediction?.geometry.coordinates || null;
    const target = prediction?.properties.target_valid_time_utc;
    document.getElementById("f4-selected").textContent =
      `観測時刻：${jst(feature.properties.observation_valid_time_utc)}\n`
      + `観測中心：北緯${o[1].toFixed(4)}°／東経${o[0].toFixed(4)}°\n`
      + (p ? `研究用${prediction.properties.lead_from_as_of_minutes}分先：${jst(target)}\n北緯${p[1].toFixed(4)}°／東経${p[0].toFixed(4)}°\n` : "")
      + "注：降雨域中心の点外挿であり、線状降水帯の予測位置・雨量・影響範囲ではありません。";
  }
  function render() {
    const slot = slotSelect.value, lead = Number(leadSelect.value);
    const rows = bySlot.get(slot) || [];
    const origins = rows.filter(f => f.properties.kind === "OBSERVED_ORIGIN");
    const ends = new Map(rows.filter(f => f.properties.kind === "RESEARCH_POINT_EXTRAPOLATION"
      && f.properties.lead_from_as_of_minutes === lead)
      .map(f => [f.properties.research_object_id, f]));
    viewport.querySelector(".f4-research-layer")?.remove();
    const layer = el("g", {"class":"f4-research-layer"});
    for (const origin of origins) {
      const future = ends.get(origin.properties.research_object_id);
      if (!future) continue;
      const o = point(origin.geometry.coordinates);
      const p = point(future.geometry.coordinates);
      const name = "保存済み観測 " + jst(origin.properties.observation_valid_time_utc);
      layer.append(el("path", {d:`M${o[0]},${o[1]} L${p[0]},${p[1]}`,
        "class":"f4-arrow"}, name + " の研究用外挿"));
      layer.append(el("circle", {cx:p[0],cy:p[1],r:3.4,"class":"f4-end"},
        lead + "分先の外挿中心"));
      const marker = el("circle", {cx:o[0],cy:o[1],r:4.3,"class":"f4-origin",
        tabindex:"0",role:"button","aria-label":name}, name);
      marker.addEventListener("click", () => select(origin, future));
      marker.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") {e.preventDefault();select(origin,future);}
      });
      layer.append(marker);
    }
    viewport.append(layer);
    document.getElementById("f4-context").textContent =
      `観測：${jst(slot)} ／ 研究用${lead}分先外挿 ／ 対象${origins.length}件（同一時刻の観測中心）`;
    status.textContent = `保存済み研究表示 · ${origins.length}件 · 予報ではありません`;
  }
  function focusSelected() {
    const rows = bySlot.get(slotSelect.value) || [];
    const origins = rows.filter(f => f.properties.kind === "OBSERVED_ORIGIN");
    if (!origins.length) return;
    const lon = origins.reduce((sum,f) => sum + f.geometry.coordinates[0],0)/origins.length;
    const lat = origins.reduce((sum,f) => sum + f.geometry.coordinates[1],0)/origins.length;
    zoomTo(lon,lat,5);
  }
  function bindZoomPan() {
    svg.addEventListener("wheel",e=>{
      e.preventDefault();
      const r=svg.getBoundingClientRect();
      const x=(e.clientX-r.left)*W/r.width,y=(e.clientY-r.top)*H/r.height;
      const next=Math.min(20,Math.max(1,scale*Math.exp(-e.deltaY*.0016)));
      const ratio=next/scale;tx=x-(x-tx)*ratio;ty=y-(y-ty)*ratio;scale=next;zoomTransform();
    },{passive:false});
    svg.addEventListener("pointerdown",e=>{
      pan={x:e.clientX,y:e.clientY};
      try{svg.setPointerCapture(e.pointerId);}catch(_){}
    });
    svg.addEventListener("pointermove",e=>{
      if(!pan)return;
      const r=svg.getBoundingClientRect();
      tx+=(e.clientX-pan.x)*W/r.width;ty+=(e.clientY-pan.y)*H/r.height;
      pan={x:e.clientX,y:e.clientY};zoomTransform();
    });
    for (const type of ["pointerup","pointercancel"]) svg.addEventListener(type,()=>{pan=null;});
  }
  async function start() {
    try {
      const [dataResponse,mapResponse]=await Promise.all([
        fetch("./data/research/f4_archived_geographic_research.geojson",{cache:"no-store"}),
        fetch("./assets/japan_primary_subdivisions.geojson",{cache:"no-store"}),
      ]);
      if(!dataResponse.ok || !mapResponse.ok) throw Error("地理データの取得失敗");
      data=await dataResponse.json();
      const map=await mapResponse.json();
      if(data.product!=="LPZ_F4_ARCHIVED_GEOGRAPHIC_RESEARCH"
        || data.archived_research_only!==true || data.risk_engine_allowed!==false
        || data.lpz_forecast_generated!==false || data.radar_coverage!=="SELECTED_FIXED_MOSAIC_NOT_NATIONWIDE"
        || data.source_run_id!=="35564667965" || data.feature_count!==data.features.length
        || map.type!=="FeatureCollection") throw Error("研究データ契約または出典不一致");
      if(data.features.some(f=>!["OBSERVED_ORIGIN","RESEARCH_POINT_EXTRAPOLATION",
        "RESEARCH_POINT_MOTION_ARROW"].includes(f.properties.kind)
        || (f.geometry.type==="Point" && !valid(f.geometry.coordinates))
        || (f.geometry.type==="LineString" && f.geometry.coordinates.some(c=>!valid(c)))))
        throw Error("位置または研究表示種別が不正");
      bySlot=new Map();
      for(const f of data.features){
        const key=f.properties.source_slot_utc;
        if(!bySlot.has(key))bySlot.set(key,[]);
        bySlot.get(key).push(f);
      }
      viewport=el("g",{"class":"f4-map-viewport"});
      const boundaries=el("g",{"class":"f4-boundaries"});
      for(const f of map.features||[]){
        const d=geoPath(f.geometry);
        if(d) boundaries.append(el("path",{d,"class":"f4-boundary","fill-rule":"evenodd"}));
      }
      viewport.append(boundaries);svg.replaceChildren(viewport);
      const slots=[...bySlot.keys()].sort();
      if(!slots.length)throw Error("観測時刻がありません");
      slotSelect.replaceChildren();
      for(const slot of slots){
        const option=document.createElement("option");option.value=slot;
        option.textContent=jst(slot);slotSelect.append(option);
      }
      slotSelect.value=slots[slots.length-1];
      slotSelect.disabled=false;leadSelect.disabled=false;focusButton.disabled=false;
      slotSelect.addEventListener("change",()=>{render();focusSelected();});
      leadSelect.addEventListener("change",render);
      focusButton.addEventListener("click",focusSelected);
      bindZoomPan();render();focusSelected();
    } catch(e) {
      console.error(e);
      status.textContent="表示できません：" + e.message;
    }
  }
  start();
})();
