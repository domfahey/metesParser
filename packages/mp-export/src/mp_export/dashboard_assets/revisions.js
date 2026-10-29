/* Exact draft persistence only. Python revalidates publication and geometry. */
"use strict";
(function (root) {
  const copy = value => JSON.parse(JSON.stringify(value));
  const fields = new Set(['distance_ft', 'bearing_azimuth_deg_from_north', 'interior_angle_deg', 'notes']);
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  function keys(value, allowed) {
    if (!object(value) || Object.keys(value).some(key => !allowed.includes(key))) throw Error('Malformed revision fields.');
  }
  function strings(values) { return Array.isArray(values) && values.every(value => typeof value === 'string'); }
  function sameMembers(left, right) {
    return strings(left) && new Set(left).size === left.length && left.length === right.length && right.every(value => left.includes(value));
  }
  let sequence = 0;
  function identifier() {
    return 'revision-' + (root.crypto && root.crypto.randomUUID ? root.crypto.randomUUID() : `${Date.now()}-${++sequence}`);
  }
  class RevisionDraftStore {
    constructor(template, storage) {
      this.template = copy(template); this.storage = storage;
      this.key = 'metesparser-draft-v1:' + template.baseline.id + ':' + template.baseline.bundle_sha256;
      this.value = copy(template); this.version = 0; this.persisted = true; this.recovered = false; this.error = '';
      this.validate(this.value);
      try {
        const retained = storage.getItem(this.key);
        if (retained !== null) { const value = JSON.parse(retained); this.validate(value); this.value = value; this.recovered = true; }
      } catch (error) { this.persisted = false; this.error = 'Draft recovery unavailable: ' + error.message; }
    }
    validate(value) {
      keys(value, ['schema_version','id','generation','parent_revision_id','baseline','kind','label','rationale','tracts','edits','corridors']);
      if (!['1.0','1.1','1.2'].includes(value.schema_version) || !/^[A-Za-z][A-Za-z0-9_.:-]*$/.test(value.id || '') ||
          !Number.isSafeInteger(value.generation) || value.generation < 0 ||
          !(value.parent_revision_id === null || typeof value.parent_revision_id === 'string') ||
          !['scenario','source_correction'].includes(value.kind) || typeof value.label !== 'string' || typeof value.rationale !== 'string') throw Error('Malformed revision envelope.');
      keys(value.baseline, ['id','bundle_sha256']);
      if (value.baseline.id !== this.template.baseline.id || value.baseline.bundle_sha256 !== this.template.baseline.bundle_sha256) throw Error('Revision baseline does not match this dashboard.');
      const corridors=value.corridors===undefined ? [] : value.corridors;
      if (!Array.isArray(corridors) || (corridors.length && value.schema_version!=='1.2')) throw Error('Corridor definitions require schema 1.2.');
      const corridorIds=new Set();
      for (const corridor of corridors) {
        keys(corridor,['id','action','raw_request_json']);
        if (!/^[A-Za-z][A-Za-z0-9_.:-]*$/.test(corridor.id || '') || corridorIds.has(corridor.id) ||
            !['retain','remove'].includes(corridor.action) || typeof corridor.raw_request_json!=='string') throw Error('Corridor identity or exact input is invalid.');
        corridorIds.add(corridor.id);
      }
      if (!Array.isArray(value.tracts) || value.tracts.length !== this.template.tracts.length || !Array.isArray(value.edits)) throw Error('Complete tract inventory is required.');
      const originalIds = new Set(this.template.tracts.flatMap(t => t.call_order));
      const seen = new Set();
      for (const tract of value.tracts) {
        keys(tract, ['id','occurrence_id','document_ids','label','call_order','action']);
        const original = this.template.tracts.find(item => item.occurrence_id === tract.occurrence_id);
        if (!original || seen.has(tract.occurrence_id) || tract.id !== original.id || typeof tract.label !== 'string' ||
            !sameMembers(tract.document_ids, original.document_ids) ||
            !['retain','remove'].includes(tract.action)) throw Error('Tract identity or complete call inventory is invalid.');
        const added = value.edits.filter(e => e.occurrence_id === tract.occurrence_id && e.action === 'add').map(e=>e.call_id);
        const removed = new Set(value.edits.filter(e=>e.action === 'remove').map(e=>e.call_id));
        const expected = [...original.call_order,...added].filter(id=>!removed.has(id));
        if (!sameMembers(tract.call_order, expected)) throw Error('Complete retained, added and removed call inventory is required.');
        seen.add(tract.occurrence_id);
      }
      const edited = new Set();
      for (const edit of value.edits) {
        keys(edit, ['call_id','occurrence_id','tract_id','document_id','page_id','action','raw_fields','structured_input','rationale','evidence_ids','source_refs']);
        const tract = value.tracts.find(item => item.occurrence_id === edit.occurrence_id);
        const original = this.template.tracts.find(item=>item.occurrence_id===edit.occurrence_id);
        const structured = edit.structured_input !== null && edit.structured_input !== undefined;
        if (!tract || !/^[A-Za-z][A-Za-z0-9_.:-]*$/.test(edit.call_id || '') || tract.id !== edit.tract_id || !tract.document_ids.includes(edit.document_id) ||
            edited.has(edit.call_id) || !['update','remove','add'].includes(edit.action) || typeof edit.rationale !== 'string' ||
            !strings(edit.evidence_ids) || !Array.isArray(edit.source_refs)) throw Error('Draft edit identity is invalid.');
        if (value.schema_version==='1.0' && (structured || edit.action==='add')) throw Error('Structured inputs require schema 1.1.');
        if (edit.action==='add' ? originalIds.has(edit.call_id) || !structured :
            !original.call_order.includes(edit.call_id) && !(edit.action==='remove' && structured && !originalIds.has(edit.call_id))) throw Error('Draft call identity does not belong to this tract.');
        if (edit.page_id!==null && edit.page_id!==undefined && typeof edit.page_id!=='string') throw Error('Invalid page identity.');
        keys(edit.raw_fields, [...fields]);
        if (Object.values(edit.raw_fields).some(value => typeof value !== 'string')) throw Error('Raw draft fields must be exact strings.');
        if (structured && (!object(edit.structured_input) || Object.values(edit.structured_input).some(v=>typeof v!=='string') || Object.keys(edit.raw_fields).length)) throw Error('Structured input must contain exact strings without legacy patches.');
        if (edit.action==='remove' && Object.keys(edit.raw_fields).length) throw Error('Removed calls cannot also contain field patches.');
        for (const ref of edit.source_refs) {
          keys(ref, ['page_id','quote']);
          if (typeof ref.page_id !== 'string' || typeof ref.quote !== 'string') throw Error('Source references must preserve page and quote.');
        }
        edited.add(edit.call_id);
      }
    }
    snapshot() { return copy(this.value); }
    raw(callId, field) { const edit = this.value.edits.find(item => item.call_id === callId); return edit ? edit.raw_fields[field] : undefined; }
    persist() {
      try { this.storage.setItem(this.key, JSON.stringify(this.value)); this.persisted = true; this.error = ''; }
      catch (error) { this.persisted = false; this.error = 'Draft is only in this tab: ' + error.message; }
    }
    change(next) {
      next.id = identifier(); next.generation = this.value.generation + 1;
      this.validate(next); this.value = next; this.version += 1; this.persist();
    }
    setField(identity, field, raw) {
      if (!fields.has(field) || typeof raw !== 'string') throw Error('Unsupported raw field.');
      const next = this.snapshot(); let edit = next.edits.find(item => item.call_id === identity.call_id);
      if (edit && (edit.structured_input || edit.action==='remove')) throw Error('Use the structured call editor for this course.');
      if (!edit) { edit = {...identity, action:'update', raw_fields:{}, rationale:'', evidence_ids:[], source_refs:[]}; next.edits.push(edit); }
      edit.raw_fields[field] = raw; this.change(next);
    }
    upgrade(next) {
      if (next.schema_version!=='1.2') next.schema_version='1.1';
      const removed=new Set(next.edits.filter(e=>e.action==='remove').map(e=>e.call_id));
      next.tracts.forEach(t=>{t.call_order=t.call_order.filter(id=>!removed.has(id));});
    }
    setStructured(identity, raw) {
      const next=this.snapshot(); this.upgrade(next);
      const tract=next.tracts.find(t=>t.occurrence_id===identity.occurrence_id);
      if (!tract) throw Error('Unknown tract.');
      let edit=next.edits.find(e=>e.call_id===identity.call_id);
      if(edit && edit.raw_fields.interior_angle_deg!==undefined) throw Error('Retained relative angle input cannot be converted to a structured call. Download it or explicitly reset this occurrence first.');
      const recorded=this.template.tracts.some(t=>t.call_order.includes(identity.call_id));
      if (!edit) {edit={...identity,action:recorded?'update':'add',raw_fields:{},rationale:'',evidence_ids:[],source_refs:[]};next.edits.push(edit);}
      if (edit.action==='remove') throw Error('Removed course must be reset before editing.');
      edit.structured_input=copy(raw);edit.raw_fields={};
      if (!recorded && !tract.call_order.includes(identity.call_id)) tract.call_order.push(identity.call_id);
      this.change(next);
    }
    removeCall(callId, identity) {
      const next=this.snapshot();this.upgrade(next);
      const tract=next.tracts.find(t=>t.call_order.includes(callId));
      if (!tract) throw Error('Course is not in the retained order.');
      let edit=next.edits.find(e=>e.call_id===callId);
      if (!edit && identity && identity.call_id===callId) {
        edit={...identity,action:'remove',raw_fields:{},rationale:'',evidence_ids:[],source_refs:[]};next.edits.push(edit);
      }
      if (!edit) throw Error('Source identity is required to remove this course.');
      edit.action='remove';edit.raw_fields={};
      tract.call_order=tract.call_order.filter(id=>id!==callId);this.change(next);
    }
    moveCall(callId, delta) {
      if (![-1,1].includes(delta)) throw Error('Move one position at a time.');
      const next=this.snapshot();this.upgrade(next);
      const tract=next.tracts.find(t=>t.call_order.includes(callId));
      if (!tract) throw Error('Course is not in the retained order.');
      const old=tract.call_order.indexOf(callId), target=old+delta;
      if (target<0 || target>=tract.call_order.length) return;
      [tract.call_order[old],tract.call_order[target]]=[tract.call_order[target],tract.call_order[old]];
      this.change(next);
    }
    setDescription(label, rationale) {
      const next = this.snapshot(); next.label = label; next.rationale = rationale; this.change(next);
    }
    setContext(identity, rationale, evidenceIds) {
      const next=this.snapshot();let edit=next.edits.find(e=>e.call_id===identity.call_id);
      if(!edit){edit={...identity,action:'update',raw_fields:{},rationale:'',evidence_ids:[],source_refs:[]};next.edits.push(edit);}
      edit.rationale=rationale;edit.evidence_ids=copy(evidenceIds);this.change(next);
    }
    resetOccurrence(occurrenceId) {
      const next = this.snapshot(); next.edits = next.edits.filter(item => item.occurrence_id !== occurrenceId);
      const original = this.template.tracts.find(item => item.occurrence_id === occurrenceId);
      next.tracts = next.tracts.map(item => item.occurrence_id === occurrenceId ? copy(original) : item); this.change(next);
    }
    importRevision(value, expectedVersion) {
      if (this.version !== expectedVersion) throw Error('Draft changed while the file was loading; load again to replace it explicitly.');
      this.validate(value); this.value = copy(value); this.version += 1; this.recovered = true; this.persist();
    }
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {RevisionDraftStore};
  root.MetesRevisionDrafts = {RevisionDraftStore};
})(globalThis);
