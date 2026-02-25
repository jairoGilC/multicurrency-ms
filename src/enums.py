from enum import Enum


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    BRL = "BRL"
    MXN = "MXN"
    COP = "COP"
    THB = "THB"


class RefundPolicy(str, Enum):
    CUSTOMER_FAVORABLE = "CUSTOMER_FAVORABLE"
    ORIGINAL_RATE = "ORIGINAL_RATE"
    CURRENT_RATE = "CURRENT_RATE"
    TIME_WEIGHTED = "TIME_WEIGHTED"


class TransactionType(str, Enum):
    FLIGHT = "FLIGHT"
    HOTEL = "HOTEL"
    TOUR_PACKAGE = "TOUR_PACKAGE"


class TransactionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    FAILED = "FAILED"


class RefundStatus(str, Enum):
    PENDING = "PENDING"
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"


class FeeType(str, Enum):
    PERCENTAGE = "PERCENTAGE"
    FIXED = "FIXED"


class PaymentMethod(str, Enum):
    CREDIT_CARD = "CREDIT_CARD"
    BANK_TRANSFER = "BANK_TRANSFER"
    DIGITAL_WALLET = "DIGITAL_WALLET"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
