from datetime import UTC, datetime

from fastapi import APIRouter

from app.schemas import RiskAssessmentRequest, RiskAssessmentResponse

router = APIRouter(prefix="/api/v1/ai", tags=["risk"])
MODEL_VERSION = "sentinelpay-risk-heuristics-v1"


def _score_and_explain(payload: RiskAssessmentRequest) -> tuple[int, list[dict[str, str | int]]]:
    score = 0
    explanations: list[dict[str, str | int]] = []

    factors: list[tuple[str, int, str]] = []

    if payload.wallet_age_days <= 7:
        factors.append(("wallet_age_days", 18, "Wallet is newly created or recently activated."))
    if payload.new_wallet:
        factors.append(("new_wallet", 12, "The wallet was just created and has not established a baseline."))
    if payload.known_malicious_address:
        factors.append(("known_malicious_address", 26, "The wallet matches a known malicious or high-risk address list."))
    if payload.suspicious_contract_interaction:
        factors.append(("suspicious_contract_interaction", 15, "The transfer interacts with a contract pattern flagged by SentinelPay."))
    if payload.failed_tx_count > 0:
        failures = min(12, payload.failed_tx_count * 4)
        factors.append(("failed_tx_count", failures, "Recent failed transactions suggest wallet instability or abuse."))
    if payload.transaction_frequency > 8:
        factors.append(("transaction_frequency", 10, "The payment volume is accelerating unusually quickly for this wallet."))
    if payload.time_since_previous_tx_hours < 1:
        factors.append(("time_since_previous_tx_hours", 8, "The wallet made a near-immediate follow-up payment after a prior transaction."))
    if payload.amount_deviation_ratio > 2:
        deviation = min(20, int(payload.amount_deviation_ratio * 6))
        factors.append(("amount_deviation_ratio", deviation, "The requested amount deviates materially from the wallet’s normal pattern."))
    if payload.wallet_reputation_score < 30:
        reputation = min(18, 30 - payload.wallet_reputation_score)
        factors.append(("wallet_reputation_score", reputation, "The wallet reputation score is below the required threshold."))
    if payload.payment_velocity > 8:
        velocity = min(16, payload.payment_velocity * 2)
        factors.append(("payment_velocity", velocity, "Payment velocity is elevated relative to the merchant’s historical baseline."))
    if payload.merchant_anomaly_score > 60:
        merchant_risk = min(18, payload.merchant_anomaly_score - 60)
        factors.append(("merchant_anomaly_score", merchant_risk, "The merchant context is anomalous relative to expected patterns."))
    if payload.transaction_amount > 0 and payload.historical_volume > 0 and payload.transaction_amount > payload.historical_volume * 2:
        factors.append(("historical_volume", 10, "The amount exceeds the wallet’s typical historical volume by more than 2x."))

    for factor, impact, note in factors:
        score += impact
        explanations.append({"factor": factor, "impact": impact, "observation": note})

    score = max(0, min(100, score))
    if not explanations:
        explanations.append(
            {
                "factor": "baseline",
                "impact": 0,
                "observation": "No configured risk indicators were triggered.",
            }
        )
    return score, explanations


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/model-info")
async def model_info() -> dict[str, str]:
    return {
        "model_version": MODEL_VERSION,
        "model_name": "SentinelPay Risk Heuristics",
        "model_type": "rules-based",
        "status": "active",
    }


@router.post("/assess", response_model=RiskAssessmentResponse)
async def assess(payload: RiskAssessmentRequest) -> RiskAssessmentResponse:
    score, explanations = _score_and_explain(payload)

    if score >= 80:
        risk_level = "HIGH"
        decision = "BLOCK"
    elif score >= 35:
        risk_level = "MEDIUM"
        decision = "REVIEW"
    else:
        risk_level = "LOW"
        decision = "ALLOW"

    return RiskAssessmentResponse(
        transaction_id=payload.transaction_id,
        risk_score=score,
        risk_level=risk_level,
        decision=decision,
        model_version=MODEL_VERSION,
        explanations=[
            {
                "factor": item["factor"],
                "impact": int(item["impact"]),
                "observation": item["observation"],
            }
            for item in explanations
        ],
        created_at=datetime.now(UTC),
    )
