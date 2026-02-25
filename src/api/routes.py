"""API routes for the Multi-Currency Refund Engine."""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.api.dependencies import get_processor, get_refund_repo, get_transaction_repo
from src.enums import Currency, FeeType, RefundPolicy
from src.models import Fee, RefundRequest

router = APIRouter(prefix="/api/v1")


class RefundRequestBody(BaseModel):
    """Request body for creating a refund."""

    transaction_id: str
    requested_amount: Decimal | None = None
    destination_currency: Currency | None = None
    policy: RefundPolicy = RefundPolicy.ORIGINAL_RATE
    fees: list[dict] = Field(default_factory=list)


class BatchRefundRequestBody(BaseModel):
    """Request body for batch refund processing."""

    requests: list[RefundRequestBody]


@router.get("/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/refunds")
def create_refund(body: RefundRequestBody):
    processor = get_processor()
    fees = [
        Fee(
            type=FeeType(f["type"]),
            value=Decimal(str(f["value"])),
            currency=Currency(f["currency"]) if f.get("currency") else None,
            description=f.get("description", ""),
        )
        for f in body.fees
    ]
    request = RefundRequest(
        transaction_id=body.transaction_id,
        requested_amount=body.requested_amount,
        destination_currency=body.destination_currency,
        policy=body.policy,
        fees=fees,
    )
    result = processor.process_refund(request)
    return result.model_dump(mode="json")


@router.post("/refunds/batch")
def create_batch_refund(body: BatchRefundRequestBody):
    processor = get_processor()
    requests = []
    for item in body.requests:
        fees = [
            Fee(
                type=FeeType(f["type"]),
                value=Decimal(str(f["value"])),
                currency=Currency(f["currency"]) if f.get("currency") else None,
                description=f.get("description", ""),
            )
            for f in item.fees
        ]
        requests.append(
            RefundRequest(
                transaction_id=item.transaction_id,
                requested_amount=item.requested_amount,
                destination_currency=item.destination_currency,
                policy=item.policy,
                fees=fees,
            )
        )
    result = processor.process_batch(requests)
    return result.model_dump(mode="json")


@router.get("/refunds/{refund_id}")
def get_refund(refund_id: str):
    repo = get_refund_repo()
    refund = repo.get(refund_id)
    if refund is None:
        raise HTTPException(status_code=404, detail="Refund not found")
    return refund.model_dump(mode="json")


@router.get("/transactions/{transaction_id}")
def get_transaction(transaction_id: str):
    repo = get_transaction_repo()
    transaction = repo.get(transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction.model_dump(mode="json")
