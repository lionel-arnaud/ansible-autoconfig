"""Entrypoint wiring — the threading guarantee behind the kill switch."""
from __future__ import annotations

import threading

from trading_agent.commands import handle_command
from trading_agent.state import State


def test_a_state_handle_cannot_be_shared_across_threads(tmp_path):
    """The constraint the two-loop design exists to respect. sqlite3 refuses a
    connection used from another thread, so each loop opens its own."""
    s = State(tmp_path / "s.db")
    errors = []

    def use_it():
        try:
            s.kill_switch_engaged()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t = threading.Thread(target=use_it)
    t.start()
    t.join()
    assert errors, "expected sqlite3 to refuse a cross-thread connection"


def test_separate_handles_on_one_file_see_each_others_writes(tmp_path):
    """Why the kill switch works: the command loop halts trading through its
    own handle while the work loop is stuck in a call it cannot interrupt."""
    path = tmp_path / "s.db"
    work_handle = State(path)
    assert not work_handle.kill_switch_engaged()

    wedged = threading.Event()
    released = threading.Event()

    def work_loop():
        State(path)  # its own handle, as in main.py
        wedged.set()
        released.wait(timeout=5)

    t = threading.Thread(target=work_loop, daemon=True)
    t.start()
    assert wedged.wait(timeout=2)

    # The command loop's handle, created while the worker is stuck.
    handle_command("/stop", state=State(path))
    assert work_handle.kill_switch_engaged(), "the halt must be visible to the worker"
    released.set()


def test_main_exposes_the_two_loops():
    from trading_agent import main as m

    assert callable(m.work_loop) and callable(m.command_loop)
    # The command loop must poll far more often than the work loop runs, or
    # /stop inherits the work loop's latency.
    assert m.COMMAND_POLL_SECONDS < m.CYCLE_INTERVAL_SECONDS / 10


# --- every injection point must actually be injected ------------------------
#
# The first Pi deploy ran clean, restarted cleanly, reported no errors, and
# found zero catalysts every cycle for twenty minutes: CatalystFeed had been
# built with http=None and news=None. Nothing failed, so nothing said so.
# These tests assert the wiring rather than the behaviour it enables.


def _paths(tmp_path):
    return {
        "state_db": str(tmp_path / "s.db"),
        "views_db": str(tmp_path / "v.db"),
        "audit_log": str(tmp_path / "a.log"),
        "universe_cache": str(tmp_path / "u.json"),
    }


def _built(tmp_path, monkeypatch):
    from trading_agent.broker import Broker
    from trading_agent.config import Config
    from trading_agent.main import build_worker

    # The only stub. alpaca-py is not installed in the test environment on
    # purpose — see test_broker_isolation — and the broker is not what these
    # tests are about.
    monkeypatch.setattr(Broker, "from_config",
                        classmethod(lambda cls, cfg: Broker.for_testing()))
    return build_worker(Config.for_testing(), _paths(tmp_path))


def test_the_catalyst_feed_is_built_with_real_clients(tmp_path, monkeypatch):
    feed = _built(tmp_path, monkeypatch)["feed"]
    assert feed._http is not None, "no trials client: upcoming_trials() returns []"
    assert feed._news is not None, "no news client: recent_news() returns []"


def test_the_universe_is_built_with_a_fetcher(tmp_path, monkeypatch):
    universe = _built(tmp_path, monkeypatch)["universe"]
    assert universe._fetcher is not None
    # And it still has a usable list before any refresh succeeds.
    assert len(universe.symbols()) >= 20


def test_stop_is_wired_to_cancel_resting_orders():
    """B2. handle_command takes on_halt as a keyword-only argument, so leaving
    it out is silent: the flag flips and the orders stay."""
    import inspect

    from trading_agent import main as m

    src = inspect.getsource(m.command_loop)
    assert "on_halt=" in src, "/stop would halt trading but leave orders resting"
    assert "cancel_all_orders" in src


def test_the_cycle_is_given_a_way_to_ask(tmp_path):
    import inspect

    from trading_agent import main as m

    assert "ask=" in inspect.getsource(m.work_loop)


def test_both_loops_are_wired_into_the_conversation():
    """The consultation subsystem existed in full — questions, briefs, reply
    parsing, follow-ups — and nothing called any of it. The agent could find a
    readout, propose a trade, and refuse itself forever for want of a view it
    had no way to ask for."""
    import inspect

    from trading_agent import main as m

    assert "ask_next" in inspect.getsource(m.consultation_loop), "nothing asks"
    assert "handle_reply" in inspect.getsource(m.command_loop), "nothing listens"


def test_the_slow_work_is_on_its_own_thread():
    """A research brief has been measured past ten minutes against the real
    backend. Trading must not queue behind it."""
    import inspect

    from trading_agent import main as m

    assert "ask_next" not in inspect.getsource(m.work_loop)
    assert "ask_next" in inspect.getsource(m.consultation_loop)
    assert "run_cycle" not in inspect.getsource(m.consultation_loop)
    # And it opens its own handles, because sqlite3 refuses a connection used
    # from another thread.
    assert "build_worker" in inspect.getsource(m.consultation_loop)


def test_every_loop_is_started():
    import inspect

    from trading_agent import main as m

    src = inspect.getsource(m.main)
    assert "work_loop" in src and "consultation_loop" in src and "command_loop" in src
