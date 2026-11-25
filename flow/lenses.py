"""How Ask answers: the **lenses** (GLOSSARY.md).

A lens is a named viewpoint Ask answers from, with instructions the user can read and
change (decisions.md 2026-11-24, "You choose, Flow does not guess"). One is selected and
stays selected until changed, in Flow Home or the pill's menu, exactly as a style is for
Refine. **No lens** is the default and is today's Ask: a plain answer, nothing added.

A lens is instructions only. It works on the question and the conversation; it reads
nothing else - no calendar, mail or task list. Reading those was left for the owner to
raise later, and a lens that needs them says so in its own words rather than pretending.

Pure and platform-neutral, like `kinds`: imported by the session and the profile on every
platform, and it knows nothing about where the question came from.
"""

from __future__ import annotations

from dataclasses import dataclass

NONE = "none"
ARCHITECTURE = "architecture"
BUSINESS = "business"

#: The prefix that marks a lens the user made, so its key can never be a built-in's.
CUSTOM_PREFIX = "my:"

#: How long a lens's name may be, and its instructions.
NAME_MAX = 40
TEXT_MAX = 4000


@dataclass(frozen=True)
class Lens:
    key: str
    #: How Flow Home and the pill's menu name it.
    label: str
    #: The instructions as shipped. "" for No lens, which adds nothing.
    instructions: str


#: The built-ins. Each says *how to look* and leaves the answer to the question: a lens
#: that tells the model what to conclude would be an opinion with a name on it.
BUILT_IN: dict[str, Lens] = {
    NONE: Lens(NONE, "No lens", ""),
    ARCHITECTURE: Lens(ARCHITECTURE, "Architecture", (
        "Answer as a pragmatic software architect. Look at structure before detail: the "
        "components involved, the boundaries between them, and what depends on what. "
        "Name the trade-offs plainly - what each option costs in complexity, coupling, "
        "operations and future change - and say which you would choose and why. Point "
        "out risks and the decisions that are hard to reverse. Where the question is "
        "about this workspace's code, ground the answer in it."
    )),
    BUSINESS: Lens(BUSINESS, "Business", (
        "Answer from a business point of view. Lead with the outcome that matters: "
        "value to users or customers, cost, time, and risk. Say what it would take, "
        "what it unlocks, and what it puts at stake, in plain words a non-engineer can "
        "act on. Where there is a choice, recommend one and say why; where the facts "
        "needed are missing, name them rather than guessing."
    )),
}

#: The order Flow Home and the menu offer them in: none first, because it is the default.
ORDER: tuple[str, ...] = (NONE, ARCHITECTURE, BUSINESS)


def custom_key(name: str) -> str:
    """The key a lens called `name` is stored under: the prefix and a slug."""
    slug = "-".join("".join(c if c.isalnum() else " " for c in name.lower()).split())
    return CUSTOM_PREFIX + (slug[:NAME_MAX] or "lens")


#: What `framing` adds to a question asked through a lens. Named as a viewpoint, not as
#: a rule, for `refine._APP_PROMPT`'s reason: the question asked is what the user wants
#: answered, and a standing preference must not beat it.
_CLAUSE = ("\n\nAnswer through the {name} lens - a viewpoint to take, not a change to "
           "the question:\n{instructions}")


def clause(name: str, instructions: str) -> str:
    """What a question asked through a lens carries, or "" for no lens."""
    text = instructions.strip() if isinstance(instructions, str) else ""
    if not text:
        return ""
    return (_CLAUSE.replace("{name}", name or "selected")
            .replace("{instructions}", text[:TEXT_MAX]))
