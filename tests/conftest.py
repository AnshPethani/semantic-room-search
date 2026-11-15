import pytest

from lang_grounding import env


@pytest.fixture(autouse=True)
def _never_read_the_real_dotenv(tmp_path, monkeypatch):
    """Tests must not pick up the developer's real .env (which may hold a live API key).

    Tests of the loader itself pass explicit paths.
    """
    monkeypatch.setattr(env, "DEFAULT_ENV_PATH", tmp_path / "no-such.env")
