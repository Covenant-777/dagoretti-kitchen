"""
database.py — Dagoretti Kitchen Incubator
SQLite schema — 6-digit PINs (1,000,000 combinations)
"""
import sqlite3, hashlib, os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "dagoretti.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()

def init_db():
    conn = get_db(); c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS Bakers (
        BakerID INTEGER PRIMARY KEY AUTOINCREMENT,
        FullName TEXT NOT NULL, PIN_Hash TEXT NOT NULL,
        HourlyRate REAL NOT NULL DEFAULT 50.0,
        IsActive INTEGER NOT NULL DEFAULT 1,
        CreatedAt TEXT NOT NULL DEFAULT (datetime('now','localtime')))""")
    c.execute("""CREATE TABLE IF NOT EXISTS Sessions (
        SessionID INTEGER PRIMARY KEY AUTOINCREMENT,
        BakerID INTEGER NOT NULL, StartTime TEXT NOT NULL,
        EndTime TEXT, DurationMinutes REAL, AmountDue REAL, Month TEXT,
        FOREIGN KEY (BakerID) REFERENCES Bakers(BakerID))""")
    c.execute("""CREATE TABLE IF NOT EXISTS FailedAttempts (
        AttemptID INTEGER PRIMARY KEY AUTOINCREMENT,
        AttemptedAt TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        Note TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS MonthlyBilling (
        BillingID INTEGER PRIMARY KEY AUTOINCREMENT,
        BakerID INTEGER NOT NULL, Month TEXT NOT NULL,
        TotalMinutes REAL NOT NULL DEFAULT 0,
        TotalHours REAL NOT NULL DEFAULT 0,
        TotalAmountKES REAL NOT NULL DEFAULT 0,
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
                  ('admin_pin_hash', hash_pin('0000')))

    c.execute("SELECT COUNT(*) FROM Bakers")
    if c.fetchone()[0] == 0:
        # 6-digit PINs — 1,000,000 possible combinations
        for name, pin, rate in [
            ("Amina Wanjiku",  "123456", 50.0),
            ("Brian Otieno",   "234567", 50.0),
            ("Carol Njeri",    "345678", 50.0),
            ("David Kamau",    "456789", 50.0),
            ("Esther Achieng", "567890", 50.0),
            ("Felix Mwangi",   "678901", 50.0),
            ("Grace Moraa",    "789012", 50.0),
            ("Hassan Abdi",    "890123", 50.0),
            ("Irene Chebet",   "901234", 50.0),
            ("James Ndegwa",   "012345", 50.0),
        ]:
            c.execute("INSERT INTO Bakers (FullName,PIN_Hash,HourlyRate) VALUES (?,?,?)",
                      (name, hash_pin(pin), rate))
    conn.commit(); conn.close()
    print(f"[DB] Ready — 6-digit PINs active")

if __name__ == "__main__":
    init_db()
