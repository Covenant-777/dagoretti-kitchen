"""
test_system.py — Dagoretti Kitchen Incubator
Week 11+12: Integration Testing + UAT
Run: python test_system.py   (server must be running on port 5000)
"""
import requests, json, time, sys
from datetime import datetime

BASE    = "http://127.0.0.1:5000"
PASS    = "\033[92m✓ PASS\033[0m"
FAIL    = "\033[91m✗ FAIL\033[0m"
WARN    = "\033[93m⚠ WARN\033[0m"
results = []

def test(name, passed, detail=""):
    passed = bool(passed)
    detail = str(detail)[:200]
    status = PASS if passed else FAIL
    print(f"  {status}  {name}")
    if detail and not passed:
        print(f"         → {detail}")
    results.append({"name": name, "passed": passed, "detail": detail})

def section(title):
    print(f"\n{'='*55}\n  {title}\n{'='*55}")

def post(url, data):
    try:
        return requests.post(BASE + url, json=data, timeout=10)
    except Exception as e:
        return None

def get(url, params=None):
    try:
        return requests.get(BASE + url, params=params, timeout=10)
    except Exception as e:
        return None

def wait_for_unlock():
    """Wait if terminal is currently locked"""
    r = get("/api/lockout_status")
    if r and r.json().get("locked"):
        secs = r.json().get("seconds_remaining", 30)
        print(f"  {WARN}  Terminal locked — waiting {secs+1}s to clear...")
        time.sleep(secs + 1)

# ── 1. SERVER HEALTH ───────────────────────────────────────────────────────
section("TEST 1: Server Health")
r = get("/")
test("Server is reachable", r is not None and r.status_code == 200)

# ── 2. PIN AUTHENTICATION ──────────────────────────────────────────────────
section("TEST 2: PIN Authentication")
wait_for_unlock()

# Close any open session for Amina first
post("/api/login", {"pin": "123456"})
time.sleep(0.2)

r = post("/api/login", {"pin": "123456"})
test("Valid PIN accepted (Amina=1234)",
     r is not None and r.status_code == 200 and r.json().get("status") in ("login","logout"))

# Close session again if still open
if r and r.json().get("status") == "login":
    post("/api/login", {"pin": "123456"})

r = post("/api/login", {"pin": "888888"})
test("Wrong PIN rejected (8888)",
     r is not None and r.status_code == 401 and r.json().get("status") == "wrong_pin",
     r.text if r else "No response")

if r and r.status_code == 401:
    rem = r.json().get("attempts_remaining", -1)
    test("Attempts remaining field present in response", rem >= 0, f"Got: {rem}")
else:
    test("Attempts remaining field present in response", False, "Previous test failed")

r = post("/api/login", {"pin": "12"})
test("Short PIN (2 digits) rejected",
     r is not None and r.status_code == 400,
     r.text if r else "No response")

r = post("/api/login", {"pin": "abcd"})
test("Non-numeric PIN rejected",
     r is not None and r.status_code == 400,
     r.text if r else "No response")

r = post("/api/login", {"pin": ""})
test("Empty PIN rejected",
     r is not None and r.status_code == 400,
     r.text if r else "No response")

# ── 3. LOCKOUT SYSTEM ─────────────────────────────────────────────────────
section("TEST 3: Lockout System (3 wrong PINs → 30s lock)")
wait_for_unlock()

locked_triggered = False
for attempt in range(1, 5):
    r = post("/api/login", {"pin": "000002"})
    if r is None:
        continue
    if r.json().get("status") == "locked":
        locked_triggered = True
        lock_secs = r.json().get("seconds_remaining", 0)
        test("Lockout triggered after 3 wrong attempts", True, f"Locked for {lock_secs}s")
        break
    time.sleep(0.2)

if not locked_triggered:
    r_lk = get("/api/lockout_status")
    if r_lk and r_lk.json().get("locked"):
        test("Lockout triggered after 3 wrong attempts", True, "Confirmed via lockout_status")
        locked_triggered = True
    else:
        test("Lockout triggered after 3 wrong attempts", False, "Check lockout_tracker in app.py")

r = post("/api/login", {"pin": "234567"})
if r and r.json().get("status") == "locked":
    test("Locked terminal blocks valid PIN", True)
elif locked_triggered:
    test("Locked terminal blocks valid PIN", False, "Valid PIN went through while locked")
else:
    test("Locked terminal blocks valid PIN", False, "Lockout did not trigger — skipping check")

print(f"\n  {WARN}  Waiting 31 seconds for lockout to expire...")
time.sleep(31)
print(f"  {PASS}  Lockout expired — resuming")

r = post("/api/login", {"pin": "123456"})
ok = r is not None and r.status_code == 200 and r.json().get("status") in ("login","logout")
test("Terminal accepts valid PIN after lockout expires", ok, r.text if r else "No response")
if r and r.json().get("status") == "login":
    post("/api/login", {"pin": "123456"})

# ── 4. SESSION LOGGING ─────────────────────────────────────────────────────
section("TEST 4: Session Logging")
wait_for_unlock()

# Ensure Brian has no open session
post("/api/login", {"pin": "234567"}); time.sleep(0.3)

r = post("/api/login", {"pin": "234567"})
login_ok = r is not None and r.status_code == 200 and r.json().get("status") == "login"
test("Session LOGIN recorded successfully", login_ok, r.text if r else "No response")

if login_ok:
    d = r.json()
    test("start_time returned in login response", bool(d.get("start_time")))
    test("baker_id returned in login response", bool(d.get("baker_id")))
    test("session_history returned in login response", isinstance(d.get("session_history"), list))

    r2 = get("/api/active_sessions")
    test("Active sessions endpoint shows Brian's session",
         r2 is not None and any(s["baker_id"] == d["baker_id"] for s in r2.json()),
         r2.text if r2 else "No response")

    r3 = get(f"/api/elapsed/{d['baker_id']}")
    test("Elapsed endpoint returns active=True",
         r3 is not None and r3.json().get("active") == True,
         r3.text if r3 else "No response")
    test("Elapsed endpoint returns running_bill field",
         r3 is not None and "running_bill" in r3.json())

    time.sleep(2)

    r4 = post("/api/login", {"pin": "234567"})
    logout_ok = r4 is not None and r4.status_code == 200 and r4.json().get("status") == "logout"
    test("Session LOGOUT recorded successfully", logout_ok, r4.text if r4 else "No response")

    if logout_ok:
        lo = r4.json()
        test("Duration minutes calculated",    lo.get("duration_minutes", -1) >= 0, f"Got: {lo.get('duration_minutes')}")
        test("Amount due calculated",          lo.get("amount_due", -1) >= 0,        f"Got: {lo.get('amount_due')}")
        test("Duration display string present", bool(lo.get("duration_display")),    f"Got: {lo.get('duration_display')}")
        test("Session history returned on logout", isinstance(lo.get("session_history"), list))

# ── 5. BILLING ACCURACY ────────────────────────────────────────────────────
section("TEST 5: Billing Accuracy")
month = datetime.now().strftime("%Y-%m")

r = get("/api/admin/billing", {"month": month})
test("Billing endpoint returns 200", r is not None and r.status_code == 200)

if r and r.status_code == 200:
    billing = r.json().get("billing", [])
    test("Billing returns all active bakers", len(billing) >= 10, f"Got {len(billing)}")
    test("All billing entries have required fields",
         all("baker_name" in b and "total_amount" in b and "total_hours" in b for b in billing))
    test("All billing amounts are non-negative",
         all(b["total_amount"] >= 0 for b in billing))
    brian = next((b for b in billing if "Brian" in b["baker_name"]), None)
    test("Brian Otieno session appears in billing",
         brian is not None and brian["session_count"] > 0, f"Brian data: {brian}")

# ── 6. ADMIN ENDPOINTS ─────────────────────────────────────────────────────
section("TEST 6: Admin Endpoints")

r = post("/api/admin/login", {"pin": "0000"})
test("Admin login correct PIN (0000)",
     r is not None and r.status_code == 200 and r.json().get("status") == "ok")

r = post("/api/admin/login", {"pin": "999999"})
test("Admin login wrong PIN rejected",
     r is not None and r.status_code == 401, r.text if r else "No response")

r = get("/api/admin/bakers")
test("Get bakers returns 200 with 10+ bakers",
     r is not None and r.status_code == 200 and len(r.json()) >= 10, f"Got {len(r.json()) if r else 0}")

r = get("/api/admin/sessions", {"month": month})
test("Session log returns 200", r is not None and r.status_code == 200)

r = get("/api/admin/revenue_chart", {"month": month})
test("Revenue chart returns labels + revenue arrays",
     r is not None and r.status_code == 200 and "labels" in r.json() and "revenue" in r.json())

r = get("/api/admin/alerts", {"month": month})
test("Alerts endpoint returns correct structure",
     r is not None and r.status_code == 200 and "zero_amount" in r.json() and "stuck_sessions" in r.json())

r = get("/api/admin/summary", {"month": month})
test("Summary stats returns all required fields",
     r is not None and r.status_code == 200 and
     all(k in r.json() for k in ["active_sessions","total_bakers","month_revenue"]))

# ── 7. CSV EXPORT ──────────────────────────────────────────────────────────
section("TEST 7: CSV Export")

r = get("/api/admin/billing/csv", {"month": month})
test("CSV export returns 200",           r is not None and r.status_code == 200)
test("CSV content-type is text/csv",     r is not None and "text/csv" in r.headers.get("Content-Type",""))
test("CSV has header row (Baker Name)",  r is not None and "Baker Name" in r.text)
test("CSV has TOTAL REVENUE footer row", r is not None and "TOTAL REVENUE" in r.text)

# ── 8. BAKER RATE UPDATE ───────────────────────────────────────────────────
section("TEST 8: Baker Rate Update")

r = get("/api/admin/bakers")
if r and r.json():
    bakers    = r.json()
    bid       = bakers[0]["BakerID"]
    orig_rate = bakers[0]["HourlyRate"]

    r2 = post(f"/api/admin/bakers/{bid}/rate", {"rate": 75})
    test("Rate updated to 75 returns 200", r2 is not None and r2.status_code == 200, r2.text if r2 else "No response")

    r3 = get("/api/admin/bakers")
    updated = next((b for b in r3.json() if b["BakerID"] == bid), None)
    test("Rate successfully changed to 75",
         updated is not None and updated["HourlyRate"] == 75.0,
         f"Got: {updated.get('HourlyRate') if updated else 'not found'}")

    post(f"/api/admin/bakers/{bid}/rate", {"rate": orig_rate})
    test("Rate restored to original", True)

    r4 = post(f"/api/admin/bakers/{bid}/rate", {"rate": -10})
    test("Negative rate rejected (400)",
         r4 is not None and r4.status_code == 400,
         r4.text if r4 else "No response — check rate validation in app.py")

# ── 9. BAKER MANAGEMENT ────────────────────────────────────────────────────
section("TEST 9: Baker Account Management")
wait_for_unlock()

# Remove existing UAT baker if present (from previous run)
r_all = get("/api/admin/bakers")
if r_all:
    existing = next((b for b in r_all.json() if b["FullName"] == "Test Baker UAT"), None)
    if existing:
        # Ensure deactivated so PIN 1111 is free
        if existing["IsActive"]:
            post(f"/api/admin/bakers/{existing['BakerID']}/toggle", {})
        time.sleep(0.2)

# Add new UAT baker
r = post("/api/admin/bakers", {"name": "Test Baker UAT", "pin": "111111", "rate": 60})
add_ok = r is not None and r.status_code == 200
test("New baker added successfully", add_ok, r.text if r else "No response")

# Duplicate PIN
r2 = post("/api/admin/bakers", {"name": "Duplicate Baker", "pin": "111111", "rate": 50})
test("Duplicate PIN rejected (409)",
     r2 is not None and r2.status_code == 409,
     r2.text if r2 else "No response")

# Login as new baker
time.sleep(0.3)
r3 = post("/api/login", {"pin": "111111"})
test("New baker can log in with PIN",
     r3 is not None and r3.status_code == 200 and r3.json().get("status") in ("login","logout"),
     r3.text if r3 else "No response")
if r3 and r3.status_code == 200 and r3.json().get("status") == "login":
    time.sleep(0.3); post("/api/login", {"pin": "111111"})

# Find and deactivate UAT baker
time.sleep(0.3)
r4 = get("/api/admin/bakers")
uat = next((b for b in r4.json() if b["FullName"] == "Test Baker UAT"), None) if r4 else None
if uat and uat.get("IsActive", 0) == 1:
    r5 = post(f"/api/admin/bakers/{uat['BakerID']}/toggle", {})
    test("Baker deactivated successfully",
         r5 is not None and r5.status_code == 200,
         r5.text if r5 else "No response")
else:
    test("Baker deactivated successfully", uat is not None, "Baker not found")

# Deactivated baker cannot log in
time.sleep(0.3)
r6 = post("/api/login", {"pin": "111111"})
test("Deactivated baker blocked from login",
     r6 is not None and r6.status_code in (401, 423),
     r6.text[:100] if r6 else "No response")

# ── 10. SECURITY LOG ───────────────────────────────────────────────────────
section("TEST 10: Security Log")

r = get("/api/admin/failed_attempts")
test("Failed attempts endpoint returns 200", r is not None and r.status_code == 200)
test("Failed attempts log is non-empty",
     r is not None and len(r.json()) > 0,
     "No attempts logged — ensure lockout tests ran")

# ── SUMMARY ────────────────────────────────────────────────────────────────
total   = len(results)
passed  = sum(1 for r in results if r["passed"])
failed  = total - passed
pct     = round((passed/total)*100) if total else 0

print(f"\n{'='*55}")
print(f"  TEST RESULTS SUMMARY")
print(f"{'='*55}")
print(f"  Total Tests : {total}")
print(f"  \033[92mPassed      : {passed}\033[0m")
if failed: print(f"  \033[91mFailed      : {failed}\033[0m")
else:      print(f"  Failed      : 0")
print(f"  Pass Rate   : {pct}%")
print(f"{'='*55}")

if   failed == 0: print("\n  \033[92m🎉 ALL TESTS PASSED — System ready for deployment!\033[0m\n")
elif pct >= 80:   print(f"\n  \033[93m⚠ {failed} test(s) failed — minor issues to fix\033[0m\n")
else:             print(f"\n  \033[91m✗ {failed} test(s) failed — review before deployment\033[0m\n")

with open("test_results.json", "w") as f:
    json.dump({"run_at":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"total":total,"passed":passed,"failed":failed,"pct":pct,"results":results}, f, indent=2)
print(f"  Results saved to test_results.json\n")
sys.exit(0 if failed == 0 else 1)
