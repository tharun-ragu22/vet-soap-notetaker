import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4


@dataclass
class InjectionRequest:
    """A mobile-originated request to inject a given exam's note into AVImark on
    the desktop. The desktop tray app polls :meth:`InjectionQueue.pending`, does
    the injection (or shows the Safety Flyout), then acks with the outcome."""

    id: str
    exam_id: str
    created_at: str
    status: str = "pending"
    outcome: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "exam_id": self.exam_id,
            "created_at": self.created_at,
            "status": self.status,
            "outcome": self.outcome,
        }


class InjectionQueue:
    """In-memory, thread-safe queue of remote injection requests.

    Deliberately not durable: an injection request is only meaningful while the
    vet is standing at the exam-room PC waiting for the note to land. A request
    that outlived a backend restart would paste into whatever chart happened to
    be open later, so dropping them on restart is the safe behavior. The
    id/clock factories are injectable so tests are deterministic (mirrors
    :class:`ExamStore`)."""

    def __init__(
        self,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], str] | None = None,
    ):
        self._requests: dict[str, InjectionRequest] = {}
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self._lock = threading.Lock()

    def request(self, exam_id: str) -> InjectionRequest:
        with self._lock:
            req = InjectionRequest(
                id=self._id_factory(),
                exam_id=exam_id,
                created_at=self._clock(),
            )
            self._requests[req.id] = req
            return req

    def pending(self) -> list[InjectionRequest]:
        # Oldest first: the desktop should service requests in the order the vet
        # made them (insertion order is chronological).
        with self._lock:
            return [r for r in self._requests.values() if r.status == "pending"]

    def get(self, request_id: str) -> InjectionRequest | None:
        with self._lock:
            return self._requests.get(request_id)

    def ack(self, request_id: str, outcome: str) -> InjectionRequest | None:
        with self._lock:
            req = self._requests.get(request_id)
            if req is None:
                return None
            req.status = "done"
            req.outcome = outcome
            return req
