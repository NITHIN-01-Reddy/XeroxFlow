"""
XeroxFlow SmartPrint - CORS Verification Test Suite
Tests CORS preflight and actual requests from:
- Production frontend: https://xerox-flow.vercel.app
- Local dev frontends: http://localhost:5173, http://127.0.0.1:5173
- Unauthorized origins (rejected)
"""

from fastapi.testclient import TestClient
from app.main import app

def run_cors_tests():
    client = TestClient(app)

    print("==================================================")
    print("RUNNING XEROXFLOW CORS VERIFICATION TESTS")
    print("==================================================")

    prod_origin = "https://xerox-flow.vercel.app"
    local_origin_1 = "http://localhost:5173"
    local_origin_2 = "http://127.0.0.1:5173"
    disallowed_origin = "https://unauthorized-evil-site.com"

    # ----------------------------------------------------
    # TEST 1: OPTIONS Preflight to /api/auth/login from Production Frontend
    # ----------------------------------------------------
    print("\n--- TEST 1: OPTIONS Preflight to /api/auth/login from Production Frontend ---")
    r_preflight_login = client.options(
        "/api/auth/login",
        headers={
            "Origin": prod_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type, Accept",
        },
    )
    assert r_preflight_login.status_code == 200, (
        f"Expected 200 OK for preflight, got {r_preflight_login.status_code}: {r_preflight_login.text}"
    )
    assert r_preflight_login.headers.get("access-control-allow-origin") == prod_origin, (
        f"Expected Access-Control-Allow-Origin: {prod_origin}, got: {r_preflight_login.headers.get('access-control-allow-origin')}"
    )
    assert r_preflight_login.headers.get("access-control-allow-credentials") == "true", (
        "Access-Control-Allow-Credentials header must be 'true'"
    )
    allow_methods = r_preflight_login.headers.get("access-control-allow-methods", "")
    for m in ["POST", "GET", "PUT", "PATCH", "DELETE", "OPTIONS"]:
        assert m in allow_methods, f"Method {m} missing from Access-Control-Allow-Methods: {allow_methods}"

    allow_headers = r_preflight_login.headers.get("access-control-allow-headers", "").lower()
    for h in ["authorization", "content-type", "accept"]:
        assert h in allow_headers, f"Header {h} missing from Access-Control-Allow-Headers: {allow_headers}"

    print(f"[PASS] Preflight /api/auth/login succeeded with Origin: {prod_origin}")
    print(f"[PASS] Access-Control-Allow-Origin: {r_preflight_login.headers.get('access-control-allow-origin')}")
    print(f"[PASS] Access-Control-Allow-Credentials: {r_preflight_login.headers.get('access-control-allow-credentials')}")
    print(f"[PASS] Access-Control-Allow-Methods: {allow_methods}")
    print(f"[PASS] Access-Control-Allow-Headers: {r_preflight_login.headers.get('access-control-allow-headers')}")

    # ----------------------------------------------------
    # TEST 2: GET /api/shops from Production Frontend
    # ----------------------------------------------------
    print("\n--- TEST 2: GET /api/shops from Production Frontend ---")
    r_shops = client.get(
        "/api/shops",
        headers={"Origin": prod_origin},
    )
    assert r_shops.status_code == 200, f"Expected 200, got {r_shops.status_code}"
    assert r_shops.headers.get("access-control-allow-origin") == prod_origin, (
        f"Expected Access-Control-Allow-Origin: {prod_origin}, got: {r_shops.headers.get('access-control-allow-origin')}"
    )
    assert r_shops.headers.get("access-control-allow-credentials") == "true", (
        "Access-Control-Allow-Credentials header must be 'true'"
    )
    assert isinstance(r_shops.json(), list), "Expected list of shops"
    print(f"[PASS] GET /api/shops returned {len(r_shops.json())} shops with valid CORS headers")

    # ----------------------------------------------------
    # TEST 3: OPTIONS Preflight to /api/shops from Production Frontend
    # ----------------------------------------------------
    print("\n--- TEST 3: OPTIONS Preflight to /api/shops from Production Frontend ---")
    r_preflight_shops = client.options(
        "/api/shops",
        headers={
            "Origin": prod_origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization, Accept",
        },
    )
    assert r_preflight_shops.status_code == 200
    assert r_preflight_shops.headers.get("access-control-allow-origin") == prod_origin
    assert r_preflight_shops.headers.get("access-control-allow-credentials") == "true"
    print(f"[PASS] Preflight /api/shops succeeded with Access-Control-Allow-Origin: {prod_origin}")

    # ----------------------------------------------------
    # TEST 4: Local Development Origins Allowed
    # ----------------------------------------------------
    print("\n--- TEST 4: Local Development Origins Allowed ---")
    for loc_origin in [local_origin_1, local_origin_2]:
        r_loc_opt = client.options(
            "/api/auth/login",
            headers={
                "Origin": loc_origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert r_loc_opt.status_code == 200
        assert r_loc_opt.headers.get("access-control-allow-origin") == loc_origin
        assert r_loc_opt.headers.get("access-control-allow-credentials") == "true"

        r_loc_get = client.get("/api/shops", headers={"Origin": loc_origin})
        assert r_loc_get.status_code == 200
        assert r_loc_get.headers.get("access-control-allow-origin") == loc_origin
        print(f"[PASS] Origin {loc_origin} verified for preflight and actual requests")

    # ----------------------------------------------------
    # TEST 5: Unauthorized Origin Rejection (Exact Allowlist Enforcement)
    # ----------------------------------------------------
    print("\n--- TEST 5: Unauthorized Origin Rejection ---")
    r_bad_opt = client.options(
        "/api/auth/login",
        headers={
            "Origin": disallowed_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    # Disallowed origin preflight must not receive Access-Control-Allow-Origin matching the bad origin
    assert r_bad_opt.headers.get("access-control-allow-origin") != disallowed_origin, (
        f"Unauthorized origin {disallowed_origin} must not be allowed!"
    )
    assert r_bad_opt.status_code == 400 or "access-control-allow-origin" not in r_bad_opt.headers

    r_bad_get = client.get("/api/shops", headers={"Origin": disallowed_origin})
    assert r_bad_get.headers.get("access-control-allow-origin") != disallowed_origin, (
        f"Unauthorized origin {disallowed_origin} must not receive allow-origin header!"
    )
    print(f"[PASS] Unauthorized origin {disallowed_origin} was correctly rejected")

    # ----------------------------------------------------
    # TEST 6: Credentials Security (No Wildcard Origin with Credentials)
    # ----------------------------------------------------
    print("\n--- TEST 6: Credentials Security Check ---")
    # Fetch specification forbids Access-Control-Allow-Origin: * when Access-Control-Allow-Credentials is true
    for resp in [r_preflight_login, r_shops, r_preflight_shops]:
        origin_val = resp.headers.get("access-control-allow-origin")
        assert origin_val != "*", "Wildcard origin '*' must not be used with credentials"
        assert origin_val in [prod_origin, local_origin_1, local_origin_2]
    print("[PASS] Explicit origin allowlist verified: no wildcard '*' used with credentials")

    # ----------------------------------------------------
    # TEST 7: Required Methods Allowed
    # ----------------------------------------------------
    print("\n--- TEST 7: Method Verification ---")
    for method in ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]:
        r_m = client.options(
            "/api/shops",
            headers={
                "Origin": prod_origin,
                "Access-Control-Request-Method": method,
            },
        )
        assert r_m.status_code == 200, f"Method {method} should be allowed in preflight"
        assert r_m.headers.get("access-control-allow-origin") == prod_origin
    print("[PASS] All required methods (GET, POST, PUT, PATCH, DELETE, OPTIONS) allowed in preflight")

    print("\n==================================================")
    print("ALL CORS VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("==================================================")

if __name__ == "__main__":
    run_cors_tests()
