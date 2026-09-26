# Demo meeting script: ATI + cardiology board, ~3.5 min

Three people, read naturally, one take. The script is built to exercise everything the
jury scores:

- Romanian / Russian / English switches **inside** sentences.
- Medical vocabulary.
- People addressed **by name**, so owners can be identified.
- Relative deadlines ("mâine", "până joi", "vineri").
- A decision that is **changed later**.
- An open question.

| Role | Person (read by) | Voice label the pipeline will give |
|---|---|---|
| **Dr. Ana Ceban**: head of ATI, chairs the meeting | teammate 1 | S1 |
| **Dr. Natalia Rusu**: cardiologist | teammate 2 | S2 |
| **Ion Popescu**: chief pharmacist | teammate 3 | S3 |

## Recording tips

- A quiet room. Phone or laptop **in the middle of the table, 50–80 cm from everyone**. No music, no fan noise.
- Don't read like a robot. Small hesitations ("deci", "așa", "ну") are fine and realistic.
- Don't talk over each other (the diarizer handles it, but the transcript gets worse).
- Save as `.m4a` or `.wav`. Record a **second copy on another phone** as a backup.
- Meeting type on upload: **Medical**. Meeting date: **the day you record** (deadlines are computed from it).

---

## Script

**Ana Ceban:** Bună ziua, colegi. Începem consiliul medical. Avem trei puncte pe agendă: pacientul din salonul patru, stocul de ceftriaxonă și raportul KPI pentru trimestrul trei.

**Ana Ceban:** Doamna Rusu, vă rog, începem cu pacientul.

**Natalia Rusu:** Da. Pacient de cincizeci și opt de ani, după un infarct miocardic acut, internat acum trei zile. Hemodinamic e stabil, dar pe ECG avem subdenivelare de segment ST în V4–V6, и тропонин всё ещё повышен.

**Natalia Rusu:** Поэтому я бы предложила repetăm ecocardiografia și troponina în dinamică, before we decide on the discharge.

**Ana Ceban:** De acord. Natalia, poți tu să faci ecocardiografia până mâine dimineață?

**Natalia Rusu:** Да, конечно, mă ocup eu.

**Ana Ceban:** Bine, atunci decidem: pacientul rămâne în ATI până avem rezultatul ecocardiografiei. Trecem la punctul doi. Domnule Popescu?

**Ion Popescu:** По цефтриаксону ситуация сложная: у нас осталось максимум на пять дней. Dacă nu facem comanda săptămâna asta, rămânem fără antibiotic în ATI.

**Ana Ceban:** Atunci facem comanda urgent. Domnule Popescu, vă ocupați de comandă până joi?

**Ion Popescu:** Da, trimit cererea la achiziții până joi.

**Ana Ceban:** Perfect. And the KPI report for Q3: we need it before the board meeting. Natalia, can you prepare it?

**Natalia Rusu:** Pot să-l pregătesc, dar am nevoie de datele de la ATI. Deadline vineri, e ok?

**Ana Ceban:** Da, vineri. Și încă ceva: protocolul de profilaxie antibiotică. Am decis să-l revizuim luna viitoare, nu acum, că avem prea multe pe cap.

**Ion Popescu:** Doamna Ceban, scuzați, joi sunt de gardă toată ziua, не успею с заказом.

**Ana Ceban:** Atunci schimbăm: comanda de ceftriaxonă o fac eu. Termenul rămâne joi.

**Ion Popescu:** Mulțumesc. Și o întrebare: RMN-ul nou intră în bugetul din acest an? Не знаю, надо уточнить у финансового отдела.

**Ana Ceban:** Asta rămâne deschisă, o discutăm la următorul consiliu. Mulțumesc tuturor, ședința s-a încheiat.

---

## What the minutes must contain (answer key)

Deadlines assume the meeting is recorded on **Sunday 27 Sep 2026**; shift them if you
record on another day.

**Decisions**
1. The patient in ward 4 stays in ATI until the echocardiography result is in.
2. Ceftriaxone is ordered urgently.
3. The antibiotic prophylaxis protocol is revised **next month**, not now.

**Action items**

| Task | Owner | Deadline |
|---|---|---|
| Repeat echocardiography (+ troponin) for the ward-4 patient | **Natalia Rusu** | **tomorrow** (2026-09-28) |
| Ceftriaxone order to procurement | **Ana Ceban**, *not Popescu: changed at the end* | **Thursday** (2026-10-01) |
| KPI report for Q3 | **Natalia Rusu** | **Friday** (2026-10-02) |

**Open question**
- Does the new MRI fit into this year's budget? (Check with the finance department.)

**Participants:** Ana Ceban, Natalia Rusu, Ion Popescu.

**Traps the pipeline must get right**

| Trap | What would be wrong |
|---|---|
| Ceftriaxone owner changes at the end | Keeping **Popescu** |
| Russian inside Romanian sentences | Dropping or mistranslating the Russian parts |
| "Deadline vineri", "by the board meeting" | Inventing a date for the board meeting (none was said) |
| The MRI question | Turning it into a decision |
| "ECG, troponină, ceftriaxonă, ATI, RMN" | Misspelling the terms |

---

## Demo flow on stage (~3 min)

1. **Security first (20 s).** Run `sh scripts/egress-check.sh`: every container prints **BLOCKED**. Then turn Wi-Fi off in front of the jury.
2. **Upload (15 s).** Upload the recording, type **Medical**. Show the progress bar moving.
3. **While it runs (60–90 s)**, show the architecture slide and the numbers:
   - lecture WER 83.6 % → ~53 %,
   - the Nemotron vs Whisper benchmark,
   - 8/8 speaker turns.
4. **Review (40 s).**
   - Decisions and tasks, each with its **quote** (click it and the transcript opens at that moment).
   - Point at the ceftriaxone owner: **Ana Ceban**, the model caught the change.
   - Type your name in **"Aprobat de"**.
5. **Approve (20 s).**
   - Open Mailpit: the email reached the **medical** distribution list with the **DOCX** attached.
   - Optionally show the n8n workflow routing by meeting type.

**Backups:**
- Process the recording once before the pitch. The finished job stays under **"Recente"**, so if anything fails live, open that one.
- Keep a screen recording of a full run.
