from vet_soap_notetaker.activation import ActivationWatcher, request_activation


def test_a_request_from_a_second_launch_fires_once_and_is_consumed(tmp_path):
    path = tmp_path / "show_history.request"
    calls = []
    watcher = ActivationWatcher(path, on_activate=lambda: calls.append("activate"))

    request_activation(path)
    watcher.poll()
    watcher.poll()

    assert calls == ["activate"]
    assert not path.exists()


def test_poll_does_nothing_without_a_request(tmp_path):
    calls = []
    watcher = ActivationWatcher(tmp_path / "show_history.request", on_activate=lambda: calls.append(1))

    watcher.poll()

    assert calls == []


def test_clear_drops_a_stale_request_left_from_before_startup(tmp_path):
    path = tmp_path / "show_history.request"
    calls = []
    watcher = ActivationWatcher(path, on_activate=lambda: calls.append(1))
    request_activation(path)

    watcher.clear()
    watcher.poll()

    assert calls == []


def test_request_activation_creates_the_folder(tmp_path):
    path = tmp_path / "missing" / "show_history.request"

    request_activation(path)

    assert path.exists()


def test_watch_polls_on_the_tk_loop_and_reschedules(tmp_path):
    path = tmp_path / "show_history.request"
    calls = []
    scheduled = []

    class FakeRoot:
        def after(self, ms, fn):
            scheduled.append((ms, fn))

    watcher = ActivationWatcher(path, on_activate=lambda: calls.append(1))
    watcher.watch(FakeRoot(), interval_ms=500)
    assert [ms for ms, _ in scheduled] == [500]

    request_activation(path)
    scheduled.pop()[1]()

    assert calls == [1]
    assert [ms for ms, _ in scheduled] == [500]  # keeps polling


def test_a_failing_handler_does_not_stop_the_polling(tmp_path):
    path = tmp_path / "show_history.request"
    scheduled = []

    class FakeRoot:
        def after(self, ms, fn):
            scheduled.append(fn)

    def boom():
        raise RuntimeError("history failed")

    watcher = ActivationWatcher(path, on_activate=boom)
    watcher.watch(FakeRoot())
    request_activation(path)
    scheduled.pop()()

    assert len(scheduled) == 1
