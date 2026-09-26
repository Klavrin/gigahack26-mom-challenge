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
// The email IS the minutes (PV): summary first, then decisions and the task table, so
// nobody has to open the attachment to know what was decided and who does what.
const TYPES = {medical: ['Consiliu medical', '#0f766e'], executive: ['Ședință executivă', '#1d4ed8'],
  administrative: ['Ședință administrativă', '#7c3aed']};
const [typeLabel, color] = TYPES[meeting.type];
const day = iso => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;
const time = iso => iso.slice(11, 16);
const when = day(meeting.started_at) === day(meeting.ended_at)
  ? `${day(meeting.started_at)}, ${time(meeting.started_at)}–${time(meeting.ended_at)}`
  : `${day(meeting.started_at)} ${time(meeting.started_at)} – ${day(meeting.ended_at)} ${time(meeting.ended_at)}`;
const isVoiceLabel = v => /^S\d+$/.test(String(v ?? '').trim());   // "S2" from diarization is not a person
const summaryNote = state.important_notes.find(n => /^Rezumat:/i.test(n));
const summary = state.summary ?? (summaryNote ? summaryNote.replace(/^Rezumat:\s*/i, '') : '');
const notes = state.important_notes.filter(n => n !== summaryNote);
const people = state.participants.filter(p => !isVoiceLabel(p));
const deadline = d => d == null ? '—' : /^\d{4}-\d{2}-\d{2}$/.test(d) ? day(d) : escape(d);
const owner = o => o == null || isVoiceLabel(o) ? '<i style="color:#b45309">Nespecificat</i>' : escape(o);
const section = (title, inner, show) => show
  ? `<h2 style="font-size:15px;margin:22px 0 8px;color:#111827">${title}</h2>${inner}` : '';
const items = (values, tag) => `<${tag} style="margin:0;padding-left:20px;line-height:1.55">` +
  values.map(v => `<li style="margin-bottom:4px">${escape(v)}</li>`).join('') + `</${tag}>`;
const td = 'style="border-bottom:1px solid #e5e7eb;padding:7px 8px;vertical-align:top;text-align:left"';
const tasks = '<table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:14px">' +
  `<tr style="background:#f3f4f6"><th ${td}>Sarcină</th><th ${td}>Responsabil</th><th ${td}>Termen</th></tr>` +
  state.action_items.map(a => `<tr><td ${td}>${escape(a.description)}</td><td ${td}>${owner(a.owner)}</td>` +
    `<td ${td}>${deadline(a.deadline)}</td></tr>`).join('') + '</table>';
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
  section('Rezumat', `<p style="margin:0;line-height:1.55">${escape(summary)}</p>`, summary) +
  section('Decizii', items(state.decisions, 'ol'), state.decisions.length) +
  section('Sarcini', tasks, state.action_items.length) +
  section('Întrebări deschise', items(state.open_questions, 'ul'), state.open_questions.length) +
  section('Participanți', `<p style="margin:0">${people.map(p => escape(p)).join(', ')}</p>`, people.length) +
  section('Subiecte discutate', items(state.topics, 'ul'), state.topics.length) +
  section('Note importante', items(notes, 'ul'), notes.length) +
  '</td></tr>' +
  '<tr><td style="padding:14px 28px;background:#f9fafb;font-size:12px;color:#6b7280;line-height:1.5">' +
  `Aprobat de <b>${escape(approval.approved_by)}</b> · ${day(approval.approved_at)} ${time(approval.approved_at)}<br>` +
  `Procesul-verbal complet este atașat: ${documents.map(d => escape(d.filename)).join(', ')}<br>` +
  'Generat on-premise. Înregistrarea și transcrierea nu au părăsit rețeaua internă a spitalului.' +
  '</td></tr></table></td></tr></table></body></html>';
return {json:{validation:'valid', delivery_id, meeting_id:meeting.id, meeting_type:meeting.type, subject, html, attachment_keys:Object.keys(binary).join(',')}, binary};
