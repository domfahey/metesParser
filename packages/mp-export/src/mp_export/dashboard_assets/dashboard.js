/* Independent, deterministic browser advisory math. No source records are changed. */
"use strict";
function deepFreeze(value) { if (value && typeof value === "object") { Object.values(value).forEach(deepFreeze); Object.freeze(value); } return value; }
function decimal(value) {
  const text = String(value).trim();
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text)) throw Error("Use a finite decimal number.");
  const result = Number(text); if (!Number.isFinite(result)) throw Error("Number is outside the finite range."); return result;
}
function parseAngle(value, maximum = 360) {
  const text = String(value).trim(); let result;
  if (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text)) result = decimal(text);
  else {
    const match = text.match(/^(\d+(?:\.\d+)?)\s*°\s*(?:(\d+(?:\.\d+)?)\s*['′]\s*(?:(\d+(?:\.\d+)?)\s*["″]\s*)?)?$/);
    if (!match) throw Error("Use decimal degrees or D° M′ S″.");
    const degrees = decimal(match[1]), minutes = decimal(match[2] || "0"), seconds = decimal(match[3] || "0");
    if (minutes >= 60 || seconds >= 60 || (match[2] && !Number.isInteger(degrees)) || (match[3] && !Number.isInteger(minutes))) throw Error("DMS components are invalid.");
    result = degrees + minutes / 60 + seconds / 3600;
  }
  if (result < 0 || result > maximum) throw Error("Angle is outside the supported range."); return result;
}
function parseBearing(value) {
  const match = String(value).trim().match(/^([NS])\s*(.*?)\s*([EW])$/i);
  if (!match) { const number = decimal(value); if (number < 0 || number >= 360) throw Error("Azimuth must be at least 0 and below 360 degrees."); return number; }
  const angle = parseAngle(match[2], 90), north = match[1].toUpperCase() === "N", east = match[3].toUpperCase() === "E";
  return (north ? (east ? angle : 360 - angle) : (east ? 180 - angle : 180 + angle)) % 360;
}
const mod = value => ((value % 360) + 360) % 360;
const residual = (a, b) => Math.abs(mod(a - b + 180) - 180);
function relativeHeadings(description) {
  const ids = description.courses.map(c => c.course_id), graph = new Map(ids.map(id => [id, []])); let ambiguous = false;
  const angles = new Map();
  for (const c of description.constraints) {
    let delta = null;
    if (c.kind === "interior" || c.kind === "exterior") {
      if (c.kind === "interior" || c.exterior_convention === "interior_complement") {
        const angle = c.kind === "interior" ? c.angle_deg : 360 - c.angle_deg;
        delta = (180 - angle) * (description.frame.orientation === "cw" ? 1 : -1); angles.set(c.to_course, angle);
      }
    } else if (c.kind === "perpendicular" && c.turn) delta = c.turn === "right" ? 90 : -90;
    else if (c.kind === "parallel" && c.parallel_direction) delta = c.parallel_direction === "same" ? 0 : 180;
    if (delta === null) { ambiguous = true; continue; }
    graph.get(c.from_course).push([c.to_course, delta]); graph.get(c.to_course).push([c.from_course, -delta]);
  }
  const headings = new Map(), anchored = new Set(); let inconsistent = false;
  for (const seed of ids) {
    if (headings.has(seed)) continue;
    const first = seed === ids[0], queue = [seed]; headings.set(seed, first ? mod(description.frame.first_azimuth_deg) : 0);
    for (let index = 0; index < queue.length; index++) {
      const current = queue[index]; if (first) anchored.add(current);
      for (const [next, delta] of graph.get(current)) {
        const expected = mod(headings.get(current) + delta);
        if (!headings.has(next)) { headings.set(next, expected); queue.push(next); }
        else if (residual(headings.get(next), expected) > 1e-8) inconsistent = true;
      }
    }
  }
  const angleSum = angles.size === ids.length ? [...angles.values()].reduce((a, b) => a + b, 0) : null;
  if (angleSum !== null && Math.abs(angleSum - (ids.length - 2) * 180) > 1e-8) inconsistent = true;
  if (inconsistent) throw Error("Inconsistent sourced angular constraints; no geometry is shown.");
  if (ambiguous || anchored.size !== ids.length) throw Error("Unresolved angular constraints; no turn or bearing was invented.");
  return {headings: ids.map(id => headings.get(id)), angleSum};
}
function calculateScenario(calculation, calls) {
  let headings, distances, angleSum = null, origin = [0, 0];
  if (calculation.method === "relative") {
    const description = calculation.relative; if (!description) throw Error("Relative input is unavailable.");
    ({headings, angleSum} = relativeHeadings(description)); origin = description.frame.origin;
    distances = description.courses.map(course => { const call = calls.find(c => c.id === course.course_id); if (!call) throw Error("Missing relative course mapping."); return call.call && call.call.distance_ft; });
  } else {
    const active = calls.filter(c => !(c.call && c.call.is_tie_in));
    if (active.some(c => !c.call || c.call.curve_dir || c.call.curve_type || c.call.is_exception || c.call.is_meander || c.call.is_indefinite || c.call.non_tangent || [c.call.radius_ft,c.call.delta_deg,c.call.arc_length_ft,c.call.chord_length_ft].some(v => v !== null && v !== undefined))) throw Error("Browser geometry supports complete straight boundaries only. Review curves, exceptions, meanders and indefinite calls in the canonical engine.");
    headings = active.map(c => c.call.bearing_azimuth_deg_from_north); distances = active.map(c => c.call.distance_ft);
  }
  if (distances.length < 3 || distances.some(d => typeof d !== "number" || !Number.isFinite(d) || d <= 0) || headings.some(h => typeof h !== "number" || !Number.isFinite(h))) throw Error("Complete finite bearings and positive distances are required.");
  const points = [[0, 0]], deltas = []; let x = 0, y = 0, area = 0, perimeter = 0;
  distances.forEach((distance, index) => { const a = headings[index] * Math.PI / 180, dx = distance * Math.sin(a), dy = distance * Math.cos(a); deltas.push([dx, dy]); x += dx; y += dy; points.push([x, y]); perimeter += distance; });
  for (let i = 0; i < points.length - 1; i++) area += points[i][0] * points[i + 1][1] - points[i + 1][0] * points[i][1];
  const gap = Math.hypot(x, y), translated = points.map(p => [p[0] + origin[0], p[1] + origin[1]]), tolerance = Math.min(1e-6, Math.min(...distances) * 1e-6);
  if (![x, y, gap, perimeter, area, ...translated.flat()].every(Number.isFinite)) throw Error("Geometry exceeds the finite numerical range.");
  translated.forEach((p, i) => { if (Math.max(Math.abs((p[0] - origin[0]) - points[i][0]), Math.abs((p[1] - origin[1]) - points[i][1])) > tolerance) throw Error("Origin loses local coordinate precision."); if (i && Math.max(Math.abs(p[0] - translated[i-1][0] - deltas[i-1][0]), Math.abs(p[1] - translated[i-1][1] - deltas[i-1][1])) > tolerance) throw Error("Translated coordinates lose course precision."); });
  const precision = gap ? perimeter / gap : null;
  return {points: translated, headings, deltas, misclosure_ft: gap, misclosure_x_ft: x, misclosure_y_ft: y, perimeter_ft: perimeter, area_sq_ft: Math.abs(area)/2, precision_denominator: Number.isFinite(precision) ? precision : null, stated_angle_sum_deg: angleSum, expected_angle_sum_deg: (distances.length - 2) * 180, computed_closing_angle_deg: calculation.method === "relative" ? mod(180 - (calculation.relative.frame.orientation === "cw" ? 1 : -1) * (headings[0] - headings.at(-1))) : null};
}
const DashboardMath = deepFreeze({decimal, parseAngle, parseBearing, relativeHeadings, calculateScenario});
if (typeof module !== "undefined" && module.exports) module.exports = DashboardMath;
if (typeof document !== "undefined") {
  const baseline = deepFreeze(JSON.parse(document.getElementById("dashboard-data").textContent));
  const bundle = baseline.bundle, selector = document.getElementById("calculation-select"), scenarioSelect = document.getElementById("scenario-select"), parcelSelect = document.getElementById("parcel-select");
  const byId = id => document.getElementById(id), clone = value => JSON.parse(JSON.stringify(value));
  let working = [], selectedCalculation, selectedSourceCalculation, previousFocus, scenarioIssue = "";
  const fmt = (value, digits = 3) => typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "Unavailable";
  const text = (tag, value) => { const node = document.createElement(tag); node.textContent = value; return node; };
  function refreshOptions() {
    const old = selector.value; selector.replaceChildren();
    bundle.calculations.filter(c => parcelSelect.value === "all" || bundle.occurrences.find(o => o.id === c.occurrence_id).parcel_id === parcelSelect.value).forEach(c => { const o = bundle.occurrences.find(o => o.id === c.occurrence_id), option = text("option", `${o.version_label} · ${o.id} · ${c.method}`); option.value = c.id; selector.append(option); });
    if ([...selector.options].some(o => o.value === old)) selector.value = old;
    reset();
  }
  function reset() {
    selectedSourceCalculation = bundle.calculations.find(c => c.id === selector.value);
    scenarioSelect.replaceChildren(); const option = text("option", "Record values"); option.value = ""; scenarioSelect.append(option);
    if (!selectedSourceCalculation) { byId("call-body").replaceChildren(); byId("scenario-status").textContent = "No calculations available for this parcel."; byId("scenario-metrics").replaceChildren(); byId("plot").replaceChildren(); return; }
    bundle.scenarios.filter(s => s.calculation_id === selectedSourceCalculation.id).forEach(s => { const option = text("option", s.label); option.value = s.id; scenarioSelect.append(option); });
    applyPreset();
  }
  function applyPreset() {
    selectedCalculation = clone(selectedSourceCalculation); working = clone(bundle.calls.filter(c => c.occurrence_id === selectedCalculation.occurrence_id));
    const preset = bundle.scenarios.find(s => s.id === scenarioSelect.value); let unsupported = "";
    if (preset) for (const edit of preset.edits) {
      const item = working.find(c => c.id === edit.call_id); if (!item || !item.call) { unsupported = "Scenario targets an unresolved recorded call."; continue; }
      if (edit.distance_ft !== null && edit.distance_ft !== undefined) item.call.distance_ft = edit.distance_ft;
      if (edit.bearing_azimuth_deg_from_north !== null && edit.bearing_azimuth_deg_from_north !== undefined) {
        if (selectedCalculation.method === "relative") unsupported = "A recorded-bearing substitution cannot establish a local angular constraint.";
        else item.call.bearing_azimuth_deg_from_north = edit.bearing_azimuth_deg_from_north;
      }
      if (edit.interior_angle_deg !== null && edit.interior_angle_deg !== undefined) {
        const matches = selectedCalculation.relative ? selectedCalculation.relative.constraints.filter(c => c.to_course === edit.call_id && c.kind === "interior") : [];
        if (matches.length !== 1) unsupported = "Angle edit has no unique explicit interior constraint."; else matches[0].angle_deg = edit.interior_angle_deg;
      }
    }
    byId("scenario-rationale").textContent = preset ? preset.edits.map(e => `${e.call_id}: ${e.rationale}`).join(" · ") : "Record values copied into a separate advisory working scenario.";
    scenarioIssue = unsupported; renderCalls(); recompute();
  }
  function renderCalls() {
    const body = byId("call-body"); body.replaceChildren();
    working.forEach((item, index) => {
      const row = document.createElement("tr"); if (item.reading_status !== "certain") row.className = "uncertain";
      row.append(text("td", `${index + 1} · ${item.id}`), text("td", item.quote));
      const distanceCell = document.createElement("td"), bearingCell = document.createElement("td");
      const fields = [[distanceCell, "distance_ft", item.call && item.call.distance_ft, "Distance in feet"], [bearingCell, "bearing_azimuth_deg_from_north", item.call && item.call.bearing_azimuth_deg_from_north, "Azimuth or quadrant bearing"]];
      fields.forEach(([cell, field, value, label]) => {
        if (!item.call || (field === "bearing_azimuth_deg_from_north" && selectedCalculation.method === "relative")) { cell.textContent = field === "bearing_azimuth_deg_from_north" ? (item.call && item.call.bearing_azimuth_deg_from_north !== null ? `Recorded ${item.call.bearing_azimuth_deg_from_north}°; local heading derived separately` : "Local heading derived; recorded bearing remains unknown") : "Unresolved"; return; }
        const input = document.createElement("input"); input.value = value === null ? "" : value; input.setAttribute("aria-label", `${item.id}: ${label}`); input.dataset.field = field; input.dataset.index = index; const original = bundle.calls.find(c => c.id === item.id).call[field];
        if (value !== original) input.classList.add("edited"); input.addEventListener("input", () => {
          try { const number = field === "distance_ft" ? decimal(input.value) : parseBearing(input.value); if (field === "distance_ft" && number <= 0) throw Error("Distance must be positive."); item.call[field] = number; input.setAttribute("aria-invalid", "false"); input.classList.toggle("edited", number !== original); input.title = ""; }
          catch (error) { input.setAttribute("aria-invalid", "true"); input.title = error.message; }
          recompute();
        }); cell.append(input);
      });
      row.append(distanceCell, bearingCell, text("td", item.stated_angle_text || "Not stated"), text("td", "—"), text("td", "—")); body.append(row);
    });
  }
  function recompute() {
    const metrics = byId("scenario-metrics"); metrics.replaceChildren(); byId("plot").replaceChildren();
    byId("closing-angle-detail").replaceChildren();
    try {
      if (scenarioIssue) throw Error(scenarioIssue); if (byId("call-body").querySelector('[aria-invalid="true"]')) throw Error("Correct the highlighted invalid input before calculating.");
      const result = calculateScenario(selectedCalculation, working);
      byId("scenario-status").textContent = `Browser advisory · ${selectedCalculation.method === "relative" ? "explicit local-angle constraints" : "straight recorded bearings"} · ${selectedCalculation.frame.name} · not engine verification`;
      const local = selectedCalculation.frame.basis === "arbitrary_local";
      [["Misclosure (ft)",result.misclosure_ft],[local ? "Local ΔX (ft)" : "ΔE (ft)",result.misclosure_x_ft],[local ? "Local ΔY (ft)" : "ΔN (ft)",result.misclosure_y_ft],["Perimeter (ft)",result.perimeter_ft],["Provisional area (sq ft)",result.area_sq_ft],["Angle sum (degrees)",result.stated_angle_sum_deg]].forEach(([label, value]) => { const node = document.createElement("div"); node.className = "metric"; node.append(text("strong", fmt(value)), text("span", label)); metrics.append(node); });
      const precision = document.createElement("div"); precision.className = "metric"; precision.append(text("strong", result.precision_denominator === null ? "Unavailable / unbounded" : `1:${fmt(result.precision_denominator, 0)}`), text("span", "Precision denominator")); metrics.append(precision);
      const closing = selectedCalculation.relative ? selectedCalculation.relative.constraints.filter(c => c.to_course === selectedCalculation.relative.courses[0].course_id) : [];
      byId("closing-angle-detail").append(text("p", `Stated closing relation: ${closing.length ? closing.map(c => `${c.kind}: ${c.angle_deg === null ? "angle not numeric" : fmt(c.angle_deg) + "°"} — ${c.source.quote}`).join("; ") : "Not supplied"}`), text("p", `Computed heading-based closing angle: ${fmt(result.computed_closing_angle_deg)}${result.computed_closing_angle_deg === null ? "" : "°"}. Expected complete angle sum: ${fmt(result.expected_angle_sum_deg)}°.`));
      const active = working.filter(c => !(c.call && c.call.is_tie_in));
      working.forEach((item, index) => { const j = active.findIndex(c => c.id === item.id), cells = byId("call-body").rows[index].cells; cells[5].textContent = j >= 0 ? fmt(result.headings[j]) + "°" : "Tie-in excluded"; cells[6].textContent = j >= 0 ? `${fmt(result.deltas[j][0])} / ${fmt(result.deltas[j][1])}` : "—"; });
      plot(result);
    } catch (error) { byId("scenario-status").textContent = `Unresolved browser scenario: ${error.message}`; [...byId("call-body").rows].forEach(row => { row.cells[5].textContent = "—"; row.cells[6].textContent = "—"; }); }
  }
  function plot(result) {
    const svg = byId("plot"), ns = "http://www.w3.org/2000/svg", points = result.points;
    const xs = points.map(p => p[0]), ys = points.map(p => p[1]), minX = Math.min(...xs), maxY = Math.max(...ys), width = Math.max(...xs) - minX, height = maxY - Math.min(...ys), scale = 260 / Math.max(width, height, 1);
    const convert = p => [60 + (p[0] - minX) * scale, 35 + (maxY - p[1]) * scale];
    const add = (tag, attributes) => { const node = document.createElementNS(ns, tag); Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value)); svg.append(node); return node; };
    add("polyline", {points: points.map(p => convert(p).join(",")).join(" "), class: "boundary"});
    const first = convert(points[0]), last = convert(points.at(-1)); add("line", {x1: last[0], y1: last[1], x2: first[0], y2: first[1], class: "gap"});
    points.slice(0,-1).forEach((p, i) => { const [x,y] = convert(p); add("circle", {cx:x,cy:y,r:3}); add("text", {x:x+6,y:y-6}).textContent = i === 0 ? "POB / 1" : String(i+1); });
    add("text", {x:12,y:325}).textContent = selectedCalculation.frame.basis === "arbitrary_local" ? "↑ Local +Y · arbitrary frame" : "↑ North · recorded bearing basis";
    const scaleLength = 100 * scale; if (scaleLength <= 280) { add("line", {x1:60,y1:345,x2:60+scaleLength,y2:345,class:"boundary"}); add("text",{x:60,y:365}).textContent = "100 ft"; } else add("text",{x:12,y:365}).textContent = "Plot fitted to boundary · units: feet";
  }
  selector.addEventListener("change", reset); parcelSelect.addEventListener("change", refreshOptions); scenarioSelect.addEventListener("change", applyPreset); byId("reset-record").addEventListener("click", reset); refreshOptions();
  document.querySelectorAll("[data-copy-target]").forEach(button => button.addEventListener("click", async () => {
    const content = byId(button.dataset.copyTarget).textContent; const status = button.parentElement.querySelector(".copy-status");
    try { if (!navigator.clipboard || !navigator.clipboard.writeText) throw Error("Clipboard unavailable"); await navigator.clipboard.writeText(content); status.textContent = "Copied."; }
    catch (_) { let area = button.parentElement.querySelector("textarea.copy-fallback"); if (!area) { area = document.createElement("textarea"); area.className = "copy-fallback"; area.setAttribute("aria-label", "Selected text for manual copying"); button.parentElement.append(area); } area.value = content; area.focus(); area.select(); status.textContent = "Clipboard unavailable. Selected text is ready for manual copy."; }
  }));
  const viewer = byId("source-viewer"); let pageIndex = 0, viewerImageURL = null;
  document.querySelectorAll("img").forEach(image => image.addEventListener("error", () => { image.hidden = true; let message = image.nextElementSibling; if (!message || !message.classList.contains("image-error")) { message = text("p", "Image could not be decoded. The source ledger reference is preserved."); message.className = "image-error warning"; image.after(message); } }));
  function showPage(index) {
    pageIndex = Math.max(0, Math.min(index, bundle.pages.length - 1)); const page = bundle.pages[pageIndex]; if (!page) return;
    const doc = bundle.documents.find(d => d.id === page.document_id); byId("viewer-label").textContent = `${doc.label} · page ${page.number} · ${page.label || page.id} · ${page.reading_status}`;
    const image = byId("viewer-image"), link = byId("open-image"); image.hidden = !page.image; byId("viewer-missing").hidden = Boolean(page.image); link.hidden = !page.image;
    viewer.querySelectorAll(".image-error").forEach(message => message.remove());
    if (viewerImageURL) { URL.revokeObjectURL(viewerImageURL); viewerImageURL = null; }
    if (page.image) {
      image.src = page.image; image.alt = `${doc.label}, source page ${page.number}`; link.href = page.image;
      if (typeof Blob !== "undefined" && typeof URL.createObjectURL === "function") {
        const [metadata, encoded] = page.image.split(","), bytes = Uint8Array.from(atob(encoded), char => char.charCodeAt(0));
        viewerImageURL = URL.createObjectURL(new Blob([bytes], {type: metadata.slice(5, metadata.indexOf(";"))})); link.href = viewerImageURL;
      }
    } else { image.removeAttribute("src"); link.removeAttribute("href"); }
    byId("viewer-prev").disabled = pageIndex === 0; byId("viewer-next").disabled = pageIndex === bundle.pages.length - 1;
  }
  document.querySelectorAll("[data-page-id]").forEach(button => button.addEventListener("click", () => { previousFocus = document.activeElement; showPage(bundle.pages.findIndex(p => p.id === button.dataset.pageId)); viewer.showModal(); byId("viewer-close").focus(); }));
  byId("viewer-prev").addEventListener("click", () => showPage(pageIndex - 1)); byId("viewer-next").addEventListener("click", () => showPage(pageIndex + 1)); byId("viewer-close").addEventListener("click", () => viewer.close()); viewer.addEventListener("close", () => { if (previousFocus) previousFocus.focus(); });
  viewer.addEventListener("keydown", event => { if (event.key === "ArrowLeft") { event.preventDefault(); showPage(pageIndex - 1); } if (event.key === "ArrowRight") { event.preventDefault(); showPage(pageIndex + 1); } if (event.key === "Escape") { event.preventDefault(); viewer.close(); } });
}
