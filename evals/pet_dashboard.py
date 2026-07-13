"""Periodic contract: dashboard includes the slow e-ink pet state mapping."""
from app.render.html import render


page = render()
required = (
    'id="petSprite"',
    'id="petDialogue"',
    "/pet/spritesheet.webp",
    "var PET_DIALOGUES",
    'setPet(seg < 4 ? "focus" : "break")',
    "setInterval(advancePet, 60000)",
    'class="pomo-message" id="pomoMessage"',
    '<span id="pomoRemain"></span> · <span id="pomoStage"></span>',
    "justify-content:flex-start",
    "messageEl.textContent = MAIN[seg]",
    'stageEl.textContent = "第 "',
    "font-size:3.5vmin",
    "font-size:calc(2.8vmin + 2pt)",
    "border:0.35vmin solid var(--ink)",
    ".pet-dialogue::before",
)
missing = [value for value in required if value not in page]
if missing:
    raise SystemExit(f"EVAL_FAIL missing pet contract: {missing}")
print("EVAL_OK dashboard includes slow pet mapping")
