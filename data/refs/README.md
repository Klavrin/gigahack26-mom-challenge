Hand-corrected reference transcripts go here locally (git-ignored, they contain meeting content).

- `dev.txt`  - minutes 0-6 of the sample recording: tune prompts/glossary against this
- `test.txt` - minutes 6-11: do NOT look at model output for this part until the final measurement
- `script-*.txt` - scripts of the meetings the team recorded (the script is the reference)

Plain text, one utterance per line is fine; punctuation and case are ignored by `eval/wer.py`.
