from typing import Optional, Protocol

from src.models import RefundResult, Transaction


class TransactionRepositoryProtocol(Protocol):
    def save(self, transaction: Transaction) -> Transaction: ...
    def get(self, transaction_id: str) -> Optional[Transaction]: ...
    def get_all(self) -> list[Transaction]: ...
    def update(self, transaction: Transaction) -> Transaction: ...


class RefundRepositoryProtocol(Protocol):
    def save(self, refund: RefundResult) -> RefundResult: ...
    def get(self, refund_id: str) -> Optional[RefundResult]: ...
    def get_all(self) -> list[RefundResult]: ...
    def update(self, refund: RefundResult) -> RefundResult: ...
    def get_by_transaction(self, transaction_id: str) -> list[RefundResult]: ...


class TransactionRepository:
    """In-memory repository for transactions."""

    def __init__(self) -> None:
        self._transactions: dict[str, Transaction] = {}

    def save(self, transaction: Transaction) -> Transaction:
        """Persist a transaction. Returns the saved transaction."""
        self._transactions[transaction.id] = transaction
        return transaction

    def get(self, transaction_id: str) -> Transaction | None:
        """Look up a transaction by ID. Returns None if not found."""
        return self._transactions.get(transaction_id)

    def get_all(self) -> list[Transaction]:
        """Return every stored transaction."""
        return list(self._transactions.values())

    def update(self, transaction: Transaction) -> Transaction:
        """Overwrite an existing transaction. Raises if not found."""
        if transaction.id not in self._transactions:
            raise KeyError(f"Transaction {transaction.id} not found")
        self._transactions[transaction.id] = transaction
        return transaction


class RefundRepository:
    """In-memory repository for refund results."""

    def __init__(self) -> None:
        self._refunds: dict[str, RefundResult] = {}

    def save(self, refund: RefundResult) -> RefundResult:
        """Persist a refund result. Returns the saved refund."""
        self._refunds[refund.id] = refund
        return refund

    def get(self, refund_id: str) -> RefundResult | None:
        """Look up a refund by ID. Returns None if not found."""
        return self._refunds.get(refund_id)

    def get_by_transaction(self, transaction_id: str) -> list[RefundResult]:
        """Return all refunds linked to *transaction_id*."""
        return [
            r for r in self._refunds.values()
            if r.transaction_id == transaction_id
        ]

    def get_all(self) -> list[RefundResult]:
        """Return every stored refund result."""
        return list(self._refunds.values())

    def update(self, refund: RefundResult) -> RefundResult:
        """Overwrite an existing refund. Raises if not found."""
        if refund.id not in self._refunds:
            raise KeyError(f"Refund {refund.id} not found")
        self._refunds[refund.id] = refund
        return refund
