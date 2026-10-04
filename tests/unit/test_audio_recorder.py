import numpy as np

from vet_soap_notetaker.audio_recorder import AudioRecorder


def test_start_creates_input_stream_and_sets_recording_true(mocker):
    mock_stream_cls = mocker.patch("vet_soap_notetaker.audio_recorder.sd.InputStream")
    recorder = AudioRecorder(sample_rate=16000, channels=1)

    recorder.start()

    mock_stream_cls.assert_called_once()
    _, kwargs = mock_stream_cls.call_args
    assert kwargs["samplerate"] == 16000
    assert kwargs["channels"] == 1
    mock_stream_cls.return_value.start.assert_called_once()
    assert recorder.is_recording is True


def test_stop_stops_and_closes_stream_and_sets_recording_false(mocker):
    mock_stream_cls = mocker.patch("vet_soap_notetaker.audio_recorder.sd.InputStream")
    recorder = AudioRecorder(sample_rate=16000, channels=1)
    recorder.start()

    recorder.stop()

    mock_stream_cls.return_value.stop.assert_called_once()
    mock_stream_cls.return_value.close.assert_called_once()
    assert recorder.is_recording is False


def test_start_passes_audio_callback_to_input_stream(mocker):
    mock_stream_cls = mocker.patch("vet_soap_notetaker.audio_recorder.sd.InputStream")
    recorder = AudioRecorder(sample_rate=16000, channels=1)

    recorder.start()

    _, kwargs = mock_stream_cls.call_args
    assert kwargs["callback"] == recorder._audio_callback


def test_audio_callback_appends_copies_of_incoming_frames_to_buffer(mocker):
    mocker.patch("vet_soap_notetaker.audio_recorder.sd.InputStream")
    recorder = AudioRecorder(sample_rate=16000, channels=1)
    recorder.start()
    chunk = np.array([[0.1], [0.2]], dtype=np.float32)

    recorder._audio_callback(chunk, 2, None, None)
    chunk[:] = 0.0

    assert len(recorder._frames) == 1
    np.testing.assert_array_equal(recorder._frames[0], np.array([[0.1], [0.2]], dtype=np.float32))


def test_save_wav_writes_concatenated_frames_at_configured_sample_rate(mocker, tmp_path):
    mocker.patch("vet_soap_notetaker.audio_recorder.sd.InputStream")
    mock_write = mocker.patch("vet_soap_notetaker.audio_recorder.wavfile.write")
    recorder = AudioRecorder(sample_rate=16000, channels=1)
    recorder.start()
    recorder._audio_callback(np.array([[0.1], [0.2]], dtype=np.float32), 2, None, None)
    recorder._audio_callback(np.array([[0.3]], dtype=np.float32), 1, None, None)
    output_path = tmp_path / "note.wav"

    recorder.save_wav(output_path)

    mock_write.assert_called_once()
    args, _ = mock_write.call_args
    assert args[0] == str(output_path)
    assert args[1] == 16000
    np.testing.assert_array_equal(args[2], np.array([[0.1], [0.2], [0.3]], dtype=np.float32))


def test_save_wav_with_no_frames_writes_empty_array(mocker, tmp_path):
    mocker.patch("vet_soap_notetaker.audio_recorder.sd.InputStream")
    mock_write = mocker.patch("vet_soap_notetaker.audio_recorder.wavfile.write")
    recorder = AudioRecorder(sample_rate=16000, channels=1)
    output_path = tmp_path / "note.wav"

    recorder.save_wav(output_path)

    args, _ = mock_write.call_args
    assert args[2].shape == (0, 1)
