# -*- coding: utf-8 -*-
"""
Общая логика работы с базой данных.
Используется и user_bot.py, и admin_bot.py — оба бота должны смотреть
на один и тот же файл БД (DB_PATH).
"""

import os
import sqlite3
from datetime import datetime, timedelta

DB_PATH = os.getenv("DB_PATH", "voenbilet.db")

# Папка для скачанных скриншотов — лежит на том же общем томе (Azure File
# Share), что и база данных, чтобы оба бота видели одни и те же файлы.
PHOTOS_DIR = os.getenv("PHOTOS_DIR", os.path.join(os.path.dirname(os.path.abspath(DB_PATH)) or ".", "photos"))
os.makedirs(PHOTOS_DIR, exist_ok=True)

# Кулдаун между заявками одного пользователя (в часах)
COOLDOWN_HOURS = int(os.getenv("COOLDOWN_HOURS", "2"))


def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            nickname TEXT,
            reg_screenshot TEXT,
            promo_screenshot TEXT,
            medcard_screenshot TEXT,
            license_screenshot TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS blocked_users (
            user_id INTEGER PRIMARY KEY
        )
        """
    )
    conn.commit()
    conn.close()


def is_blocked(user_id: int) -> bool:
    conn = db_connect()
    row = conn.execute(
        "SELECT 1 FROM blocked_users WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row is not None


def block_user_db(user_id: int):
    conn = db_connect()
    conn.execute(
        "INSERT OR IGNORE INTO blocked_users (user_id) VALUES (?)", (user_id,)
    )
    conn.commit()
    conn.close()


def unblock_user_db(user_id: int):
    conn = db_connect()
    conn.execute("DELETE FROM blocked_users WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_cooldown_remaining(user_id: int):
    """Возвращает timedelta до конца кулдауна, либо None если можно начинать."""
    conn = db_connect()
    row = conn.execute(
        """
        SELECT created_at FROM applications
        WHERE user_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    last_time = datetime.fromisoformat(row["created_at"])
    elapsed = datetime.now() - last_time
    cooldown = timedelta(hours=COOLDOWN_HOURS)
    if elapsed < cooldown:
        return cooldown - elapsed
    return None


def save_application(data: dict) -> int:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO applications
            (user_id, username, nickname, reg_screenshot, promo_screenshot,
             medcard_screenshot, license_screenshot, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (
            data["user_id"],
            data["username"],
            data["nickname"],
            data["reg_screenshot"],
            data["promo_screenshot"],
            data["medcard_screenshot"],
            data["license_screenshot"],
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    app_id = cur.lastrowid
    conn.close()
    return app_id


def get_pending_applications():
    conn = db_connect()
    rows = conn.execute(
        "SELECT * FROM applications WHERE status = 'pending' ORDER BY id ASC"
    ).fetchall()
    conn.close()
    return rows


def get_application(app_id: int):
    conn = db_connect()
    row = conn.execute(
        "SELECT * FROM applications WHERE id = ?", (app_id,)
    ).fetchone()
    conn.close()
    return row


def delete_application(app_id: int):
    app = get_application(app_id)
    if app:
        for key in ("reg_screenshot", "promo_screenshot", "medcard_screenshot", "license_screenshot"):
            path = app[key]
            if path and os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
    conn = db_connect()
    conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
    conn.commit()
    conn.close()
