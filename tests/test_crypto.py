import time
import pytest
from itsdangerous import SignatureExpired, BadSignature
from app.routes.main import get_qr_serializer

def test_qr_token_generation_and_verification(app):
    with app.app_context():
        serializer = get_qr_serializer()
        payload = {"nonce": "test12345", "created_at": time.time()}
        token = serializer.dumps(payload)

        # Immediate verification should succeed
        decoded = serializer.loads(token, max_age=15)
        assert decoded["nonce"] == "test12345"

def test_qr_token_expired(app):
    with app.app_context():
        serializer = get_qr_serializer()
        payload = {"nonce": "test_expired", "created_at": time.time()}
        token = serializer.dumps(payload)

        # Negative max_age guarantees instantaneous expiration test
        with pytest.raises(SignatureExpired):
            serializer.loads(token, max_age=-1)

def test_qr_token_tampered(app):
    with app.app_context():
        serializer = get_qr_serializer()
        payload = {"nonce": "test_tamper", "created_at": time.time()}
        token = serializer.dumps(payload)

        # Tampered token
        tampered_token = token + "xyz"
        with pytest.raises(BadSignature):
            serializer.loads(tampered_token, max_age=15)

def test_verify_qr_token_api(client):
    with client.application.app_context():
        serializer = get_qr_serializer()
        token = serializer.dumps({"nonce": "api_test", "created_at": time.time()})

    res = client.post("/verify_qr_token", json={"token": token})
    assert res.status_code == 200
    assert res.get_json()["valid"] is True
