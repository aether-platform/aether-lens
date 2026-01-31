import threading

_active_loops = {}
_lock = threading.Lock()


def register_loop(target_dir, observer):
    with _lock:
        if target_dir in _active_loops:
            _active_loops[target_dir].stop()
            _active_loops[target_dir].join()
        _active_loops[target_dir] = observer


def stop_loop(target_dir):
    with _lock:
        if target_dir in _active_loops:
            observer = _active_loops.pop(target_dir)
            observer.stop()
            observer.join()
            return True
        return False


def list_loops():
    with _lock:
        return list(_active_loops.keys())
