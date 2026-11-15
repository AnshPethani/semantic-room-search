import os

import pytest

from lang_grounding import env
from lang_grounding.backends import GeminiBackend, HttpResponse, create_backend
from lang_grounding.config import REPO_ROOT, ConfigError, load_config
from lang_grounding.env import load_env_file, resolve_env_path
from lang_grounding.ground import main

SECRET = "sk-test-secret-value-98765"
REAL_DEFAULT_ENV_PATH = env.DEFAULT_ENV_PATH  # captured at import, before conftest redirects it


def write(tmp_path, text, name=".env"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def load(tmp_path, text):
    environ = {}
    load_env_file(write(tmp_path, text), environ=environ)
    return environ


def unset(monkeypatch, *names):
    """Make sure the variables are absent now and are restored when the test ends."""
    for name in names:
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)


# ----------------------------------------------------------------- parsing

def test_basic_parsing(tmp_path):
    assert load(tmp_path, "A=1\nB=two words\nC=\n") == {"A": "1", "B": "two words", "C": ""}


def test_blank_lines_comments_and_inline_comments(tmp_path):
    text = "\n# a comment\n   # indented comment\nA=1\n\nB=value   # trailing comment\nC=a#b\n"
    assert load(tmp_path, text) == {"A": "1", "B": "value", "C": "a#b"}


def test_export_prefix(tmp_path):
    assert load(tmp_path, "export A=1\nexport   B = 2\n") == {"A": "1", "B": "2"}


def test_quotes_are_stripped_only_when_matching(tmp_path):
    text = "A=\"double quoted\"\nB='single quoted'\nC=\"it's\"\nD=\"a # not a comment\"\n"
    text += "E=\"quoted\"  # comment after the quote\nF=  ' padded '  \n"
    assert load(tmp_path, text) == {
        "A": "double quoted", "B": "single quoted", "C": "it's",
        "D": "a # not a comment", "E": "quoted", "F": " padded ",
    }


def test_no_variable_expansion_and_no_escapes(tmp_path):
    text = "A=$HOME\nB=${HOME}/x\nC=\"line\\nbreak\"\n"
    assert load(tmp_path, text) == {"A": "$HOME", "B": "${HOME}/x", "C": "line\\nbreak"}


def test_value_may_contain_equals_signs(tmp_path):
    assert load(tmp_path, "A=x=y==\n") == {"A": "x=y=="}


def test_later_line_wins_within_the_file(tmp_path):
    assert load(tmp_path, "A=1\nA=2\n") == {"A": "2"}


def test_utf8_bom_and_crlf_are_tolerated(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(b"\xef\xbb\xbfA=1\r\nB=2\r\n")
    environ = {}
    load_env_file(path, environ=environ)
    assert environ == {"A": "1", "B": "2"}


# ----------------------------------------------------------------- environment rules

def test_existing_variable_wins(tmp_path):
    path = write(tmp_path, "A=from-file\nB=from-file\n")
    environ = {"A": "from-env"}
    load_env_file(path, environ=environ)
    assert environ == {"A": "from-env", "B": "from-file"}


def test_existing_empty_variable_still_wins(tmp_path):
    environ = {"A": ""}
    load_env_file(write(tmp_path, "A=from-file\n"), environ=environ)
    assert environ == {"A": ""}


def test_default_target_is_os_environ(tmp_path, monkeypatch):
    unset(monkeypatch, "LG_TEST_NEW", "LG_TEST_OLD")
    monkeypatch.setenv("LG_TEST_OLD", "from-env")
    load_env_file(write(tmp_path, "LG_TEST_NEW=from-file\nLG_TEST_OLD=from-file\n"))
    assert os.environ["LG_TEST_NEW"] == "from-file"
    assert os.environ["LG_TEST_OLD"] == "from-env"


def test_missing_file_is_not_an_error(tmp_path):
    environ = {}
    load_env_file(tmp_path / "does-not-exist.env", environ=environ)
    assert environ == {}


def test_default_path_is_the_repo_root_env_file():
    assert REAL_DEFAULT_ENV_PATH == REPO_ROOT / ".env"
    # during tests conftest redirects the default; resolve_env_path follows the redirect
    assert resolve_env_path(None) == env.DEFAULT_ENV_PATH != REAL_DEFAULT_ENV_PATH


def test_relative_path_is_relative_to_the_repo_root(tmp_path):
    assert resolve_env_path("sub/x.env") == REPO_ROOT / "sub" / "x.env"
    assert resolve_env_path(tmp_path / "x.env") == tmp_path / "x.env"


def test_default_path_is_used_when_no_path_given(tmp_path, monkeypatch):
    path = write(tmp_path, "A=1\n", name="default.env")
    monkeypatch.setattr(env, "DEFAULT_ENV_PATH", path)
    environ = {}
    load_env_file(environ=environ)
    assert environ == {"A": "1"}


# ----------------------------------------------------------------- errors never show values

@pytest.mark.parametrize("line", [
    f'GEMINI_API_KEY="{SECRET}',            # unterminated quote
    f"GEMINI_API_KEY='{SECRET}\"",          # mismatched quotes
    SECRET,                                 # a bare secret with no NAME=
    f"1BAD-NAME={SECRET}",                  # invalid variable name
    f'GEMINI_API_KEY="{SECRET}"extra',      # text after the closing quote
    f"export {SECRET}",                     # export without an assignment
])
def test_malformed_line_error_names_the_line_but_not_the_value(tmp_path, line):
    path = write(tmp_path, f"# comment\nGOOD=1\n{line}\nLATER=2\n")
    environ = {}
    with pytest.raises(ConfigError) as info:
        load_env_file(path, environ=environ)
    message = str(info.value)
    assert "line 3" in message
    assert str(path) in message
    assert SECRET not in message
    assert "GEMINI_API_KEY" not in message and "1BAD-NAME" not in message
    assert environ == {}  # nothing was applied from a malformed file


def test_unreadable_files_are_config_errors(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_env_file(tmp_path, environ={})  # a directory
    binary = tmp_path / "bin.env"
    binary.write_bytes(b"\xff\xfe\x00\x80")
    with pytest.raises(ConfigError, match="UTF-8"):
        load_env_file(binary, environ={})


# ----------------------------------------------------------------- wiring

def test_key_from_env_file_reaches_the_gemini_backend(tmp_path):
    path = write(tmp_path, f"GEMINI_API_KEY={SECRET}\nGEMINI_MODEL=some-model\n")
    environ = {}
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        create_backend("gemini", load_config(), env=environ)  # before loading: no key

    load_env_file(path, environ=environ)
    backend = create_backend("gemini", load_config(), env=environ)
    assert isinstance(backend, GeminiBackend)
    assert backend.model == "some-model"
    assert SECRET not in repr(backend)

    sent = {}

    def fake_post(url, headers, payload, timeout):
        sent["headers"] = dict(headers)
        return HttpResponse(200, '{"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}')

    backend._http_post = fake_post  # replace the HTTP layer; no network
    backend.generate("system", "user", {"type": "object"})
    assert sent["headers"] == {"x-goog-api-key": SECRET}


def test_load_config_reads_the_env_file(tmp_path, monkeypatch):
    unset(monkeypatch, "LG_TEST_FROM_ENV_FILE")
    path = write(tmp_path, "LG_TEST_FROM_ENV_FILE=hello\n")
    load_config(env_file=path)
    assert os.environ["LG_TEST_FROM_ENV_FILE"] == "hello"


def test_load_config_reads_the_default_env_file(tmp_path, monkeypatch):
    unset(monkeypatch, "LG_TEST_FROM_DEFAULT")
    monkeypatch.setattr(env, "DEFAULT_ENV_PATH", write(tmp_path, "LG_TEST_FROM_DEFAULT=yes\n"))
    load_config()
    assert os.environ["LG_TEST_FROM_DEFAULT"] == "yes"


def test_cli_reads_the_key_from_the_env_file(tmp_path, monkeypatch, capsys):
    # The file has a key but no model: the error is about the missing model, not the key,
    # which shows the key was read from the file, with nothing exported and no network used.
    unset(monkeypatch, "GEMINI_API_KEY", "GEMINI_MODEL")
    path = write(tmp_path, f"GEMINI_API_KEY={SECRET}\n")
    code = main(["find the banana", "--backend", "gemini", "--no-cache", "--no-log",
                 "--env-file", str(path)])
    err = capsys.readouterr().err
    assert code == 2
    assert "no Gemini model name" in err
    assert "GEMINI_API_KEY is not set" not in err
    assert SECRET not in err


def test_cli_malformed_env_file_is_a_clean_error(tmp_path, capsys):
    path = write(tmp_path, f"{SECRET}\n")
    code = main(["find the banana", "--no-cache", "--no-log", "--env-file", str(path)])
    err = capsys.readouterr().err
    assert code == 2 and "line 1" in err and SECRET not in err


def test_cli_missing_env_file_is_fine(tmp_path, capsys):
    code = main(["find the banana", "--backend", "fake", "--no-cache", "--no-log",
                 "--env-file", str(tmp_path / "missing.env")])
    assert code == 0
    capsys.readouterr()
