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
const {state, approval, documents, recording, delivery_id} = body;
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
if (recording) {
  const bytes = Buffer.from(recording.data_base64, 'base64');
  if (bytes.toString('base64') !== recording.data_base64) return invalid('Non-canonical base64');
  if (bytes.length > 15 * 1024 * 1024) return invalid('Recording exceeds 15 MiB');
  if (bytes.subarray(0,4).toString() !== 'OggS') return invalid('Invalid recording signature');
  if (!(recording.duration_s >= 0)) return invalid('Invalid recording duration');
  binary.recording = {data:recording.data_base64, mimeType:recording.mime_type, fileName:recording.filename};
}
const escape = value => String(value ?? 'Nespecificat').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Short email: the final decisions and what is attached. Tasks with owners and deadlines,
// open questions and participants are in the minutes (DOCX); the recording lets anyone
// hear what was actually said.
const TYPES = {medical: ['Consiliu medical', '#0f766e'], executive: ['Ședință executivă', '#1d4ed8'],
  administrative: ['Ședință administrativă', '#7c3aed']};
const [typeLabel, color] = TYPES[meeting.type];
const automatic = approval.status === 'automatic';   // the uploader chose no review
const day = iso => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;
const time = iso => iso.slice(11, 16);
const when = day(meeting.started_at) === day(meeting.ended_at)
  ? `${day(meeting.started_at)}, ${time(meeting.started_at)}–${time(meeting.ended_at)}`
  : `${day(meeting.started_at)} ${time(meeting.started_at)} – ${day(meeting.ended_at)} ${time(meeting.ended_at)}`;
const section = (title, inner, show) => show
  ? `<h2 style="font-size:15px;margin:22px 0 8px;color:#111827">${title}</h2>${inner}` : '';
const list = (html, tag) => `<${tag} style="margin:0;padding-left:20px;line-height:1.55">` +
  html.map(v => `<li style="margin-bottom:4px">${v}</li>`).join('') + `</${tag}>`;
const decisions = state.decisions.length ? list(state.decisions.map(escape), 'ol')
  : '<p style="margin:0;color:#6b7280">Nicio decizie finală înregistrată.</p>';
const n = state.action_items.length;   // Romanian: "5 sarcini", "20 de sarcini", "101 sarcini"
const tasks = n === 0 ? '' : n === 1 ? ', cu o sarcină (responsabil și termen)'
  : `, cu ${n}${n % 100 >= 20 || n % 100 === 0 ? ' de' : ''} sarcini (responsabili și termene)`;
const length = s => s < 60 ? `${Math.round(s)} s` : s < 3600 ? `${Math.round(s / 60)} min`
  : `${Math.floor(s / 3600)} h ${Math.floor(s % 3600 / 60)} min`;
const attached = documents.map(d => `<b>${escape(d.filename)}</b>: procesul-verbal complet${tasks}`)
  .concat(recording ? [`<b>${escape(recording.filename)}</b>: înregistrarea ședinței (${length(recording.duration_s)})`] : []);
const subject = `[MoM] ${meeting.title}`;
if (/[\r\n]/.test(subject)) return invalid('Title must not contain newlines');
const html = '<!doctype html><html lang="ro"><head><meta charset="utf-8"></head>' +
  '<body style="margin:0;padding:0;background:#f4f5f7;font-family:Segoe UI,Arial,sans-serif;color:#1f2937">' +
  '<table width="100%" cellspacing="0" cellpadding="0" style="background:#f4f5f7;padding:24px 0"><tr><td align="center">' +
  '<table width="680" cellspacing="0" cellpadding="0" style="background:#ffffff;border-radius:8px;overflow:hidden">' +
  `<tr><td style="background:${color};padding:20px 28px;color:#ffffff">` +
  `<div style="font-size:12px;letter-spacing:.06em;text-transform:uppercase;opacity:.9">${typeLabel} · ${when}</div>` +
  `<div style="font-size:22px;font-weight:600;margin-top:4px">${escape(meeting.title)}</div></td></tr>` +
  '<tr><td style="padding:4px 28px 24px">' +
  (automatic ? '<p style="margin:18px 0 0;padding:10px 12px;background:#fef3c7;border-radius:6px;' +
    'font-size:13px;color:#92400e">Proces-verbal generat și trimis automat, fără verificare umană.</p>' : '') +
  section('Decizii finale', decisions, true) +
  section('Atașamente', list(attached, 'ul'), true) +
  section('Note importante', list(state.important_notes.map(escape), 'ul'), state.important_notes.length) +
  '</td></tr>' +
  '<tr><td style="padding:14px 28px;background:#f9fafb;font-size:12px;color:#6b7280;line-height:1.5">' +
  (automatic ? '<b>Trimis automat, fără verificare umană</b>' : `Aprobat de <b>${escape(approval.approved_by)}</b>`) +
  ` · ${day(approval.approved_at)} ${time(approval.approved_at)}<br>` +
  'Generat de Synaps, on-premise. Înregistrarea și transcrierea nu au părăsit rețeaua internă a spitalului.' +
  '</td></tr></table></td></tr></table></body></html>';
return {json:{validation:'valid', delivery_id, meeting_id:meeting.id, meeting_type:meeting.type, subject, html, attachment_keys:Object.keys(binary).join(',')}, binary};
