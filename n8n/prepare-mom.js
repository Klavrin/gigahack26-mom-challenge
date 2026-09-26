// Schema is embedded by sync-workflow.cjs. Runs without external packages in n8n.
const invalid = error => ({json: {validation: 'invalid', error}});
const validate = (value, rule, path = 'body') => {
  const types = Array.isArray(rule.type) ? rule.type : [rule.type];
  const type = value === null ? 'null' : Array.isArray(value) ? 'array' : typeof value;
  if (!types.includes(type)) return `${path}: expected ${types.join(' or ')}`;
  if (rule.enum && !rule.enum.includes(value)) return `${path}: unsupported value`;
  if (type === 'string') {
    if (rule.minLength && !value.trim()) return `${path}: must not be blank`;
    if (value.length < (rule.minLength ?? 0) || value.length > (rule.maxLength ?? Infinity)) return `${path}: invalid length`;
    if (rule.pattern && !new RegExp(rule.pattern).test(value)) return `${path}: invalid format`;
    if (rule.format === 'date-time' && (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value)) || new Date(value.slice(0,10)).toISOString().slice(0,10) !== value.slice(0,10))) return `${path}: invalid timestamp`;
  }
  if (type === 'object') {
    for (const key of rule.required ?? []) if (!(key in value)) return `${path}.${key}: required`;
    for (const key of Object.keys(value)) {
      if (!Object.hasOwn(rule.properties, key)) return `${path}.${key}: unsupported field`;
      const error = validate(value[key], rule.properties[key], `${path}.${key}`);
      if (error) return error;
    }
  }
  if (type === 'array') {
    if (value.length < (rule.minItems ?? 0) || value.length > (rule.maxItems ?? Infinity)) return `${path}: invalid item count`;
    for (let i=0; i<value.length; i++) {
      const error = validate(value[i], rule.items, `${path}[${i}]`);
      if (error) return error;
    }
  }
};
const body = $json.body;
const error = validate(body, schema);
if (error) return invalid(error);
const {state, approval, documents, delivery_id} = body;
const {meeting} = state;
if (Date.parse(meeting.ended_at) < Date.parse(meeting.started_at) || Date.parse(approval.approved_at) < Date.parse(meeting.ended_at)) return invalid('Approval must follow meeting end; end must follow start');
if (JSON.stringify(state).length > 500000) return invalid('State exceeds 500000 characters');
const binary = {};
let total = 0;
const names = new Set();
for (const [i, doc] of documents.entries()) {
  const pdf = doc.filename.endsWith('.pdf');
  if (doc.mime_type !== (pdf ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')) return invalid('Document extension and MIME type mismatch');
  if (names.has(doc.filename.toLowerCase())) return invalid('Duplicate document filename');
  names.add(doc.filename.toLowerCase());
  const bytes = Buffer.from(doc.data_base64, 'base64');
  if (bytes.toString('base64') !== doc.data_base64) return invalid('Non-canonical base64');
  total += bytes.length;
  if (total > 5 * 1024 * 1024) return invalid('Documents exceed 5 MiB total');
  if (pdf ? bytes.subarray(0,5).toString() !== '%PDF-' : bytes.subarray(0,4).toString('hex') !== '504b0304') return invalid('Invalid document signature');
  binary[`document_${i}`] = {data:doc.data_base64, mimeType:doc.mime_type, fileName:doc.filename};
}
const escape = value => String(value ?? 'Nespecificat').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const list = values => '<ul>' + values.map(v => `<li>${escape(v)}</li>`).join('') + '</ul>';
const subject = `[MoM] ${meeting.title}`;
if (/[\r\n]/.test(subject)) return invalid('Title must not contain newlines');
const html = '<!doctype html><html lang="ro"><meta charset="utf-8"><body>' +
  `<h1>${escape(meeting.title)}</h1><p>${escape(meeting.started_at)} — ${escape(meeting.ended_at)} · ${escape(meeting.type)}</p>` +
  '<h2>Participanți</h2>' + list(state.participants) + '<h2>Subiecte</h2>' + list(state.topics) +
  '<h2>Decizii</h2>' + list(state.decisions) +
  '<h2>Sarcini</h2><table><tr><th>Acțiune</th><th>Responsabil</th><th>Termen</th><th>Status</th></tr>' +
  state.action_items.map(a => `<tr><td>${escape(a.description)}</td><td>${escape(a.owner)}</td><td>${escape(a.deadline)}</td><td>${escape(a.status)}</td></tr>`).join('') + '</table>' +
  '<h2>Întrebări deschise</h2>' + list(state.open_questions) + '<h2>Note importante</h2>' + list(state.important_notes) +
  `<p>Aprobat: ${escape(approval.approved_by)} · ${escape(approval.approved_at)}</p></body></html>`;
return {json:{validation:'valid', delivery_id, meeting_id:meeting.id, meeting_type:meeting.type, subject, html, attachment_keys:Object.keys(binary).join(',')}, binary};
