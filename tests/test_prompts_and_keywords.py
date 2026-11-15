import json
from pathlib import Path

import pytest

from lang_grounding.config import ConfigError, load_config
from lang_grounding.grounding_output import GroundingResult, load_vocabulary, validate_grounding
from lang_grounding.keyword_fallback import (
    KeywordTable,
    check_keyword_table,
    keyword_ground,
    load_keyword_table,
)
from lang_grounding.prompts import (
    FewShotExample,
    PromptBuilder,
    build_retry_prompt,
    load_fewshot,
)
from lang_grounding.scene_graph import load_scene_graph, render_for_prompt

ROOT = Path(__file__).resolve().parents[1]
GRAPH = load_scene_graph(ROOT / "data" / "scene_graph.placeholder.json")
VOCAB = load_vocabulary()
TABLE = load_keyword_table()
ROOMS = ["E", "K", "LR", "D", "B1", "B2"]


# ----------------------------------------------------------------- config

def test_default_config_loads():
    config = load_config()
    assert config.ollama.model == "llama3.1:8b"
    assert config.gemini.model is None
    assert config.floor == 0.001
    assert config.resolve("configs/x").is_absolute()


def test_bad_config(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"gemini": {}}')
    with pytest.raises(ConfigError, match="invalid config"):
        load_config(p)
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "missing.json")


# ----------------------------------------------------------------- prompts

def test_real_prompt_files_build():
    config = load_config()
    builder = PromptBuilder.from_config(config)
    examples = load_fewshot(config.resolve(config.paths.fewshot))
    assert examples and builder.examples == tuple(examples)
    assert "{scene_graph}" in builder.system_template
    assert "{vocabulary}" in builder.system_template

    # Works whether system.md has an {examples} placeholder or not (D-116): either way every
    # example appears in the final system prompt and no placeholder is left unfilled.
    prompts = builder.build("  find something  ", GRAPH, VOCAB)
    assert render_for_prompt(GRAPH) in prompts.system
    assert ", ".join(VOCAB) in prompts.system
    for placeholder in ("{scene_graph}", "{vocabulary}", "{examples}"):
        assert placeholder not in prompts.system
    for ex in examples:
        assert f"Command: {ex.command}" in prompts.system
        assert json.dumps(ex.response, ensure_ascii=False) in prompts.system
    assert prompts.user == "Command: find something"


def test_every_fewshot_response_passes_the_validator():
    """Each few-shot response must be a valid answer for the real graph and vocabulary."""
    config = load_config()
    graph = load_scene_graph(config.resolve(config.paths.scene_graph))
    vocabulary = load_vocabulary(config.resolve(config.paths.vocabulary))
    examples = load_fewshot(config.resolve(config.paths.fewshot))
    assert examples
    for ex in examples:
        outcome = validate_grounding(ex.response, graph, vocabulary)
        assert isinstance(outcome, GroundingResult), f"{ex.command!r}: {outcome}"


def test_template_needs_scene_graph_and_vocabulary_but_not_examples():
    with pytest.raises(ConfigError, match="missing placeholder"):
        PromptBuilder("only {scene_graph} here")
    with pytest.raises(ConfigError, match="missing placeholder"):
        PromptBuilder("only {vocabulary} here")
    builder = PromptBuilder("graph {scene_graph} vocab {vocabulary}")
    system = builder.build("c", GRAPH, ["one"]).system
    assert "vocab one" in system and "## Examples" not in system  # no examples, nothing added


def test_examples_are_appended_when_the_template_has_no_placeholder():
    example = FewShotExample("my command", {"targets": ["x"]})
    builder = PromptBuilder("graph {scene_graph} vocab {vocabulary}\n", [example])
    system = builder.build("c", GRAPH, ["one"]).system
    assert system.startswith("graph ")
    assert system.rstrip().endswith('Response: {"targets": ["x"]}')
    assert system.count("## Examples") == 1
    assert "Command: my command" in system


def test_examples_are_rendered_and_substitution_is_single_pass():
    example = FewShotExample("cmd with {vocabulary} text", {"targets": ["x"]})
    builder = PromptBuilder("A {scene_graph}\nB {vocabulary}\nC {examples}", [example])
    system = builder.build("c", GRAPH, ["one", "two"]).system
    assert "B one, two" in system
    assert 'Response: {"targets": ["x"]}' in system
    assert "Command: cmd with {vocabulary} text" in system  # not substituted twice


def test_no_examples_renders_none():
    builder = PromptBuilder("{scene_graph} {vocabulary} {examples}")
    assert builder.render_examples() == "(none)"


@pytest.mark.parametrize("content", [
    "not json",
    '"just a string"',
    '{"other": []}',  # an object needs an "examples" key
    '{"examples": "x"}',
    '["just a string"]',
    '[{"command": "", "response": {}}]',
    '[{"command": "a", "response": []}]',
    '[{"command": "a"}]',
    '{"examples": [{"command": "a"}]}',
])
def test_bad_fewshot_files(tmp_path, content):
    p = tmp_path / "f.json"
    p.write_text(content)
    with pytest.raises(ConfigError):
        load_fewshot(p)


@pytest.mark.parametrize("content", ["[]", '{"examples": []}'])
def test_empty_fewshot_is_allowed(tmp_path, content):
    p = tmp_path / "f.json"
    p.write_text(content)
    assert load_fewshot(p) == []


def test_fewshot_accepts_a_bare_list_and_an_examples_object(tmp_path):
    items = [{"command": "a command", "response": {"targets": ["x"]}}]
    as_list = tmp_path / "list.json"
    as_list.write_text(json.dumps(items))
    as_object = tmp_path / "object.json"
    as_object.write_text(json.dumps({"examples": items}))
    expected = [FewShotExample("a command", {"targets": ["x"]})]
    assert load_fewshot(as_list) == expected
    assert load_fewshot(as_object) == expected


def test_retry_prompt_appends_errors():
    text = build_retry_prompt("Command: x", ["targets: bad", "room_prior: worse"])
    assert text.startswith("Command: x")
    assert "- targets: bad" in text and "- room_prior: worse" in text


# ----------------------------------------------------------------- keyword table

def test_real_table_is_valid_and_covers_vocabulary():
    assert check_keyword_table(TABLE, GRAPH, VOCAB) == []
    covered = {t for e in TABLE.entries for t in e.targets}
    assert set(VOCAB) <= covered
    keywords = {k for e in TABLE.entries for k in e.keywords}
    assert {"food", "drink", "electronics", "toy", "reading"} <= keywords


def test_every_vocabulary_class_matches_itself():
    for name in VOCAB:
        match = keyword_ground(f"find the {name}", GRAPH, VOCAB, TABLE)
        assert not match.no_match
        assert name in match.result.targets, name


def test_specific_class_command():
    match = keyword_ground("find the banana", GRAPH, VOCAB, TABLE)
    assert match.result.targets == ["banana"]
    assert match.matched == ("banana",)
    prior = match.result.room_prior
    assert max(prior, key=prior.get) == "K"
    assert abs(sum(prior.values()) - 1) < 1e-9
    assert match.result.room_constraint is None


@pytest.mark.parametrize("command, expected", [
    ("find me food", {"banana", "apple", "orange", "sandwich"}),
    ("find something to drink from", {"cup", "bottle"}),
    ("find some electronics", {"laptop", "remote", "cell phone"}),
    ("find a toy", {"teddy bear"}),
    ("I want to read", {"book"}),
])
def test_category_commands(command, expected):
    assert set(keyword_ground(command, GRAPH, VOCAB, TABLE).result.targets) == expected


def test_multiple_matches_combine_in_command_order():
    match = keyword_ground("find a remote and a banana", GRAPH, VOCAB, TABLE)
    assert match.result.targets == ["remote", "banana"]
    prior = match.result.room_prior
    assert abs(sum(prior.values()) - 1) < 1e-9
    assert prior["LR"] > prior["D"]


def test_whole_word_and_plural_matching():
    assert keyword_ground("find the bananas", GRAPH, VOCAB, TABLE).result.targets == ["banana"]
    assert keyword_ground("FIND   THE  Banana", GRAPH, VOCAB, TABLE).result.targets == ["banana"]
    assert keyword_ground("check the cupboard", GRAPH, VOCAB, TABLE).no_match


def test_no_match_gives_uniform_prior_and_whole_vocabulary():
    match = keyword_ground("xyzzy plugh", GRAPH, VOCAB, TABLE)
    assert match.no_match is True
    assert match.matched == ()
    assert match.result.targets == list(VOCAB)
    assert set(match.result.room_prior) == set(ROOMS)
    assert all(abs(p - 1 / 6) < 1e-9 for p in match.result.room_prior.values())


def test_entries_outside_the_vocabulary_are_skipped():
    small = [v for v in VOCAB if v != "banana"]
    assert keyword_ground("find the banana", GRAPH, small, TABLE).no_match


def test_invalid_entry_is_reported_by_check():
    table = KeywordTable.model_validate({"entries": [
        {"keywords": ["x"], "targets": ["mug"],
         "room_prior": {"K": 1.0}}]})
    problems = check_keyword_table(table, GRAPH, VOCAB)
    assert problems and all(p.startswith("entry 'x'") for p in problems)


def test_keyword_table_file_errors(tmp_path):
    p = tmp_path / "t.json"
    p.write_text('{"entries": [{"keywords": [], "targets": ["a"], "room_prior": {}}]}')
    with pytest.raises(ConfigError, match="non-empty keywords"):
        load_keyword_table(p)
    with pytest.raises(ConfigError, match="cannot read"):
        load_keyword_table(tmp_path / "missing.json")
