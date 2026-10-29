"""Offline raster control collection; no fitting, deed placement or verification."""

from __future__ import annotations

import base64
import json
from typing import Any

from mp_models.raster import image_header

_HTML = r"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Raster control picker</title>
<style>
body{font:16px/1.4 system-ui,sans-serif;margin:24px;color:#17202a;background:#f6f8fa}main{max-width:1280px;margin:auto}h1{font-size:1.5rem}button,input,select{font:inherit}button{padding:.35rem .7rem;margin:.2rem}button:focus,input:focus,select:focus{outline:3px solid #1769aa;outline-offset:2px}.note{background:#fff;padding:12px;border-left:4px solid #1769aa}.toolbar{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.viewport{height:55vh;min-height:240px;overflow:auto;background:#d8dee5;border:1px solid #607080;margin:12px 0;position:relative}.canvas{position:relative;width:max-content;line-height:0}#scan{display:block;max-width:none;image-orientation:none}#markers{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}table{border-collapse:collapse;width:100%;background:white}th,td{padding:6px;text-align:left;border:1px solid #ccd3da}input.coordinate{width:7rem}input.name{width:10rem}.table-wrap{overflow:auto}#message{min-height:1.5em;white-space:pre-wrap;color:#8a2200}details pre{white-space:pre-wrap}small{display:block}#scene{font-size:.85rem}
</style>
<main><h1>Raster control picker</h1>
<p class="note">Collect controls on this exact scan. Native integer pixels are centers: u increases right, v increases down; outer edges are −0.5 and width/height −0.5. This page does not fit a transform, place a deed or verify geometry.</p>
<div class="toolbar"><button id="fit-image" type="button">Fit image</button><label>Zoom <input id="zoom" type="range" min="1" max="5000" step="0.5" value="100"></label><output id="zoom-label"></output><label><input id="snap" type="checkbox" checked> Snap clicks to nearest native pixel center</label></div>
<p>Select a row, then click its known point. Enter independently supplied scene X/Y and keep fit/checkpoint roles separate. Existing scene values are never inferred from clicks.</p>
<div id="viewport" class="viewport" tabindex="0" aria-label="Scrollable supplied scan"><div class="canvas"><img id="scan" alt="Supplied scan for choosing native pixel controls"><svg id="markers" aria-hidden="true"></svg></div></div>
<div class="toolbar"><button id="add-control" type="button">Add control</button><label id="matrix-option"><input id="keep-matrix" type="checkbox"> Retain supplied affine matrix (controls become residual evidence, not a refit)</label></div>
<div class="table-wrap"><table><thead><tr><th>Pick</th><th>Control name</th><th>Role</th><th>Pixel u</th><th>Pixel v</th><th>Scene X</th><th>Scene Y</th><th>Remove</th></tr></thead><tbody id="controls"></tbody></table></div>
<p id="message" role="status" aria-live="polite"></p><button id="download" type="button">Download controls JSON</button>
<p>Keep the original image, source controls and picker manifest with your downloaded file. Run <code>register-raster IMAGE --controls controls-picked.json --output NEW_RASTER.json</code> in the shared runtime to fit and validate. At least three noncollinear fit controls are required without a supplied matrix. Independent checkpoint accuracy remains separate.</p>
<details><summary>Retained scene and source identities</summary><pre id="scene"></pre></details>
</main><script id="picker-data" type="application/json">__DATA__</script>
<script>
(()=>{'use strict';
const seed=JSON.parse(document.getElementById('picker-data').textContent);
const img=document.getElementById('scan'),view=document.getElementById('viewport'),tbody=document.getElementById('controls'),svg=document.getElementById('markers'),message=document.getElementById('message'),zoom=document.getElementById('zoom');
const rows=seed.config.controls.map(c=>({id:c.id,role:c.role,pixel:c.pixel.map(String),scene:c.scene.map(String)}));
let active=rows.length?0:-1,dimensionsReady=false;
const ns='http://www.w3.org/2000/svg';
svg.setAttribute('viewBox',`-0.5 -0.5 ${seed.width} ${seed.height}`);
document.getElementById('scene').textContent=JSON.stringify({scene:seed.config.scene,image_sha256:seed.image_sha256,original_controls_sha256:seed.controls_sha256,pixel_convention:seed.pixel_convention},null,2);
const matrixToggle=document.getElementById('keep-matrix');matrixToggle.checked=Array.isArray(seed.config.matrix);document.getElementById('matrix-option').hidden=!matrixToggle.checked;
function marks(){svg.replaceChildren();rows.forEach((row,index)=>{const u=Number(row.pixel[0]),v=Number(row.pixel[1]);if(row.pixel.some(x=>String(x).trim()==='')||!Number.isFinite(u)||!Number.isFinite(v))return;const dot=document.createElementNS(ns,'circle');dot.setAttribute('cx',u);dot.setAttribute('cy',v);dot.setAttribute('r',Math.max(seed.width,seed.height)*.006);dot.setAttribute('fill',index===active?'#bb1100':row.role==='checkpoint'?'#b45a00':'#0055aa');svg.append(dot);});}
function textInput(value,label,change,number=false){const input=document.createElement('input');input.type=number?'number':'text';if(number)input.step='any';input.className=number?'coordinate':'name';input.value=value;input.setAttribute('aria-label',label);input.addEventListener('input',()=>{change(input.value);marks();});return input;}
function render(){tbody.replaceChildren();rows.forEach((row,index)=>{const tr=document.createElement('tr');tr.dataset.index=index;const pick=document.createElement('input');pick.type='radio';pick.name='active-control';pick.checked=active===index;pick.setAttribute('aria-label','Select '+(row.id||'unnamed control '+(index+1)));pick.addEventListener('change',()=>{active=index;marks();});const values=[pick,textInput(row.id,'Control name '+(index+1),x=>{row.id=x;pick.setAttribute('aria-label','Select '+(row.id||'unnamed control '+(index+1)));remove.setAttribute('aria-label','Remove '+(row.id||'unnamed control'));})];const role=document.createElement('select');role.setAttribute('aria-label','Role '+(index+1));for(const [value,label] of [['','Choose role'],['fit','Fit'],['checkpoint','Checkpoint']]){const option=document.createElement('option');option.value=value;option.textContent=label;role.append(option);}role.value=row.role;role.addEventListener('change',()=>{row.role=role.value;marks();});values.push(role);for(const [field,prefix] of [['pixel','Pixel'],['scene','Scene']])for(let axis=0;axis<2;axis++)values.push(textInput(row[field][axis],`${prefix} ${axis===0?(field==='pixel'?'u':'X'):(field==='pixel'?'v':'Y')} ${index+1}`,x=>{row[field][axis]=x;},true));const remove=document.createElement('button');remove.textContent='Remove';remove.type='button';remove.setAttribute('aria-label','Remove '+(row.id||'unnamed control'));remove.addEventListener('click',()=>{rows.splice(index,1);active=rows.length?Math.min(active,rows.length-1):-1;render();});values.push(remove);for(const value of values){const td=document.createElement('td');td.append(value);tr.append(td);}tbody.append(tr);});marks();}
function setZoom(value){zoom.value=String(Math.max(1,Math.min(5000,value)));img.style.width=(seed.width*Number(zoom.value)/100)+'px';img.style.height=(seed.height*Number(zoom.value)/100)+'px';document.getElementById('zoom-label').textContent=Number(zoom.value).toFixed(1)+'%';}
function fit(){setZoom((view.clientWidth-4)/seed.width*100);}
img.addEventListener('load',()=>{dimensionsReady=img.naturalWidth===seed.width&&img.naturalHeight===seed.height;if(!dimensionsReady){message.textContent='Browser decoded dimensions differ from the retained scan. Point picking is unavailable.';return;}fit();});
img.addEventListener('click',event=>{if(!dimensionsReady)return;if(active<0||!rows[active]){message.textContent='Add or select a control row before picking.';return;}const box=img.getBoundingClientRect();let u=(event.clientX-box.left)*seed.width/box.width-.5,v=(event.clientY-box.top)*seed.height/box.height-.5;if(document.getElementById('snap').checked){u=Math.max(0,Math.min(seed.width-1,Math.round(u)));v=Math.max(0,Math.min(seed.height-1,Math.round(v)));}rows[active].pixel=[String(u),String(v)];message.textContent=`Picked ${rows[active].id||'unnamed control'}: native pixel (${u}, ${v}). Scene coordinates unchanged.`;render();});
zoom.addEventListener('input',()=>setZoom(Number(zoom.value)));document.getElementById('fit-image').addEventListener('click',fit);document.getElementById('add-control').addEventListener('click',()=>{rows.push({id:'',role:'',pixel:['',''],scene:['','']});active=rows.length-1;render();});
document.getElementById('download').addEventListener('click',()=>{try{const seen=new Set();const controls=rows.map((row,i)=>{const id=row.id.trim();if(!id||seen.has(id))throw Error('Control names must be nonempty and unique.');seen.add(id);if(!['fit','checkpoint'].includes(row.role))throw Error('Choose a fit/checkpoint role for every control.');const numbers=values=>values.map(value=>{if(String(value).trim()===''||!Number.isFinite(Number(value)))throw Error('Every pixel and scene coordinate must be explicitly supplied and finite.');return Number(value);});return{id,role:row.role,pixel:numbers(row.pixel),scene:numbers(row.scene)};});if(!matrixToggle.checked&&controls.filter(c=>c.role==='fit').length<3)throw Error('Supply at least three fit controls, or retain an explicitly supplied matrix.');const config={...seed.config,controls,pixel_convention:seed.pixel_convention,picker_evidence:{image_sha256:seed.image_sha256,original_controls_sha256:seed.controls_sha256,click_mode:document.getElementById('snap').checked?'nearest_integer_center':'subpixel_center_coordinates',previous:seed.config.picker_evidence||null,registration_performed:false}};if(!matrixToggle.checked)delete config.matrix;const blob=new Blob([JSON.stringify(config,null,2)+'\n'],{type:'application/json'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='controls-picked.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);message.textContent='Downloaded controls only. Run register-raster for shared validation and fit/checkpoint residuals.';}catch(error){message.textContent=error.message;}});
render();img.src=seed.image_url;
})();
</script></html>"""


def render_raster_picker(data: bytes, config: dict[str, Any], *, controls_sha256: str) -> str:
    """Render exact supported image bytes and schema-validated controls supplied by adapter."""
    import hashlib

    mime, width, height = image_header(data)
    seed = {
        "image_url": f"data:{mime};base64," + base64.b64encode(data).decode(),
        "image_sha256": hashlib.sha256(data).hexdigest(),
        "controls_sha256": controls_sha256,
        "width": width,
        "height": height,
        "pixel_convention": "integer_pixel_centers",
        "config": config,
    }
    payload = (
        json.dumps(seed, ensure_ascii=False, allow_nan=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return _HTML.replace("__DATA__", payload)
