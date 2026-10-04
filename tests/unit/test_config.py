import json

from vet_soap_notetaker.config import Config, DEFAULT_CONFIG


def test_config_returns_defaults_when_no_file_exists(tmp_path):
    config_path = tmp_path / "config.json"

    config = Config.load(config_path)

    assert config.api_endpoint == DEFAULT_CONFIG["api_endpoint"]
    assert config.api_timeout_seconds == DEFAULT_CONFIG["api_timeout_seconds"]
    assert config.hotkey == DEFAULT_CONFIG["hotkey"]
    assert config.api_key == DEFAULT_CONFIG["api_key"]
    assert config.target_window_matcher == DEFAULT_CONFIG["target_window_matcher"]
    assert config.launch_on_startup == DEFAULT_CONFIG["launch_on_startup"]


def test_config_loads_values_from_existing_file(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "api_endpoint": "https://vet_soap_notetaker.example.com/api/soap",
        "api_timeout_seconds": 45,
        "hotkey": "<ctrl>+<alt>+v",
        "api_key": "secret-token",
        "target_window_matcher": "PracticeSoft",
        "launch_on_startup": True,
    }))

    config = Config.load(config_path)

    assert config.api_endpoint == "https://vet_soap_notetaker.example.com/api/soap"
    assert config.api_timeout_seconds == 45
    assert config.hotkey == "<ctrl>+<alt>+v"
    assert config.api_key == "secret-token"
    assert config.target_window_matcher == "PracticeSoft"
    assert config.launch_on_startup is True


def test_config_fills_missing_keys_with_defaults(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"api_endpoint": "https://vet_soap_notetaker.example.com/api/soap"}))

    config = Config.load(config_path)

    assert config.api_endpoint == "https://vet_soap_notetaker.example.com/api/soap"
    assert config.api_timeout_seconds == DEFAULT_CONFIG["api_timeout_seconds"]
    assert config.hotkey == DEFAULT_CONFIG["hotkey"]


def test_config_save_writes_json_that_can_be_reloaded(tmp_path):
    config_path = tmp_path / "config.json"
    config = Config(api_endpoint="https://vet_soap_notetaker.example.com/api/soap", api_timeout_seconds=60, hotkey="<ctrl>+<alt>+v")

    config.save(config_path)
    reloaded = Config.load(config_path)

    assert reloaded == config


def test_config_defaults_avimark_calibration_to_none(tmp_path):
    config = Config.load(tmp_path / "config.json")

    assert config.avimark_calibration is None


def test_config_round_trips_an_avimark_calibration(tmp_path):
    config_path = tmp_path / "config.json"
    calibration = {
        "subjective": {"control_id": 1001, "class_name": "Edit", "rel_x": 0.1, "rel_y": 0.2},
        "objective": {"control_id": 1002, "class_name": "Edit", "rel_x": 0.1, "rel_y": 0.4},
    }
    config = Config(
        api_endpoint="http://localhost:8443/api/soap",
        api_timeout_seconds=30,
        hotkey="<ctrl>+<shift>+r",
        avimark_calibration=calibration,
    )

    config.save(config_path)

    assert Config.load(config_path).avimark_calibration == calibration


def test_config_without_calibration_key_loads_as_none(tmp_path):
    # a config written before calibration existed must still load
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"api_endpoint": "http://localhost:8443/api/soap"}))

    assert Config.load(config_path).avimark_calibration is None
