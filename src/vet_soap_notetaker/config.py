import json
from dataclasses import asdict, dataclass

DEFAULT_CONFIG = {
    "api_endpoint": "https://localhost:8443/api/soap",
    "api_timeout_seconds": 30,
    # Read timeout for the calls that wait on the AI provider (transcription +
    # note generation), which can take minutes for a long exam. Matches the
    # mobile app's 480s. A separate key, not a new api_timeout_seconds default,
    # so installs that already saved 30 pick it up without a migration.
    "api_generate_timeout_seconds": 480,
    "hotkey": "<ctrl>+<shift>+r",
    "api_key": "",
    "target_window_matcher": "AVImark",
    "launch_on_startup": False,
    # Per-site AVImark SOAP-box calibration (avimark_calibration.BoxCalibration
    # serialized via .to_dict()), or None until the vet has calibrated. Kept as a
    # plain dict here so config stays pure data; main.py rehydrates it.
    "avimark_calibration": None,
}


@dataclass
class Config:
    api_endpoint: str
    api_timeout_seconds: int
    hotkey: str
    api_key: str = ""
    target_window_matcher: str = "AVImark"
    launch_on_startup: bool = False
    avimark_calibration: dict | None = None
    api_generate_timeout_seconds: int = 480

    @classmethod
    def load(cls, path):
        if not path.exists():
            return cls(**DEFAULT_CONFIG)
        values = {**DEFAULT_CONFIG, **json.loads(path.read_text())}
        return cls(**values)

    def save(self, path):
        path.write_text(json.dumps(asdict(self)))
