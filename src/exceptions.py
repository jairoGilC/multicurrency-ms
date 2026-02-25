"""Domain-specific exceptions for the Multi-Currency Refund Engine."""


class RefundEngineError(Exception):
    """Base exception for all refund engine errors."""


class RateNotFoundError(RefundEngineError):
    """Raised when an exchange rate cannot be found."""


class TransactionNotFoundError(RefundEngineError):
    """Raised when a transaction cannot be found."""


class RefundProcessingError(RefundEngineError):
    """Raised when refund processing encounters an unrecoverable error."""
