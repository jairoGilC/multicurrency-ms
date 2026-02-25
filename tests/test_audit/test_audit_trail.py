import pytest

from src.audit.audit_trail import AuditTrail
from src.models import AuditEntry


@pytest.fixture
def trail() -> AuditTrail:
    return AuditTrail()


class TestRecord:
    def test_record_creates_entry(self, trail: AuditTrail) -> None:
        entry = trail.record("VALIDATION_PASSED", "Refund request validated successfully")
        assert isinstance(entry, AuditEntry)
        assert entry.action == "VALIDATION_PASSED"
        assert entry.details == "Refund request validated successfully"
        assert entry.data == {}

    def test_record_with_data(self, trail: AuditTrail) -> None:
        data = {"original": "5.20", "current": "5.35"}
        entry = trail.record("RATE_LOOKUP", "Retrieved exchange rates", data=data)
        assert entry.data == data

    def test_record_stores_entry(self, trail: AuditTrail) -> None:
        trail.record("ACTION_1", "First action")
        trail.record("ACTION_2", "Second action")
        assert len(trail.get_entries()) == 2


class TestGetEntries:
    def test_empty_trail(self, trail: AuditTrail) -> None:
        assert trail.get_entries() == []

    def test_returns_chronological_order(self, trail: AuditTrail) -> None:
        trail.record("FIRST", "First")
        trail.record("SECOND", "Second")
        trail.record("THIRD", "Third")
        entries = trail.get_entries()
        assert entries[0].action == "FIRST"
        assert entries[1].action == "SECOND"
        assert entries[2].action == "THIRD"


class TestToDict:
    def test_empty_trail_returns_empty_list(self, trail: AuditTrail) -> None:
        assert trail.to_dict() == []

    def test_serializes_entries(self, trail: AuditTrail) -> None:
        trail.record("ACTION", "Some details", data={"key": "value"})
        result = trail.to_dict()
        assert len(result) == 1
        entry = result[0]
        assert entry["action"] == "ACTION"
        assert entry["details"] == "Some details"
        assert entry["data"] == {"key": "value"}
        assert "timestamp" in entry

    def test_multiple_entries(self, trail: AuditTrail) -> None:
        trail.record("A", "First")
        trail.record("B", "Second")
        result = trail.to_dict()
        assert len(result) == 2
        assert result[0]["action"] == "A"
        assert result[1]["action"] == "B"


class TestFormatReport:
    def test_empty_trail_returns_empty_string(self, trail: AuditTrail) -> None:
        assert trail.format_report() == ""

    def test_format_without_data(self, trail: AuditTrail) -> None:
        entry = trail.record("VALIDATION_PASSED", "Refund request validated successfully")
        report = trail.format_report()
        ts = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        expected = f"[{ts}] VALIDATION_PASSED: Refund request validated successfully"
        assert report == expected

    def test_format_with_data(self, trail: AuditTrail) -> None:
        entry = trail.record(
            "RATE_LOOKUP",
            "Retrieved exchange rates",
            data={"original": "5.20", "current": "5.35"},
        )
        report = trail.format_report()
        ts = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        assert f"[{ts}] RATE_LOOKUP: Retrieved exchange rates" in report
        assert "original=5.20" in report
        assert "current=5.35" in report

    def test_multiline_report(self, trail: AuditTrail) -> None:
        trail.record("FIRST", "First action")
        trail.record("SECOND", "Second action")
        report = trail.format_report()
        lines = report.strip().split("\n")
        assert len(lines) == 2
        assert "FIRST" in lines[0]
        assert "SECOND" in lines[1]
