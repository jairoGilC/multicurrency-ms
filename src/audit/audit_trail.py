from src.models import AuditEntry


class AuditTrail:
    """In-memory audit trail for tracking refund operations."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def record(
        self, action: str, details: str, data: dict | None = None
    ) -> AuditEntry:
        """Create and store an audit entry."""
        entry = AuditEntry(
            action=action,
            details=details,
            data=data if data is not None else {},
        )
        self._entries.append(entry)
        return entry

    def get_entries(self) -> list[AuditEntry]:
        """Return all entries in chronological order."""
        return list(self._entries)

    def to_dict(self) -> list[dict]:
        """Serialize all entries to list of dicts."""
        return [
            {
                "timestamp": entry.timestamp.isoformat(),
                "action": entry.action,
                "details": entry.details,
                "data": entry.data,
            }
            for entry in self._entries
        ]

    def format_report(self) -> str:
        """Return a human-readable audit report string."""
        if not self._entries:
            return ""

        lines: list[str] = []
        for entry in self._entries:
            ts = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            line = f"[{ts}] {entry.action}: {entry.details}"
            if entry.data:
                data_str = ", ".join(f"{k}={v}" for k, v in entry.data.items())
                line += f" | {data_str}"
            lines.append(line)

        return "\n".join(lines)
