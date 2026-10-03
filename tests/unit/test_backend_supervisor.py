from vetscribe.backend_supervisor import BackendSupervisor


class FakeProcess:
    """A stand-in for subprocess.Popen the supervisor can poll/terminate.

    ``alive`` controls what poll() reports: None while running, the return code
    once it has "exited". terminate()/kill() mark it exited so the supervisor
    sees it stop.
    """

    def __init__(self, returncode=0):
        self._returncode = returncode
        self.returncode = None
        self.alive = True
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self.alive else self.returncode

    def die(self):
        self.alive = False
        self.returncode = self._returncode

    def terminate(self):
        self.terminated = True
        self.die()

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True
        self.die()


def test_start_is_a_noop_when_no_bundled_backend():
    # Dev checkout: launch is None, so nothing is spawned and no thread runs.
    supervisor = BackendSupervisor(launch=None)
    supervisor.start()
    assert supervisor._process is None
    assert supervisor._thread is None
    supervisor.stop()  # must be safe even though nothing started


def test_process_once_launches_the_backend_on_first_call():
    launches = []

    def launch():
        proc = FakeProcess()
        launches.append(proc)
        return proc

    supervisor = BackendSupervisor(launch=launch)
    supervisor.process_once()

    assert len(launches) == 1
    assert supervisor._process is launches[0]


def test_process_once_leaves_a_live_backend_alone():
    launches = []

    def launch():
        proc = FakeProcess()
        launches.append(proc)
        return proc

    supervisor = BackendSupervisor(launch=launch)
    supervisor.process_once()
    supervisor.process_once()  # still alive -> must not relaunch

    assert len(launches) == 1


def test_process_once_relaunches_a_dead_backend():
    launches = []

    def launch():
        proc = FakeProcess(returncode=1)
        launches.append(proc)
        return proc

    supervisor = BackendSupervisor(launch=launch)
    supervisor.process_once()
    launches[0].die()  # the backend crashed
    supervisor.process_once()

    assert len(launches) == 2
    assert supervisor._process is launches[1]


def test_failed_launch_does_not_raise_and_retries_next_poll():
    attempts = {"n": 0}

    def launch():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise OSError("exe missing")
        return FakeProcess()

    supervisor = BackendSupervisor(launch=launch)
    supervisor.process_once()  # first launch raises, swallowed
    assert supervisor._process is None

    supervisor.process_once()  # retries and succeeds
    assert supervisor._process is not None
    assert attempts["n"] == 2


def test_stop_terminates_a_running_backend():
    proc = FakeProcess()
    supervisor = BackendSupervisor(launch=lambda: proc)
    supervisor.process_once()

    supervisor.stop()

    assert proc.terminated is True


def test_stop_is_safe_when_backend_already_exited():
    proc = FakeProcess()
    supervisor = BackendSupervisor(launch=lambda: proc)
    supervisor.process_once()
    proc.die()

    supervisor.stop()  # must not try to terminate an already-dead process

    assert proc.terminated is False


def test_start_then_stop_runs_the_poll_loop_and_shuts_down():
    proc = FakeProcess()
    # A tiny interval so the daemon thread actually ticks before we stop it.
    supervisor = BackendSupervisor(launch=lambda: proc, poll_interval_seconds=0.01)

    supervisor.start()
    assert supervisor._process is proc  # launched immediately on start
    supervisor.stop()

    assert supervisor._thread is not None
    assert not supervisor._thread.is_alive()
    assert proc.terminated is True
