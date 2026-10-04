import logging

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

logger = logging.getLogger("vet_soap_notetaker.audio_recorder")


class AudioRecorder:
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self._stream = None
        self._recording = False
        self._frames = []

    @property
    def is_recording(self) -> bool:
        return self._recording

    def _audio_callback(self, indata, frames, time, status):
        self._frames.append(indata.copy())

    def start(self):
        self._frames = []
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            callback=self._audio_callback,
        )
        self._stream.start()
        self._recording = True
        logger.info("mic recording started (sample_rate=%s, channels=%s)", self.sample_rate, self.channels)

    def stop(self):
        self._stream.stop()
        self._stream.close()
        self._recording = False
        logger.info("mic recording stopped (%d frame chunks captured)", len(self._frames))

    def save_wav(self, path):
        if self._frames:
            data = np.concatenate(self._frames)
        else:
            data = np.zeros((0, self.channels), dtype=np.float32)
        wavfile.write(str(path), self.sample_rate, data)
