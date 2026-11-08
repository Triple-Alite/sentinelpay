import pytest


def registration_payload(email: str = "owner@example.com") -> dict[str, str]:
    return {
        "full_name": "Test Owner",
        "business_name": "Test Shop",
        "email": email,
        "password": "Correct-Horse-42!",
        "country": "US",
        "website": "https://shop.example.com",
    }


@pytest.mark.asyncio
async def test_register_login_refresh_and_logout(client):
    response = await client.post("/api/v1/auth/register", json=registration_payload())
    assert response.status_code == 201
    assert response.json()["merchant"]["business_name"] == "Test Shop"
    assert response.cookies.get("sentinelpay_access")
    assert "httponly" in response.headers["set-cookie"].lower()

    profile = await client.get("/api/v1/auth/me")
    assert profile.status_code == 200
    assert profile.json()["user"]["email"] == "owner@example.com"

    settings_response = await client.get("/api/v1/merchants/settings")
    assert settings_response.status_code == 200
    assert settings_response.json()["automatic_settlement_enabled"] is False

    old_refresh = client.cookies.get("sentinelpay_refresh")
    rotated = await client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 204
    assert client.cookies.get("sentinelpay_refresh") != old_refresh
    assert (await client.get("/api/v1/auth/me")).status_code == 200

    logged_out = await client.post("/api/v1/auth/logout")
    assert logged_out.status_code == 204
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_duplicate_registration_and_invalid_password_are_rejected(client):
    assert (await client.post("/api/v1/auth/register", json=registration_payload())).status_code == 201
    duplicate = await client.post("/api/v1/auth/register", json=registration_payload())
    assert duplicate.status_code == 409

    await client.post("/api/v1/auth/logout")
    invalid_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "wrong-password"},
    )
    assert invalid_login.status_code == 401


@pytest.mark.asyncio
async def test_merchant_settings_are_validated_and_origin_is_restricted(client):
    await client.post("/api/v1/auth/register", json=registration_payload())
    invalid_thresholds = await client.patch(
        "/api/v1/merchants/settings",
        json={"low_risk_threshold": 40, "high_risk_threshold": 35},
    )
    assert invalid_thresholds.status_code == 422

    blocked_origin = await client.patch(
        "/api/v1/merchants/me",
        json={"business_name": "Changed Shop"},
        headers={"Origin": "https://attacker.example"},
    )
    assert blocked_origin.status_code == 403