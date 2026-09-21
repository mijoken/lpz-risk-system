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
  let data, bySlot, cities = [], scale = 1, tx = 0, ty = 0;
  let selectedId = null, selectedRows = [], selectedMarkers = new Map();
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
  const km = (a,b) => {
    const r = Math.PI / 180, dLat = (b[1]-a[1])*r, dLon = (b[0]-a[0])*r;
    const h = Math.sin(dLat/2)**2 + Math.cos(a[1]*r)*Math.cos(b[1]*r)*Math.sin(dLon/2)**2;
    return 12742.0176*Math.asin(Math.min(1,Math.sqrt(h)));
  };
  const nearestCity = coord => {
    if (!cities.length) return null;
    return cities.map(c => ({...c, distance:km(coord,[c.lon,c.lat])}))
      .sort((a,b)=>a.distance-b.distance)[0];
  };
  const regionName = coord => {
    const city=nearestCity(coord);
    return city ? city.name_ja+"の中心から約"+city.distance.toFixed(0)+" km（方位・影響地域ではありません）"
      : "参考都市データなし";
  };
  const formatArea = area => Number.isFinite(area) ? area.toLocaleString("ja-JP",{maximumFractionDigits:0})+" km²（概算・輪郭なし）" : "未取得";
  function select(feature, prediction) {
    selectedId = feature.properties.research_object_id;
    for (const [id, marker] of selectedMarkers) marker.setAttribute("aria-pressed",String(id===selectedId));
    for (const button of document.querySelectorAll("#f4-object-list button")) {
      button.setAttribute("aria-pressed",String(button.dataset.objectId===selectedId));
    }
    const o=feature.geometry.coordinates;
    const p=prediction?.geometry.coordinates || null;
    const target=prediction?.properties.target_valid_time_utc;
    const observation=feature.properties.observation_valid_time_utc;
    const elapsed=target ? Math.round((new Date(target)-new Date(observation))/60000) : null;
    const area=feature.properties.observed_approx_area_km2;
    document.getElementById("f4-selected").textContent =
      "観測地点の目安："+regionName(o)+"\n"
      + "観測時刻："+jst(observation)+"\n"
      + "観測中心：北緯"+o[1].toFixed(4)+"°／東経"+o[0].toFixed(4)+"°\n"
      + "30 mm/h以上の観測域の概算面積："+formatArea(area)+"\n"
      + (feature.properties.observed_boundary_truncated ? "解析範囲の端で切れています。面積は全域を表さない可能性があります。\n" : "")
      + (p ? "研究用外挿先："+jst(target)+"\n"
        + "北緯"+p[1].toFixed(4)+"°／東経"+p[0].toFixed(4)+"°\n"
        + "観測から"+elapsed+"分後（選択した15/30分は基準時刻からの時間）\n"
        + "中心からの直線距離：約"+km(o,p).toFixed(1)+" km\n" : "")
      + "降雨域の実際の輪郭・長さ・幅・予測雨量・発生確率は未算出。";
  }
  function render() {
    const slot=slotSelect.value, lead=Number(leadSelect.value);
    const rows=bySlot.get(slot)||[];
    const origins=rows.filter(f=>f.properties.kind==="OBSERVED_ORIGIN");
    const ends=new Map(rows.filter(f=>f.properties.kind==="RESEARCH_POINT_EXTRAPOLATION"
      && f.properties.lead_from_as_of_minutes===lead)
      .map(f=>[f.properties.research_object_id,f]));
    viewport.querySelector(".f4-research-layer")?.remove();
    selectedMarkers=new Map();
    selectedRows=[];
    const list=document.getElementById("f4-object-list");
    list.replaceChildren();
    const layer=el("g",{"class":"f4-research-layer"});
    origins.forEach((origin,index)=>{
      const future=ends.get(origin.properties.research_object_id);
      if(!future)return;
      const o=point(origin.geometry.coordinates),p=point(future.geometry.coordinates);
      const name="観測対象"+(index+1)+"・"+regionName(origin.geometry.coordinates);
      const dx=p[0]-o[0],dy=p[1]-o[1],len=Math.hypot(dx,dy);
      layer.append(el("path",{d:"M"+o[0]+","+o[1]+" L"+p[0]+","+p[1],
        "class":"f4-arrow"},name+"の研究用外挿"));
      if(len>5){
        const ux=dx/len,uy=dy/len,head=6;
        layer.append(el("path",{d:"M"+p[0]+","+p[1]+" l"+(-ux*head-uy*head*.5)+","+(-uy*head+ux*head*.5)
          +" l"+(uy*head)+","+(-ux*head)+" Z","class":"f4-arrow-head"}));
      }
      layer.append(el("circle",{cx:p[0],cy:p[1],r:4,"class":"f4-end"},lead+"分先の研究用外挿"));
      const marker=el("circle",{cx:o[0],cy:o[1],r:9,"class":"f4-origin",
        tabindex:"0",role:"button","aria-pressed":"false","aria-label":name},name);
      const number=el("text",{x:o[0],y:o[1],"class":"f4-origin-number"});
      number.textContent=String(index+1);
      const activate=()=>{select(origin,future);zoomTo(origin.geometry.coordinates[0],origin.geometry.coordinates[1],9);};
      marker.addEventListener("click",activate);
      marker.addEventListener("keydown",e=>{
        if(e.key==="Enter"||e.key===" "){e.preventDefault();activate();}
      });
      layer.append(marker,number);
      selectedMarkers.set(origin.properties.research_object_id,marker);
      selectedRows.push({origin,future});
      const button=document.createElement("button");
      button.type="button";button.dataset.objectId=origin.properties.research_object_id;
      button.setAttribute("aria-pressed","false");
      button.textContent=(index+1)+". "+regionName(origin.geometry.coordinates)
        +" ／ 観測中心 "+origin.geometry.coordinates[1].toFixed(3)+"°N, "
        +origin.geometry.coordinates[0].toFixed(3)+"°E ／ 面積 "
        +formatArea(origin.properties.observed_approx_area_km2);
      button.addEventListener("click",activate);
      list.append(button);
    });
    viewport.append(layer);
    document.getElementById("f4-context").textContent=
      "観測："+jst(slot)+" ／ 研究用基準時刻から"+lead+"分先 ／ 対象"+selectedRows.length+"件";
    status.textContent="保存済み研究表示 · "+selectedRows.length+"件 · 予報ではありません";
    const selected=selectedRows.find(x=>x.origin.properties.research_object_id===selectedId);
    if(selected)select(selected.origin,selected.future);
    else if(selectedRows.length)select(selectedRows[0].origin,selectedRows[0].future);
    else document.getElementById("f4-selected").textContent="この時刻の対象はありません。";
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
      const [dataResponse,mapResponse,cityResponse]=await Promise.all([
        fetch("./data/research/f4_archived_geographic_research.geojson",{cache:"no-store"}),
        fetch("./assets/japan_primary_subdivisions.geojson",{cache:"no-store"}),
        fetch("./data/reference_cities.json",{cache:"no-store"}),
      ]);
      if(!dataResponse.ok || !mapResponse.ok || !cityResponse.ok) throw Error("地理データの取得失敗");
      data=await dataResponse.json();
      const map=await mapResponse.json();
      const cityDoc=await cityResponse.json();
      if(cityDoc.product!=="LPZ_PUBLIC_REFERENCE_CITIES" || cityDoc.scientific_input_allowed!==false || !Array.isArray(cityDoc.cities)) throw Error("参考都市データ契約不一致");
      cities=cityDoc.cities.filter(c=>Number.isFinite(c.lon)&&Number.isFinite(c.lat));
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
      viewport.append(boundaries);
      const cityLayer=el("g",{"class":"f4-cities","pointer-events":"none"});
      for(const city of cities){
        const [x,y]=point([city.lon,city.lat]);
        const g=el("g",{"class":"f4-city"});
        g.append(el("circle",{cx:x,cy:y,r:2.3}));
        const label=el("text",{x:x+5,y:y-5});label.textContent=city.name_ja;
        g.append(label);cityLayer.append(g);
      }
      viewport.append(cityLayer);svg.replaceChildren(viewport);
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
