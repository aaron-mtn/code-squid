from storage.error_log import write_error_log


def test_write_error_log_writes_latest_log_with_exception_text(tmp_path) -> None:
    error = RuntimeError("provider unavailable")

    log_path = write_error_log(tmp_path / ".code-squid", error)
    log_text = log_path.read_text(encoding="utf-8")

    assert log_path == tmp_path / ".code-squid" / "logs" / "latest.log"
    assert log_text.startswith("Timestamp: ")
    assert "RuntimeError: provider unavailable" in log_text
