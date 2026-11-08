import pytest


@pytest.mark.asyncio
async def test_ai_assessment_returns_score_and_explanation(client):
    response = await client.post(
        "/api/v1/ai/assess",
        json={
            "transaction_id": "txn_123",
            "wallet_age_days": 4,
            "transaction_amount": 0.9,
            "transaction_frequency": 8,
            "failed_tx_count": 3,
            "historical_volume": 2.1,
            "time_since_previous_tx_hours": 0.5,
            "new_wallet": True,
            "known_malicious_address": False,
            "suspicious_contract_interaction": True,
            "amount_deviation_ratio": 3.2,
            "wallet_reputation_score": 18,
            "payment_velocity": 9,
            "merchant_anomaly_score": 72,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["transaction_id"] == "txn_123"
    assert 0 <= payload["risk_score"] <= 100
    assert payload["risk_level"] in {"LOW", "MEDIUM", "HIGH"}
    assert payload["decision"] in {"ALLOW", "REVIEW", "BLOCK"}
    assert payload["model_version"]
    assert payload["explanations"]
    assert any(item["factor"] == "wallet_age_days" for item in payload["explanations"])

@pytest.mark.asyncio
async def test_ai_assessment_allows_clean_payment(client):
    response = await client.post(
        "/api/v1/ai/assess",
        json={
            "transaction_id": "txn_clean",
            "wallet_age_days": 365,
            "transaction_amount": 0.1,
            "transaction_frequency": 2,
            "failed_tx_count": 0,
            "historical_volume": 5,
            "time_since_previous_tx_hours": 24,
            "new_wallet": False,
            "known_malicious_address": False,
            "suspicious_contract_interaction": False,
            "amount_deviation_ratio": 1,
            "wallet_reputation_score": 95,
            "payment_velocity": 1,
            "merchant_anomaly_score": 10,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["risk_score"] == 0
    assert payload["risk_level"] == "LOW"
    assert payload["decision"] == "ALLOW"
    assert payload["explanations"] == [
        {
            "factor": "baseline",
            "impact": 0,
            "observation": "No configured risk indicators were triggered.",
        }
    ]


@pytest.mark.asyncio
async def test_ai_service_rejects_missing_required_fields(client):
    response = await client.post(
        "/api/v1/ai/assess",
        json={"transaction_id": "txn_missing"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ai_health_and_model_info(client):
    health = await client.get("/api/v1/ai/health")
    assert health.status_code == 200
    info = await client.get("/api/v1/ai/model-info")
    assert info.status_code == 200
    assert info.json()["model_version"]
    assert info.json()["model_type"] == "rules-based"
