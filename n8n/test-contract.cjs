const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
const schema=JSON.parse(fs.readFileSync(path.join(__dirname,'../schemas/meeting-delivery-v2.schema.json')));
const expectedCode=`const schema = ${JSON.stringify(schema)};\n`+fs.readFileSync(path.join(__dirname,'prepare-mom.js'),'utf8');
const workflow = JSON.parse(fs.readFileSync(path.join(__dirname,'workflows/mom-routing.json')));
assert.equal(workflow.nodes.find(n=>n.name==='Validate payload').parameters.jsCode,expectedCode,'Run node n8n/sync-workflow.cjs');
const run = new Function('$json',workflow.nodes.find(n=>n.name==='Validate payload').parameters.jsCode);
const sample = JSON.parse(fs.readFileSync(path.join(__dirname,'examples/approved-meeting.json')));
for (const type of ['medical','executive','administrative']) {
  const body = structuredClone(sample); body.state.meeting.type=type;
  const result=run({body});
  assert.equal(result.json.validation,'valid');
  assert.equal(result.json.meeting_type,type);
  assert.ok(result.json.html.includes('Nespecificat'));
  assert.ok(result.json.html.includes('Friday'));
  assert.ok(result.json.html.includes('Note importante'));
  assert.equal(result.binary.document_0.data,body.documents[0].data_base64);
}
const mutations = [
 b=>delete b.approval, b=>b.approval.status='pending', b=>b.approval.approved_by='',
 b=>b.state.meeting.ended_at=null, b=>b.state.meeting.type='unknown',
 b=>b.approval.approved_at='2026-02-30T10:00:00Z', b=>b.approval.approved_at='2025-09-26T10:00:00Z',
 b=>b.state.meeting.title='Header\r\nInjection', b=>b.state.action_items[0].owner=42,
 b=>b.state.action_items[0].task='old schema', b=>b.state.important_notes=[{}],
 b=>b.documents=[], b=>b.documents[0].data_base64='!!!!',
 b=>b.documents[0].filename='../file.pdf', b=>b.documents[0].mime_type='text/plain',
 b=>b.documents.push({...b.documents[0]}), b=>b.documents[0].data_base64=Buffer.from('not pdf').toString('base64'),
 b=>b.documents[0].data_base64=Buffer.concat([Buffer.from('%PDF-'),Buffer.alloc(5*1024*1024)]).toString('base64'),
 b=>b.recipients=['outsider@example.com'], b=>b.schema_version='1',
];
for (const mutate of mutations) {
 const body=structuredClone(sample);mutate(body);
 assert.equal(run({body}).json.validation,'invalid',mutate.toString());
}
for(const body of [null,[],{}, {job_id:'legacy',meeting_type:'medical',html:'<p>Unapproved</p>'}]) assert.equal(run({body}).json.validation,'invalid');
const escaped=structuredClone(sample);escaped.state.meeting.title='<script>alert(1)</script>';
assert.ok(run({body:escaped}).json.html.includes('&lt;script&gt;'));
const both=structuredClone(sample);

assert.equal(run({body:both}).json.attachment_keys,'document_0,document_1');
for(const node of workflow.nodes.filter(n=>n.type==='n8n-nodes-base.emailSend')) {
 assert.equal(node.parameters.options.attachments,'={{ $json.attachment_keys }}');
 assert.equal(workflow.connections[node.name].main[1][0].node,'Report delivery failure');
}
console.log('Passed: routes, approval gate, schema, nulls, escaping, document transport, rejection cases, SMTP failure wiring');
