/* Geographic coordinates and source identities arrive prepared; no survey math here. */
(() => {
  "use strict";
  const freeze = value => { if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); } return value; };
  const baseline = freeze(JSON.parse(document.getElementById("online-map-data").textContent));
  const artifact = baseline.artifact, bundle = baseline.bundle;
  const $ = selector => document.querySelector(selector);
  const status = message => { $('[data-testid="map-status"]').textContent = message; };
  const panel = $('[data-testid="map-source-panel"]');
  const dialog = $("#map-page-dialog");
  let map = null, generation = 0, selected = null, pageTrigger = null, timeout = null;
  let opacity = baseline.view.raster_opacity, mapError = false, pendingToken = "";
  const visibility = Object.fromEntries(Array.from(document.querySelectorAll("[data-map-layer]")).map(el => [el.dataset.mapLayer, true]));
  const styles = {standard: "mapbox://styles/mapbox/standard", "standard-satellite": "mapbox://styles/mapbox/standard-satellite"};
  const collection = features => ({type: "FeatureCollection", features});
  const selectionData = () => collection(artifact.features.filter(feature => feature.properties.call_id === selected));
  const text = (tag, content, parent) => { const element = document.createElement(tag); element.textContent = content; parent.append(element); return element; };
  function showPage(pageId, trigger) {
    pageTrigger = trigger;
    const page = (bundle.pages || []).find(item => item.id === pageId);
    const content = $("#map-page-content"); content.replaceChildren();
    $("#map-page-title").textContent = page ? `Source page ${page.number}: ${page.label || page.id}` : "Source page unavailable";
    if (page && page.image) { const img = document.createElement("img"); img.src = page.image; img.alt = `Original source page ${page.number}`; content.append(img); }
    else text("p", "Source image unavailable; no image was supplied for this page.", content);
    if (page && page.notes) text("p", page.notes, content);
    dialog.showModal(); $("#map-page-close").focus();
  }
  $("#map-page-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => { if (pageTrigger && pageTrigger.isConnected) pageTrigger.focus(); });
  function selectCall(callId) {
    const call = bundle.calls.find(item => item.id === callId); if (!call) return;
    selected = callId; panel.replaceChildren();
    text("h3", call.id, panel); text("p", call.quote || (call.call && call.call.direction_text) || "Source wording unavailable", panel).className = "source-quote";
    text("p", call.reading_status ? `Reading: ${call.reading_status}. ${call.reading_note || ""}` : "Reading status unavailable; no source review was supplied.", panel);
    if (call.source_reference) text("p", `Source reference: ${call.source_reference}`, panel);
    if (call.page_id) text("p", `Source page reference: ${call.page_id}`, panel);
    const feature = artifact.features.find(item => item.properties.call_id === callId);
    text("p", feature ? `Placement: ${feature.properties.placement_status}; geometry: ${feature.properties.completeness || "not supplied"}` : "Geographic course unavailable; original record retained.", panel);
    const page = (bundle.pages || []).find(item => item.id === call.page_id);
    if (!page || !page.image) text("p", "Source image unavailable", panel);
    if (page) {
      const button = text("button", "Open original source page", panel); button.type = "button";
      button.addEventListener("click", () => showPage(call.page_id, button));
    }
    document.querySelectorAll("[data-map-call]").forEach(el => el.setAttribute("aria-pressed", String(el.dataset.mapCall === callId)));
    if (map && map.getSource("review-selection")) map.getSource("review-selection").setData(selectionData());
  }
  document.querySelectorAll("[data-map-call]").forEach(el => { el.setAttribute("aria-pressed", "false"); el.addEventListener("click", () => selectCall(el.dataset.mapCall)); });
  const layerId = kind => `review-${kind}`;
  const rasterId = id => `review-raster-${id}`;
  function ensureReviewLayers() {
    if (!map) return;
    map.setProjection("mercator"); map.setTerrain(null); map.setPitch(0);
    if ($('[data-testid="map-style"]').value === "standard") {
      map.setConfigProperty("basemap", "show3dObjects", false);
    }
    for (const raster of artifact.rasters) {
      const id = rasterId(raster.id);
      if (!map.getSource(id)) map.addSource(id, {type: "image", url: raster.path, coordinates: raster.corners});
      if (!map.getLayer(id)) map.addLayer({id, type: "raster", source: id, paint: {"raster-opacity": opacity, "raster-fade-duration": 0}, layout: {visibility: visibility[`raster-${raster.id}`] ? "visible" : "none"}});
    }
    const specs = [
      ["parcel_context", "line", {"line-color": "#874eac", "line-width": 2}],
      ["recorded_course", "line", {"line-color": "#0069ac", "line-width": 4}],
      ["pob", "circle", {"circle-color": "#167d42", "circle-radius": 6, "circle-stroke-color": "#ffffff", "circle-stroke-width": 2}],
      ["closure_gap", "line", {"line-color": "#bd2333", "line-width": 3, "line-dasharray": [2, 2]}]
    ];
    for (const [kind, type, paint] of specs) {
      const id = layerId(kind);
      if (!map.getSource(id)) map.addSource(id, {type: "geojson", data: collection(artifact.features.filter(feature => feature.properties.kind === kind))});
      if (!map.getLayer(id)) map.addLayer({id, type, source: id, paint, layout: {visibility: visibility[kind] ? "visible" : "none"}});
      if (kind === "recorded_course" && !map.getLayer("review-course-labels")) map.addLayer({id: "review-course-labels", type: "symbol", source: id, layout: {"symbol-placement": "line", "text-field": ["get", "label"], "text-size": 12, visibility: visibility[kind] ? "visible" : "none"}, paint: {"text-color": "#004b7c", "text-halo-color": "#ffffff", "text-halo-width": 2}});
    }
    if (!map.getSource("review-selection")) map.addSource("review-selection", {type: "geojson", data: selectionData()});
    if (!map.getLayer("review-selection")) map.addLayer({id: "review-selection", type: "line", source: "review-selection", paint: {"line-color": "#eeaa22", "line-width": 7}});
    if (!mapError) status("Style loaded. Waiting for visible tiles and source data.");
  }
  function fit() { if (map && artifact.bounds) map.fitBounds([[artifact.bounds[0], artifact.bounds[1]], [artifact.bounds[2], artifact.bounds[3]]], {padding: 40, maxZoom: 20, duration: 0}); }
  $("#map-fit").addEventListener("click", fit);
  document.querySelectorAll("[data-map-layer]").forEach(el => el.addEventListener("change", () => {
    visibility[el.dataset.mapLayer] = el.checked;
    const id = el.dataset.mapLayer.startsWith("raster-") ? rasterId(el.dataset.mapLayer.slice(7)) : layerId(el.dataset.mapLayer);
    if (map && map.getLayer(id)) map.setLayoutProperty(id, "visibility", el.checked ? "visible" : "none");
    if (el.dataset.mapLayer === "recorded_course" && map && map.getLayer("review-course-labels")) map.setLayoutProperty("review-course-labels", "visibility", el.checked ? "visible" : "none");
  }));
  $("#map-opacity").addEventListener("input", event => {
    opacity = Number(event.target.value);
    for (const raster of artifact.rasters) if (map && map.getLayer(rasterId(raster.id))) map.setPaintProperty(rasterId(raster.id), "raster-opacity", opacity);
  });
  $('[data-testid="map-style"]').addEventListener("change", event => { if (map) { mapError = false; status("Loading basemap style."); map.setStyle(styles[event.target.value], {diff: false}); } });
  let sdkPromise = null;
  function loadSDK() {
    if (window.mapboxgl) return Promise.resolve(window.mapboxgl);
    if (sdkPromise) return sdkPromise;
    sdkPromise = new Promise((resolve, reject) => {
      const css = document.createElement("link"); css.rel = "stylesheet"; css.href = baseline.sdk.files["mapbox-gl.css"].url; css.integrity = baseline.sdk.files["mapbox-gl.css"].integrity; css.crossOrigin = "anonymous"; document.head.append(css);
      const script = document.createElement("script"); script.src = baseline.sdk.files["mapbox-gl.js"].url; script.integrity = baseline.sdk.files["mapbox-gl.js"].integrity; script.crossOrigin = "anonymous";
      script.onload = () => window.mapboxgl ? resolve(window.mapboxgl) : reject(new Error("sdk"));
      script.onerror = () => { script.remove(); css.remove(); sdkPromise = null; reject(new Error("sdk")); };
      document.head.append(script);
    });
    return sdkPromise;
  }
  function disconnect(message = "Disconnected. Source records remain available offline.") {
    generation++; pendingToken = ""; clearTimeout(timeout); if (map) { map.remove(); map = null; }
    $("#map-token").value = "";
    if (window.mapboxgl) window.mapboxgl.accessToken = "";
    $('[data-testid="map-connect"]').disabled = false; $('[data-testid="map-disconnect"]').disabled = true; status(message);
  }
  $('[data-testid="map-disconnect"]').addEventListener("click", () => disconnect());
  $("#map-connection").addEventListener("submit", async event => {
    event.preventDefault(); let token = $("#map-token").value.trim(); $("#map-token").value = "";
    if (!/^pk\.[A-Za-z0-9._-]+$/.test(token)) { token = ""; status("Enter a public Mapbox token beginning with pk. Secret tokens are rejected."); return; }
    if (!artifact.bounds) { token = ""; status("Geographic display unavailable. Use the offline evidence view and source records."); return; }
    pendingToken = token; token = ""; mapError = false; const current = ++generation; $('[data-testid="map-connect"]').disabled = true; $('[data-testid="map-disconnect"]').disabled = false;
    status("Loading Mapbox SDK.");
    timeout = setTimeout(() => { if (generation === current) disconnect("Map connection timed out. Check connectivity and retry; source records remain available."); }, 30000);
    try {
      const sdk = await loadSDK(); if (current !== generation) { token = ""; return; }
      if (!sdk.supported()) throw new Error("webgl");
      map = new sdk.Map({container: "online-map", accessToken: pendingToken, style: styles[$('[data-testid="map-style"]').value], projection: "mercator", pitch: 0, maxPitch: 0, attributionControl: true}); pendingToken = ""; token = "";
      map.on("style.load", () => { try { ensureReviewLayers(); } catch (_) { mapError = true; clearTimeout(timeout); status("Map style could not load review layers. Source records remain available."); } });
      map.on("load", fit);
      map.on("idle", () => { if (map && !mapError && map.areTilesLoaded()) { clearTimeout(timeout); status("Map connected; currently visible tiles loaded. Placement and registration remain as recorded."); } });
      map.on("error", () => { mapError = true; clearTimeout(timeout); status("Map data unavailable: authorization, style, or network request failed. Check the public token and connection, or use the offline evidence view."); });
      map.on("webglcontextlost", () => disconnect("WebGL context lost. Retry or use the offline evidence view."));
      map.on("click", event => { if (!map || !map.getLayer("review-recorded_course")) return; const features = map.queryRenderedFeatures(event.point, {layers: ["review-recorded_course"]}); if (features.length) selectCall(features[0].properties.call_id); });
    } catch (_) { token = ""; disconnect("Map unavailable: SDK, WebGL, or connection failed. Retry or use the offline evidence view."); }
  });
})();
