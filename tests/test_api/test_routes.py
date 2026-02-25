"""Tests for the FastAPI API routes."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.dependencies import (
    get_processor,
    get_rate_provider,
    get_refund_repo,
    get_transaction_repo,
)
from src.models import RiskConfig
from src.notifications.notifier import RefundNotifier
from src.refund.processor import RefundProcessor
from src.storage.repository import RefundRepository, TransactionRepository


@pytest.fixture
def client():
    """Create a test client with fresh dependencies."""
    # Clear lru_cache
    get_rate_provider.cache_clear()
    get_transaction_repo.cache_clear()
    get_refund_repo.cache_clear()
    get_processor.cache_clear()

    return TestClient(app)


@pytest.fixture
def seeded_client(rate_provider, sample_transaction):
    """Create a test client with seeded data."""
    get_rate_provider.cache_clear()
    get_transaction_repo.cache_clear()
    get_refund_repo.cache_clear()
    get_processor.cache_clear()

    txn_repo = TransactionRepository()
    txn_repo.save(sample_transaction)
    refund_repo = RefundRepository()
    notifier = RefundNotifier()

    processor = RefundProcessor(
        rate_provider=rate_provider,
        transaction_repo=txn_repo,
        refund_repo=refund_repo,
        risk_config=RiskConfig(),
        notifier=notifier,
    )

    # Override dependencies
    with (
        patch("src.api.routes.get_processor", return_value=processor),
        patch("src.api.routes.get_refund_repo", return_value=refund_repo),
        patch("src.api.routes.get_transaction_repo", return_value=txn_repo),
    ):
        yield TestClient(app)


class TestHealthCheck:
    def test_health_returns_200(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data


class TestCreateRefund:
    def test_create_refund_success(self, seeded_client):
        response = seeded_client.post(
            "/api/v1/refunds",
            json={
                "transaction_id": "txn-001",
                "requested_amount": "500",
                "policy": "ORIGINAL_RATE",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["transaction_id"] == "txn-001"
        assert data["status"] in ["APPROVED", "FLAGGED"]

    def test_create_refund_not_found(self, seeded_client):
        response = seeded_client.post(
            "/api/v1/refunds",
            json={
                "transaction_id": "txn-nonexistent",
                "requested_amount": "100",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "REJECTED"


class TestGetRefund:
    def test_get_nonexistent_refund(self, seeded_client):
        response = seeded_client.get("/api/v1/refunds/nonexistent-id")
        assert response.status_code == 404


class TestGetTransaction:
    def test_get_existing_transaction(self, seeded_client):
        response = seeded_client.get("/api/v1/transactions/txn-001")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "txn-001"

    def test_get_nonexistent_transaction(self, seeded_client):
        response = seeded_client.get("/api/v1/transactions/nonexistent")
        assert response.status_code == 404


class TestBatchRefund:
    def test_batch_refund(self, seeded_client):
        response = seeded_client.post(
            "/api/v1/refunds/batch",
            json={
                "requests": [
                    {
                        "transaction_id": "txn-001",
                        "requested_amount": "200",
                        "policy": "ORIGINAL_RATE",
                    }
                ]
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_processed"] == 1
