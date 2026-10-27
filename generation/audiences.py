"""Product audience modes: concrete design requirements, not fixed game templates."""

AUDIENCES = {
    "everyone": "Clear rules and accessible controls for a general audience.",
    "gamers": "Responsive controls, meaningful challenge and concise feedback for experienced players.",
    "children": "Simple instructions, forgiving difficulty, generous touch targets and child-friendly imagery.",
    "seniors": "Large readable text and controls, strong contrast, calm pace and simple navigation.",
    "beginners": "For first-time players: teach one action at a time with an immediately playable example, visible hints, forgiving early mistakes and gradual difficulty. Avoid unexplained conventions or complex key combinations.",
    "family": "For mixed-experience families: familiar age-appropriate themes, shared understandable goals, short rounds, clear turn/result feedback and an easy restart. Do not require multiple players unless requested; make a solo game easy to take turns playing.",
    "learning": "For learning: practice one concrete skill relevant to the user's topic, explain mistakes with helpful feedback, introduce concepts progressively and show meaningful learning progress. Do not substitute arithmetic or a quiz for an explicitly requested mechanic.",
    "relax": "For relaxed play: calm pacing, forgiving mistakes, gentle feedback and no time pressure or harsh penalties unless explicitly requested. Keep a meaningful goal, responsive controls and a satisfying outcome; avoid frantic effects.",
}

APPLICATION_GUIDANCE = "Apply the selected audience to actual rules, pace, instructions and controls, not only colors or a label. Include at least one concrete audience adaptation in the plan summary or game design summary and implement it. Preserve explicit user requirements and the game's genre."
