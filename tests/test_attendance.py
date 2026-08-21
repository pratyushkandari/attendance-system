import time
import pytest
from app.models.student import Student
from app.routes.main import get_qr_serializer

def test_register_student_success(authenticated_client):
    payload = {
        "first_name": "Alice",
        "last_name": "Smith",
        "department": "CSE",
        "year": "2026",
        "email": "alice@univ.edu"
    }
    res = authenticated_client.post("/register", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "2026CSE" in data["roll"]

def test_register_duplicate_email_blocked(authenticated_client):
    payload = {
        "first_name": "Bob",
        "last_name": "Jones",
        "department": "ECE",
        "year": "2026",
        "email": "bob@univ.edu"
    }
    res1 = authenticated_client.post("/register", json=payload)
    assert res1.status_code == 200

    # Duplicate email
    res2 = authenticated_client.post("/register", json=payload)
    assert res2.status_code == 400

def test_mark_attendance_qr_flow(client, authenticated_client):
    # Register student first
    authenticated_client.post("/register", json={
        "first_name": "Charlie",
        "last_name": "Brown",
        "department": "ME",
        "year": "2026",
        "email": "charlie@univ.edu"
    })
    roll = "2026ME001"

    # Generate valid QR token
    with client.application.app_context():
        serializer = get_qr_serializer()
        qr_token = serializer.dumps({"nonce": "test_nonce", "created_at": time.time()})

    # Mark attendance via QR
    res = client.post("/mark_attendance", json={
        "roll": roll,
        "method": "QR",
        "qr_token": qr_token
    })
    assert res.status_code == 200
    assert res.get_json()["status"] == "marked"

    # Duplicate same-day check
    res_dup = client.post("/mark_attendance", json={
        "roll": roll,
        "method": "QR",
        "qr_token": qr_token
    })
    assert res_dup.status_code == 200
    assert res_dup.get_json()["status"] == "already marked today"

def test_metrics_endpoint(client):
    res = client.get("/metrics")
    assert res.status_code == 200
    assert b"http_requests_total" in res.data


def test_export_records_csv(authenticated_client):
    res = authenticated_client.get("/export_records")
    assert res.status_code == 200
    assert res.mimetype == "text/csv"
    assert "attachment; filename=attendance_report_" in res.headers.get("Content-Disposition", "")
    assert b"Roll Number" in res.data
    assert b"Student Name" in res.data

