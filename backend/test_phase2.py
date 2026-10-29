import io
import json
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.database import get_db
from app.models import User, Shop, PrintOrder, run_db_migrations
from app.security import create_token, hash_password
from app.pricing import extract_document_page_count, parse_and_validate_pages, calculate_order_price

def run_phase2_tests():
    client = TestClient(app)
    db = next(get_db())

    print("==================================================")
    print("RUNNING XEROXFLOW SMARTPRINT PHASE 2 TEST SUITE")
    print("==================================================")

    # 1. Setup Test Users and Shops with Specific Phase 2 Pricing Rates
    shop1_owner = db.scalar(select(User).where(User.email == "p2_shop1@example.com"))
    if not shop1_owner:
        shop1_owner = User(
            name="Alpha Xerox Owner",
            email="p2_shop1@example.com",
            phone="9811111111",
            password_hash=hash_password("password123"),
            role="shopkeeper"
        )
        db.add(shop1_owner)
        db.flush()
        shop1 = Shop(
            owner_id=shop1_owner.id,
            name="Alpha Xerox Works",
            address="10 University Circle",
            phone="9811111111",
            bw_price=2.0,
            color_price=8.0,
            a3_multiplier=2.5,
            a5_multiplier=0.75,
            double_sided_discount=15.0,  # 15% discount for duplex
            stapling_price=6.0           # ₹6 per stapled set
        )
        db.add(shop1)
        db.commit()
        db.refresh(shop1_owner)
        db.refresh(shop1)
    else:
        shop1 = db.scalar(select(Shop).where(Shop.owner_id == shop1_owner.id))

    shop2_owner = db.scalar(select(User).where(User.email == "p2_shop2@example.com"))
    if not shop2_owner:
        shop2_owner = User(
            name="Beta Xerox Owner",
            email="p2_shop2@example.com",
            phone="9822222222",
            password_hash=hash_password("password123"),
            role="shopkeeper"
        )
        db.add(shop2_owner)
        db.flush()
        shop2 = Shop(
            owner_id=shop2_owner.id,
            name="Beta Xerox Express",
            address="20 Market St",
            phone="9822222222",
            bw_price=3.0,
            color_price=12.0,
            a3_multiplier=2.0,
            a5_multiplier=0.8,
            double_sided_discount=0.0,
            stapling_price=5.0
        )
        db.add(shop2)
        db.commit()
        db.refresh(shop2_owner)
        db.refresh(shop2)
    else:
        shop2 = db.scalar(select(Shop).where(Shop.owner_id == shop2_owner.id))

    cust1 = db.scalar(select(User).where(User.email == "p2_cust1@example.com"))
    if not cust1:
        cust1 = User(
            name="John Student",
            email="p2_cust1@example.com",
            phone="9100000001",
            password_hash=hash_password("password123"),
            role="customer"
        )
        db.add(cust1)
        db.commit()
        db.refresh(cust1)

    cust2 = db.scalar(select(User).where(User.email == "p2_cust2@example.com"))
    if not cust2:
        cust2 = User(
            name="Alice Scholar",
            email="p2_cust2@example.com",
            phone="9100000002",
            password_hash=hash_password("password123"),
            role="customer"
        )
        db.add(cust2)
        db.commit()
        db.refresh(cust2)

    s1_token = create_token(shop1_owner)
    s2_token = create_token(shop2_owner)
    c1_token = create_token(cust1)
    c2_token = create_token(cust2)

    # ----------------------------------------------------
    # TEST 1: PRICING ENGINE UNIT TESTS
    # ----------------------------------------------------
    print("\n--- TEST 1: Pricing Engine & Calculations ---")

    # 1.1 Single sided A4 B/W 5 pages, 2 copies, no stapling
    # page_rate = 2.0, 5 pages * 2.0 = 10.0 per copy * 2 = 20.0
    p1 = calculate_order_price(
        shop_bw_price=2.0, shop_color_price=8.0, shop_a3_multiplier=2.5, shop_a5_multiplier=0.75,
        shop_double_sided_discount=15.0, shop_stapling_price=6.0, copies=2, selected_page_count=5,
        color_mode="bw", paper_size="A4", sides="single", orientation="portrait", finishing="none"
    )
    assert p1["total_printing_cost"] == 20.0
    assert p1["total_finishing_cost"] == 0.0
    assert p1["subtotal"] == 20.0
    assert p1["final_total"] == 20.0
    assert p1["total_sheets"] == 10
    print("[PASS] Single-sided A4 B/W price calculated accurately")

    # 1.2 Double sided A3 Colour 4 pages, 3 copies, stapling
    # base = 8.0 * 2.5 (A3) = 20.0 / page.
    # Duplex discount = 15%: rate per copy = 4 * 20.0 * 0.85 = 68.0
    # 3 copies * 68.0 = 204.0
    # Stapling = 3 * 6.0 = 18.0. Total = 222.0
    p2 = calculate_order_price(
        shop_bw_price=2.0, shop_color_price=8.0, shop_a3_multiplier=2.5, shop_a5_multiplier=0.75,
        shop_double_sided_discount=15.0, shop_stapling_price=6.0, copies=3, selected_page_count=4,
        color_mode="color", paper_size="A3", sides="double", orientation="landscape", finishing="stapling"
    )
    assert p2["effective_page_rate"] == 20.0
    assert p2["total_printing_cost"] == 204.0
    assert p2["total_finishing_cost"] == 18.0
    assert p2["final_total"] == 222.0
    assert p2["sheets_per_copy"] == 2
    assert p2["total_sheets"] == 6
    print("[PASS] Double-sided A3 Colour + Stapling price calculated accurately")

    # 1.3 Pricing Estimate API Endpoint
    r_est = client.post("/api/pricing/estimate", json={
        "shop_id": shop1.id,
        "copies": 3,
        "pages": "1-4",
        "color_mode": "color",
        "paper_size": "A3",
        "sides": "double",
        "orientation": "landscape",
        "finishing": "stapling"
    })
    assert r_est.status_code == 200
    est_data = r_est.json()
    assert est_data["final_total"] == 222.0
    assert est_data["currency"] == "INR"
    print("[PASS] POST /api/pricing/estimate returned verified itemized breakdown")

    # ----------------------------------------------------
    # TEST 2: PDF PAGE COUNT & RANGE VALIDATION
    # ----------------------------------------------------
    print("\n--- TEST 2: PDF Page Count & Range Validation ---")

    # Sample valid 2-page PDF
    # Minimal 2-page PDF binary
    two_page_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
        b"2 0 obj <</Type /Pages /Kids [3 0 R 4 0 R] /Count 2>> endobj\n"
        b"3 0 obj <</Type /Page /Parent 2 0 R>> endobj\n"
        b"4 0 obj <</Type /Page /Parent 2 0 R>> endobj\n"
        b"xref\n0 5\n0000000000 65535 f \n0000000010 00000 n \n0000000057 00000 n \n0000000116 00000 n \n0000000161 00000 n \n"
        b"trailer <</Size 5 /Root 1 0 R>>\nstartxref\n206\n%%EOF"
    )

    actual_cnt, err = extract_document_page_count(two_page_pdf, "test_doc.pdf")
    assert actual_cnt == 2, f"Expected 2 pages, got {actual_cnt} ({err})"
    print(f"[PASS] PDF page count extracted accurately: {actual_cnt} pages")

    # 2.1 Valid page selection: 'all' -> 2 pages
    pages_list, cnt, _ = parse_and_validate_pages("all", 2)
    assert pages_list == [1, 2] and cnt == 2
    print("[PASS] Page selection 'all' resolved to [1, 2]")

    # 2.2 Valid page selection: '1' -> 1 page
    pages_list, cnt, _ = parse_and_validate_pages("1", 2)
    assert pages_list == [1] and cnt == 1
    print("[PASS] Page selection '1' resolved to [1]")

    # 2.3 Invalid: requested page exceeds document count
    try:
        parse_and_validate_pages("1-5", 2)
        assert False, "Should have failed on page 5 exceeding 2"
    except ValueError as e:
        assert "exceeds" in str(e).lower()
        print(f"[PASS] Rejected out-of-bounds page range: {e}")

    # 2.4 Invalid range: reversed range 5-2
    try:
        parse_and_validate_pages("5-2", 10)
        assert False, "Should have failed on 5-2"
    except ValueError as e:
        assert "cannot exceed" in str(e).lower()
        print(f"[PASS] Rejected reversed range 5-2: {e}")

    # ----------------------------------------------------
    # TEST 3: ADVANCED ORDER CREATION & VALIDATION (API)
    # ----------------------------------------------------
    print("\n--- TEST 3: Advanced Order Creation (API) ---")

    # 3.1 Customer attempts order with invalid page range -> rejected with 400
    r_bad_order = client.post(
        "/api/orders",
        data={
            "shop_id": str(shop1.id),
            "copies": "1",
            "pages": "1-10",  # PDF only has 2 pages!
            "color_mode": "bw",
            "paper_size": "A4",
            "sides": "single",
            "orientation": "portrait",
            "finishing": "none"
        },
        files={"document": ("sample2p.pdf", io.BytesIO(two_page_pdf), "application/pdf")},
        headers={"Authorization": f"Bearer {c1_token}"}
    )
    assert r_bad_order.status_code == 400, f"Expected 400, got {r_bad_order.status_code}: {r_bad_order.text}"
    assert "exceeds" in r_bad_order.json()["detail"].lower()
    print(f"[PASS] Server rejected order exceeding PDF pages: {r_bad_order.json()['detail']}")

    # 3.2 Customer creates valid advanced order
    # Shop 1: bw_price=2.0, A5 multiplier=0.75 -> effective page rate = 1.50
    # 2 pages * 1.50 = 3.00 * 2 copies = 6.00 + stapling (2 * 6.0 = 12.0) = 18.00 INR
    r_good_order = client.post(
        "/api/orders",
        data={
            "shop_id": str(shop1.id),
            "copies": "2",
            "pages": "all",
            "color_mode": "bw",
            "paper_size": "A5",
            "sides": "single",
            "orientation": "portrait",
            "finishing": "stapling",
            "notes": "Urgent for morning lecture"
        },
        files={"document": ("physics_notes_2p.pdf", io.BytesIO(two_page_pdf), "application/pdf")},
        headers={"Authorization": f"Bearer {c1_token}"}
    )
    assert r_good_order.status_code == 200, f"Order failed: {r_good_order.status_code} {r_good_order.text}"
    o1 = r_good_order.json()
    order1_id = o1["id"]
    assert o1["page_count"] == 2
    assert o1["paper_size"] == "A5"
    assert o1["orientation"] == "portrait"
    assert o1["finishing"] == "stapling"
    assert o1["final_price"] == 18.0
    assert o1["status"] == "pending"
    assert o1["payment_status"] == "pending"
    assert o1["price_breakdown"]["total_finishing_cost"] == 12.0
    print(f"[PASS] Created Order #{order1_id} with stored pricing breakdown snapshot (Total: INR {o1['final_price']})")

    # ----------------------------------------------------
    # TEST 4: PRICE SNAPSHOT PERSISTENCE
    # ----------------------------------------------------
    print("\n--- TEST 4: Price Snapshot Persistence ---")
    # Even if Shop 1 changes their rates, Order 1's price must remain 18.0!
    r_update_price = client.put(
        "/api/shopkeeper/pricing",
        json={
            "bw_price": 50.0,  # massive increase
            "color_price": 100.0,
            "a3_multiplier": 2.0,
            "a5_multiplier": 1.0,
            "double_sided_discount": 0.0,
            "stapling_price": 25.0
        },
        headers={"Authorization": f"Bearer {s1_token}"}
    )
    assert r_update_price.status_code == 200

    # Retrieve Order 1: Price must still be 18.0!
    r_check_o1 = client.get(f"/api/orders/{order1_id}", headers={"Authorization": f"Bearer {c1_token}"})
    assert r_check_o1.status_code == 200
    assert r_check_o1.json()["final_price"] == 18.0
    assert r_check_o1.json()["price_breakdown"]["final_total"] == 18.0
    print("[PASS] Order snapshot preserved! Future shop price changes did not alter existing order price.")

    # Restore reasonable rates
    client.put("/api/shopkeeper/pricing", json={
        "bw_price": 2.0, "color_price": 8.0, "a3_multiplier": 2.5,
        "a5_multiplier": 0.75, "double_sided_discount": 15.0, "stapling_price": 6.0
    }, headers={"Authorization": f"Bearer {s1_token}"})

    # ----------------------------------------------------
    # TEST 5: SHOPKEEPER WORKFLOW & STATUS TRANSITIONS
    # ----------------------------------------------------
    print("\n--- TEST 5: Server-Side Status Transitions ---")

    # 5.1 Invalid transition: pending directly to completed -> 400 Bad Request
    r_jump = client.patch(
        f"/api/orders/{order1_id}/status",
        json={"status_value": "completed"},
        headers={"Authorization": f"Bearer {s1_token}"}
    )
    assert r_jump.status_code == 400
    assert "invalid status transition" in r_jump.json()["detail"].lower()
    print("[PASS] Rejected invalid status transition (pending -> completed)")

    # 5.2 Valid transition: pending -> accepted
    r_accept = client.patch(
        f"/api/orders/{order1_id}/status",
        json={"status_value": "accepted"},
        headers={"Authorization": f"Bearer {s1_token}"}
    )
    assert r_accept.status_code == 200
    assert r_accept.json()["status"] == "accepted"
    print("[PASS] Order transitioned: pending -> accepted")

    # 5.3 Customer attempts to cancel accepted order -> 409 Conflict
    r_cust_cancel = client.post(
        f"/api/orders/{order1_id}/cancel",
        json={"reason": "Changed my mind"},
        headers={"Authorization": f"Bearer {c1_token}"}
    )
    assert r_cust_cancel.status_code == 409
    assert "accepted" in r_cust_cancel.json()["detail"].lower()
    print("[PASS] Customer cannot unilaterally cancel already accepted order (409 Conflict)")

    # 5.4 Valid transition: accepted -> printing
    r_print = client.patch(
        f"/api/orders/{order1_id}/status",
        json={"status_value": "printing"},
        headers={"Authorization": f"Bearer {s1_token}"}
    )
    assert r_print.status_code == 200
    assert r_print.json()["status"] == "printing"
    print("[PASS] Order transitioned: accepted -> printing")

    # 5.5 Valid transition: printing -> ready
    r_ready = client.patch(
        f"/api/orders/{order1_id}/status",
        json={"status_value": "ready"},
        headers={"Authorization": f"Bearer {s1_token}"}
    )
    assert r_ready.status_code == 200
    assert r_ready.json()["status"] == "ready"
    print("[PASS] Order transitioned: printing -> ready")

    # 5.6 Valid transition: ready -> completed + mark payment as paid
    r_complete = client.patch(
        f"/api/orders/{order1_id}/status",
        json={"status_value": "completed", "payment_status": "paid"},
        headers={"Authorization": f"Bearer {s1_token}"}
    )
    assert r_complete.status_code == 200
    assert r_complete.json()["status"] == "completed"
    assert r_complete.json()["payment_status"] == "paid"
    print("[PASS] Order completed and marked as PAID")

    # 5.7 Terminal state: cannot change completed order -> 409 Conflict
    r_term = client.patch(
        f"/api/orders/{order1_id}/status",
        json={"status_value": "printing"},
        headers={"Authorization": f"Bearer {s1_token}"}
    )
    assert r_term.status_code == 409
    print("[PASS] Completed order is terminal and rejects further modifications (409 Conflict)")

    # ----------------------------------------------------
    # TEST 6: CUSTOMER CANCELLATION (PENDING ORDER)
    # ----------------------------------------------------
    print("\n--- TEST 6: Customer Cancellation of Pending Order ---")
    r_o2 = client.post(
        "/api/orders",
        data={
            "shop_id": str(shop1.id),
            "copies": "1",
            "pages": "all",
            "color_mode": "bw",
            "paper_size": "A4",
            "sides": "single",
            "orientation": "portrait",
            "finishing": "none"
        },
        files={"document": ("to_cancel.pdf", io.BytesIO(two_page_pdf), "application/pdf")},
        headers={"Authorization": f"Bearer {c2_token}"}
    )
    assert r_o2.status_code == 200
    order2_id = r_o2.json()["id"]

    r_cancel_ok = client.post(
        f"/api/orders/{order2_id}/cancel",
        json={"reason": "Uploaded wrong file"},
        headers={"Authorization": f"Bearer {c2_token}"}
    )
    assert r_cancel_ok.status_code == 200
    assert r_cancel_ok.json()["status"] == "cancelled"
    assert r_cancel_ok.json()["cancellation_reason"] == "Uploaded wrong file"
    print(f"[PASS] Customer successfully cancelled pending Order #{order2_id}")

    # ----------------------------------------------------
    # TEST 7: BILLING & RECEIPTS (FEATURE 5)
    # ----------------------------------------------------
    print("\n--- TEST 7: Billing & Printable Receipts ---")

    # 7.1 Customer retrieves receipt
    r_rec = client.get(f"/api/orders/{order1_id}/receipt", headers={"Authorization": f"Bearer {c1_token}"})
    assert r_rec.status_code == 200
    rec = r_rec.json()
    assert rec["order_id"] == order1_id
    assert rec["shop"]["name"] == "Alpha Xerox Works"
    assert rec["customer"]["name"] == "John Student"
    assert rec["final_amount_inr"] == 18.0
    assert rec["payment_status"] == "paid"
    assert rec["status"] == "completed"
    print("[PASS] Customer retrieved valid receipt with itemized charges & payment status")

    # 7.2 Shopkeeper retrieves receipt
    r_sk_rec = client.get(f"/api/orders/{order1_id}/receipt", headers={"Authorization": f"Bearer {s1_token}"})
    assert r_sk_rec.status_code == 200
    print("[PASS] Shopkeeper retrieved valid receipt")

    # 7.3 Unrelated customer cannot retrieve receipt -> 403 Forbidden
    r_bad_rec = client.get(f"/api/orders/{order1_id}/receipt", headers={"Authorization": f"Bearer {c2_token}"})
    assert r_bad_rec.status_code == 403
    print("[PASS] Unrelated user denied access to private receipt (403 Forbidden)")

    # ----------------------------------------------------
    # TEST 8: PERMISSIONS & CROSS-SHOP SECURITY
    # ----------------------------------------------------
    print("\n--- TEST 8: Permissions & Cross-Shop Isolation ---")

    # Unrelated Shop 2 cannot view or update Shop 1's order
    r_cross_view = client.get(f"/api/orders/{order1_id}", headers={"Authorization": f"Bearer {s2_token}"})
    assert r_cross_view.status_code == 403
    print("[PASS] Cross-shop order viewing rejected (403 Forbidden)")

    r_cross_stat = client.patch(
        f"/api/orders/{order1_id}/status",
        json={"status_value": "cancelled"},
        headers={"Authorization": f"Bearer {s2_token}"}
    )
    assert r_cross_stat.status_code == 404  # Shopkeeper does not own the order
    print("[PASS] Cross-shop status tampering blocked (404/403)")

    # ----------------------------------------------------
    # TEST 9: SEARCH & FILTERING ENDPOINTS
    # ----------------------------------------------------
    print("\n--- TEST 9: Order Search & Filtering ---")

    # Filter by status
    r_filter = client.get("/api/orders?status=completed", headers={"Authorization": f"Bearer {s1_token}"})
    assert r_filter.status_code == 200
    assert all(o["status"] == "completed" for o in r_filter.json())
    print(f"[PASS] Filtered shopkeeper orders by status=completed ({len(r_filter.json())} orders)")

    # Search by filename
    r_search = client.get("/api/orders?search=physics", headers={"Authorization": f"Bearer {s1_token}"})
    assert r_search.status_code == 200
    assert len(r_search.json()) >= 1
    print(f"[PASS] Search by keyword 'physics' matched successfully")

    # Clean up test orders created
    try:
        db.delete(db.get(PrintOrder, order1_id))
        db.delete(db.get(PrintOrder, order2_id))
        db.commit()
    except Exception:
        pass

    print("\n==================================================")
    print("ALL PHASE 2 TEST SUITES PASSED PERFECTLY!")
    print("==================================================")

if __name__ == "__main__":
    run_phase2_tests()
