import sys

from vet_soap_notetaker_backend.config import BackendConfig, _default_dotenv_path


def test_default_dotenv_path_is_backend_env_in_dev(monkeypatch):
    # Not frozen: resolve to backend/.env (two levels up from the config module).
    monkeypatch.delattr(sys, "frozen", raising=False)
    path = _default_dotenv_path()
    assert path.name == ".env"
    assert path.parent.name == "backend"


def test_default_dotenv_path_is_beside_the_exe_when_frozen(monkeypatch, tmp_path):
    # Frozen build: the installer drops .env next to the backend executable.
    exe = tmp_path / "VetSoapNotetakerBackend.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    assert _default_dotenv_path() == tmp_path / ".env"


def test_from_env_loads_values_from_dotenv_file(monkeypatch, tmp_path):
    monkeypatch.delenv("VETSCRIBE_NOTE_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "VETSCRIBE_NOTE_PROVIDER=anthropic\nANTHROPIC_API_KEY=sk-from-dotenv\n"
    )

    config = BackendConfig.from_env(dotenv_path=dotenv_path)

    assert config.note_provider == "anthropic"
    assert config.anthropic_api_key == "sk-from-dotenv"


def test_from_env_prefers_real_env_var_over_dotenv_file(monkeypatch, tmp_path):
    monkeypatch.setenv("VETSCRIBE_NOTE_PROVIDER", "gemini")
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("VETSCRIBE_NOTE_PROVIDER=anthropic\n")

    config = BackendConfig.from_env(dotenv_path=dotenv_path)

    assert config.note_provider == "gemini"


def test_from_env_works_when_dotenv_file_does_not_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("VETSCRIBE_NOTE_PROVIDER", "gemini")

    config = BackendConfig.from_env(dotenv_path=tmp_path / "nonexistent.env")

    assert config.note_provider == "gemini"


def test_from_env_reads_provider_selection_and_keys(monkeypatch):
    monkeypatch.setenv("VETSCRIBE_TRANSCRIPTION_PROVIDER", "gemini")
    monkeypatch.setenv("VETSCRIBE_NOTE_PROVIDER", "anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic")
    monkeypatch.setenv("GEMINI_API_KEY", "sk-gemini")
    monkeypatch.setenv("VETSCRIBE_BACKEND_API_KEY", "shared-secret")

    config = BackendConfig.from_env()

    assert config.transcription_provider == "gemini"
    assert config.note_provider == "anthropic"
    assert config.openai_api_key == "sk-openai"
    assert config.anthropic_api_key == "sk-anthropic"
    assert config.gemini_api_key == "sk-gemini"
    assert config.backend_api_key == "shared-secret"


def test_from_env_defaults_to_openai_for_both_providers(monkeypatch):
    monkeypatch.delenv("VETSCRIBE_TRANSCRIPTION_PROVIDER", raising=False)
    monkeypatch.delenv("VETSCRIBE_NOTE_PROVIDER", raising=False)

    config = BackendConfig.from_env()

    assert config.transcription_provider == "openai"
    assert config.note_provider == "openai"


def test_from_env_defaults_backend_api_key_to_empty_string(monkeypatch):
    monkeypatch.delenv("VETSCRIBE_BACKEND_API_KEY", raising=False)

    config = BackendConfig.from_env()

    assert config.backend_api_key == ""
