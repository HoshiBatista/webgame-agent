import json
import logging

from generation.transport_diagnostics import TransportDiagnostics, TransportLogFormatter, error_facts


def test_diagnostics_drop_sensitive_trace_info_and_exception_text():
    diag = TransportDiagnostics(trace_id=None, config={"read_timeout": 10, "connect_timeout": 2},
                                request_bytes=42, streaming=True)
    for _ in range(50):
        diag.trace("http11.receive_response_headers.complete", {
            "return_value": (b"HTTP/1.1", 200, b"OK", [(b"Authorization", b"Bearer SECRET")]),
            "exception": ValueError("prompt and key SECRET"),
        })
    snapshot = diag.finish("test")
    assert len(snapshot["http_events"]) == 32
    assert "SECRET" not in json.dumps(snapshot)
    record = logging.LogRecord("generation.transport", logging.INFO, "", 0, "SECRET", (), None)
    record.transport_event = "finished"
    record.transport = snapshot
    output = TransportLogFormatter().format(record)
    assert json.loads(output)["transport"]["trace_id"] == snapshot["trace_id"]
    assert "SECRET" not in output


def test_exception_chain_retains_errno_without_message():
    try:
        try:
            raise ConnectionResetError(104, "SECRET")
        except OSError as exc:
            raise RuntimeError("Bearer SECRET") from exc
    except RuntimeError as exc:
        assert error_facts(exc) == [{"type": "RuntimeError"}, {"type": "ConnectionResetError", "errno": 104}]
