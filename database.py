"""
database.py — Dagoretti Kitchen Incubator
PostgreSQL database — data persists forever on Render
"""
import psycopg2, psycopg2.extras, hashlib, os
from datetime import datetime

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://dagoretti_db_user:WwRfDK9joeJPF1GxUzYPPBrjvHj4rM8X@dpg-d91eqirsq97s738fr60g-a/dagoretti_db"
)

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return conn

def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()

def init_db():
    conn = get_db(); c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS Bakers (
        BakerID    SERIAL PRIMARY KEY,
        FullName   TEXT NOT NULL,
        PIN_Hash   TEXT NOT NULL,
        HourlyRate REAL NOT NULL DEFAULT 50.0,
        IsActive   INTEGER NOT NULL DEFAULT 1,
        CreatedAt  TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS')))""")

    c.execute("""CREATE TABLE IF NOT EXISTS Sessions (
        SessionID       SERIAL PRIMARY KEY,
        BakerID         INTEGER NOT NULL REFERENCES Bakers(BakerID),
        StartTime       TEXT NOT NULL,
        EndTime         TEXT,
        DurationMinutes REAL,
        AmountDue       REAL,
        Month           TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS FailedAttempts (
        AttemptID   SERIAL PRIMARY KEY,
        AttemptedAt TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
        Note        TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS MonthlyBilling (
        BillingID      SERIAL PRIMARY KEY,
        BakerID        INTEGER NOT NULL REFERENCES Bakers(BakerID),
        Month          TEXT NOT NULL,
        TotalMinutes   REAL NOT NULL DEFAULT 0,
        TotalHours     REAL NOT NULL DEFAULT 0,
        TotalAmountKES REAL NOT NULL DEFAULT 0,
<<<<<<< HEAD
        GeneratedAt TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (BakerID) REFERENCES Bakers(BakerID))""")

    # Admin settings table - stores hashed admin PIN
    c.execute("""CREATE TABLE IF NOT EXISTS AdminSettings (
        SettingID   INTEGER PRIMARY KEY AUTOINCREMENT,
        SettingKey  TEXT NOT NULL UNIQUE,
        SettingValue TEXT NOT NULL,
        UpdatedAt   TEXT NOT NULL DEFAULT (datetime('now','localtime')))""")

    # PIN change requests table
    c.execute("""CREATE TABLE IF NOT EXISTS PINChangeRequests (
        RequestID   INTEGER PRIMARY KEY AUTOINCREMENT,
        BakerID     INTEGER NOT NULL,
        NewPIN_Hash TEXT NOT NULL,
        Status      TEXT NOT NULL DEFAULT 'pending',
        RequestedAt TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        ApprovedAt  TEXT,
        FOREIGN KEY (BakerID) REFERENCES Bakers(BakerID))""")
    # Seed default admin PIN (0000) if not set
    c.execute("SELECT COUNT(*) FROM AdminSettings WHERE SettingKey='admin_pin_hash'")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO AdminSettings (SettingKey, SettingValue) VALUES (?,?)",
=======
        GeneratedAt    TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS')))""")

    c.execute("""CREATE TABLE IF NOT EXISTS AdminSettings (
        SettingID    SERIAL PRIMARY KEY,
        SettingKey   TEXT NOT NULL UNIQUE,
        SettingValue TEXT NOT NULL,
        UpdatedAt    TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS')))""")

    c.execute("""CREATE TABLE IF NOT EXISTS PINChangeRequests (
        RequestID   SERIAL PRIMARY KEY,
        BakerID     INTEGER NOT NULL REFERENCES Bakers(BakerID),
        NewPIN_Hash TEXT NOT NULL,
        Status      TEXT NOT NULL DEFAULT 'pending',
        RequestedAt TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
        ApprovedAt  TEXT)""")

    c.execute("SELECT COUNT(*) FROM AdminSettings WHERE SettingKey='admin_pin_hash'")
    if c.fetchone()['count'] == 0:
        c.execute("INSERT INTO AdminSettings (SettingKey, SettingValue) VALUES (%s,%s)",
>>>>>>> 7275d62 (Switch to PostgreSQL)
                  ('admin_pin_hash', hash_pin('0000')))

    c.execute("SELECT COUNT(*) FROM Bakers")
    if c.fetchone()['count'] == 0:
        for name, pin, rate in [
            ("Amina Wanjiku","123456",50.0),("Brian Otieno","234567",50.0),
            ("Carol Njeri","345678",50.0),("David Kamau","456789",50.0),
            ("Esther Achieng","567890",50.0),("Felix Mwangi","678901",50.0),
            ("Grace Moraa","789012",50.0),("Hassan Abdi","890123",50.0),
            ("Irene Chebet","901234",50.0),("James Ndegwa","012345",50.0),
        ]:
            c.execute("INSERT INTO Bakers (FullName,PIN_Hash,HourlyRate) VALUES (%s,%s,%s)",
                      (name,hash_pin(pin),rate))

    conn.commit(); conn.close()
    print("[DB] PostgreSQL ready — data persists forever!")

if __name__ == "__main__":
    init_db()
