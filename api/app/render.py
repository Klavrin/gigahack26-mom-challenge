"""MoM -> email-safe HTML (inline styles, tables; renders in Outlook too)."""
import datetime as dt

from jinja2 import Environment

TYPE_LABELS = {
    "medical": ("Consiliu medical", "#0f766e"),
    "executive": ("Ședință executivă", "#1d4ed8"),
    "administrative": ("Ședință administrativă", "#7c3aed"),
}

_TEMPLATE = """\
<!doctype html>
<html><body style="margin:0;padding:0;background:#f4f5f7;font-family:Segoe UI,Arial,sans-serif;color:#1f2937">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f7;padding:24px 0"><tr><td align="center">
<table width="680" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden">
  <tr><td style="background:{{ color }};padding:20px 28px;color:#fff">
    <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.85">{{ type_label }} · {{ date }}</div>
    <div style="font-size:22px;font-weight:600;margin-top:4px">{{ mom.title or "Proces-verbal" }}</div>
  </td></tr>
  <tr><td style="padding:24px 28px">
    <h3 style="margin:0 0 8px;font-size:15px">Rezumat</h3>
    <p style="margin:0 0 20px;line-height:1.5">{{ mom.summary }}</p>

    {% if mom.participants %}
    <p style="margin:0 0 20px;font-size:13px;color:#4b5563"><b>Participanți:</b> {{ mom.participants | join(", ") }}</p>
    {% endif %}

    <h3 style="margin:0 0 8px;font-size:15px">Decizii</h3>
    {% if mom.decisions %}
    <ol style="margin:0 0 20px;padding-left:20px;line-height:1.5">
      {% for d in mom.decisions %}
      <li style="margin-bottom:6px">{{ d.decision }}
        {% if d.evidence %}<div style="font-size:12px;color:#6b7280;font-style:italic">„{{ d.evidence }}”</div>{% endif %}
      </li>
      {% endfor %}
    </ol>
    {% else %}<p style="margin:0 0 20px;color:#6b7280">Nicio decizie înregistrată.</p>{% endif %}

    <h3 style="margin:0 0 8px;font-size:15px">Sarcini (Action Items)</h3>
    {% if mom.action_items %}
    <table width="100%" cellpadding="8" cellspacing="0" style="border-collapse:collapse;font-size:14px;margin-bottom:20px">
      <tr style="background:#f3f4f6;text-align:left">
        <th style="border-bottom:1px solid #e5e7eb">Sarcină</th>
        <th style="border-bottom:1px solid #e5e7eb;width:150px">Responsabil</th>
        <th style="border-bottom:1px solid #e5e7eb;width:110px">Termen</th>
      </tr>
      {% for a in mom.action_items %}
      <tr>
        <td style="border-bottom:1px solid #f3f4f6;vertical-align:top">{{ a.task }}</td>
        <td style="border-bottom:1px solid #f3f4f6;vertical-align:top">{{ a.owner or "Nespecificat" }}</td>
        <td style="border-bottom:1px solid #f3f4f6;vertical-align:top">{{ a.deadline or a.deadline_text or "—" }}</td>
      </tr>
      {% endfor %}
    </table>
    {% else %}<p style="margin:0 0 20px;color:#6b7280">Nicio sarcină înregistrată.</p>{% endif %}

    {% if mom.topics %}
    <h3 style="margin:0 0 8px;font-size:15px">Subiecte discutate</h3>
    {% for t in mom.topics %}
    <p style="margin:0 0 10px;line-height:1.5"><b>{{ t.topic }}.</b> {{ t.discussion }}</p>
    {% endfor %}
    {% endif %}

    {% if mom.open_questions %}
    <h3 style="margin:16px 0 8px;font-size:15px">Întrebări deschise</h3>
    <ul style="margin:0;padding-left:20px;line-height:1.5">
      {% for q in mom.open_questions %}<li>{{ q }}</li>{% endfor %}
    </ul>
    {% endif %}
  </td></tr>
  <tr><td style="padding:14px 28px;background:#f9fafb;font-size:11px;color:#6b7280">
    Generat automat on-premise ({{ generated }}). Înregistrarea și transcrierea nu au părăsit rețeaua internă a spitalului.
  </td></tr>
</table>
</td></tr></table>
</body></html>
"""

_env = Environment(autoescape=True)
_tpl = _env.from_string(_TEMPLATE)


def subject(mom: dict, meeting_type: str, date: dt.date) -> str:
    label = TYPE_LABELS.get(meeting_type, (meeting_type, ""))[0]
    return f"[MoM · {label}] {mom.get('title') or 'Proces-verbal'} · {date.isoformat()}"


def render_html(mom: dict, meeting_type: str, date: dt.date) -> str:
    label, color = TYPE_LABELS.get(meeting_type, (meeting_type, "#374151"))
    return _tpl.render(
        mom=mom, type_label=label, color=color, date=date.isoformat(),
        generated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
