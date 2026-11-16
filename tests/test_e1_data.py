"""Checks on the E1 test commands and the few-shot examples (D-017, D-117).

The D-017 check: no few-shot command may equal an E1 command (lowercased, punctuation removed,
whitespace collapsed) or be a near duplicate (Jaccard similarity of the token sets, after
removing stop words, of at least 0.6).
"""

import json
import re
from pathlib import Path

from lang_grounding.config import load_config
from lang_grounding.grounding_output import load_vocabulary
from lang_grounding.prompts import load_fewshot
from lang_grounding.scene_graph import load_scene_graph

ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config()
E1_PATH = ROOT / "data" / "e1_commands.json"
GRAPH = load_scene_graph(CONFIG.resolve(CONFIG.paths.scene_graph))
VOCAB = load_vocabulary(CONFIG.resolve(CONFIG.paths.vocabulary))
FEWSHOT = load_fewshot(CONFIG.resolve(CONFIG.paths.fewshot))
E1 = json.loads(E1_PATH.read_text(encoding="utf-8"))["commands"]

JACCARD_LIMIT = 0.6
STOP_WORDS = frozenset("""
a an the is are was were be been am im i me my mine we our you your he she it its they their
to of in on at for from with by as and or but if so that this these those there can could would
will shall should may might must do does did please some any up down out into one
""".split())


def normalize_text(text):
    """Lowercase, remove punctuation, collapse whitespace."""
    return " ".join(re.sub(r"[^\w\s]", "", text.lower()).split())


def content_tokens(text):
    return {t for t in normalize_text(text).split() if t not in STOP_WORDS}


def jaccard(a, b):
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def d017_violations(fewshot_commands, e1_commands, limit=JACCARD_LIMIT):
    """Few-shot commands that equal or nearly duplicate an E1 command (empty list = fine)."""
    problems = []
    for fs in fewshot_commands:
        for e1 in e1_commands:
            if normalize_text(fs) == normalize_text(e1["command"]):
                problems.append(f"few-shot {fs!r} equals E1 {e1['id']} {e1['command']!r}")
                continue
            score = jaccard(content_tokens(fs), content_tokens(e1["command"]))
            if score >= limit:
                problems.append(
                    f"few-shot {fs!r} is a near duplicate of E1 {e1['id']} "
                    f"{e1['command']!r} (Jaccard {score:.2f} >= {limit})")
    return problems


def mentions(command, name):
    """True if `name` (a word or phrase) occurs in the command; a plural s/es is allowed."""
    pattern = r"(?<![a-z0-9])" + re.escape(name.lower()) + r"(?:s|es)?(?![a-z0-9])"
    return re.search(pattern, normalize_text(command)) is not None


# ----------------------------------------------------------------- the real files

def test_no_fewshot_command_overlaps_an_e1_command():
    problems = d017_violations([ex.command for ex in FEWSHOT], E1)
    assert not problems, "D-017 violated:\n" + "\n".join(problems)


def test_every_vocabulary_class_appears_in_an_e1_command():
    missing = [v for v in VOCAB if not any(mentions(c["command"], v) for c in E1)]
    assert not missing, f"vocabulary classes not named in any E1 command: {missing}"


def test_expected_constraint_room_ids_exist_in_the_scene_graph():
    room_ids = set(GRAPH.room_ids)
    for command in E1:
        assert "expected_constraint" in command, command["id"]
        constraint = command["expected_constraint"]
        if constraint is None:
            continue
        assert isinstance(constraint, list) and constraint, command["id"]
        unknown = [r for r in constraint if r not in room_ids]
        assert not unknown, f"{command['id']}: unknown room ID(s) {unknown}"


# ----------------------------------------------------------------- the checking code itself

E1_SAMPLE = [
    {"id": "s1", "command": "find the banana"},
    {"id": "s2", "command": "I'm thirsty"},
]


def test_normalization_and_tokens():
    assert normalize_text("  FIND   the Banana!! ") == "find the banana"
    assert normalize_text("I'm thirsty") == "im thirsty"
    assert content_tokens("I'm thirsty") == {"thirsty"}
    assert content_tokens("find the banana") == {"find", "banana"}


def test_detects_exact_match_after_lowercasing_and_stripping_punctuation():
    problems = d017_violations(["FIND the banana!"], E1_SAMPLE)
    assert len(problems) == 1 and "equals E1 s1" in problems[0]
    assert d017_violations(["i'm thirsty?"], E1_SAMPLE)


def test_detects_near_duplicates():
    assert d017_violations(["please find a banana"], E1_SAMPLE)  # same content tokens
    assert d017_violations(["find the banana in the kitchen"], E1_SAMPLE)  # Jaccard 2/3


def test_threshold_is_inclusive():
    # tokens {red, green, blue} vs {red, green, blue, yellow, purple}: exactly 0.6
    e1 = [{"id": "x", "command": "red green blue yellow purple"}]
    assert d017_violations(["red green blue"], e1)
    assert not d017_violations(["red green blue"], e1, limit=0.61)


def test_distinct_commands_pass():
    assert not d017_violations(["is there a book in the dining area?"], E1_SAMPLE)
    assert not d017_violations(["find the cup"], E1_SAMPLE)  # {find, cup} vs {find, banana}
    assert not d017_violations(["I'm bored"], E1_SAMPLE)


def test_empty_token_sets_are_not_a_near_duplicate():
    # Only stop words: no content tokens, so the Jaccard score is 0 (exact match still checks).
    assert jaccard(content_tokens("to the of"), content_tokens("it is")) == 0.0


def test_mentions_matches_whole_words_and_phrases():
    assert mentions("locate the cell phone", "cell phone")
    assert mentions("find the BANANAS", "banana")
    assert not mentions("check the cupboard", "cup")
    assert not mentions("find some tableware", "bowl")
