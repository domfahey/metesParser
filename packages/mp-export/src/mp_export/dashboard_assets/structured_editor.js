/* Exact structured drafts. Shared Python packages interpret and plot these inputs. */
"use strict";
(function(root) {
  const clone=value=>JSON.parse(JSON.stringify(value));
  const node=(tag,value)=>{const n=document.createElement(tag);if(value!==undefined)n.textContent=value;return n;};
  const choices={
    geometry_type:[['line','Line'],['circular_arc','Circular arc'],['annotation','Annotation']],
    role:[['boundary','Boundary'],['tie_in','Tie-in'],['reference','Reference'],['omitted','Intentionally omitted']],
    orientation:[['supplied','Supplied bearing / tangent'],['inherited_tangent','Inherit adjacent ending tangent']],
    bearing_format:[['decimal_azimuth','Decimal azimuth'],['quadrant_dms','Quadrant DMS'],['packed_dms_azimuth','Packed DMS azimuth'],['quadrant_packed_dms','Packed DMS quadrant']],
    distance_unit:[['feet','Native deed feet'],['meters','Meters'],['international_ft','International feet'],['us_survey_ft','US survey feet']],
    delta_format:[['decimal_degrees','Decimal degrees'],['packed_dms','Packed DMS']],
    curve_dir:[['','Unspecified'],['left','Left'],['right','Right']],
    quadrant_ns:[['','Unspecified'],['N','North'],['S','South']],
    quadrant_ew:[['','Unspecified'],['E','East'],['W','West']],
  };
  const fields=[
    ['geometry_type','Geometry'],['role','Course role'],['orientation','Orientation'],
    ['bearing_format','Bearing format'],['bearing_value','Bearing / start tangent'],
    ['quadrant_ns','Packed quadrant N/S'],['quadrant_ew','Packed quadrant E/W'],
    ['distance_unit','Distance unit'],['distance_value','Distance / stated arc length'],
    ['curve_dir','Curve direction'],['radius_value','Radius'],['delta_format','Central angle format'],['delta_value','Central angle'],
    ['arc_length_value','Arc length'],['chord_length_value','Chord length'],
    ['chord_bearing_format','Chord bearing format'],['chord_bearing_value','Chord bearing'],
    ['chord_quadrant_ns','Packed chord N/S'],['chord_quadrant_ew','Packed chord E/W'],
    ['radial_bearing_format','Radial bearing format'],['radial_bearing_value','Radial bearing (retained; unsupported orientation)'],
    ['direction_text','Direction text'],['along','Along'],['to','To'],['notes','Notes'],
    ['non_tangent','Non-tangent'],['is_exception','Exception'],['is_meander','Meander'],['is_indefinite','Indefinite'],
  ];
  choices.chord_bearing_format=choices.bearing_format;choices.radial_bearing_format=choices.bearing_format;
  choices.chord_quadrant_ns=choices.quadrant_ns;choices.chord_quadrant_ew=choices.quadrant_ew;
  for(const key of ['non_tangent','is_exception','is_meander','is_indefinite'])choices[key]=[['','Unspecified'],['false','False'],['true','True']];
  function seed(item, edit) {
    if(edit && edit.structured_input)return clone(edit.structured_input);
    const call=item && item.call || {}, patch=edit && edit.raw_fields || {};
    const curved=!!(call.curve_dir || call.radius_ft || call.curve_type);
    const raw={geometry_type:curved?'circular_arc':'line',role:call.is_tie_in?'tie_in':'boundary',orientation:'supplied',bearing_format:'decimal_azimuth',distance_unit:'feet'};
    const mapping={bearing_azimuth_deg_from_north:'bearing_value',distance_ft:'distance_value',radius_ft:'radius_value',delta_deg:'delta_value',arc_length_ft:'arc_length_value',chord_length_ft:'chord_length_value'};
    for(const [source,target] of Object.entries(mapping))if(call[source]!==null&&call[source]!==undefined)raw[target]=String(call[source]);
    for(const key of ['curve_dir','along','to','notes','direction_text','non_tangent','is_exception','is_meander','is_indefinite','curve_type','monument_type','monument_status','quality'])if(call[key]!==null&&call[key]!==undefined)raw[key]=String(call[key]);
    for(const prefix of ['chord_bearing','radial_bearing'])if(call[prefix]){
      raw[prefix+'_value']=String(call[prefix]);raw[prefix+'_format']=/^[NS]/i.test(call[prefix])?'quadrant_dms':'decimal_azimuth';
    }
    if(curved)raw.delta_format='decimal_degrees';
    if(patch.distance_ft!==undefined)raw.distance_value=patch.distance_ft;
    if(patch.bearing_azimuth_deg_from_north!==undefined){raw.bearing_value=patch.bearing_azimuth_deg_from_north;raw.bearing_format=/^[NS]/i.test(raw.bearing_value.trim())?'quadrant_dms':'decimal_azimuth';}
    if(patch.notes!==undefined)raw.notes=patch.notes;
    return raw;
  }
  function mount({container,store,bundle,getCalculation,onChange,onStatus}) {
    const selector=node('select');selector.id='structured-call-select';selector.setAttribute('aria-label','Structured course');
    const docs=node('select');docs.setAttribute('aria-label','Document for added course');
    const toolbar=node('div');toolbar.className='controls';
    const label=node('label','Course');label.append(selector);toolbar.append(label);
    const docLabel=node('label','Document for added course');docLabel.append(docs);toolbar.append(docLabel);
    const form=node('div');form.className='controls structured-fields';
    const status=node('p');status.id='structured-call-status';status.setAttribute('role','status');
    const removed=node('p');removed.className='muted';
    container.append(toolbar,status,form,removed);
    let currentOccurrence=null, selectedRaw=null, selectedIdentity=null;
    function changed(){onStatus();onChange();}
    function button(label,run){const b=node('button',label);b.type='button';b.addEventListener('click',()=>{try{run();}catch(error){onStatus('Draft unchanged: '+error.message);}});toolbar.append(b);return b;}
    function identity(item){const occurrence=bundle.occurrences.find(o=>o.id===item.occurrence_id),page=bundle.pages.find(p=>p.id===item.page_id);return {call_id:item.id,occurrence_id:item.occurrence_id,tract_id:occurrence.parcel_id,document_id:page.document_id,page_id:page.id};}
    function drawForm(){
      form.replaceChildren();selectedRaw=null;selectedIdentity=null;
      const saved=store.snapshot(),edit=saved.edits.find(e=>e.call_id===selector.value),item=bundle.calls.find(c=>c.id===selector.value);
      if(!edit&&!item){status.textContent='No retained course. Add a course or reset this occurrence.';return;}
      if(edit && edit.raw_fields.interior_angle_deg!==undefined){
        status.textContent='This draft retains an exact relative angle input. Continue editing its existing fields in the workbench, or download it before an explicit Reset to record. Structured replacement would discard that constraint, so it is unavailable for this course.';return;
      }
      selectedIdentity=item?identity(item):{call_id:edit.call_id,occurrence_id:edit.occurrence_id,tract_id:edit.tract_id,document_id:edit.document_id,page_id:edit.page_id??null};
      selectedRaw=seed(item,edit);
      status.textContent=`${selector.value} · ${item?'Original source retained':'Hypothetical addition; no source quote attributed'}. Values are saved exactly. Download this draft for Cowork to compute and display fresh shared geometry.`;
      for(const [key,title] of fields){
        const label=node('label',title);let input;
        if(choices[key]){input=node('select');const options=choices[key].slice();if(!options.some(([v])=>v===(selectedRaw[key]??'')))options.unshift([selectedRaw[key]??'','Unspecified / retained value']);for(const [value,name] of options){const option=node('option',name);option.value=value;input.append(option);}}
        else input=node(['notes','along','to','direction_text'].includes(key)?'textarea':'input');
        input.value=selectedRaw[key]??'';input.dataset.structuredField=key;input.setAttribute('aria-label',title);
        input.addEventListener('input',()=>{
          const next={...selectedRaw,[key]:input.value};
          try{store.setStructured(selectedIdentity,next);selectedRaw=next;changed();}
          catch(error){onStatus('Draft field was not saved: '+error.message);}
        });label.append(input);form.append(label);
      }
    }
    function refresh(){
      const calc=getCalculation(),old=selector.value;selector.replaceChildren();docs.replaceChildren();
      currentOccurrence=calc&&calc.occurrence_id;
      const saved=store.snapshot(),tract=saved.tracts.find(t=>t.occurrence_id===currentOccurrence);
      if(!tract){form.replaceChildren();status.textContent='Select an occurrence first.';return;}
      for(const id of tract.call_order){const option=node('option',id);option.value=id;selector.append(option);}
      if(tract.call_order.includes(old))selector.value=old;
      for(const id of tract.document_ids){const option=node('option',bundle.documents.find(d=>d.id===id)?.label||id);option.value=id;docs.append(option);}
      removed.textContent='Explicitly removed: '+(saved.edits.filter(e=>e.occurrence_id===currentOccurrence&&e.action==='remove').map(e=>e.call_id).join(', ')||'none')+'. Reset to record restores original inventory.';
      drawForm();
    }
    for(const [kind,title] of [['line','Add line'],['circular_arc','Add circular arc'],['annotation','Add annotation']])button(title,()=>{
      const tract=store.snapshot().tracts.find(t=>t.occurrence_id===currentOccurrence);if(!tract||!docs.value)throw Error('Select an occurrence and document.');
      const callId='call-'+(root.crypto.randomUUID?root.crypto.randomUUID():Date.now().toString(36));
      const raw={geometry_type:kind,role:kind==='annotation'?'reference':'boundary',orientation:'supplied',bearing_format:'decimal_azimuth',distance_unit:'feet'};
      if(kind==='circular_arc')raw.delta_format='decimal_degrees';
      store.setStructured({call_id:callId,occurrence_id:tract.occurrence_id,tract_id:tract.id,document_id:docs.value},raw);refresh();selector.value=callId;drawForm();changed();
    });
    button('Move course up',()=>{store.moveCall(selector.value,-1);refresh();changed();});
    button('Move course down',()=>{store.moveCall(selector.value,1);refresh();changed();});
    button('Remove course',()=>{store.removeCall(selector.value,selectedIdentity);refresh();changed();});
    selector.addEventListener('change',drawForm);
    return {refresh};
  }
  root.MetesStructuredEditor={mount};
})(globalThis);
