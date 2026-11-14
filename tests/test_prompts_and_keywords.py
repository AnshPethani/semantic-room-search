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

def test_placeholder_prompt_files_build():
    builder = PromptBuilder.from_config(load_config())
    prompts = builder.build("  find something  ", GRAPH, VOCAB)
    assert "PLACEHOLDER" in builder.system_template
    assert render_for_prompt(GRAPH) in prompts.system
    assert ", ".join(VOCAB) in prompts.system
    assert "PLACEHOLDER: search the dining area for a bowl" in prompts.system
    assert "{scene_graph}" not in prompts.system and "{examples}" not in prompts.system
    assert prompts.user == "Command: find something"


def test_placeholder_fewshot_examples_pass_the_validator():
    config = load_config()
    examples = load_fewshot(config.resolve(config.paths.fewshot))
    assert examples
    for ex in examples:
        assert isinstance(validate_grounding(ex.response, GRAPH, VOCAB), GroundingResult)


def test_fewshot_file_has_placeholder_marker():
    text = (ROOT / "configs" / "prompts" / "fewshot.json").read_text()
    assert "PLACEHOLDER" in text


def test_template_must_contain_all_placeholders():
    with pytest.raises(ConfigError, match="missing placeholder"):
        PromptBuilder("only {scene_graph} here")


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
    "[]",
    '{"examples": "x"}',
    '{"examples": [{"command": "", "response": {}}]}',
    '{"examples": [{"command": "a", "response": []}]}',
])
def test_bad_fewshot_files(tmp_path, content):
    p = tmp_path / "f.json"
    p.write_text(content)
    with pytest.raises(ConfigError):
        load_fewshot(p)


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
