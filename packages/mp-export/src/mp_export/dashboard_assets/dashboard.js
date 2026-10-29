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
function accurateSum(values) {
  let total = 0, correction = 0;
  for (const value of values) {
    const next = total + value;
    correction += Math.abs(total) >= Math.abs(value) ? (total-next)+value : (value-next)+total;
    total = next;
  }
  return total + correction;
}
function sensitivityRanks(values) {
  const close = (a,b) => Math.abs(a-b) <= Math.max(1e-12, 1e-10 * Math.max(Math.abs(a),Math.abs(b)));
  const groups = [];
  for (const value of values.slice().sort((a,b)=>b-a)) if (!groups.length || !close(value,groups.at(-1))) groups.push(value);
  return values.map(value => groups.findIndex(group=>close(value,group))+1);
}
function binaryUlp(value) {
  let exponent = Math.floor(Math.log2(value));
  // log2 can round a value immediately below 2^k up to the integer k.
  if (value < Math.pow(2,exponent)) exponent -= 1;
  return Math.max(Number.MIN_VALUE,Math.pow(2,exponent-52));
}
function diagnoseScenario(calculation, calls) {
  const unavailable = (availability, reason) => ({availability, residual:null, sensitivities:[], excluded_call_ids:[], ranking_available:false, limitations:[reason]});
  if (calculation.method !== 'canonical') return unavailable('unsupported','Relative constraints are unsupported by canonical straight-bearing diagnosis.');
  const records = calls.filter(c=>c.occurrence_id === calculation.occurrence_id);
  if (records.some(c=>!c.call)) return unavailable('incomplete','Unknown source calls block diagnosis; no partial residual was manufactured.');
  const active = records.filter(c=>!c.call.is_tie_in), excluded = records.filter(c=>c.call.is_tie_in).map(c=>c.id);
  if (active.some(c=>c.call.curve_dir || c.call.curve_type || c.call.non_tangent || c.call.radial_bearing || c.call.chord_bearing || c.call.radius_ft !== null && c.call.radius_ft !== undefined || c.call.is_exception || c.call.is_meander)) return {...unavailable('unsupported','Curves, meanders and exception boundaries are unsupported; no partial residual was manufactured.'),excluded_call_ids:excluded};
  if (active.length < 3 || active.some(c=>c.call.is_indefinite || !Number.isFinite(c.call.bearing_azimuth_deg_from_north) || !Number.isFinite(c.call.distance_ft) || c.call.distance_ft <= 0)) return {...unavailable('incomplete','At least three complete finite straight boundary courses are required.'),excluded_call_ids:excluded};
  const derivatives = active.map(item=>{
    const d=item.call.distance_ft, a=item.call.bearing_azimuth_deg_from_north*Math.PI/180, sine=Math.sin(a), cosine=Math.cos(a), factor=Math.PI/648000;
    return {call_id:item.id, distance_derivative:{east:sine,north:cosine}, angle_derivative_per_radian:{east:d*cosine,north:-d*sine}, angle_derivative_per_arcsecond:{east:d*cosine*factor,north:-d*sine*factor}};
  });
  const east=accurateSum(active.map((c,i)=>c.call.distance_ft*derivatives[i].distance_derivative.east)), north=accurateSum(active.map((c,i)=>c.call.distance_ft*derivatives[i].distance_derivative.north));
  const magnitude=Math.hypot(east,north), perimeter=accurateSum(active.map(c=>c.call.distance_ft));
  if (![east,north,magnitude,perimeter].every(Number.isFinite)) return {...unavailable('unsupported','Calculation exceeds finite arithmetic limits.'),excluded_call_ids:excluded};
  const threshold=32*binaryUlp(perimeter), ranking=magnitude>threshold;
  const unitEast=ranking?east/magnitude:0, unitNorth=ranking?north/magnitude:0;
  const distance=ranking?derivatives.map(row=>Math.abs(accurateSum([row.distance_derivative.east*unitEast,row.distance_derivative.north*unitNorth]))):[];
  const angle=ranking?derivatives.map(row=>Math.abs(accurateSum([row.angle_derivative_per_radian.east*unitEast,row.angle_derivative_per_radian.north*unitNorth]))*Math.PI/648000):[];
  if (![...distance,...angle].every(Number.isFinite)) return {...unavailable('unsupported','Calculation exceeds finite arithmetic limits.'),excluded_call_ids:excluded};
  const dr=sensitivityRanks(distance), ar=sensitivityRanks(angle);
  return {availability:'supported',residual:{east_ft:east,north_ft:north,magnitude_ft:magnitude},ranking_available:ranking,numerical_zero_threshold_ft:threshold,excluded_call_ids:excluded,limitations:ranking?[]:['Residual direction ranking unavailable at numerical zero residual.'],sensitivities:derivatives.map((row,i)=>({...row,distance_projection_abs:ranking?distance[i]:null,angle_projection_abs_per_arcsecond:ranking?angle[i]:null,distance_rank:ranking?dr[i]:null,angle_rank:ranking?ar[i]:null}))};
}

function scenePoints(points, placement, nativeUnits = "unknown_ft", sceneUnits = "unknown_ft") {
  if (!placement) return points.map(point => point.slice());
  const meters = {international_ft: .3048, us_survey_ft: 1200/3937, m: 1};
  if ((nativeUnits === 'unknown_ft') !== (sceneUnits === 'unknown_ft')) throw Error('Unknown foot definition cannot establish map alignment.');
  const factor = nativeUnits === 'unknown_ft' ? 1 : meters[nativeUnits] / meters[sceneUnits];
  const a = mod(placement.rotation_deg) * Math.PI/180, c = Math.cos(a), s = Math.sin(a);
  return points.map(([x,y]) => [(c*x+s*y)*factor+placement.translation[0],(-s*x+c*y)*factor+placement.translation[1]]);
}
const DashboardMath = deepFreeze({scenePoints, decimal, parseAngle, parseBearing, relativeHeadings, calculateScenario, diagnoseScenario});
if (typeof module !== "undefined" && module.exports) module.exports = DashboardMath;
if (typeof document !== "undefined") {
  const baseline = deepFreeze(JSON.parse(document.getElementById("dashboard-data").textContent));
  const bundle = baseline.bundle, selector = document.getElementById("calculation-select"), scenarioSelect = document.getElementById("scenario-select"), parcelSelect = document.getElementById("parcel-select");
  const byId = id => document.getElementById(id), clone = value => JSON.parse(JSON.stringify(value));
  let working = [], selectedCalculation, selectedSourceCalculation, previousFocus, scenarioIssue = "";
  const fmt = (value, digits = 3) => typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "Unavailable";
  const text = (tag, value) => { const node = document.createElement(tag); node.textContent = value; return node; };
  const drafts = new MetesRevisionDrafts.RevisionDraftStore(baseline.revision_template, {
    getItem: key => window.localStorage.getItem(key),
    setItem: (key, value) => window.localStorage.setItem(key, value),
  });
  function draftIdentity(item) {
    const occurrence = bundle.occurrences.find(o => o.id === item.occurrence_id);
    const page = bundle.pages.find(p => p.id === item.page_id);
    return {call_id:item.id, occurrence_id:item.occurrence_id, tract_id:occurrence.parcel_id, document_id:page.document_id};
  }
  function draftStatus(message = '') {
    byId('revision-status').textContent = message || (drafts.persisted ?
      `${drafts.recovered ? 'Recovered draft. ' : ''}Draft saved in this browser; not published or verified.` : drafts.error);
  }
  function draftDescription() {
    const saved = drafts.snapshot(); byId('revision-label').value = saved.label; byId('revision-rationale').value = saved.rationale; draftStatus();
  }
  for (const id of ['revision-label','revision-rationale']) byId(id).addEventListener('input', () => {
    drafts.setDescription(byId('revision-label').value, byId('revision-rationale').value); draftStatus();
  });
  byId('revision-download').addEventListener('click', () => {
    const saved = drafts.snapshot(), url = URL.createObjectURL(new Blob([JSON.stringify(saved,null,2)+'\n'], {type:'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = saved.id + '.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    draftStatus('Draft download prepared. Cowork must validate and publish it with the original bundle; no geometry status was changed.');
  });
  byId('revision-import').addEventListener('change', async event => {
    const file = event.target.files[0], version = drafts.version; if (!file) return;
    try { const saved = JSON.parse(await file.text()); drafts.importRevision(saved,version); draftDescription(); applyPreset(); }
    catch (error) { draftStatus('Draft was not loaded: '+error.message); }
    event.target.value = '';
  });
  window.addEventListener('beforeunload', event => {
    if (!drafts.persisted && drafts.version > 0) { event.preventDefault(); event.returnValue = ''; }
  });
  draftDescription();
  const structuredEditor = MetesStructuredEditor.mount({
    container:byId('structured-editor-fields'),store:drafts,bundle,
    getCalculation:()=>selectedSourceCalculation,
    onChange:()=>applyPreset(false),onStatus:draftStatus,
  });
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
  function applyPreset(refreshEditor = true) {
    if (!selectedSourceCalculation) { structuredEditor.refresh(); return; }
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
    const saved = drafts.snapshot(), tract = saved.tracts.find(t => t.occurrence_id === selectedCalculation.occurrence_id);
    const originalOrder=baseline.revision_template.tracts.find(t=>t.occurrence_id===selectedCalculation.occurrence_id).call_order;
    if (tract && JSON.stringify(tract.call_order)!==JSON.stringify(originalOrder)) unsupported='Call order or inventory changed. Download the draft for fresh shared geometry and a revision view.';
    if (tract && tract.action === 'remove') unsupported = 'This tract is removed in the draft. Publish the revision to inspect its resulting inventory.';
    for (const edit of saved.edits.filter(e => e.occurrence_id === selectedCalculation.occurrence_id)) {
      if (edit.structured_input) { unsupported='Structured call edits are retained exactly. Download the draft for fresh shared geometry and a revision view.'; continue; }
      if (edit.action === 'remove') { unsupported = 'A course removal is retained in this draft. Publish the revision to regenerate its geometry.'; continue; }
      if (edit.raw_fields.interior_angle_deg !== undefined) {
        const matches = selectedCalculation.relative ? selectedCalculation.relative.constraints.filter(c => c.to_course === edit.call_id && c.kind === 'interior') : [];
        try { if (matches.length !== 1) throw Error('No unique sourced interior constraint for this draft.'); matches[0].angle_deg = parseAngle(edit.raw_fields.interior_angle_deg); }
        catch (error) { unsupported = error.message; }
      }
    }
    byId("scenario-rationale").textContent = preset ? preset.edits.map(e => `${e.call_id}: ${e.rationale}`).join(" · ") : "Record values copied into a separate advisory working scenario.";
    scenarioIssue = unsupported; renderCalls(); recompute();
    if(refreshEditor)structuredEditor.refresh();
  }
  function renderCalls() {
    const body = byId("call-body"); body.replaceChildren();
    working.forEach((item, index) => {
      const retainedEdit=drafts.snapshot().edits.find(e=>e.call_id===item.id);
      const useStructured=retainedEdit && (retainedEdit.structured_input || retainedEdit.action==='remove');
      const row = document.createElement("tr"); if (item.reading_status !== "certain") row.className = "uncertain";
      const courseCell=text('td',''), sourceButton=text('button',`${index+1} · ${item.id}`); sourceButton.type='button'; sourceButton.addEventListener('click',()=>selectSourceCall(item.id)); courseCell.append(sourceButton);
      const sourceCell = text('td',item.quote), noteLabel = text('label','Draft note'), note = document.createElement('textarea');
      note.rows = 2; note.setAttribute('aria-label',`${item.id}: Draft note`); note.value = drafts.raw(item.id,'notes') ?? '';
      if(useStructured){note.disabled=true;note.title='Use the structured call editor for this draft.';}
      note.addEventListener('input', () => { drafts.setField(draftIdentity(item),'notes',note.value); draftStatus(); });
      noteLabel.append(note); sourceCell.append(noteLabel); row.append(courseCell,sourceCell);
      const distanceCell = document.createElement("td"), bearingCell = document.createElement("td");
      const fields = [[distanceCell, "distance_ft", item.call && item.call.distance_ft, "Distance in feet"], [bearingCell, "bearing_azimuth_deg_from_north", item.call && item.call.bearing_azimuth_deg_from_north, "Azimuth or quadrant bearing"]];
      fields.forEach(([cell, field, value, label]) => {
        if (!item.call || (field === "bearing_azimuth_deg_from_north" && selectedCalculation.method === "relative")) { cell.textContent = field === "bearing_azimuth_deg_from_north" ? (item.call && item.call.bearing_azimuth_deg_from_north !== null ? `Recorded ${item.call.bearing_azimuth_deg_from_north}°; local heading derived separately` : "Local heading derived; recorded bearing remains unknown") : "Unresolved"; return; }
        const input = document.createElement("input"); input.value = drafts.raw(item.id,field) ?? (value === null ? "" : value); input.setAttribute("aria-label", `${item.id}: ${label}`); input.dataset.field = field; input.dataset.index = index; const original = bundle.calls.find(c => c.id === item.id).call[field];
        if(useStructured){input.disabled=true;input.title='Use the structured call editor for this draft.';}
        const readInput = () => {
          try { const number = field === "distance_ft" ? decimal(input.value) : parseBearing(input.value); if (field === "distance_ft" && number <= 0) throw Error("Distance must be positive."); item.call[field] = number; input.setAttribute("aria-invalid", "false"); input.classList.toggle("edited", number !== original); input.title = ""; }
          catch (error) { input.setAttribute("aria-invalid", "true"); input.title = error.message; }
        };
        readInput(); input.addEventListener("input", () => {
          drafts.setField(draftIdentity(item),field,input.value); draftStatus(); readInput();
          recompute();
        }); cell.append(input);
      });
      row.append(distanceCell, bearingCell, text("td", item.stated_angle_text || "Not stated"), text("td", "—"), text("td", "—")); body.append(row);
    });
  }

  function renderDiagnosis(container, diagnosis) {
    container.replaceChildren();
    const value = diagnosis && diagnosis.baseline ? diagnosis.baseline : diagnosis;
    if (!value) { container.append(text('p','Diagnosis unavailable.')); return; }
    container.append(text('p',`Availability: ${value.availability}.`));
    if (value.residual) container.append(text('p',`Endpoint residual: ${fmt(value.residual.magnitude_ft)} ft · ΔE ${fmt(value.residual.east_ft)} ft · ΔN ${fmt(value.residual.north_ft)} ft.`));
    for (const limitation of value.limitations || []) container.append(text('p',limitation));
    if ((value.excluded_call_ids || []).length) container.append(text('p',`Commencement tie-ins excluded: ${value.excluded_call_ids.join(', ')}.`));
    if (!value.sensitivities || !value.sensitivities.length) return;
    const wrap=text('div',''); wrap.className='table-wrap'; const table=text('table',''), head=text('thead',''), header=text('tr','');
    for (const label of ['Source course','Distance rank / |projection| (ft/ft)','Bearing rank / |projection| (ft/arcsecond)']) header.append(text('th',label));
    head.append(header); table.append(head); const body=text('tbody','');
    for (const item of value.sensitivities) {
      const row=text('tr',''); row.dataset.diagnosticCall=item.call_id;
      row.dataset.distanceRank=item.distance_rank === null ? '' : item.distance_rank;
      row.dataset.angleRank=item.angle_rank === null ? '' : item.angle_rank;
      const source=bundle.calls.find(c=>c.id===item.call_id), cell=text('td',''), button=text('button',item.call_id);
      button.type='button'; button.dataset.diagnosticSource=item.call_id; button.addEventListener('click',()=>selectSourceCall(item.call_id)); cell.append(button);
      if (source && source.reading_status !== 'certain') cell.append(text('p',`Uncertain source: ${source.reading_note}`));
      row.append(cell,text('td',item.distance_rank === null ? 'Ranking unavailable' : `${item.distance_rank} / ${fmt(item.distance_projection_abs,6)}`),text('td',item.angle_rank === null ? 'Ranking unavailable' : `${item.angle_rank} / ${fmt(item.angle_projection_abs_per_arcsecond,8)}`)); body.append(row);
      for (const parameter of item.curve_parameters || []) {
        const detail = text('tr',''); detail.dataset.curveParameter = parameter.parameter;
        const label = text('td',`${item.call_id} · ${parameter.parameter}`);
        const value = text('td',`Derivative ΔE ${fmt(parameter.derivative.east,8)}, ΔN ${fmt(parameter.derivative.north,8)} ${parameter.derivative_units}; rank ${parameter.rank ?? 'unavailable'}; |projection| ${fmt(parameter.projection_abs,8)}`);
        const constraint = text('td',`Fixed: ${parameter.fixed_parameters.join(', ')}. ${parameter.constraint}`);
        detail.append(label,value,constraint); body.append(detail);
      }
    }
    table.append(body); wrap.append(table); container.append(wrap);
  }
  function updateDiagnoses() {
    const original=baseline.diagnostics.find(d=>d.calculation_id===selector.value);
    renderDiagnosis(byId('baseline-diagnostics'),original);
    const invalid=scenarioIssue || (byId('call-body').querySelector('[aria-invalid="true"]') ? 'Correct highlighted invalid input before diagnosis.' : '');
    renderDiagnosis(byId('scenario-diagnostics'),invalid ? {availability:'incomplete',limitations:[invalid]} : diagnoseScenario(selectedCalculation,working));
  }
  function recompute() {
    updateDiagnoses();
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
      plot(result); enhanceRecordPlot(result);
    } catch (error) { enhanceRecordPlot(null); byId("scenario-status").textContent = `Unresolved browser scenario: ${error.message}`; [...byId("call-body").rows].forEach(row => { row.cells[5].textContent = "—"; row.cells[6].textContent = "—"; }); }
  }
  function plot(result) {
    const svg = byId("plot"), ns = "http://www.w3.org/2000/svg", points = result.points;
    const xs = points.map(p => p[0]), ys = points.map(p => p[1]), minX = Math.min(...xs), maxY = Math.max(...ys), width = Math.max(...xs) - minX, height = maxY - Math.min(...ys), scale = 260 / Math.max(width, height, 1);
    const convert = p => [60 + (p[0] - minX) * scale, 35 + (maxY - p[1]) * scale];
    const add = (tag, attributes) => { const node = document.createElementNS(ns, tag); Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value)); svg.append(node); return node; };
    add("polyline", {points: points.map(p => convert(p).join(",")).join(" "), class: "boundary"});
    const first = convert(points[0]), last = convert(points.at(-1)); add("line", {x1: last[0], y1: last[1], x2: first[0], y2: first[1], class: "gap"});
    points.slice(0,-1).forEach((p, i) => { const [x,y] = convert(p); add("circle", {cx:x,cy:y,r:3}); add("text", {x:x+6,y:y-6}).textContent = i === 0 ? "POB / 1" : String(i+1); });
    add("text", {x:12,y:325}).textContent = selectedCalculation.frame.basis === "arbitrary_local" ? "↑ Local +Y · arbitrary frame" : "↑ Local +Y · recorded bearing basis; geographic north unestablished";
    const scaleLength = 100 * scale; if (scaleLength <= 280) { add("line", {x1:60,y1:345,x2:60+scaleLength,y2:345,class:"boundary"}); add("text",{x:60,y:365}).textContent = "100 ft"; } else add("text",{x:12,y:365}).textContent = "Plot fitted to boundary · units: feet";
  }
  selector.addEventListener("change", reset); parcelSelect.addEventListener("change", refreshOptions);
  scenarioSelect.addEventListener('change', () => {
    drafts.resetOccurrence(selectedSourceCalculation.occurrence_id);
    const preset = bundle.scenarios.find(s => s.id === scenarioSelect.value);
    if (preset) for (const edit of preset.edits) {
      const item = bundle.calls.find(c => c.id === edit.call_id); if (!item) continue;
      for (const field of ['distance_ft','bearing_azimuth_deg_from_north','interior_angle_deg']) {
        if (edit[field] !== null && edit[field] !== undefined) drafts.setField(draftIdentity(item),field,String(edit[field]));
      }
      drafts.setContext(draftIdentity(item),edit.rationale,edit.evidence_ids);
    }
    draftStatus(); applyPreset();
  });
  byId('reset-record').addEventListener('click', () => { if(selectedSourceCalculation)drafts.resetOccurrence(selectedSourceCalculation.occurrence_id); draftStatus(); reset(); });
  document.querySelectorAll("[data-copy-target]").forEach(button => button.addEventListener("click", async () => {
    const content = byId(button.dataset.copyTarget).textContent; const status = button.parentElement.querySelector(".copy-status");
    try { if (!navigator.clipboard || !navigator.clipboard.writeText) throw Error("Clipboard unavailable"); await navigator.clipboard.writeText(content); status.textContent = "Copied."; }
    catch (_) { let area = button.parentElement.querySelector("textarea.copy-fallback"); if (!area) { area = document.createElement("textarea"); area.className = "copy-fallback"; area.setAttribute("aria-label", "Selected text for manual copying"); button.parentElement.append(area); } area.value = content; area.focus(); area.select(); status.textContent = "Clipboard unavailable. Selected text is ready for manual copy."; }
  }));
  const viewer = byId("source-viewer"); let pageIndex = 0, viewerImageURL = null;
  document.querySelectorAll("img").forEach(image => image.addEventListener("error", () => { image.hidden = true; let message = image.nextElementSibling; if (!message || !message.classList.contains("image-error")) { message = text("p", "Image could not be decoded. The source ledger reference is preserved."); message.className = "image-error warning"; image.after(message); } }));
  function showPage(index) {
    viewer.querySelectorAll(".selected-source-detail").forEach(node => node.remove());
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
  function currentRecordPlot() { return [...document.querySelectorAll('[data-baseline-plot]')].find(node => node.dataset.baselinePlot === selector.value); }
  function updateScale(svg) {
    const box = svg.viewBox.baseVal, width = svg.getBoundingClientRect().width;
    const height = svg.getBoundingClientRect().height, pixelsPerUnit = Math.min(width / box.width, height / box.height);
    const target = 90 / pixelsPerUnit, exponent = Math.pow(10, Math.floor(Math.log10(target)));
    const length = [1, 2, 5, 10].map(v => v * exponent).find(v => v >= target) || exponent * 10;
    const label = svg.parentElement.querySelector('.plot-scale');
    label.replaceChildren(); const bar = document.createElement('span'); bar.className = 'scale-bar'; bar.style.width = `${length * pixelsPerUnit}px`; label.append(bar, document.createTextNode(`${Number(length.toPrecision(3))} ${svg.dataset.units} · viewport scale`));
    svg.dataset.scaleLength = length; svg.dataset.scalePixels = length * pixelsPerUnit;
    svg.querySelectorAll('marker').forEach(n=>{n.setAttribute('markerWidth',8/pixelsPerUnit);n.setAttribute('markerHeight',8/pixelsPerUnit);});
    svg.querySelectorAll('.pob-marker').forEach(n=>n.setAttribute('r',3/pixelsPerUnit));
    svg.querySelectorAll('.pob-label').forEach(n=>n.style.fontSize = `${12/pixelsPerUnit}px`);
    svg.querySelectorAll('.course-label').forEach(n => n.style.fontSize = `${13/pixelsPerUnit}px`);
    svg.querySelectorAll('.bearing-label,.distance-label').forEach(n => n.style.fontSize = `${11/pixelsPerUnit}px`);
  }
  function setPlotView(svg, values) { svg.setAttribute('viewBox', values.join(' ')); updateScale(svg); }
  function zoomPlot(factor) { const svg = currentRecordPlot(); if (!svg) return; const b = svg.viewBox.baseVal, w=b.width*factor, h=b.height*factor; setPlotView(svg,[b.x+(b.width-w)/2,b.y+(b.height-h)/2,w,h]); }
  function enhanceRecordPlot(result) {
    document.querySelectorAll('[data-plot-panel]').forEach(panel => panel.hidden = panel.dataset.plotPanel !== selector.value);
    const svg = currentRecordPlot(); if (!svg) return;
    const layer = svg.querySelector('[data-scenario-layer]'); layer.replaceChildren();
    if (result) {
      const placement = baseline.plots.placements.find(p => p.calculation_id === selector.value && p.status !== 'unplaced');
      const scene = placement && bundle.scenes.find(s => s.id === placement.scene_id);
      const points = scenePoints(result.points, placement, selectedCalculation.frame.foot_definition || 'unknown_ft', scene ? scene.units : 'unknown_ft');
      const path = document.createElementNS('http://www.w3.org/2000/svg','path'); path.classList.add('scenario-course');
      path.setAttribute('d', points.map((p,i) => `${i ? 'L':'M'} ${p[0]} ${-p[1]}`).join(' ')); layer.append(path);
      layer.dataset.baselineGeometryHash = baseline.plots.geometries.find(g=>g.calculation_id===selector.value).geometry_hash;
      layer.dataset.scenarioId = scenarioSelect.value || 'browser-working-copy';
      layer.dataset.rotation = placement ? placement.rotation_deg : 0;
      layer.dataset.translation = JSON.stringify(placement ? placement.translation : [0,0]);
    }
    updateScale(svg);
  }
  document.querySelectorAll('[data-baseline-plot]').forEach(svg => {
    svg.setAttribute('tabindex','0'); let dragging = null;
    svg.addEventListener('pointerdown', event => { if (event.target.closest('[data-plot-call],[data-source-call]')) return; dragging = [event.clientX,event.clientY,...[svg.viewBox.baseVal.x,svg.viewBox.baseVal.y]]; svg.setPointerCapture(event.pointerId); });
    svg.addEventListener('pointermove', event => { if (!dragging) return; const b=svg.viewBox.baseVal, scale=Math.min(svg.clientWidth/b.width,svg.clientHeight/b.height); setPlotView(svg,[dragging[2]-(event.clientX-dragging[0])/scale,dragging[3]-(event.clientY-dragging[1])/scale,b.width,b.height]); });
    svg.addEventListener('pointerup',()=>{dragging=null;}); svg.addEventListener('pointercancel',()=>{dragging=null;});
    svg.addEventListener('keydown',event=>{ if (event.target !== svg) return; const b=svg.viewBox.baseVal, steps={ArrowLeft:[-.1,0],ArrowRight:[.1,0],ArrowUp:[0,-.1],ArrowDown:[0,.1]}; if(steps[event.key]) { event.preventDefault(); const d=steps[event.key];setPlotView(svg,[b.x+d[0]*b.width,b.y+d[1]*b.height,b.width,b.height]); } else if(event.key==='+'||event.key==='='){event.preventDefault();zoomPlot(.8);}else if(event.key==='-'){event.preventDefault();zoomPlot(1.25);} });
  });
  byId('plot-zoom-in').addEventListener('click',()=>zoomPlot(.8)); byId('plot-zoom-out').addEventListener('click',()=>zoomPlot(1.25));
  for(const id of ['plot-fit','plot-reset']) byId(id).addEventListener('click',()=>{const svg=currentRecordPlot();if(svg){svg.setAttribute('viewBox',id === 'plot-fit' ? svg.dataset.fitViewbox : svg.dataset.initialViewbox);updateScale(svg);}});
  byId('plot-labels').addEventListener('change',event=>document.querySelectorAll('.course-label').forEach(n=>n.toggleAttribute('hidden',!event.target.checked)));
  byId('plot-bearings').addEventListener('change',event=>document.querySelectorAll('.bearing-label').forEach(n=>n.style.display=event.target.checked?'block':'none'));
  byId('plot-distances').addEventListener('change',event=>document.querySelectorAll('.distance-label').forEach(n=>n.style.display=event.target.checked?'block':'none'));
  function selectSourceCall(id) {
    document.querySelectorAll('[data-call-row]').forEach(row=>row.classList.toggle('selected-call',row.dataset.callRow===id));
    document.querySelectorAll('[data-plot-call]').forEach(path=>path.classList.toggle('selected-call',path.dataset.plotCall===id));
    const row=[...document.querySelectorAll('[data-call-row]')].find(r=>r.dataset.callRow===id);
    if(row) {
      row.scrollIntoView({block:'nearest'}); row.querySelector('[data-page-id]').click();
      const source=bundle.calls.find(c=>c.id===id), evidence=bundle.evidence.find(e=>e.call_id===id), detail=text('div',''); detail.className='selected-source-detail';
      detail.append(text('p',`${id}: ${source.quote}`));
      if(evidence && evidence.image) { const image=document.createElement('img');image.src=evidence.image;image.alt=evidence.label;image.className='selected-source-crop';image.addEventListener('error',()=>{image.hidden=true;detail.append(text('p','Evidence crop could not be decoded. Inspect the source page.'));});detail.append(image,text('p',`Evidence: ${evidence.label}. Crop pixels: ${JSON.stringify(evidence.bounds_px)}.`)); }
      else detail.append(text('p','No individual evidence crop supplied; inspect the linked source page.'));
      byId('viewer-label').after(detail);
    }
  }
  document.querySelectorAll('[data-plot-call],[data-source-call]').forEach(node=>{
    const select=()=>selectSourceCall(node.dataset.plotCall||node.dataset.sourceCall);
    node.addEventListener('click',select); node.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select();}});
  });
  document.querySelectorAll('[data-comparison-source]').forEach(button=>button.addEventListener('click',()=>selectSourceCall(button.dataset.comparisonSource)));
  const initialView = bundle.plot_view || {};
  const labels = initialView.labels || ['course'];
  byId('plot-labels').checked=labels.includes('course'); byId('plot-bearings').checked=labels.includes('bearing'); byId('plot-distances').checked=labels.includes('distance');
  document.querySelectorAll('.course-label').forEach(n=>n.toggleAttribute('hidden',!labels.includes('course')));
  document.querySelectorAll('.bearing-label').forEach(n=>n.style.display=labels.includes('bearing')?'block':'none');
  document.querySelectorAll('.distance-label').forEach(n=>n.style.display=labels.includes('distance')?'block':'none');
  document.querySelectorAll('[data-layer-opacity]').forEach(input => { const pair=(initialView.opacity || []).find(p=>p[0]===input.dataset.layerOpacity); if(pair)input.value=pair[1]; });
  document.querySelectorAll('[data-layer-toggle]').forEach(input => { if((initialView.visible_layer_ids || []).length)input.checked=initialView.visible_layer_ids.includes(input.dataset.layerToggle); document.querySelectorAll('[data-map-layer]').forEach(layer=>{if(layer.dataset.mapLayer===input.dataset.layerToggle)layer.toggleAttribute('hidden',!input.checked);}); });
  document.querySelectorAll('[data-layer-toggle]').forEach(input=>input.addEventListener('change',()=>document.querySelectorAll('[data-map-layer]').forEach(layer=>{if(layer.dataset.mapLayer===input.dataset.layerToggle)layer.toggleAttribute('hidden',!input.checked);})));
  document.querySelectorAll('[data-layer-opacity]').forEach(input=>input.addEventListener('input',()=>document.querySelectorAll('[data-map-layer]').forEach(layer=>{if(layer.dataset.mapLayer===input.dataset.layerOpacity)layer.style.opacity=input.value;})));
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(()=>{const svg=currentRecordPlot();if(svg)updateScale(svg);}).observe(byId('workbench'));


  refreshOptions();
}
