import logging
from datetime import datetime, timezone

from src.models import RefundResult

logger = logging.getLogger(__name__)


class RefundNotifier:
    """Simulates sending webhook notifications for refund events.

    Stores all dispatched notifications in memory for inspection.
    """

    def __init__(self) -> None:
        self._notifications: list[dict] = []

    def notify(self, refund_result: RefundResult, event: str) -> None:
        """Record and log a notification for a refund event.

        Args:
            refund_result: The refund result to notify about.
            event: One of REFUND_CALCULATED, REFUND_APPROVED,
                   REFUND_FLAGGED, REFUND_REJECTED, REFUND_COMPLETED.
        """
        notification: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "refund_id": refund_result.id,
            "status": refund_result.status.value,
            "amount": str(refund_result.destination_amount),
            "currency": refund_result.destination_currency.value,
        }
        self._notifications.append(notification)
        logger.info(
            "Notification dispatched: %s for refund %s: %s",
            event,
            refund_result.id,
            refund_result.status.value,
        )

    def get_notifications(self) -> list[dict]:
        """Return all recorded notifications."""
        return list(self._notifications)
