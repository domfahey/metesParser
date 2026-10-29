"""Behavior of the offline draft store, independently of the HTML renderer."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ASSET = Path(__file__).parents[1] / "src/mp_export/dashboard_assets/revisions.js"


def run_store(body: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the explicit browser implementation gate")
    script = """
const assert = require('node:assert/strict');
const {RevisionDraftStore} = require(ASSET);
const template = {
  schema_version:'1.0', id:'revision-1', generation:0, parent_revision_id:null,
  baseline:{id:'baseline',bundle_sha256:'a'.repeat(64)}, kind:'scenario',
  label:'Alternative', rationale:'',
  tracts:[{id:'parcel', occurrence_id:'occurrence', document_ids:['document'],
    label:'Tract',call_order:['call-one','call-two'],action:'retain'}], edits:[]
};
const identity = {call_id:'call-one', occurrence_id:'occurrence', tract_id:'parcel',
  document_id:'document'};
const memory = new Map();
const storage = {getItem:k=>memory.get(k)??null,setItem:(k,v)=>memory.set(k,v)};
""".replace("ASSET", json.dumps(str(ASSET)))
    result = subprocess.run([node, "-e", script + body], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_invalid_raw_fields_and_notes_survive_reopen_without_changing_baseline():
    run_store(r"""
const original=JSON.stringify(template), store=new RevisionDraftStore(template,storage);
store.setField(identity,'bearing_azimuth_deg_from_north',' N  ');
store.setField(identity,'notes','  source says unreadable\u000aexact whitespace  ');
const reopened=new RevisionDraftStore(template,storage);
assert.equal(reopened.raw('call-one','bearing_azimuth_deg_from_north'),' N  ');
assert.equal(reopened.raw('call-one','notes'),'  source says unreadable\u000aexact whitespace  ');
assert.equal(JSON.stringify(template),original);
assert.equal(reopened.recovered,true);
assert.equal(reopened.persisted,true);
""")


def test_failed_storage_preserves_in_memory_draft_and_reports_not_saved():
    run_store("""
const blocked={getItem:()=>null,setItem:()=>{throw Error('Quota exceeded');}};
const store=new RevisionDraftStore(template,blocked);
store.setField(identity,'distance_ft','12.');
assert.equal(store.raw('call-one','distance_ft'),'12.');
assert.equal(store.persisted,false);
assert.match(store.error,/Quota exceeded/);
assert.equal(store.snapshot().edits.length,1);
""")


def test_import_rejects_wrong_baseline_and_late_completion_without_mutation():
    run_store("""
const store=new RevisionDraftStore(template,storage), token=store.version;
store.setField(identity,'distance_ft','120');
const before=JSON.stringify(store.snapshot()), wrong=structuredClone(template);
wrong.baseline.bundle_sha256='b'.repeat(64);
assert.throws(()=>store.importRevision(wrong,store.version),/baseline/i);
assert.throws(()=>store.importRevision(template,token),/changed/i);
assert.equal(JSON.stringify(store.snapshot()),before);
""")


def test_import_validates_complete_tract_inventory_and_exact_raw_field_types():
    run_store("""
const store=new RevisionDraftStore(template,storage);
for(const mutate of [p=>p.tracts=[],p=>p.tracts[0].call_order=['call-one'],
  p=>p.edits=[{...identity,action:'update',raw_fields:{distance_ft:12},
    rationale:'',evidence_ids:[],source_refs:[]}],
  p=>p.edits=[{...identity,document_id:'wrong',action:'update',raw_fields:{distance_ft:'12'},
    rationale:'',evidence_ids:[],source_refs:[]}],p=>p.canonical_status='verified']) {
  const payload=structuredClone(template); mutate(payload);
  assert.throws(()=>store.importRevision(payload,store.version));
}
assert.equal(store.snapshot().edits.length,0);
""")


def test_reset_occurrence_keeps_other_tract_drafts_and_revision_identity_advances():
    run_store("""
template.tracts.push({id:'other',occurrence_id:'other-occ',document_ids:['other-doc'],
 label:'Other',call_order:['other-call'],action:'retain'});
const store=new RevisionDraftStore(template,storage);
store.setField(identity,'distance_ft','120'); const first=store.snapshot();
store.setField({call_id:'other-call',occurrence_id:'other-occ',tract_id:'other',
 document_id:'other-doc'},'distance_ft','30');
store.resetOccurrence('occurrence');
assert.equal(store.raw('call-one','distance_ft'),undefined);
assert.equal(store.raw('other-call','distance_ft'),'30');
assert.notEqual(store.snapshot().id,first.id);
assert.ok(store.snapshot().generation>first.generation);
""")


def test_structured_add_reorder_delete_and_reopen_preserve_raw_curve():
    run_store("""
const store=new RevisionDraftStore(template,storage);
const added={...identity,call_id:'new-arc'};
const raw={geometry_type:'circular_arc',radius_value:' 10. ',delta_value:'18',
  bearing_format:'packed_dms_azimuth',bearing_value:'0.0000',notes:'  exact  '};
store.setStructured(added,raw);
assert.equal(store.snapshot().schema_version,'1.1');
assert.deepEqual(store.snapshot().tracts[0].call_order,['call-one','call-two','new-arc']);
store.moveCall('new-arc',-1);
store.removeCall('call-one',identity);
assert.deepEqual(store.snapshot().tracts[0].call_order,['new-arc','call-two']);
let reopened=new RevisionDraftStore(template,storage);
assert.deepEqual(reopened.snapshot().edits.find(e=>e.call_id==='new-arc').structured_input,raw);
reopened.removeCall('new-arc');
reopened=new RevisionDraftStore(template,storage);
const removed=reopened.snapshot().edits.find(e=>e.call_id==='new-arc');
assert.equal(removed.action,'remove');
assert.deepEqual(removed.structured_input,raw);
assert.deepEqual(reopened.snapshot().tracts[0].call_order,['call-two']);
assert.deepEqual(template.tracts[0].call_order,['call-one','call-two']);
""")


def test_structural_import_refuses_unaccounted_calls_and_cross_tract_id_reuse():
    run_store("""
template.tracts.push({id:'other',occurrence_id:'other-occ',document_ids:['other-doc'],
 label:'Other',call_order:['other-call'],action:'retain'});
const store=new RevisionDraftStore(template,storage);
assert.throws(()=>store.setStructured({...identity,call_id:'other-call'},{geometry_type:'line'}));
const bad=structuredClone(template); bad.schema_version='1.1';
bad.tracts[0].call_order=['call-one'];
assert.throws(()=>store.importRevision(bad,store.version));
store.setStructured(identity,{geometry_type:'line',bearing_value:'  N  '});
assert.throws(()=>store.setField(identity,'distance_ft','5'),/structured/i);
const legacy=store.snapshot();legacy.schema_version='1.0';
assert.throws(()=>store.importRevision(legacy,store.version));
""")


def test_legacy_explicit_removal_import_and_relative_patch_no_silent_loss():
    run_store("""
const removed=structuredClone(template);removed.tracts[0].call_order=['call-two'];
removed.edits=[{...identity,action:'remove',raw_fields:{},rationale:'explicit removal',source_refs:[],evidence_ids:[]}];
const store=new RevisionDraftStore(template,storage);store.importRevision(removed,store.version);
assert.deepEqual(store.snapshot().tracts[0].call_order,['call-two']);
store.resetOccurrence('occurrence');store.setField(identity,'interior_angle_deg',' 89. ');
const before=JSON.stringify(store.snapshot());
assert.throws(()=>store.setStructured(identity,{geometry_type:'line',notes:'x'}),/relative.*angle/i);
assert.equal(JSON.stringify(store.snapshot()),before);
""")


def test_corridor_definition_survives_draft_edit_reset_and_reopen_without_downgrade():
    run_store(r"""
const store=new RevisionDraftStore(template,storage), draft=structuredClone(template);
draft.schema_version='1.2';
draft.corridors=[{id:'corridor-one',action:'retain',raw_request_json:'  {"widths": [ incomplete\n'}];
store.importRevision(draft,store.version);
store.setStructured(identity,{geometry_type:'line',bearing_value:' N '});
store.setDescription('Renamed alternative','  exact rationale  ');
store.resetOccurrence('occurrence');
const reopened=new RevisionDraftStore(template,storage);
assert.equal(reopened.snapshot().schema_version,'1.2');
assert.deepEqual(reopened.snapshot().corridors,draft.corridors);
assert.equal(reopened.snapshot().rationale,'  exact rationale  ');
assert.deepEqual(reopened.snapshot().edits,[]);
""")


def test_corridor_envelope_rejects_silent_loss_or_ambiguous_identity():
    run_store("""
const store=new RevisionDraftStore(template,storage), draft=structuredClone(template);
draft.schema_version='1.2';
draft.corridors=[{id:'corridor-one',action:'remove',raw_request_json:' original raw '}];
store.importRevision(draft,store.version);
for(const mutate of [p=>p.schema_version='1.1',p=>p.corridors.push({...p.corridors[0]}),
 p=>p.corridors[0].raw_request_json={},p=>p.corridors[0].action='delete',
 p=>p.corridors[0].id='../unsafe',p=>p.corridors[0].status='verified']) {
 const bad=structuredClone(draft);mutate(bad);
 assert.throws(()=>store.importRevision(bad,store.version));
 assert.deepEqual(store.snapshot().corridors,draft.corridors);
}
""")
