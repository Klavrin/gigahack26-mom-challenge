// Synthetic data only. Node 18+; runs on Windows, macOS, Linux.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.N8N_TEST_URL || 'http://localhost:5678/webhook/mom';
const inbox = process.env.MAILPIT_TEST_URL || 'http://localhost:8025';
const sample = JSON.parse(fs.readFileSync(path.join(__dirname,'examples/approved-meeting.json')));
const post = body => fetch(base,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(60000)});
(async()=>{
 const types=process.argv[2] ? [process.argv[2]] : ['medical','executive','administrative'];
 const recipients={medical:['consiliul-medical','director.medical','sef.sectie'],executive:['board','ceo','cfo'],administrative:['administratie','hr','achizitii']};
 for(const type of types) {
  assert.ok(recipients[type], 'Unknown meeting type');
  const body=structuredClone(sample);
  body.delivery_id=`smoke-${type}-${Date.now()}`;
  body.state.meeting.type=type;
  body.state.meeting.title=body.delivery_id;
  const response=await post(body);
  assert.equal(response.status,200,await response.clone().text());
  const result=await response.json();assert.equal(result.status,'delivered');assert.equal(result.delivery_id,body.delivery_id);assert.equal(result.meeting_id,body.state.meeting.id);
  const list=await (await fetch(`${inbox}/api/v1/messages`,{signal:AbortSignal.timeout(10000)})).json();
  const message=list.messages.find(m=>m.Subject===`[MoM] ${body.delivery_id}`);
  assert.ok(message,'Message must appear in Mailpit');
  const detail=await (await fetch(`${inbox}/api/v1/message/${message.ID}`)).json();
  assert.deepEqual(detail.To.map(r=>r.Address).sort(),recipients[type].map(r=>`${r}@medpark.local`).sort());
  assert.equal(detail.Attachments.length,body.documents.length);
  for (const document of body.documents) {
  const attachment=detail.Attachments.find(a=>a.FileName===document.filename);
  assert.ok(attachment,'Expected attachment');
  
  const bytes=await (await fetch(`${inbox}/api/v1/message/${message.ID}/part/${attachment.PartID}`)).arrayBuffer();
  assert.deepEqual(Buffer.from(bytes),Buffer.from(document.data_base64,'base64'));
  }
  console.log(`${type}: SMTP accepted, recipients correct, PDF/DOCX bytes intact`);
 }
 for(const mutate of [b=>b.approval.status='pending',b=>b.documents=[],b=>b.schema_version='1']) {
  const body=structuredClone(sample);mutate(body);
  const response=await post(body);assert.equal(response.status,400,await response.text());
 }
 console.log('Unapproved, missing-document, and legacy payloads rejected');
})().catch(e=>{console.error(e);process.exitCode=1;});
