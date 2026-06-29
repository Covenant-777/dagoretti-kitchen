from flask import Flask, request, jsonify, send_from_directory, Response
from database import get_db, hash_pin, init_db
from datetime import datetime, timedelta
import csv, io, os, json as _json

app = Flask(__name__, static_folder="static")
init_db()

# Auto-seed demo data if DB is empty (for Render deployment)
def auto_seed_if_empty():
    import os, random
    from datetime import timedelta
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM Sessions WHERE EndTime IS NOT NULL")
    if c.fetchone()['count'] == 0:
        now = __import__('datetime').datetime.now()
        month = now.strftime("%Y-%m")
        base = now.replace(day=1, hour=7, minute=0, second=0, microsecond=0)
        random.seed(42)
        for baker_id in range(1, 11):
            day_offset = 0
            for _ in range(random.randint(3, 5)):
                day_offset += random.randint(1, 2)
                if day_offset >= max(now.day, 2): break
                dur = random.randint(45, 120)
                start = base.replace(day=max(1, day_offset),
                                     hour=random.randint(7,15),
                                     minute=random.choice([0,15,30]))
                end = start + timedelta(minutes=dur)
                amt = round((dur/60)*50.0, 2)
                c.execute("INSERT INTO Sessions (BakerID,StartTime,EndTime,DurationMinutes,AmountDue,Month) VALUES (%s,%s,%s,%s,%s,%s)",
                          (baker_id, start.strftime("%Y-%m-%d %H:%M:%S"),
                           end.strftime("%Y-%m-%d %H:%M:%S"), float(dur), amt, month))
        conn.commit()
    conn.close()

auto_seed_if_empty()

MAX_ATTEMPTS = 3
LOCKOUT_SECONDS = 30
lockout_tracker = {}

def get_ip(): return request.remote_addr or "127.0.0.1"

def check_lockout(ip):
    if ip not in lockout_tracker: return False, 0
    lu = lockout_tracker[ip].get("locked_until")
    if lu and datetime.now() < lu:
        return True, int((lu - datetime.now()).total_seconds())
    if lu: lockout_tracker[ip] = {"count": 0, "locked_until": None}
    return False, 0

def record_fail(ip, reason):
    if ip not in lockout_tracker: lockout_tracker[ip] = {"count": 0, "locked_until": None}
    lockout_tracker[ip]["count"] += 1
    count = lockout_tracker[ip]["count"]
    conn = get_db()
    conn.execute("INSERT INTO FailedAttempts (Note) VALUES (%s)",
                 (f"{reason} | Attempt {count}/{MAX_ATTEMPTS} from {ip}",))
    conn.commit(); conn.close()
    if count >= MAX_ATTEMPTS:
        lockout_tracker[ip]["locked_until"] = datetime.now() + timedelta(seconds=LOCKOUT_SECONDS)
        lockout_tracker[ip]["count"] = 0
        return True, LOCKOUT_SECONDS
    return False, 0

def reset_fail(ip): lockout_tracker[ip] = {"count": 0, "locked_until": None}
def attempts_left(ip):
    if ip not in lockout_tracker: return MAX_ATTEMPTS
    return max(0, MAX_ATTEMPTS - lockout_tracker[ip].get("count", 0))

@app.route("/")
def index(): return send_from_directory("static", "index.html")

@app.route("/api/login", methods=["POST"])
def baker_login():
    ip = get_ip(); data = request.json; pin = data.get("pin","").strip()
    if not pin or len(pin) != 6 or not pin.isdigit():
        return jsonify({"status":"error","message":"Enter a valid 4-digit PIN"}), 400
    locked, secs = check_lockout(ip)
    if locked:
        return jsonify({"status":"locked","message":f"Terminal locked. Try again in {secs}s.","seconds_remaining":secs}), 423
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM Bakers WHERE PIN_Hash=%s AND IsActive=1", (hash_pin(pin),))
    baker = c.fetchone()
    if not baker:
        conn.close(); just_locked, ls = record_fail(ip, "Wrong PIN")
        if just_locked:
            return jsonify({"status":"locked","message":f"Too many wrong PINs! Locked for {ls}s.","seconds_remaining":ls}), 423
        rem = attempts_left(ip)
        return jsonify({"status":"wrong_pin","message":f"Incorrect PIN. {rem} attempt{'s' if rem!=1 else ''} remaining.","attempts_remaining":rem}), 401
    reset_fail(ip)
    bid = baker["BakerID"]; bname = baker["FullName"]
    c.execute("SELECT * FROM Sessions WHERE BakerID=%s AND EndTime IS NULL ORDER BY SessionID DESC LIMIT 1", (bid,))
    active = c.fetchone()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if active:
        start_dt = datetime.strptime(active["StartTime"], "%Y-%m-%d %H:%M:%S")
        dur_min = (datetime.strptime(now,"%Y-%m-%d %H:%M:%S") - start_dt).total_seconds() / 60
        amount = round((dur_min/60)*baker["HourlyRate"], 2)
        month = start_dt.strftime("%Y-%m")
        c.execute("UPDATE Sessions SET EndTime=%s,DurationMinutes=%s,AmountDue=%s,Month=%s WHERE SessionID=%s",
                  (now, round(dur_min,2), amount, month, active["SessionID"]))
        c.execute("SELECT StartTime,EndTime,DurationMinutes,AmountDue FROM Sessions WHERE BakerID=%s AND EndTime IS NOT NULL ORDER BY SessionID DESC LIMIT 5", (bid,))
        history = [dict(r) for r in c.fetchall()]
        conn.commit(); conn.close()
        m = int(dur_min); s = int((dur_min%1)*60)
        return jsonify({"status":"logout","baker_name":bname,"baker_id":bid,"start_time":active["StartTime"],"end_time":now,"duration_minutes":round(dur_min,2),"duration_display":f"{m}m {s}s","amount_due":amount,"hourly_rate":baker["HourlyRate"],"session_history":history,"message":f"Session ended. {m}m {s}s. Bill: KES {amount}"})
    else:
        c.execute("INSERT INTO Sessions (BakerID,StartTime) VALUES (%s,%s)", (bid, now))
        sid = c.lastrowid
        c.execute("SELECT StartTime,EndTime,DurationMinutes,AmountDue FROM Sessions WHERE BakerID=%s AND EndTime IS NOT NULL ORDER BY SessionID DESC LIMIT 5", (bid,))
        history = [dict(r) for r in c.fetchall()]
        conn.commit(); conn.close()
        return jsonify({"status":"login","baker_name":bname,"baker_id":bid,"session_id":sid,"start_time":now,"hourly_rate":baker["HourlyRate"],"session_history":history,"message":f"Welcome {bname.split()[0]}! Session started at {now[11:]}"})

@app.route("/api/elapsed/<int:baker_id>")
def get_elapsed(baker_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT s.SessionID,s.StartTime,b.HourlyRate FROM Sessions s JOIN Bakers b ON s.BakerID=b.BakerID WHERE s.BakerID=%s AND s.EndTime IS NULL ORDER BY s.SessionID DESC LIMIT 1", (baker_id,))
    row = c.fetchone(); conn.close()
    if not row: return jsonify({"active":False})
    elapsed_s = int((datetime.now()-datetime.strptime(row["StartTime"],"%Y-%m-%d %H:%M:%S")).total_seconds())
    return jsonify({"active":True,"session_id":row["SessionID"],"start_time":row["StartTime"],"elapsed_seconds":elapsed_s,"elapsed_display":f"{elapsed_s//60}m {elapsed_s%60}s","running_bill":round((elapsed_s/3600)*row["HourlyRate"],2)})

@app.route("/api/lockout_status")
def lockout_status():
    ip = get_ip(); locked, secs = check_lockout(ip)
    return jsonify({"locked":locked,"seconds_remaining":secs,"attempts_remaining":attempts_left(ip)})

@app.route("/api/active_sessions")
def active_sessions():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT s.SessionID,b.BakerID,b.FullName,s.StartTime,b.HourlyRate FROM Sessions s JOIN Bakers b ON s.BakerID=b.BakerID WHERE s.EndTime IS NULL ORDER BY s.StartTime ASC")
    rows = c.fetchall(); conn.close(); now = datetime.now()
    return jsonify([{"session_id":r["SessionID"],"baker_id":r["BakerID"],"baker_name":r["FullName"],"start_time":r["StartTime"],"elapsed_seconds":int((now-datetime.strptime(r["StartTime"],"%Y-%m-%d %H:%M:%S")).total_seconds()),"running_bill":round(((now-datetime.strptime(r["StartTime"],"%Y-%m-%d %H:%M:%S")).total_seconds()/3600)*r["HourlyRate"],2)} for r in rows])

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    pin = request.json.get("pin","").strip()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT SettingValue FROM AdminSettings WHERE SettingKey='admin_pin_hash'")
    row = c.fetchone(); conn.close()
    stored_hash = row["SettingValue"] if row else hash_pin("0000")
    if hash_pin(pin) == stored_hash:
        return jsonify({"status":"ok"})
    return jsonify({"status":"error","message":"Wrong admin PIN"}), 401

@app.route("/api/admin/change_pin", methods=["POST"])
def admin_change_pin():
    """Admin changes their own PIN"""
    data = request.json
    current = data.get("current_pin","").strip()
    new_pin = data.get("new_pin","").strip()
    if len(new_pin) != 4 or not new_pin.isdigit():
        return jsonify({"error":"New PIN must be exactly 4 digits"}), 400
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT SettingValue FROM AdminSettings WHERE SettingKey='admin_pin_hash'")
    row = c.fetchone(); conn.close()
    stored_hash = row["SettingValue"] if row else hash_pin("0000")
    if hash_pin(current) != stored_hash:
        return jsonify({"error":"Current PIN is incorrect"}), 401
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE AdminSettings SET SettingValue=?, UpdatedAt=datetime('now','localtime') WHERE SettingKey='admin_pin_hash'",
    c.execute("UPDATE AdminSettings SET SettingValue=%s, UpdatedAt=to_char(now(), 'YYYY-MM-DD HH24:MI:SS') WHERE SettingKey='admin_pin_hash'",
              (hash_pin(new_pin),))
    conn.commit(); conn.close()
    return jsonify({"status":"ok","message":"Admin PIN changed successfully"})

@app.route("/api/admin/summary")
def admin_summary():
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM Sessions WHERE EndTime IS NULL")
    active = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM Bakers WHERE IsActive=1")
    bakers = c.fetchone()[0]
    c.execute("SELECT COUNT(*),COALESCE(SUM(AmountDue),0) FROM Sessions WHERE Month=%s AND EndTime IS NOT NULL", (month,))
    row = c.fetchone()
    c.execute("SELECT COUNT(*) FROM FailedAttempts WHERE AttemptedAt >= date('now','start of month')")
    fails = c.fetchone()[0]
    conn.close()
    return jsonify({"active_sessions":active,"total_bakers":bakers,"month_sessions":row[0],"month_revenue":round(row[1],2),"month_failed_attempts":fails,"month":month})

@app.route("/api/admin/sessions")
def all_sessions():
    bf = request.args.get("baker_id"); mf = request.args.get("month")
    conn = get_db(); c = conn.cursor()
    q = "SELECT s.SessionID,b.FullName,b.BakerID,s.StartTime,s.EndTime,s.DurationMinutes,s.AmountDue,s.Month FROM Sessions s JOIN Bakers b ON s.BakerID=b.BakerID WHERE s.EndTime IS NOT NULL"
    p = []
    if bf: q += " AND b.BakerID=?"; p.append(bf)
    if mf: q += " AND s.Month=?"; p.append(mf)
    q += " ORDER BY s.StartTime DESC LIMIT 200"
    c.execute(q, p); rows = c.fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/admin/billing")
def billing_summary():
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    conn = get_db(); c = conn.cursor()
    c.execute("""SELECT b.BakerID,b.FullName,b.HourlyRate,
                        COALESCE(SUM(s.DurationMinutes),0) AS TotalMinutes,
                        COALESCE(SUM(s.AmountDue),0) AS TotalAmount,
                        COUNT(s.SessionID) AS SessionCount
                 FROM Bakers b LEFT JOIN Sessions s ON b.BakerID=s.BakerID AND s.Month=? AND s.EndTime IS NOT NULL
                 WHERE b.IsActive=1 GROUP BY b.BakerID ORDER BY TotalAmount DESC""", (month,))
    rows = c.fetchall(); conn.close()
    return jsonify({"month":month,"billing":[{"baker_id":r["BakerID"],"baker_name":r["FullName"],"hourly_rate":r["HourlyRate"],"session_count":r["SessionCount"],"total_minutes":round(r["TotalMinutes"],1),"total_hours":round(r["TotalMinutes"]/60,2),"total_amount":round(r["TotalAmount"],2)} for r in rows]})

@app.route("/api/admin/billing/csv")
def billing_csv():
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    conn = get_db(); c = conn.cursor()
    c.execute("""SELECT b.FullName,b.HourlyRate,COALESCE(SUM(s.DurationMinutes),0) AS TotalMinutes,
                        COALESCE(SUM(s.AmountDue),0) AS TotalAmount,COUNT(s.SessionID) AS SessionCount
                 FROM Bakers b LEFT JOIN Sessions s ON b.BakerID=s.BakerID AND s.Month=? AND s.EndTime IS NOT NULL
                 WHERE b.IsActive=1 GROUP BY b.BakerID ORDER BY b.FullName""", (month,))
    rows = c.fetchall(); conn.close()
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["Baker Name","Sessions","Total Hours","Total Minutes","Rate (KES/hr)","Amount Due (KES)"])
    total_rev = 0
    for r in rows:
        writer.writerow([r["FullName"],r["SessionCount"],round(r["TotalMinutes"]/60,2),round(r["TotalMinutes"],1),r["HourlyRate"],round(r["TotalAmount"],2)])
        total_rev += r["TotalAmount"]
    writer.writerow([]); writer.writerow(["","","","","TOTAL REVENUE:",round(total_rev,2)])
    writer.writerow(["","","","","Generated:",datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition":f"attachment;filename=billing_{month}.csv"})

@app.route("/api/admin/revenue_chart")
def revenue_chart():
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    conn = get_db(); c = conn.cursor()
    c.execute("""SELECT b.FullName,COALESCE(SUM(s.AmountDue),0) AS Revenue,
                        COALESCE(SUM(s.DurationMinutes),0) AS Minutes,COUNT(s.SessionID) AS Sessions
                 FROM Bakers b LEFT JOIN Sessions s ON b.BakerID=s.BakerID AND s.Month=? AND s.EndTime IS NOT NULL
                 WHERE b.IsActive=1 GROUP BY b.BakerID ORDER BY Revenue DESC""", (month,))
    rows = c.fetchall(); conn.close()
    return jsonify({"month":month,"labels":[r["FullName"].split()[0] for r in rows],"revenue":[round(r["Revenue"],2) for r in rows],"sessions":[r["Sessions"] for r in rows],"minutes":[round(r["Minutes"],1) for r in rows]})

@app.route("/api/admin/alerts")
def alerts():
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    conn = get_db(); c = conn.cursor()
    c.execute("""SELECT b.FullName,COUNT(s.SessionID) AS Sessions,COALESCE(SUM(s.AmountDue),0) AS Total
                 FROM Bakers b JOIN Sessions s ON b.BakerID=s.BakerID AND s.Month=? AND s.EndTime IS NOT NULL
                 WHERE b.IsActive=1 GROUP BY b.BakerID HAVING Total=0 OR Total IS NULL""", (month,))
    zero = c.fetchall()
    c.execute("""SELECT b.FullName,s.StartTime FROM Sessions s JOIN Bakers b ON s.BakerID=b.BakerID
                 WHERE s.EndTime IS NULL AND (julianday('now','localtime')-julianday(s.StartTime))*24 > 4""")
    stuck = c.fetchall()
    conn.close()
    return jsonify({"zero_amount":[{"name":r["FullName"],"sessions":r["Sessions"]} for r in zero],"stuck_sessions":[{"name":r["FullName"],"start":r["StartTime"]} for r in stuck]})

@app.route("/api/admin/bakers")
def get_bakers():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT BakerID,FullName,HourlyRate,IsActive,CreatedAt FROM Bakers ORDER BY FullName")
    rows = c.fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/admin/bakers", methods=["POST"])
def add_baker():
    data = request.json; name = data.get("name","").strip(); pin = data.get("pin","").strip(); rate = float(data.get("rate",50))
    if not name or not pin or len(pin)!=6 or not pin.isdigit():
        return jsonify({"error":"Invalid name or PIN"}), 400
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT 1 FROM Bakers WHERE PIN_Hash=%s", (hash_pin(pin),))
    if c.fetchone(): conn.close(); return jsonify({"error":"PIN already in use"}), 409
    c.execute("INSERT INTO Bakers (FullName,PIN_Hash,HourlyRate) VALUES (%s,%s,%s)", (name,hash_pin(pin),rate))
    conn.commit(); conn.close()
    return jsonify({"status":"ok","message":f"{name} added successfully"})

@app.route("/api/admin/bakers/<int:bid>/toggle", methods=["POST"])
def toggle_baker(bid):
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE Bakers SET IsActive=1-IsActive WHERE BakerID=%s", (bid,))
    conn.commit(); c.execute("SELECT IsActive FROM Bakers WHERE BakerID=%s", (bid,))
    row = c.fetchone(); conn.close()
    return jsonify({"status":"ok","message":f"Baker {'activated' if row['IsActive'] else 'deactivated'}"})

@app.route("/api/admin/bakers/<int:bid>/rate", methods=["POST"])
def update_rate(bid):
    rate = float(request.json.get("rate", 0))
    if rate <= 0: return jsonify({"error":"Rate must be greater than 0"}), 400
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE Bakers SET HourlyRate=%s WHERE BakerID=%s", (rate, bid))
    conn.commit(); c.execute("SELECT FullName FROM Bakers WHERE BakerID=%s", (bid,))
    row = c.fetchone(); conn.close()
    return jsonify({"status":"ok","message":f"Rate updated to KES {rate}/hr for {row['FullName']}"})

@app.route("/api/admin/failed_attempts")
def failed_attempts():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM FailedAttempts ORDER BY AttemptedAt DESC LIMIT 50")
    rows = c.fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/test_results")
def test_results():
    path = os.path.join(os.path.dirname(__file__), "test_results.json")
    if not os.path.exists(path):
        return jsonify({"error":"No test results yet. Run: python test_system.py"}), 404
    with open(path) as f:
        return jsonify(_json.load(f))


# ── FORCE LOGOUT (Admin closes any active session) ─────────────────────────
@app.route("/api/admin/sessions/<int:session_id>/force_end", methods=["POST"])
def force_end_session(session_id):
    """Admin force-closes an active session when baker forgets their PIN"""
    conn = get_db(); c = conn.cursor()
    c.execute("""
        SELECT s.*, b.FullName, b.HourlyRate
        FROM Sessions s JOIN Bakers b ON s.BakerID=b.BakerID
        WHERE s.SessionID=? AND s.EndTime IS NULL
    """, (session_id,))
    session = c.fetchone()
    if not session:
        conn.close()
        return jsonify({"error": "Session not found or already closed"}), 404
    now          = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_dt     = datetime.strptime(session["StartTime"], "%Y-%m-%d %H:%M:%S")
    duration_min = (datetime.strptime(now, "%Y-%m-%d %H:%M:%S") - start_dt).total_seconds() / 60
    amount_due   = round((duration_min / 60) * session["HourlyRate"], 2)
    month        = start_dt.strftime("%Y-%m")
    c.execute("UPDATE Sessions SET EndTime=%s, DurationMinutes=%s, AmountDue=%s, Month=%s WHERE SessionID=%s",
              (now, round(duration_min, 2), amount_due, month, session_id))
    c.execute("INSERT INTO FailedAttempts (Note) VALUES (%s)",
              (f"ADMIN FORCE-LOGOUT: {session['FullName']} | Session {session_id} | Duration: {int(duration_min)}m | KES {amount_due}",))
    conn.commit(); conn.close()
    m = int(duration_min); s = int((duration_min % 1) * 60)
    return jsonify({
        "status": "ok",
        "message": f"Session force-ended for {session['FullName']}. Duration: {m}m {s}s. Bill: KES {amount_due}",
        "baker_name": session["FullName"],
        "duration_display": f"{m}m {s}s",
        "amount_due": amount_due
    })


# ── AUTO-TIMEOUT (Close sessions open longer than 8 hours) ─────────────────
@app.route("/api/admin/auto_timeout", methods=["POST"])
def auto_timeout():
    """Auto-close any session open longer than 8 hours"""
    MAX_HOURS = 8
    conn = get_db(); c = conn.cursor()
    c.execute("""
        SELECT s.*, b.FullName, b.HourlyRate
        FROM Sessions s JOIN Bakers b ON s.BakerID=b.BakerID
        WHERE s.EndTime IS NULL
        AND (EXTRACT(EPOCH FROM (now() - TO_TIMESTAMP(s.StartTime, 'YYYY-MM-DD HH24:MI:SS')))/3600 > %s
    """, (MAX_HOURS,))
    stuck = c.fetchall()
    if not stuck:
        conn.close()
        return jsonify({"status": "ok", "message": "No sessions exceeded 8 hours", "closed": 0})
    closed = 0
    for session in stuck:
        now          = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_dt     = datetime.strptime(session["StartTime"], "%Y-%m-%d %H:%M:%S")
        duration_min = (datetime.strptime(now, "%Y-%m-%d %H:%M:%S") - start_dt).total_seconds() / 60
        billed_min   = min(duration_min, MAX_HOURS * 60)
        amount_due   = round((billed_min / 60) * session["HourlyRate"], 2)
        month        = start_dt.strftime("%Y-%m")
        c.execute("UPDATE Sessions SET EndTime=%s, DurationMinutes=%s, AmountDue=%s, Month=%s WHERE SessionID=%s",
                  (now, round(billed_min, 2), amount_due, month, session["SessionID"]))
        c.execute("INSERT INTO FailedAttempts (Note) VALUES (%s)",
                  (f"AUTO-TIMEOUT: {session['FullName']} | Session {session['SessionID']} | KES {amount_due}",))
        closed += 1
    conn.commit(); conn.close()
    return jsonify({"status": "ok", "message": f"{closed} session(s) auto-closed after {MAX_HOURS} hours", "closed": closed})



# ── BAKER PIN CHANGE ────────────────────────────────────────────────────────
@app.route("/api/baker/request_pin_change", methods=["POST"])
def request_pin_change():
    """Baker submits a PIN change request — admin must approve"""
    data    = request.json
    old_pin = data.get("old_pin","").strip()
    new_pin = data.get("new_pin","").strip()
    confirm = data.get("confirm_pin","").strip()
    if len(new_pin) != 6 or not new_pin.isdigit():
        return jsonify({"error":"New PIN must be exactly 6 digits"}), 400
    if new_pin != confirm:
        return jsonify({"error":"New PIN and confirmation do not match"}), 400
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM Bakers WHERE PIN_Hash=? AND IsActive=1", (hash_pin(old_pin),))
    c.execute("SELECT * FROM Bakers WHERE PIN_Hash=%s AND IsActive=1", (hash_pin(old_pin),))
    baker = c.fetchone()
    if not baker:
        conn.close()
        return jsonify({"error":"Current PIN is incorrect"}), 401
    # Check no pending request exists
    c.execute("SELECT 1 FROM PINChangeRequests WHERE BakerID=? AND Status='pending'", (baker["BakerID"],))
    c.execute("SELECT 1 FROM PINChangeRequests WHERE BakerID=%s AND Status='pending'", (baker["BakerID"],))
    if c.fetchone():
        conn.close()
        return jsonify({"error":"You already have a pending PIN change request"}), 409
    # Check new PIN not already in use
    c.execute("SELECT 1 FROM Bakers WHERE PIN_Hash=?", (hash_pin(new_pin),))
    if c.fetchone():
        conn.close()
        return jsonify({"error":"That PIN is already in use by another baker"}), 409
    c.execute("INSERT INTO PINChangeRequests (BakerID, NewPIN_Hash) VALUES (?,?)",
    c.execute("SELECT 1 FROM Bakers WHERE PIN_Hash=%s", (hash_pin(new_pin),))
    if c.fetchone():
        conn.close()
        return jsonify({"error":"That PIN is already in use by another baker"}), 409
    c.execute("INSERT INTO PINChangeRequests (BakerID, NewPIN_Hash) VALUES (%s,%s)",
              (baker["BakerID"], hash_pin(new_pin)))
    conn.commit(); conn.close()
    return jsonify({"status":"ok","message":f"PIN change request submitted for {baker['FullName']}. Waiting for admin approval."})


@app.route("/api/admin/pin_requests", methods=["GET"])
def get_pin_requests():
    """Admin views all pending PIN change requests"""
    conn = get_db(); c = conn.cursor()
    c.execute("""SELECT r.RequestID, b.FullName, b.BakerID, r.Status, r.RequestedAt
                 FROM PINChangeRequests r JOIN Bakers b ON r.BakerID=b.BakerID
                 WHERE r.Status='pending'
                 ORDER BY r.RequestedAt DESC""")
    rows = c.fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/admin/pin_requests/<int:req_id>/approve", methods=["POST"])
def approve_pin_request(req_id):
    """Admin approves a baker PIN change"""
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM PINChangeRequests WHERE RequestID=? AND Status='pending'", (req_id,))
    c.execute("SELECT * FROM PINChangeRequests WHERE RequestID=%s AND Status='pending'", (req_id,))
    req = c.fetchone()
    if not req:
        conn.close()
        return jsonify({"error":"Request not found or already processed"}), 404
    # Apply new PIN hash to baker
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("UPDATE Bakers SET PIN_Hash=? WHERE BakerID=?", (req["NewPIN_Hash"], req["BakerID"]))
    c.execute("UPDATE PINChangeRequests SET Status='approved', ApprovedAt=? WHERE RequestID=?", (now, req_id))
    c.execute("SELECT FullName FROM Bakers WHERE BakerID=?", (req["BakerID"],))
    c.execute("UPDATE Bakers SET PIN_Hash=%s WHERE BakerID=%s", (req["NewPIN_Hash"], req["BakerID"]))
    c.execute("UPDATE PINChangeRequests SET Status='approved', ApprovedAt=%s WHERE RequestID=%s", (now, req_id))
    c.execute("SELECT FullName FROM Bakers WHERE BakerID=%s", (req["BakerID"],))
    name = c.fetchone()["FullName"]
    conn.commit(); conn.close()
    return jsonify({"status":"ok","message":f"PIN change approved for {name}"})


@app.route("/api/admin/pin_requests/<int:req_id>/reject", methods=["POST"])
def reject_pin_request(req_id):
    """Admin rejects a baker PIN change"""
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE PINChangeRequests SET Status='rejected' WHERE RequestID=? AND Status='pending'", (req_id,))
    c.execute("UPDATE PINChangeRequests SET Status='rejected' WHERE RequestID=%s AND Status='pending'", (req_id,))
    conn.commit(); conn.close()
    return jsonify({"status":"ok","message":"PIN change request rejected"})


if __name__ == "__main__":
    print("\n🍰 Dagoretti Kitchen Incubator — FINAL")
    print("=" * 45)
    print("Baker terminal : http://127.0.0.1:5000")
    print("Admin PIN      : 0000  (Baker PINs: 6 digits)")
    print("Features       : 6-digit PINs | Force-logout | Auto-timeout")
    print("-" * 45)
    print("Bakers: Amina=123456  Brian=234567  Carol=345678")
    print("        David=456789  Esther=567890 Felix=678901")
    print("        Grace=789012  Hassan=890123 Irene=901234")
    print("        James=012345")
    print("=" * 45 + "\n")
    app.run(debug=True, port=5000)
