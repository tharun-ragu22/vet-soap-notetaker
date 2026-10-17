from pathlib import Path

from vet_soap_notetaker_backend.llm.evals.transcription.run import upload_mime
from vet_soap_notetaker_backend.llm.transcription.audio_format import transcription_mime


def test_phone_clips_are_labelled_the_way_the_backend_labels_a_phone_upload():
    assert upload_mime("phone") == transcription_mime("audio/m4a")


def test_desktop_clips_are_labelled_as_wav():
    assert upload_mime("desktop") == "audio/wav"


def test_an_override_relabels_phone_clips_for_comparison():
    assert upload_mime("phone", override="audio/wav") == "audio/wav"
    assert upload_mime("desktop", override="audio/aac") == "audio/wav"


def test_short_clip_cases_cover_the_start_of_each_recording_and_silence_in_each_format(tmp_path):
    import json
    import math
    import wave

    from vet_soap_notetaker_backend.llm.evals.transcription.run import build_short_cases

    audio_dir = tmp_path / "eval_audio"
    audio_dir.mkdir()
    with wave.open(str(audio_dir / "visit.desktop.wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"".join(
            int(8000 * math.sin(2 * math.pi * 440 * n / 16000)).to_bytes(2, "little", signed=True)
            for n in range(16000 * 30)
        ))
    segments = [
        {"kind": "turn", "speaker": "Veterinarian", "start": 0.0, "end": 8.0, "text": "Hello Murphy."},
        {"kind": "turn", "speaker": "Owner", "start": 9.0, "end": 26.0, "text": "He limps."},
    ]
    (audio_dir / "visit.segments.json").write_text(json.dumps(segments))
    recordings = [{
        "name": "visit",
        "files": {"desktop": "visit.desktop.wav", "segments": "visit.segments.json"},
    }]

    cases = build_short_cases(audio_dir, recordings, ["phone", "desktop"], tmp_path / "clips")

    by_name = {case.name: case for case in cases}
    assert set(by_name) == {
        "visit_first_20s [phone]", "visit_first_20s [desktop]",
        "silence_10s [phone]", "silence_10s [desktop]",
        "silence_30s [phone]", "silence_30s [desktop]",
    }
    assert by_name["visit_first_20s [phone]"].expected_output == "Veterinarian: Hello Murphy.\n"
    assert by_name["silence_10s [desktop]"].expected_output == ""
    for case in cases:
        assert Path(case.inputs.audio_path).exists()
    assert by_name["visit_first_20s [phone]"].inputs.audio_path.endswith(".m4a")
    assert by_name["silence_30s [desktop]"].inputs.audio_path.endswith(".wav")


def test_results_of_both_datasets_are_saved_side_by_side(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from vet_soap_notetaker_backend.llm.evals.transcription import run

    monkeypatch.setattr(run, "RESULTS_DIR", tmp_path)

    def report(name, metadata):
        case = SimpleNamespace(
            name=f"{name} [phone]", output="", task_duration=1.0, scores={}, assertions={},
            inputs=SimpleNamespace(name=name, format="phone"), metadata=metadata,
        )
        # pydantic-evals names a report after the task function, not the dataset.
        return SimpleNamespace(name="transcribe", cases=[case], failures=[])

    long_dir = run.save_results(
        "transcription",
        report("transcription", {"audio_min": 5.0, "audio_mb": 3.7, "upload_path": "inline"}),
        "gemini", "m",
    )
    short_dir = run.save_results(
        "transcription_short_clips", report("transcription_short_clips", {"audio_mb": 0.1}), "gemini", "m"
    )

    assert long_dir != short_dir
    [short] = json.loads((short_dir / "results.json").read_text())["results"]
    assert short["case"] == "transcription_short_clips [phone]"
    assert short["audio_mb"] == 0.1
