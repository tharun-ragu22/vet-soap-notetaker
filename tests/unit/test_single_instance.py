from vet_soap_notetaker.single_instance import SingleInstance


def test_first_instance_acquires_the_lock(tmp_path):
    guard = SingleInstance(tmp_path / "app.lock")

    assert guard.acquire() is True

    guard.release()


def test_second_instance_cannot_acquire_while_the_first_holds_it(tmp_path):
    lock_path = tmp_path / "app.lock"
    first = SingleInstance(lock_path)
    assert first.acquire() is True

    # A second launch pointing at the same lock file must be turned away -- this
    # is what stops autostart + a manual click from both running (and the second
    # desktop app spawning a backend that crash-loops fighting over port 8443).
    second = SingleInstance(lock_path)
    assert second.acquire() is False

    first.release()


def test_releasing_the_lock_lets_a_new_instance_acquire(tmp_path):
    lock_path = tmp_path / "app.lock"
    first = SingleInstance(lock_path)
    assert first.acquire() is True
    first.release()

    # Once the holder exits (and releases), the next launch may take the lock.
    second = SingleInstance(lock_path)
    assert second.acquire() is True
    second.release()


def test_acquire_is_idempotent_for_the_holder(tmp_path):
    guard = SingleInstance(tmp_path / "app.lock")
    assert guard.acquire() is True
    # Calling acquire again on the holder is a no-op success, not a self-deadlock.
    assert guard.acquire() is True
    guard.release()
