"""CLI signal handling feeds the active run cancellation predicate."""

from code_squid.console.cli.session_runner import RunCancellationController


def test_cli_ctrl_c_sets_active_run_cancellation_state() -> None:
    import signal

    controller = RunCancellationController()
    previous = signal.getsignal(signal.SIGINT)

    with controller.handle_sigint():
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler)
        handler(signal.SIGINT, None)
        assert controller.should_cancel() is True

    assert signal.getsignal(signal.SIGINT) is previous
