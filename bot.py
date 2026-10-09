import os
import re
import json
import uuid
import html
import sqlite3
import requests
import time
import asyncio
import io
from collections import defaultdict
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = 5698123475
ALERT_CHAT_ID = int(os.getenv("ALERT_CHAT_ID", "0"))

MELO_BASE_URL = "https://api.melostore.id"
MELO_API_KEY = os.getenv("MELO_API_KEY", "")
MELO_SECRET_KEY = os.getenv("MELO_SECRET_KEY", "")
MELO_SANDBOX = os.getenv("MELO_SANDBOX", "true").lower() == "true"

MC_PER_USD = 17.98786
KS_PER_USD = 4450
MC_PROFIT_MARGIN = 1.0058

LICENSE_KEY = os.getenv("LICENSE_KEY", "")
LICENSE_SECRET = "EREN_SHOP_SECRET_2026"

SERVER_MAP = {
    "gl": "Global", "global": "Global",
    "id": "Indonesia", "indo": "Indonesia", "indonesia": "Indonesia",
    "my": "Malaysia", "malaysia": "Malaysia",
    "sg": "Singapore", "singapore": "Singapore",
    "ttr": "Turkey", "tr": "Turkey", "turkey": "Turkey",
    "php": "Philippines", "ph": "Philippines", "philippines": "Philippines",
    "brl": "Brazil", "br": "Brazil", "brazil": "Brazil",
    "pubg": "PUBG",
    "tgs": "TGS",
    "tgp": "TGP",
}

SERVER_FLAGS = {
    "Global": "🌍", "Indonesia": "🇮🇩", "Malaysia": "🇲🇾",
    "Singapore": "🇸🇬", "Turkey": "🇹🇷", "Philippines": "🇵🇭",
    "Brazil": "🇧🇷", "PUBG": "🎮", "TGS": "⭐", "TGP": "👑",
}

MLBB_SKU_PREFIX = {
    "mlgl": "Global", "mlid": "Indonesia", "mlmy": "Malaysia",
    "mlsg": "Singapore", "mltr": "Turkey", "mlph": "Philippines",
    "mlbr": "Brazil",
}

SMART_SKU_PREFIX = {
    "smartmlgl": "Global", "smartmlid": "Indonesia",
    "smartmlmy": "Malaysia", "smartmlsg": "Singapore",
    "smartmltr": "Turkey", "smartmlph": "Philippines",
    "smartmlbr": "Brazil",
}

SMART_BRAND_IDS = {
    "Global": 316, "Indonesia": None, "Malaysia": None,
    "Singapore": None, "Turkey": None, "Philippines": None, "Brazil": None,
}

PUBG_FALLBACK_SKUS = {
    "60": ["PUBGMGL60U-S12A", "PUBGMGL60U-S7", "PUBGMGL60U-S13",
           "PUBGMGL60UCO-S11", "PUBGMGL60U-S10"],
}

AMOUNT_ALIASES = {
    "wp": "weeklypass", "tp": "twilightpass",
    "web": "weeklyelitebundle", "meb": "monthlyepicbundle",
}

DATA_DIR = os.getenv("DATA_DIR", "/data")
if not os.path.exists(DATA_DIR):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        DATA_DIR = "."

ACCESS_DB = os.path.join(DATA_DIR, "access.db")
USER_BALANCE_DB = os.path.join(DATA_DIR, "user_balance.db")
SUBSCRIPTION_DB = os.path.join(DATA_DIR, "subscription.db")
USER_API_DB = os.path.join(DATA_DIR, "user_api.db")
MANUAL_PRICE_DB = os.path.join(DATA_DIR, "manual_price.db")
MANUAL_PRODUCT_DB = os.path.join(DATA_DIR, "manual_product.db")

print(f"📁 DATA_DIR: {DATA_DIR}")
print(f"🔔 ALERT_CHAT_ID: {ALERT_CHAT_ID}")
print(f"🧪 MELO_SANDBOX: {MELO_SANDBOX}")

# ============================================================
# အခန်း ၂ — Database Init (Tables)
# ============================================================

def init_access_db():
    conn = sqlite3.connect(ACCESS_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS bot_access (
        user_id INTEGER PRIMARY KEY,
        username TEXT, first_name TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        requested_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()


def init_balance_db():
    conn = sqlite3.connect(USER_BALANCE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS user_balance (
        user_id INTEGER PRIMARY KEY,
        balance REAL DEFAULT 0.0,
        referral_count INTEGER DEFAULT 0,
        total_spent REAL DEFAULT 0.0,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()


def init_subscription_db():
    conn = sqlite3.connect(SUBSCRIPTION_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
        user_id INTEGER PRIMARY KEY,
        expiry_date TEXT, status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()


def init_user_api_db():
    conn = sqlite3.connect(USER_API_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS user_api (
        user_id INTEGER PRIMARY KEY,
        api_key TEXT, secret_key TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()


def init_manual_price_db():
    conn = sqlite3.connect(MANUAL_PRICE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS manual_price (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server TEXT NOT NULL, amount TEXT NOT NULL,
        mc_price REAL NOT NULL,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(server, amount)
    )""")
    conn.commit()
    conn.close()


def init_manual_product_db():
    conn = sqlite3.connect(MANUAL_PRODUCT_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS manual_product (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server TEXT NOT NULL, amount TEXT NOT NULL,
        sku_code TEXT, display_name TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(server, amount)
    )""")
    conn.commit()
    conn.close()


def init_referral_db():
    conn = sqlite3.connect(USER_BALANCE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        referred_user_id INTEGER UNIQUE,
        rewarded INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()


def init_checkin_db():
    conn = sqlite3.connect(USER_BALANCE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS checkins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        checkin_date TEXT NOT NULL,
        reward INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, checkin_date)
    )""")
    conn.commit()
    conn.close()


def init_mission_db():
    conn = sqlite3.connect(USER_BALANCE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS missions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        mission_date TEXT NOT NULL,
        progress INTEGER DEFAULT 0,
        target INTEGER DEFAULT 5,
        claimed INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, mission_date)
    )""")
    conn.commit()
    conn.close()


def init_feedback_db():
    conn = sqlite3.connect(USER_BALANCE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS feedbacks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()


def init_favorites_db():
    conn = sqlite3.connect(USER_BALANCE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        server TEXT NOT NULL,
        amount TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, server, amount)
    )""")
    conn.commit()
    conn.close()


def init_orders_db():
    conn = sqlite3.connect(USER_BALANCE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        game TEXT NOT NULL,
        product TEXT NOT NULL,
        player_id TEXT,
        zone_id TEXT,
        price REAL DEFAULT 0.0,
        status TEXT DEFAULT 'pending',
        transaction_id TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()


def init_all_db():
    init_access_db()
    init_balance_db()
    init_subscription_db()
    init_user_api_db()
    init_manual_price_db()
    init_manual_product_db()
    init_referral_db()
    init_checkin_db()
    init_mission_db()
    init_feedback_db()
    init_favorites_db()
    init_orders_db()

# ============================================================
# အခန်း ၃ — Access Control (User Approval)
# ============================================================

def get_access_status(user_id):
    if int(user_id) == ADMIN_ID:
        return "approved"
    conn = sqlite3.connect(ACCESS_DB)
    row = conn.execute("SELECT status FROM bot_access WHERE user_id=?", (int(user_id),)).fetchone()
    conn.close()
    return row[0] if row else None


def save_access_request(user_id, username, first_name):
    conn = sqlite3.connect(ACCESS_DB)
    conn.execute("""INSERT INTO bot_access
        (user_id, username, first_name, status, requested_at)
        VALUES (?, ?, ?, 'pending', CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
        username=excluded.username, first_name=excluded.first_name,
        status='pending', requested_at=CURRENT_TIMESTAMP
    """, (int(user_id), username or "", first_name or ""))
    conn.commit()
    conn.close()


def set_access_status(user_id, status):
    conn = sqlite3.connect(ACCESS_DB)
    conn.execute("UPDATE bot_access SET status=? WHERE user_id=?", (status, int(user_id)))
    conn.commit()
    conn.close()


def access_request_keyboard(user_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"access:approve:{user_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"access:reject:{user_id}"),
    ]])


async def request_access(update, context, force_request=False):
    user = update.effective_user
    if not user:
        return False
    if user.id == ADMIN_ID:
        return True

    status = get_access_status(user.id)

    if status is None or (force_request and status in ("pending", "rejected")):
        save_access_request(user.id, user.username, user.first_name)
        username = f"@{user.username}" if user.username else "—"

        admin_text = (
            "🔔 <b>NEW USER REGISTER REQUEST</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Name: <b>{html.escape(user.first_name or '—')}</b>\n"
            f"🔗 Username: <b>{html.escape(username)}</b>\n"
            f"🆔 User ID: <code>{user.id}</code>\n\n"
            "⚠️ Grant access to this user?"
        )

        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID, text=admin_text, parse_mode="HTML",
                reply_markup=access_request_keyboard(user.id),
            )
        except Exception as e:
            print("ACCESS REQUEST SEND ERROR:", e)

    if status == "rejected" and not force_request:
        if update.message:
            await update.message.reply_text(
                "❌ <b>Access Denied</b>\n\nPress /start to send a new request.",
                parse_mode="HTML",
            )
        return False

    if status == "pending":
        if update.message:
            await update.message.reply_text(
                "⏳ <b>Access Pending</b>\n\nRequest sent to Admin.",
                parse_mode="HTML",
            )
        return False

    if status == "approved":
        return True

    return False


async def handle_access_callback(update, context):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Admin only", show_alert=True)
        return True

    parts = (query.data or "").split(":")
    if len(parts) != 3:
        return True

    action, uid_text = parts[1], parts[2]
    try:
        user_id = int(uid_text)
    except ValueError:
        return True

    if action == "approve":
        status = "approved"
        label = "✅ APPROVED"
    elif action == "reject":
        status = "rejected"
        label = "❌ REJECTED"
    else:
        return True

    set_access_status(user_id, status)

    try:
        await query.edit_message_text((query.message.text or "") + f"\n\n<b>{label}</b>", parse_mode="HTML")
    except Exception:
        pass

    if status == "approved":
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ <b>Access Approved!</b>\n\nPress /start to begin.",
                parse_mode="HTML",
            )
        except Exception as e:
            print("APPROVAL DM ERROR:", e)
        await query.answer("Approved ✅")
    else:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ <b>Access Denied</b>\n\nPress /start to send a new request.",
                parse_mode="HTML",
            )
        except Exception as e:
            print("REJECTION DM ERROR:", e)
        await query.answer("Rejected ❌")

    return True

# ============================================================
# အခန်း ၄ — Balance System
# ============================================================

def mc_to_ks(mc_amount):
    return mc_amount * (KS_PER_USD / MC_PER_USD)


def get_user_balance(user_id):
    conn = sqlite3.connect(USER_BALANCE_DB)
    row = conn.execute("SELECT balance FROM user_balance WHERE user_id=?", (int(user_id),)).fetchone()
    conn.close()
    return row[0] if row else 0.0


def add_user_balance(user_id, amount):
    conn = sqlite3.connect(USER_BALANCE_DB)
    conn.execute("""INSERT INTO user_balance (user_id, balance, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
        balance = balance + ?, updated_at = CURRENT_TIMESTAMP
    """, (int(user_id), float(amount), float(amount)))
    conn.commit()
    conn.close()


def deduct_user_balance(user_id, amount):
    conn = sqlite3.connect(USER_BALANCE_DB)
    conn.execute("""UPDATE user_balance SET balance = balance - ?, updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND balance >= ?
    """, (float(amount), int(user_id), float(amount)))
    affected = conn.total_changes
    conn.commit()
    conn.close()
    return affected > 0


def add_total_spent(user_id, amount):
    conn = sqlite3.connect(USER_BALANCE_DB)
    conn.execute("""UPDATE user_balance SET total_spent = total_spent + ? WHERE user_id = ?
    """, (float(amount), int(user_id)))
    conn.commit()
    conn.close()


def get_total_spent(user_id):
    conn = sqlite3.connect(USER_BALANCE_DB)
    row = conn.execute("SELECT total_spent FROM user_balance WHERE user_id=?", (int(user_id),)).fetchone()
    conn.close()
    return row[0] if row else 0.0

# ============================================================
# အခန်း ၅ — Subscription System
# ============================================================

def get_subscription(user_id):
    conn = sqlite3.connect(SUBSCRIPTION_DB)
    row = conn.execute("SELECT expiry_date, status FROM subscriptions WHERE user_id=?", (int(user_id),)).fetchone()
    conn.close()
    if row:
        return {"expiry_date": row[0], "status": row[1]}
    return None


def set_subscription(user_id, days=30):
    expiry = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(SUBSCRIPTION_DB)
    conn.execute("""INSERT INTO subscriptions (user_id, expiry_date, status)
        VALUES (?, ?, 'active')
        ON CONFLICT(user_id) DO UPDATE SET expiry_date = ?, status = 'active'
    """, (int(user_id), expiry, expiry))
    conn.commit()
    conn.close()
    return expiry


def validate_license_key(license_key):
    import hashlib
    import hmac
    import base64
    try:
        decoded = base64.b64decode(license_key).decode()
        parts = decoded.split("|")
        if len(parts) != 3:
            return None
        user_id, expiry_date, signature = parts
        expected_sig = hmac.new(
            LICENSE_SECRET.encode(),
            f"{user_id}|{expiry_date}".encode(),
            hashlib.sha256
        ).hexdigest()[:16]
        if signature != expected_sig:
            return None
        return {"user_id": user_id, "expiry_date": expiry_date}
    except Exception:
        return None

# ============================================================
# အခန်း ၆ — User API
# ============================================================

def get_user_api(user_id):
    conn = sqlite3.connect(USER_API_DB)
    row = conn.execute("SELECT api_key, secret_key FROM user_api WHERE user_id=?", (int(user_id),)).fetchone()
    conn.close()
    if row:
        return {"api_key": row[0], "secret_key": row[1]}
    return None

# ============================================================
# အခန်း ၇ — Manual Price
# ============================================================

def get_manual_price(server, amount):
    conn = sqlite3.connect(MANUAL_PRICE_DB)
    row = conn.execute("SELECT mc_price FROM manual_price WHERE server=? AND amount=?", (server, amount)).fetchone()
    conn.close()
    return {"mc_price": row[0]} if row else None


def set_manual_price(server, amount, mc_price):
    conn = sqlite3.connect(MANUAL_PRICE_DB)
    conn.execute("""INSERT INTO manual_price (server, amount, mc_price, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(server, amount) DO UPDATE SET mc_price = ?, updated_at = CURRENT_TIMESTAMP
    """, (server, amount, float(mc_price), float(mc_price)))
    conn.commit()
    conn.close()


def get_all_manual_prices(server=None):
    conn = sqlite3.connect(MANUAL_PRICE_DB)
    if server:
        rows = conn.execute("SELECT server, amount, mc_price FROM manual_price WHERE server=? ORDER BY amount", (server,)).fetchall()
    else:
        rows = conn.execute("SELECT server, amount, mc_price FROM manual_price ORDER BY server, amount").fetchall()
    conn.close()
    return rows


def delete_manual_price(server, amount):
    conn = sqlite3.connect(MANUAL_PRICE_DB)
    conn.execute("DELETE FROM manual_price WHERE server=? AND amount=?", (server, amount))
    conn.commit()
    conn.close()

# ============================================================
# အခန်း ၈ — Manual Product
# ============================================================

def add_manual_product(server, amount, sku_code, display_name=None):
    conn = sqlite3.connect(MANUAL_PRODUCT_DB)
    try:
        conn.execute("""INSERT INTO manual_product
            (server, amount, sku_code, display_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(server, amount) DO UPDATE SET
            sku_code=excluded.sku_code, display_name=excluded.display_name
        """, (server, amount, sku_code or "", display_name or f"{amount}"))
        conn.commit()
        return True
    except Exception as e:
        print(f"Add Manual Product Error: {e}")
        return False
    finally:
        conn.close()


def delete_manual_product(server, amount):
    conn = sqlite3.connect(MANUAL_PRODUCT_DB)
    conn.execute("DELETE FROM manual_product WHERE server=? AND amount=?", (server, amount))
    affected = conn.total_changes
    conn.commit()
    conn.close()
    return affected > 0


def get_all_manual_products(server=None):
    conn = sqlite3.connect(MANUAL_PRODUCT_DB)
    if server:
        rows = conn.execute("SELECT server, amount, sku_code, display_name FROM manual_product WHERE server=? ORDER BY amount", (server,)).fetchall()
    else:
        rows = conn.execute("SELECT server, amount, sku_code, display_name FROM manual_product ORDER BY server, amount").fetchall()
    conn.close()
    return rows


def get_manual_products_for_server(server):
    conn = sqlite3.connect(MANUAL_PRODUCT_DB)
    rows = conn.execute("SELECT server, amount, sku_code, display_name FROM manual_product WHERE server=?", (server,)).fetchall()
    conn.close()
    products = []
    for srv, amount, sku, display_name in rows:
        if srv in ("Global", "Indonesia", "Malaysia", "Singapore", "Turkey", "Philippines", "Brazil"):
            game_type = "MLBB"
        elif srv == "PUBG":
            game_type = "PUBG"
        elif srv in ("TGS", "TGP"):
            game_type = "Telegram"
        else:
            game_type = "MLBB"

        products.append({
            "server": srv,
            "amount": amount,
            "display_name": display_name or amount,
            "sku_code": sku,
            "name": display_name or amount,
            "type_name": "Manual",
            "is_manual": True,
            "price": 999999999,
            "game_type": game_type,
        })
    return products

# ============================================================
# Chapter 9 — Backup/Restore (Cookie JSON)
# ============================================================

def create_backup_cookie():
    """Save all bot data as Cookie JSON file"""
    backup = {
        "version": "1.0",
        "type": "cookie_backup",
        "backup_date": datetime.now().isoformat(),
        "bot_name": "Eren's Diamond Bot",
        "data": {}
    }

    # Users + Balance
    conn = sqlite3.connect(USER_BALANCE_DB)
    rows = conn.execute("SELECT user_id, balance, referral_count, total_spent, updated_at FROM user_balance").fetchall()
    backup["data"]["users"] = [
        {"user_id": r[0], "balance": r[1], "referral_count": r[2],
         "total_spent": r[3], "updated_at": r[4]} for r in rows
    ]
    conn.close()

    # Access
    conn = sqlite3.connect(ACCESS_DB)
    rows = conn.execute("SELECT user_id, username, first_name, status, requested_at FROM bot_access").fetchall()
    backup["data"]["access"] = [
        {"user_id": r[0], "username": r[1], "first_name": r[2],
         "status": r[3], "requested_at": r[4]} for r in rows
    ]
    conn.close()

    # Manual Prices
    conn = sqlite3.connect(MANUAL_PRICE_DB)
    rows = conn.execute("SELECT server, amount, mc_price, updated_at FROM manual_price").fetchall()
    backup["data"]["manual_prices"] = [
        {"server": r[0], "amount": r[1], "mc_price": r[2],
         "updated_at": r[3]} for r in rows
    ]
    conn.close()

    # Manual Products
    conn = sqlite3.connect(MANUAL_PRODUCT_DB)
    rows = conn.execute("SELECT server, amount, sku_code, display_name FROM manual_product").fetchall()
    backup["data"]["manual_products"] = [
        {"server": r[0], "amount": r[1], "sku_code": r[2],
         "display_name": r[3]} for r in rows
    ]
    conn.close()

    # Subscriptions
    conn = sqlite3.connect(SUBSCRIPTION_DB)
    rows = conn.execute("SELECT user_id, expiry_date, status FROM subscriptions").fetchall()
    backup["data"]["subscriptions"] = [
        {"user_id": r[0], "expiry_date": r[1], "status": r[2]} for r in rows
    ]
    conn.close()

    # User API
    conn = sqlite3.connect(USER_API_DB)
    rows = conn.execute("SELECT user_id, api_key, secret_key FROM user_api").fetchall()
    backup["data"]["user_api"] = [
        {"user_id": r[0], "api_key": r[1], "secret_key": r[2]} for r in rows
    ]
    conn.close()

    # Referrals
    conn = sqlite3.connect(USER_BALANCE_DB)
    rows = conn.execute("SELECT user_id, referred_user_id, rewarded, created_at FROM referrals").fetchall()
    backup["data"]["referrals"] = [
        {"user_id": r[0], "referred_user_id": r[1],
         "rewarded": r[2], "created_at": r[3]} for r in rows
    ]
    conn.close()

    # Check-ins
    conn = sqlite3.connect(USER_BALANCE_DB)
    rows = conn.execute("SELECT user_id, checkin_date, reward, created_at FROM checkins").fetchall()
    backup["data"]["checkins"] = [
        {"user_id": r[0], "checkin_date": r[1],
         "reward": r[2], "created_at": r[3]} for r in rows
    ]
    conn.close()

    # Orders
    conn = sqlite3.connect(USER_BALANCE_DB)
    rows = conn.execute("""SELECT user_id, game, product, player_id, zone_id,
        price, status, transaction_id, created_at FROM orders""").fetchall()
    backup["data"]["orders"] = [
        {"user_id": r[0], "game": r[1], "product": r[2],
         "player_id": r[3], "zone_id": r[4], "price": r[5],
         "status": r[6], "transaction_id": r[7],
         "created_at": r[8]} for r in rows
    ]
    conn.close()

    return json.dumps(backup, indent=2, ensure_ascii=False)


def restore_backup_cookie(json_str):
    """Restore bot data from Cookie JSON file"""
    try:
        backup = json.loads(json_str)
        data = backup.get("data", {})

        # Users
        conn = sqlite3.connect(USER_BALANCE_DB)
        for u in data.get("users", []):
            conn.execute("""INSERT INTO user_balance (user_id, balance, referral_count, total_spent)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                balance=excluded.balance,
                referral_count=excluded.referral_count,
                total_spent=excluded.total_spent
            """, (u["user_id"], u.get("balance", 0.0),
                  u.get("referral_count", 0), u.get("total_spent", 0.0)))
        conn.commit()
        conn.close()

        # Access
        conn = sqlite3.connect(ACCESS_DB)
        for a in data.get("access", []):
            conn.execute("""INSERT INTO bot_access (user_id, username, first_name, status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                status=excluded.status
            """, (a["user_id"], a.get("username", ""),
                  a.get("first_name", ""), a.get("status", "pending")))
        conn.commit()
        conn.close()

        # Manual Prices
        conn = sqlite3.connect(MANUAL_PRICE_DB)
        for p in data.get("manual_prices", []):
            conn.execute("""INSERT INTO manual_price (server, amount, mc_price)
                VALUES (?, ?, ?)
                ON CONFLICT(server, amount) DO UPDATE SET mc_price=excluded.mc_price
            """, (p["server"], p["amount"], p["mc_price"]))
        conn.commit()
        conn.close()

        # Manual Products
        conn = sqlite3.connect(MANUAL_PRODUCT_DB)
        for p in data.get("manual_products", []):
            conn.execute("""INSERT INTO manual_product (server, amount, sku_code, display_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(server, amount) DO UPDATE SET
                sku_code=excluded.sku_code,
                display_name=excluded.display_name
            """, (p["server"], p["amount"], p.get("sku_code", ""), p.get("display_name", "")))
        conn.commit()
        conn.close()

        # Subscriptions
        conn = sqlite3.connect(SUBSCRIPTION_DB)
        for s in data.get("subscriptions", []):
            conn.execute("""INSERT INTO subscriptions (user_id, expiry_date, status)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                expiry_date=excluded.expiry_date,
                status=excluded.status
            """, (s["user_id"], s.get("expiry_date", ""), s.get("status", "active")))
        conn.commit()
        conn.close()

        # User API
        conn = sqlite3.connect(USER_API_DB)
        for u in data.get("user_api", []):
            conn.execute("""INSERT INTO user_api (user_id, api_key, secret_key)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                api_key=excluded.api_key,
                secret_key=excluded.secret_key
            """, (u["user_id"], u.get("api_key", ""), u.get("secret_key", "")))
        conn.commit()
        conn.close()

        # Referrals
        conn = sqlite3.connect(USER_BALANCE_DB)
        for r in data.get("referrals", []):
            conn.execute("""INSERT OR IGNORE INTO referrals (user_id, referred_user_id, rewarded)
                VALUES (?, ?, ?)
            """, (r["user_id"], r["referred_user_id"], r.get("rewarded", 0)))
        conn.commit()
        conn.close()

        # Check-ins
        conn = sqlite3.connect(USER_BALANCE_DB)
        for c in data.get("checkins", []):
            conn.execute("""INSERT OR IGNORE INTO checkins (user_id, checkin_date, reward)
                VALUES (?, ?, ?)
            """, (c["user_id"], c["checkin_date"], c.get("reward", 0)))
        conn.commit()
        conn.close()

        # Orders
        conn = sqlite3.connect(USER_BALANCE_DB)
        for o in data.get("orders", []):
            conn.execute("""INSERT INTO orders (user_id, game, product, player_id, zone_id, price, status, transaction_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (o["user_id"], o["game"], o["product"], o.get("player_id", ""),
                  o.get("zone_id", ""), o.get("price", 0.0), o.get("status", "pending"),
                  o.get("transaction_id", "")))
        conn.commit()
        conn.close()

        return True, None
    except Exception as e:
        return False, str(e)

# ============================================================
# Chapter 10 — Melostore API Functions
# ============================================================

def api_headers(user_id=None):
    if user_id:
        user_api = get_user_api(user_id)
        if user_api:
            return {"X-API-Key": user_api["api_key"], "X-Secret-Key": user_api["secret_key"]}
    return {"X-API-Key": MELO_API_KEY, "X-Secret-Key": MELO_SECRET_KEY}


def api_get(path, params=None, user_id=None, retries=3):
    url = MELO_BASE_URL + path
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=api_headers(user_id), params=params, timeout=60)
            if response.status_code >= 400:
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                try:
                    data = response.json()
                    return None, (data.get("message") or f"HTTP {response.status_code}")
                except Exception:
                    return None, f"HTTP {response.status_code}"
            try:
                return response.json(), None
            except Exception:
                return {"success": False, "message": response.text}, None
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            return None, str(e)
    return None, "API Error (Retry Failed)"


def api_post(path, payload, user_id=None, retries=3):
    url = MELO_BASE_URL + path
    headers = api_headers(user_id)
    headers["Content-Type"] = "application/json"
    for attempt in range(retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            if response.status_code >= 400:
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                try:
                    data = response.json()
                    return None, (data.get("message") or f"HTTP {response.status_code}")
                except Exception:
                    return None, f"HTTP {response.status_code}"
            try:
                return response.json(), None
            except Exception:
                return {"success": False, "message": response.text}, None
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            return None, str(e)
    return None, "API Error (Retry Failed)"


def get_profile(user_id=None):
    return api_get("/api/v1/h2h/profile", user_id=user_id)


def get_balance(user_id=None):
    return api_get("/api/v1/h2h/profile/balance", user_id=user_id)


def get_smart_pricelists(brand_id=316, limit=500):
    params = {"brand": brand_id, "limit": limit}
    return api_get("/api/v1/h2h/smart-pricelists", params=params)


def check_ml_nickname(player_id, zone_id):
    payload = {
        "game_code": "mobile-legends",
        "customer_target": str(player_id),
        "customer_target_zone": str(zone_id),
    }
    return api_post("/api/v1/h2h/check-nickname", payload)


def check_ml_purchase_limit(player_id, zone_id):
    payload = {
        "customer_target": str(player_id),
        "customer_target_zone": str(zone_id),
    }
    return api_post("/api/v1/h2h/mobile-legends/purchase-limit", payload)


def create_transaction(product, player_id, zone_id, max_bid=None):
    sku = product.get("sku_code", "")
    buyer_trx_id = "EREN-" + uuid.uuid4().hex[:20].upper()
    payload = {
        "sku_code": sku,
        "customer_target": str(player_id),
        "customer_target_zone": str(zone_id) if zone_id else "",
        "buyer_trx_id": buyer_trx_id,
        "sandbox_mode": MELO_SANDBOX,
    }
    return api_post("/api/v1/h2h/transaction", payload)


async def check_transaction_status(transaction_id):
    data, error = api_get(f"/api/v1/h2h/transaction/{transaction_id}")
    if error:
        return None, error
    result = data.get("data", {})
    return result.get("status", "unknown"), None


async def get_transaction_detail(transaction_id):
    data, error = api_get(f"/api/v1/h2h/transaction/{transaction_id}")
    if error:
        return None, error
    return data.get("data", {}), None

# ============================================================
# Chapter 11 — Product Loading (Cache + Filter)
# ============================================================

PRODUCT_CACHE = {
    "Global": [], "Indonesia": [], "Malaysia": [], "Singapore": [],
    "Turkey": [], "Philippines": [], "Brazil": [],
    "PUBG": [], "TGS": [], "TGP": [],
}
LAST_PRODUCTS_LOAD = 0
PRODUCT_CACHE_TTL = 300
PRODUCT_LOAD_LOCK = __import__("threading").Lock()
PRODUCT_LAST_ERROR = {}


def format_amount_for_display(amount):
    try:
        if "." in str(amount):
            f = float(amount)
            if f.is_integer():
                return f"{int(f):,}"
            return f"{f:,}"
        return f"{int(amount):,}"
    except Exception:
        return str(amount)


def diamond_sort_key(product):
    amount = product.get("amount", "")
    match = re.search(r"(\d+(?:\.\d+)?)", str(amount))
    if match:
        try:
            return float(match.group(1))
        except Exception:
            pass
    return 999999999


def get_mc_price(server, amount, product=None):
    manual = get_manual_price(server, amount)
    if manual:
        return round(manual["mc_price"] * MC_PROFIT_MARGIN, 3)
    return None


def get_unique_products(server):
    products = PRODUCT_CACHE.get(server, [])
    amount_groups = defaultdict(list)
    for product in products:
        amount = product.get("amount", "?")
        amount_groups[amount].append(product)

    unique_products = []
    for amount, group in amount_groups.items():
        cheapest = min(group, key=lambda p: p.get("price", 999999999))
        unique_products.append(cheapest)
    return unique_products


def load_server_products(server):
    params = {"limit": 1000}
    data, error = api_get("/api/v1/h2h/pricelists", params=params)
    if error:
        PRODUCT_LAST_ERROR[server] = error
        print(f"❌ API Error [{server}]: {error}")
        return [], error

    rows = data.get("data", []) if isinstance(data, dict) else []
    meta = data.get("meta", {}) if isinstance(data, dict) else {}
    brands = meta.get("brands", [])
    brand_map = {str(x.get("id")): x.get("name", "") for x in brands if isinstance(x, dict)}

    print(f"📦 API returned {len(rows)} products for {server}")

    products = []
    for product in rows:
        brand_id = str(product.get("brand_id", ""))
        brand_name = brand_map.get(brand_id, "")
        name_text = f"{brand_name} {product.get('name', '')} {product.get('type_name', '')}".lower()
        sku = str(product.get("sku_code", ""))
        sku_lower = sku.lower()

        game_keywords = {
            "MLBB": ["ml diamonds", "mobile legends"],
            "PUBG": ["pubg", "unknown cash", "uc"],
            "Telegram": ["telegram", "star", "premium"],
        }

        game_type = None
        for game, keywords in game_keywords.items():
            if any(kw in name_text for kw in keywords):
                game_type = game
                break
        if not game_type:
            continue

        product_server = None
        if game_type == "MLBB":
            for prefix, srv_name in SMART_SKU_PREFIX.items():
                if sku_lower.startswith(prefix):
                    product_server = srv_name
                    break
            if not product_server:
                for prefix, srv_name in MLBB_SKU_PREFIX.items():
                    if sku_lower.startswith(prefix):
                        product_server = srv_name
                        break
            if not product_server:
                if "indonesia" in name_text or "(id)" in name_text:
                    product_server = "Indonesia"
                elif "malaysia" in name_text or "(my)" in name_text:
                    product_server = "Malaysia"
                elif "singapore" in name_text or "(sg)" in name_text:
                    product_server = "Singapore"
                elif "turkey" in name_text or "(tr)" in name_text:
                    product_server = "Turkey"
                elif "philippines" in name_text or "(ph)" in name_text:
                    product_server = "Philippines"
                elif "brazil" in name_text or "(br)" in name_text:
                    product_server = "Brazil"
                elif "global" in name_text:
                    product_server = "Global"
        elif game_type == "PUBG":
            product_server = "PUBG"
        elif game_type == "Telegram":
            if "premium" in name_text or "gift card" in name_text or "gazette" in name_text:
                product_server = "TGP"
            elif "star" in name_text:
                product_server = "TGS"
            else:
                product_server = "TGS"

        if product_server != server:
            continue

        name = str(product.get("name", ""))
        if game_type == "PUBG":
            num_match = re.search(r"(\d+)", name)
            amount = num_match.group(1) if num_match else name.strip()
            display_name = name.strip()
        elif game_type == "Telegram":
            if product_server == "TGP":
                amount = name.strip()
                display_name = name.strip()
            else:
                num_match = re.search(r"(\d+)", name)
                amount = num_match.group(1) if num_match else name.strip()
                display_name = name.strip()
        else:
            clean_name = re.sub(r"(?i)^mobile\s*legends?\s*", "", name).strip()
            name_lower = clean_name.lower()
            pass_keywords = ["pass", "bundle", "elite", "twilight", "weekly", "monthly", "pack"]
            is_pass_or_bundle = any(kw in name_lower for kw in pass_keywords)
            if is_pass_or_bundle:
                amount = re.sub(r"(?i)\bdiamonds?\b", "", clean_name).replace(" ", "").strip()
                if not amount:
                    amount = "unknown"
            else:
                dd_match = re.search(r"(\d+)\s*\+\s*(\d+)", clean_name)
                if dd_match:
                    amount = f"{dd_match.group(1)}+{dd_match.group(2)}"
                else:
                    sku_match = re.search(r"(\d+)$", sku)
                    if sku_match:
                        amount = sku_match.group(1)
                    else:
                        num_match = re.search(r"(\d+)", clean_name)
                        amount = num_match.group(1) if num_match else clean_name.replace(" ", "").strip() or "unknown"
            display_name = amount

        price = product.get("price", 999999999)
        try:
            price = float(price)
        except Exception:
            price = 999999999

        item = dict(product)
        item["server"] = server
        item["amount"] = amount
        item["display_name"] = display_name
        item["sku_code"] = sku
        item["price"] = price
        item["is_manual"] = False
        item["game_type"] = game_type
        products.append(item)

    manual_products = get_manual_products_for_server(server)
    if manual_products:
        products.extend(manual_products)

    print(f"✅ Filtered {len(products)} products for {server}")
    return sorted(products, key=diamond_sort_key), None


def refresh_products(server=None, force=False):
    global PRODUCT_CACHE, LAST_PRODUCTS_LOAD
    servers = [server] if server else list(PRODUCT_CACHE.keys())
    now = time.time()
    with PRODUCT_LOAD_LOCK:
        for name in servers:
            if not force and PRODUCT_CACHE.get(name) and (now - LAST_PRODUCTS_LOAD) < PRODUCT_CACHE_TTL:
                continue
            products, error = load_server_products(name)
            if error:
                continue
            PRODUCT_CACHE[name] = products
        LAST_PRODUCTS_LOAD = now
    return PRODUCT_CACHE


def ensure_server_products(server):
    now = time.time()
    if PRODUCT_CACHE.get(server) and (now - LAST_PRODUCTS_LOAD) < PRODUCT_CACHE_TTL:
        return PRODUCT_CACHE[server], None
    refresh_products(server=server, force=True)
    products = PRODUCT_CACHE.get(server, [])
    return products, PRODUCT_LAST_ERROR.get(server) if not products else None

# ============================================================
# Chapter 12 — Inline Keyboard Menus
# ============================================================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 MLBB Diamond", callback_data="menu:mlbb")],
        [InlineKeyboardButton("💰 Wallet", callback_data="menu:wallet"),
         InlineKeyboardButton("💳 Recharge", callback_data="menu:recharge")],
        [InlineKeyboardButton("📊 Dashboard", callback_data="menu:dashboard")],
        [InlineKeyboardButton("📅 Daily Check-in", callback_data="menu:checkin")],
        [InlineKeyboardButton("⭐ Favorites", callback_data="menu:favorites")],
        [InlineKeyboardButton("📋 Order History", callback_data="menu:orders"),
         InlineKeyboardButton("👥 Referral", callback_data="menu:referral")],
        [InlineKeyboardButton("🏆 Rewards", callback_data="menu:rewards")],
        [InlineKeyboardButton("💡 Feedback", callback_data="menu:feedback"),
         InlineKeyboardButton("🏅 Top Inviters", callback_data="menu:topinviters")],
        [InlineKeyboardButton("📞 Admin Contact", callback_data="menu:admin"),
         InlineKeyboardButton("📌 Daily Mission", callback_data="menu:mission")],
    ])


def back_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")]
    ])


def server_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Global Server", callback_data="server:Global")],
        [InlineKeyboardButton("🇮🇩 Indonesia Server", callback_data="server:Indonesia")],
        [InlineKeyboardButton("🇲🇾 Malaysia Server", callback_data="server:Malaysia")],
        [InlineKeyboardButton("🇸🇬 Singapore Server", callback_data="server:Singapore")],
        [InlineKeyboardButton("🇹🇷 Turkey Server", callback_data="server:Turkey")],
        [InlineKeyboardButton("🇵🇭 Philippines Server", callback_data="server:Philippines")],
        [InlineKeyboardButton("🇧🇷 Brazil Server", callback_data="server:Brazil")],
        [InlineKeyboardButton("🎮 PUBG", callback_data="server:PUBG")],
        [InlineKeyboardButton("⭐ Telegram Stars", callback_data="server:TGS")],
        [InlineKeyboardButton("👑 Telegram Premium", callback_data="server:TGP")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])


def amount_keyboard(server, is_admin=False, page=0, per_page=11):
    unique_products = get_unique_products(server)
    total = len(unique_products)
    start = page * per_page
    end = start + per_page
    page_items = unique_products[start:end]

    buttons = []
    for index, product in enumerate(page_items):
        amount = product.get("amount", "?")
        display_amount = product.get("display_name", amount)
        mc_price = get_mc_price(server, amount, product)
        price_text = f"{mc_price:.3f} Coin" if mc_price else "No Price"

        game_type = product.get("game_type", "MLBB")
        if game_type == "PUBG":
            label = f"🎮 {display_amount} • {price_text}"
        elif game_type == "Telegram":
            if server == "TGP":
                label = f"👑 {display_amount} • {price_text}"
            else:
                label = f"⭐ {display_amount} • {price_text}"
        else:
            label = f"💎 {format_amount_for_display(display_amount)} • {price_text}"

        real_index = start + index
        buttons.append([InlineKeyboardButton(label, callback_data=f"amount:{server}:{real_index}")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page:{server}:{page-1}"))
    if end < total:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"page:{server}:{page+1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton("⬅️ Back to Servers", callback_data="back:servers")])
    buttons.append([InlineKeyboardButton("🏠 Home", callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)

# ============================================================
# Chapter 13 — Start Handler
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    user = update.effective_user
    user_id = user.id
    first_name = user.first_name or "User"
    balance = get_user_balance(user_id)

    if user_id == ADMIN_ID:
        text = (
            f"✨ <b>Welcome, {html.escape(first_name)}!</b> ✨\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "💎 <b>Eren's Diamond Bot</b>\n\n"
            f"👑 <b>Status:</b> Admin\n"
            f"🪙 <b>Balance:</b> {balance:.3f} Coin\n\n"
            "👇 Choose from the menu below"
        )
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu())
        return

    status = get_access_status(user_id)

    if status == "approved":
        status_text = "✅ <b>Active</b>"
        show_menu = True
    elif status == "pending":
        status_text = "⏳ <b>Pending</b>"
        show_menu = False
    elif status == "rejected":
        status_text = "❌ <b>Rejected</b>"
        show_menu = False
    else:
        await request_access(update, context, force_request=True)
        status_text = "⏳ <b>Pending Approval</b>"
        show_menu = False

    text = (
        f"✨ <b>Welcome, {html.escape(first_name)}!</b> ✨\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💎 <b>Eren's Diamond Bot</b>\n\n"
        f"👤 <b>Status:</b> {status_text}\n"
        f"🪙 <b>Balance:</b> {balance:.3f} Coin\n"
        f"👥 <b>Referrals:</b> 0\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚡ Powered by Eren"
    )

    if show_menu:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu())
    else:
        await update.message.reply_text(text, parse_mode="HTML")

# ============================================================
# Chapter 14 — Wallet & Dashboard Handler
# ============================================================

async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    balance = get_user_balance(user_id)
    referral_count = get_referral_count(user_id)

    text = (
        "💰 <b>Wallet</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"💎 Balance: <b>{balance:.3f} Coins</b>\n"
        f"👥 Referral count: <b>{referral_count}</b>\n\n"
        "💡 Use <b>Recharge</b> to add Coins."
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Recharge", callback_data="menu:recharge")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)


async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    balance = get_user_balance(user_id)
    referral_count = get_referral_count(user_id)

    conn = sqlite3.connect(USER_BALANCE_DB)
    orders = conn.execute(
        "SELECT game, product, status, created_at FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 3",
        (user_id,)
    ).fetchall()
    conn.close()

    orders_text = ""
    if orders:
        for game, product, status, created_at in orders:
            emoji = {"success": "✅", "pending": "⏳", "failed": "❌"}.get(status, "❓")
            orders_text += f"  {emoji} {game} — {product}\n"
    else:
        orders_text = "  • None yet"

    text = (
        "📊 <b>Dashboard</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 ID: <code>{user_id}</code>\n"
        f"💎 Balance: <b>{balance:.3f}</b>\n"
        f"👥 Referrals: <b>{referral_count}</b>\n\n"
        "📦 <b>Recent Orders</b>\n"
        f"{orders_text}\n\n"
        "💳 <b>Recent Recharges</b>\n"
        "  • None yet"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="menu:dashboard")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

# ============================================================
# Chapter 15 — Recharge (Deposit) Handler
# ============================================================

async def show_recharge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = (
        "💳 <b>WALLET RECHARGE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💰 Minimum recharge amount — <b>5,000 MMK</b>\n\n"
        "💳 Choose your preferred payment method\n"
        "from the options below.\n\n"
        "👇 <b>Select Payment Method</b> 👇"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 K-Pay", callback_data="recharge:kpay")],
        [InlineKeyboardButton("💚 UAB Pay", callback_data="recharge:uab")],
        [InlineKeyboardButton("❤️ AYA Pay", callback_data="recharge:aya")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)


async def show_kpay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = (
        "💳 <b>KPAY | WALLET RECHARGE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👤 Account Name: <b>Thet Naing Swan</b>\n"
        "📱 Payment Number:\n"
        "<code>09766605879</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💰 Enter the recharge amount in MMK.\n\n"
        "📌 Minimum Recharge — <b>5,000 MMK</b>\n\n"
        "💡 Example —\n"
        "  5000\n"
        "  10000\n"
        "  20000\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚠️ Please verify the account number\n"
        "before making payment."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back", callback_data="menu:recharge")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)


async def show_uab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = (
        "💚 <b>UAB PAY | WALLET RECHARGE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👤 Account Name: <b>Thet Naing Swan</b>\n"
        "📱 Payment Number:\n"
        "<code>09425160424</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💰 Enter the recharge amount in MMK.\n\n"
        "📌 Minimum Recharge — <b>5,000 MMK</b>\n\n"
        "💡 Example —\n"
        "  5000\n"
        "  10000\n"
        "  20000\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚠️ Please verify the account number\n"
        "before making payment."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back", callback_data="menu:recharge")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)


async def show_aya(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = (
        "❤️ <b>AYA PAY | WALLET RECHARGE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👤 Account Name: <b>Hnin Hnin Soe</b>\n"
        "📱 Payment Number:\n"
        "<code>09678664100</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💰 Enter the recharge amount in MMK.\n\n"
        "📌 Minimum Recharge — <b>5,000 MMK</b>\n\n"
        "💡 Example —\n"
        "  5000\n"
        "  10000\n"
        "  20000\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚠️ Please verify the account number\n"
        "before making payment."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back", callback_data="menu:recharge")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)



# ============================================================
# Chapter 16 — Referral System
# ============================================================

def get_referral_count(user_id):
    conn = sqlite3.connect(USER_BALANCE_DB)
    row = conn.execute("SELECT COUNT(*) FROM referrals WHERE user_id=?", (int(user_id),)).fetchone()
    conn.close()
    return row[0] if row else 0


def register_referral(referrer_id, new_user_id):
    if referrer_id == new_user_id:
        return False
    conn = sqlite3.connect(USER_BALANCE_DB)
    existing = conn.execute("SELECT id FROM referrals WHERE referred_user_id=?", (int(new_user_id),)).fetchone()
    if existing:
        conn.close()
        return False
    conn.execute("""INSERT INTO referrals (user_id, referred_user_id, rewarded)
        VALUES (?, ?, 0)
    """, (int(referrer_id), int(new_user_id)))
    conn.commit()
    conn.close()
    return True


async def show_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    total = get_referral_count(user_id)

    text = (
        "👥 <b>Referral</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 {ref_link}\n\n"
        f"Total: <b>{total}</b>\n\n"
        "💡 Invite friends to earn +10 Coins."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share", url=f"https://t.me/share/url?url={ref_link}")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

# ============================================================
# Chapter 17 — Daily Check-in
# ============================================================

def can_checkin_today(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(USER_BALANCE_DB)
    row = conn.execute("SELECT id FROM checkins WHERE user_id=? AND checkin_date=?",
                       (int(user_id), today)).fetchone()
    conn.close()
    return row is None


def save_checkin(user_id, reward):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(USER_BALANCE_DB)
    conn.execute("""INSERT OR IGNORE INTO checkins (user_id, checkin_date, reward)
        VALUES (?, ?, ?)
    """, (int(user_id), today, int(reward)))
    conn.commit()
    conn.close()


async def show_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not can_checkin_today(user_id):
        balance = get_user_balance(user_id)
        text = (
            "⚠️ You have already checked in today.\n"
            f"💎 <b>{balance:.3f} Coins</b>"
        )
    else:
        import random
        reward = random.randint(2, 9)
        add_user_balance(user_id, reward)
        save_checkin(user_id, reward)
        balance = get_user_balance(user_id)
        text = (
            "✅ <b>Check-in Successful!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎁 Reward: <b>+{reward} Coins</b>\n"
            f"💎 Balance: <b>{balance:.3f} Coins</b>\n\n"
            "📅 Come back tomorrow."
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

# ============================================================
# Chapter 18 — Daily Mission
# ============================================================

def get_mission_progress(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(USER_BALANCE_DB)
    row = conn.execute("""SELECT progress, target, claimed FROM missions
        WHERE user_id=? AND mission_date=?
    """, (int(user_id), today)).fetchone()
    conn.close()
    if row:
        return {"progress": row[0], "target": row[1], "claimed": row[2]}
    return {"progress": 0, "target": 5, "claimed": 0}


async def show_mission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    mission = get_mission_progress(user_id)
    progress = mission["progress"]
    target = mission["target"]
    claimed = mission["claimed"]
    status = "✅ Claimed" if claimed else ("🎉 Ready" if progress >= target else "⏳ Pending")

    text = (
        "📌 <b>Daily Invite Mission</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Invite 5 friends today!\n"
        f"Progress: <b>{progress}/{target}</b>\n"
        f"Status: {status}\n\n"
        "🎁 Reward: <b>500 Coins</b>\n\n"
        "Use /claimmission to claim when completed."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="menu:mission")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

# ============================================================
# Chapter 19 — MLBB Order Handler
# ============================================================

async def ml_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not await request_access(update, context):
        return

    user = update.effective_user
    user_id = user.id
    args = context.args

    if len(args) == 4:
        player_id, zone_id = args[0], args[1]
        server_input = args[2].strip().lower()
        amount_input = args[3].strip().lower()
        if server_input not in SERVER_MAP:
            await update.message.reply_text(
                "❌ <b>Invalid Server.</b>\n\n"
                "<code>gl</code>, <code>id</code>, <code>my</code>, <code>sg</code>, <code>ttr</code>, <code>php</code>, <code>brl</code>",
                parse_mode="HTML",
            )
            return
        server = SERVER_MAP[server_input]
    elif len(args) == 3:
        player_id, zone_id = args[0], args[1]
        server = "Global"
        amount_input = args[2].strip().lower()
    else:
        await update.message.reply_text(
            "❌ <b>Usage</b>\n\n"
            "<code>.ml PLAYER_ID ZONE_ID AMOUNT</code>\n"
            "<code>.ml PLAYER_ID ZONE_ID SERVER AMOUNT</code>\n\n"
            "<b>Server Codes:</b> gl, id, my, sg, ttr, php, brl",
            parse_mode="HTML",
        )
        return

    if not player_id.isdigit() or not zone_id.isdigit():
        await update.message.reply_text("❌ Player ID / Zone ID must be numeric.")
        return

    if amount_input in AMOUNT_ALIASES:
        amount_input = AMOUNT_ALIASES[amount_input]

    all_products = get_unique_products(server)
    matched_product = None
    for p in all_products:
        if str(p.get("amount", "")).strip().lower() == amount_input:
            matched_product = p
            break

    if not matched_product:
        available = [str(p.get("amount", "?")) for p in all_products]
        await update.message.reply_text(
            f"❌ <b>Product not found.</b>\n\n"
            f"💡 <b>Available:</b>\n<code>{', '.join(available[:20])}</code>",
            parse_mode="HTML",
        )
        return

    amount = matched_product.get("amount", "?")
    display_amount = matched_product.get("display_name", amount)
    mc_price = get_mc_price(server, amount, matched_product)

    if mc_price is None:
        await update.message.reply_text("⚠️ <b>Price not set.</b>", parse_mode="HTML")
        return

    user_balance = get_user_balance(user_id)
    if user_balance < mc_price:
        await update.message.reply_text(
            f"❌ <b>Insufficient balance.</b>\n\n"
            f"🪙 Current: <b>{user_balance:.3f} Coin</b>\n"
            f"💰 Required: <b>{mc_price:.3f} Coin</b>",
            parse_mode="HTML",
        )
        return

    checking_msg = await update.message.reply_text("🔍 <b>Checking...</b>", parse_mode="HTML")

    data, error = check_ml_nickname(player_id, zone_id)
    if error:
        await checking_msg.edit_text(f"❌ <b>Check Failed</b>\n\n{html.escape(str(error))}", parse_mode="HTML")
        return

    info = data.get("data", {})
    nickname = info.get("username") or info.get("nickname") or info.get("name") or "-"

    text = (
        "🔍 <b>Account Verified</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Nickname: <b>{html.escape(str(nickname))}</b>\n"
        f"🆔 Player ID: <code>{html.escape(str(player_id))}</code>\n"
        f"🌐 Zone ID: <code>{html.escape(str(zone_id))}</code>\n\n"
        f"🌍 Server: <b>{html.escape(server)}</b>\n"
        f"💎 Product: <b>{html.escape(str(display_amount))}</b>\n"
        f"🪙 Coin Price: <b>{mc_price:.3f} Coin</b>\n"
        f"🪙 Balance: <b>{user_balance:.3f} Coin</b>\n\n"
        "⚠️ <b>Order will be placed after confirmation.</b>"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data="ml:confirm"),
            InlineKeyboardButton("❌ Reject", callback_data="ml:reject"),
        ]
    ])

    context.user_data["ml_order"] = {
        "player_id": player_id,
        "zone_id": zone_id,
        "server": server,
        "amount": amount,
        "display_amount": display_amount,
        "mc_price": mc_price,
        "nickname": nickname,
        "product": matched_product,
    }

    await checking_msg.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

# ============================================================
# Chapter 20 — PUBG Order Handler
# ============================================================

async def pg_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not await request_access(update, context):
        return

    user = update.effective_user
    user_id = user.id
    args = context.args

    if len(args) != 2:
        await update.message.reply_text(
            "❌ <b>Usage</b>\n\n"
            "<code>.pg PLAYER_ID AMOUNT</code>\n\n"
            "<b>Example:</b>\n<code>.pg 5123456789 60</code>",
            parse_mode="HTML",
        )
        return

    player_id = args[0].strip()
    amount_input = args[1].strip()

    if not player_id.isdigit():
        await update.message.reply_text("❌ Player ID must be numeric.")
        return

    if amount_input not in PUBG_FALLBACK_SKUS:
        available = ", ".join(PUBG_FALLBACK_SKUS.keys())
        await update.message.reply_text(
            f"❌ <b>Amount not found.</b>\n\n"
            f"💡 <b>Available:</b> <code>{available}</code>",
            parse_mode="HTML",
        )
        return

    mc_price = get_mc_price("PUBG", amount_input, None)
    if mc_price is None:
        await update.message.reply_text("⚠️ <b>Price not set.</b>", parse_mode="HTML")
        return

    user_balance = get_user_balance(user_id)
    if user_balance < mc_price:
        await update.message.reply_text(
            f"❌ <b>Insufficient balance.</b>\n\n"
            f"🪙 Current: <b>{user_balance:.3f} Coin</b>\n"
            f"💰 Required: <b>{mc_price:.3f} Coin</b>",
            parse_mode="HTML",
        )
        return

    text = (
        "🔍 <b>PUBG Order Confirm</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 Player ID: <code>{html.escape(player_id)}</code>\n\n"
        f"🎮 Product: <b>{html.escape(amount_input)} UC</b>\n"
        f"🪙 Coin Price: <b>{mc_price:.3f} Coin</b>\n"
        f"🪙 Balance: <b>{user_balance:.3f} Coin</b>\n\n"
        "⚠️ <b>Order will be placed after confirmation.</b>"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data="pg:confirm"),
            InlineKeyboardButton("❌ Reject", callback_data="pg:reject"),
        ]
    ])

    context.user_data["pg_order"] = {
        "player_id": player_id,
        "amount": amount_input,
        "mc_price": mc_price,
    }

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

# ============================================================
# Chapter 21 — Telegram Order Handler
# ============================================================

async def tg_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not await request_access(update, context):
        return

    user = update.effective_user
    user_id = user.id
    args = context.args

    if len(args) != 2:
        await update.message.reply_text(
            "❌ <b>Usage</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            "<code>.tg TARGET AMOUNT</code>\n\n"
            "⭐ <b>Stars:</b>\n<code>.tg @username 50</code>\n\n"
            "👑 <b>Premium:</b>\n<code>.tg email@gmail.com 3M</code>",
            parse_mode="HTML",
        )
        return

    target = args[0].strip()
    amount_input = args[1].strip()

    matched_product = None
    matched_server = None

    for srv in ["TGS", "TGP"]:
        products, error = ensure_server_products(srv)
        if not products:
            continue

        for p in products:
            p_amount = str(p.get("amount", "")).strip().lower()
            p_name = str(p.get("display_name", "")).strip().lower()

            if p_amount == amount_input.lower() or p_name == amount_input.lower():
                matched_product = p
                matched_server = srv
                break

        if matched_product:
            break

    if not matched_product:
        star_products, _ = ensure_server_products("TGS")
        prem_products, _ = ensure_server_products("TGP")

        star_amounts = sorted(set(str(p.get("amount", "?")) for p in star_products))
        prem_names = sorted(set(str(p.get("display_name", "?")) for p in prem_products))

        text = "❌ <b>Product not found.</b>\n\n"
        if star_amounts:
            text += f"⭐ <b>Stars:</b>\n<code>{', '.join(star_amounts[:10])}</code>\n\n"
        if prem_names:
            text += f"👑 <b>Premium:</b>\n<code>{', '.join(prem_names[:10])}</code>"

        await update.message.reply_text(text, parse_mode="HTML")
        return

    server = matched_server
    amount = matched_product.get("amount", "?")
    display_amount = matched_product.get("display_name", amount)
    mc_price = get_mc_price(server, amount, matched_product)

    if mc_price is None:
        await update.message.reply_text("⚠️ <b>Price not set.</b>", parse_mode="HTML")
        return

    if server == "TGP":
        if "@" not in target:
            await update.message.reply_text(
                "❌ <b>Email required for Telegram Premium.</b>\n\n"
                "Example: <code>email@gmail.com</code>",
                parse_mode="HTML",
            )
            return
    elif server == "TGS":
        if not target.startswith("@"):
            await update.message.reply_text(
                "❌ <b>Username required for Telegram Stars.</b>\n\n"
                "Example: <code>@username</code>",
                parse_mode="HTML",
            )
            return

    user_balance = get_user_balance(user_id)
    if user_balance < mc_price:
        await update.message.reply_text(
            f"❌ <b>Insufficient balance.</b>\n\n"
            f"🪙 Current: <b>{user_balance:.3f} Coin</b>\n"
            f"💰 Required: <b>{mc_price:.3f} Coin</b>",
            parse_mode="HTML",
        )
        return

    if server == "TGP":
        emoji = "👑"
        label = "Telegram Premium"
    else:
        emoji = "⭐"
        label = "Telegram Stars"

    text = (
        f"🔍 <b>{label} Order Confirm</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Target: <code>{html.escape(target)}</code>\n\n"
        f"{emoji} Product: <b>{html.escape(str(display_amount))}</b>\n"
        f"🪙 Coin Price: <b>{mc_price:.3f} Coin</b>\n"
        f"🪙 Balance: <b>{user_balance:.3f} Coin</b>\n\n"
        "⚠️ <b>Order will be placed after confirmation.</b>"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data="tg:confirm"),
            InlineKeyboardButton("❌ Reject", callback_data="tg:reject"),
        ]
    ])

    context.user_data["tg_order"] = {
        "target": target,
        "server": server,
        "amount": amount,
        "display_amount": display_amount,
        "mc_price": mc_price,
        "product": matched_product,
    }

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

# ============================================================
# Chapter 22 — Order Confirm Handlers
# ============================================================

async def handle_ml_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    order = context.user_data.get("ml_order")
    if not order:
        await query.edit_message_text("❌ <b>Order not found.</b>\n\nPlease /start again.", parse_mode="HTML")
        return

    user = query.from_user
    user_id = user.id

    player_id = order["player_id"]
    zone_id = order["zone_id"]
    server = order["server"]
    amount = order["amount"]
    display_amount = order["display_amount"]
    mc_price = order["mc_price"]
    nickname = order["nickname"]
    matched_product = order["product"]

    user_balance = get_user_balance(user_id)
    if user_balance < mc_price:
        await query.edit_message_text(
            f"❌ <b>Insufficient balance.</b>\n\n"
            f"🪙 Current: <b>{user_balance:.3f} Coin</b>",
            parse_mode="HTML",
        )
        context.user_data.pop("ml_order", None)
        return

    await query.edit_message_text("🛒 <b>Creating Order...</b>", parse_mode="HTML")

    product = dict(matched_product)
    sku_code = product.get("sku_code", "")

    max_bid = None
    if sku_code.lower().startswith("smart"):
        max_bid = product.get("max_price")
        if not max_bid:
            max_bid = int(round(mc_price * 1000))

    data, error = create_transaction(product, player_id, zone_id, max_bid)

    if error:
        await query.edit_message_text(f"❌ <b>Order Failed</b>\n\n{html.escape(str(error))}", parse_mode="HTML")
        context.user_data.pop("ml_order", None)
        return

    result = data.get("data", {})
    transaction_id = result.get("id", "-")
    status = result.get("status", "pending")
    order_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if deduct_user_balance(user_id, mc_price):
        new_balance = get_user_balance(user_id)
    else:
        new_balance = user_balance

    text = (
        "🛒 <b>Order Created</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Nickname: <b>{html.escape(str(nickname))}</b>\n"
        f"🆔 Player ID: <code>{html.escape(str(player_id))}</code>\n"
        f"🌐 Zone ID: <code>{html.escape(str(zone_id))}</code>\n\n"
        f"🌍 Server: <b>{html.escape(server)}</b>\n"
        f"💎 Product: <b>{html.escape(str(display_amount))}</b>\n"
        f"🪙 Coin Price: <b>{mc_price:.3f} Coin</b>\n\n"
        f"🆔 Trx: <code>{html.escape(str(transaction_id))}</code>\n"
        f"⏳ Status: <b>{html.escape(str(status).upper())}</b>\n\n"
        f"🪙 Balance: <b>{new_balance:.3f} Coin</b>"
    )
    sent_msg = await query.edit_message_text(text, parse_mode="HTML")

    order_info = (
        f"🌍 Server: <b>{html.escape(server)}</b>\n"
        f"👤 Nickname: <b>{html.escape(str(nickname))}</b>\n"
        f"🆔 Player ID: <code>{html.escape(str(player_id))}</code>\n"
        f"🌐 Zone ID: <code>{html.escape(str(zone_id))}</code>\n\n"
        f"💎 Product: <b>{html.escape(str(display_amount))}</b>\n"
        f"🪙 Coin Price: <b>{mc_price:.3f} Coin</b>\n\n"
    )

    uname = f"@{user.username}" if user.username else "—"
    fname = user.first_name or "User"
    user_info = (
        f"👤 Name: <b>{html.escape(fname)}</b>\n"
        f"🔗 Username: <b>{html.escape(uname)}</b>\n"
        f"🆔 User ID: <code>{user_id}</code>\n\n"
    )

    asyncio.create_task(
        auto_status_update(
            context=context,
            transaction_id=str(transaction_id),
            user_id=user_id,
            chat_id=query.message.chat_id,
            message_id=sent_msg.message_id,
            order_info=order_info,
            product_amount=str(amount),
            user_info=user_info,
            mc_price=mc_price,
        )
    )

    try:
        alarm_text = (
            "🔔 <b>NEW ORDER!</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Name: <b>{html.escape(fname)}</b>\n"
            f"🔗 Username: <b>{html.escape(uname)}</b>\n"
            f"🆔 User ID: <code>{user_id}</code>\n\n"
            f"{order_info}"
            f"🧾 Trx: <code>{html.escape(str(transaction_id))}</code>\n"
            f"⏰ Time: <code>{order_time}</code>"
        )
        alert_target = ALERT_CHAT_ID if ALERT_CHAT_ID else ADMIN_ID
        await context.bot.send_message(chat_id=alert_target, text=alarm_text, parse_mode="HTML")
    except Exception as e:
        print("ORDER ALARM ERROR:", e)

    context.user_data.pop("ml_order", None)


async def handle_pg_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    order = context.user_data.get("pg_order")
    if not order:
        await query.edit_message_text("❌ <b>Order not found.</b>", parse_mode="HTML")
        return

    user = query.from_user
    user_id = user.id

    player_id = order["player_id"]
    amount_input = order["amount"]
    mc_price = order["mc_price"]

    user_balance = get_user_balance(user_id)
    if user_balance < mc_price:
        await query.edit_message_text("❌ <b>Insufficient balance.</b>", parse_mode="HTML")
        context.user_data.pop("pg_order", None)
        return

    if not deduct_user_balance(user_id, mc_price):
        await query.edit_message_text("❌ Failed to deduct balance.")
        return

    await query.edit_message_text("🔄 <b>Processing...</b>", parse_mode="HTML")

    skus = PUBG_FALLBACK_SKUS[amount_input]
    last_error = None
    data = None
    error = None
    used_sku = None

    for idx, sku in enumerate(skus, 1):
        product = {"sku_code": sku, "amount": amount_input, "server": "PUBG"}
        data, error = create_transaction(product, player_id, "")
        if not error:
            used_sku = sku
            break
        else:
            last_error = error

    if error:
        add_user_balance(user_id, mc_price)
        await query.edit_message_text(
            "❌ <b>Order Failed</b>\n\nBalance has been refunded.",
            parse_mode="HTML",
        )
        context.user_data.pop("pg_order", None)
        return

    result = data.get("data", {})
    transaction_id = result.get("id", "-")
    status = result.get("status", "pending")
    order_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_balance = get_user_balance(user_id)

    text = (
        "🛒 <b>PUBG Order Created</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 Player ID: <code>{html.escape(player_id)}</code>\n\n"
        f"🎮 Product: <b>{html.escape(amount_input)} UC</b>\n"
        f"🪙 Coin Price: <b>{mc_price:.3f} Coin</b>\n\n"
        f"🆔 Trx: <code>{html.escape(str(transaction_id))}</code>\n"
        f"⏳ Status: <b>{html.escape(str(status).upper())}</b>\n\n"
        f"🪙 Balance: <b>{new_balance:.3f} Coin</b>"
    )
    sent_msg = await query.edit_message_text(text, parse_mode="HTML")

    order_info = (
        f"🎮 Game: <b>PUBG Mobile</b>\n"
        f"🆔 Player ID: <code>{html.escape(player_id)}</code>\n\n"
        f"🎮 Product: <b>{html.escape(amount_input)} UC</b>\n"
        f"🪙 Coin Price: <b>{mc_price:.3f} Coin</b>\n"
        f"📦 SKU: <code>{html.escape(str(used_sku))}</code>\n\n"
    )

    uname = f"@{user.username}" if user.username else "—"
    fname = user.first_name or "User"
    user_info = (
        f"👤 Name: <b>{html.escape(fname)}</b>\n"
        f"🔗 Username: <b>{html.escape(uname)}</b>\n"
        f"🆔 User ID: <code>{user_id}</code>\n\n"
    )

    asyncio.create_task(
        auto_status_update(
            context=context,
            transaction_id=str(transaction_id),
            user_id=user_id,
            chat_id=query.message.chat_id,
            message_id=sent_msg.message_id,
            order_info=order_info,
            product_amount=str(amount_input),
            user_info=user_info,
            mc_price=mc_price,
        )
    )

    try:
        alarm_text = (
            "🔔 <b>NEW PUBG ORDER!</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Name: <b>{html.escape(fname)}</b>\n"
            f"🔗 Username: <b>{html.escape(uname)}</b>\n"
            f"🆔 User ID: <code>{user_id}</code>\n\n"
            f"{order_info}"
            f"🧾 Trx: <code>{html.escape(str(transaction_id))}</code>\n"
            f"⏰ Time: <code>{order_time}</code>"
        )
        alert_target = ALERT_CHAT_ID if ALERT_CHAT_ID else ADMIN_ID
        await context.bot.send_message(chat_id=alert_target, text=alarm_text, parse_mode="HTML")
    except Exception as e:
        print("ORDER ALARM ERROR:", e)

    context.user_data.pop("pg_order", None)


async def handle_tg_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    order = context.user_data.get("tg_order")
    if not order:
        await query.edit_message_text("❌ <b>Order not found.</b>", parse_mode="HTML")
        return

    user = query.from_user
    user_id = user.id

    target = order["target"]
    server = order["server"]
    amount = order["amount"]
    display_amount = order["display_amount"]
    mc_price = order["mc_price"]
    matched_product = order["product"]

    user_balance = get_user_balance(user_id)
    if user_balance < mc_price:
        await query.edit_message_text("❌ <b>Insufficient balance.</b>", parse_mode="HTML")
        context.user_data.pop("tg_order", None)
        return

    await query.edit_message_text("🛒 <b>Creating Order...</b>", parse_mode="HTML")

    product = dict(matched_product)
    data, error = create_transaction(product, target, "")

    if error:
        await query.edit_message_text(f"❌ <b>Order Failed</b>\n\n{html.escape(str(error))}", parse_mode="HTML")
        context.user_data.pop("tg_order", None)
        return

    result = data.get("data", {})
    transaction_id = result.get("id", "-")
    status = result.get("status", "pending")
    serial_number = result.get("serial_number", "")
    order_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if deduct_user_balance(user_id, mc_price):
        new_balance = get_user_balance(user_id)
    else:
        new_balance = user_balance

    if server == "TGP":
        emoji = "👑"
        label = "Telegram Premium"
        code_section = ""
        if serial_number:
            code_section = f"\n🎁 <b>Gift Code:</b>\n<code>{html.escape(str(serial_number))}</code>\n"
    else:
        emoji = "⭐"
        label = "Telegram Stars"
        code_section = ""

    text = (
        f"🛒 <b>{label} Order Created</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Target: <code>{html.escape(target)}</code>\n\n"
        f"{emoji} Product: <b>{html.escape(str(display_amount))}</b>\n"
        f"🪙 Coin Price: <b>{mc_price:.3f} Coin</b>\n\n"
        f"🆔 Trx: <code>{html.escape(str(transaction_id))}</code>\n"
        f"⏳ Status: <b>{html.escape(str(status).upper())}</b>\n"
        f"{code_section}\n"
        f"🪙 Balance: <b>{new_balance:.3f} Coin</b>"
    )
    sent_msg = await query.edit_message_text(text, parse_mode="HTML")

    order_info = (
        f"⭐ Game: <b>{label}</b>\n"
        f"🎯 Target: <code>{html.escape(target)}</code>\n\n"
        f"{emoji} Product: <b>{html.escape(str(display_amount))}</b>\n"
        f"🪙 Coin Price: <b>{mc_price:.3f} Coin</b>\n\n"
    )

    uname = f"@{user.username}" if user.username else "—"
    fname = user.first_name or "User"
    user_info = (
        f"👤 Name: <b>{html.escape(fname)}</b>\n"
        f"🔗 Username: <b>{html.escape(uname)}</b>\n"
        f"🆔 User ID: <code>{user_id}</code>\n\n"
    )

    asyncio.create_task(
        auto_status_update(
            context=context,
            transaction_id=str(transaction_id),
            user_id=user_id,
            chat_id=query.message.chat_id,
            message_id=sent_msg.message_id,
            order_info=order_info,
            product_amount=str(amount),
            user_info=user_info,
            mc_price=mc_price,
        )
    )

    try:
        alarm_text = (
            f"🔔 <b>NEW {label.upper()} ORDER!</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Name: <b>{html.escape(fname)}</b>\n"
            f"🔗 Username: <b>{html.escape(uname)}</b>\n"
            f"🆔 User ID: <code>{user_id}</code>\n\n"
            f"{order_info}"
        )
        if serial_number:
            alarm_text += f"🎁 Gift Code: <code>{html.escape(str(serial_number))}</code>\n\n"
        alarm_text += (
            f"🧾 Trx: <code>{html.escape(str(transaction_id))}</code>\n"
            f"⏰ Time: <code>{order_time}</code>"
        )
        alert_target = ALERT_CHAT_ID if ALERT_CHAT_ID else ADMIN_ID
        await context.bot.send_message(chat_id=alert_target, text=alarm_text, parse_mode="HTML")
    except Exception as e:
        print("ORDER ALARM ERROR:", e)

    context.user_data.pop("tg_order", None)

# ============================================================
# Chapter 23 — Admin Panel & Commands
# ============================================================

def admin_panel_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Dashboard", callback_data="admin:dashboard")],
        [InlineKeyboardButton("💰 Price", callback_data="admin:price"),
         InlineKeyboardButton("📦 Product", callback_data="admin:product")],
        [InlineKeyboardButton("👥 Users", callback_data="admin:users")],
        [InlineKeyboardButton("💳 Deposits", callback_data="admin:deposits")],
        [InlineKeyboardButton("📋 Orders", callback_data="admin:orders")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin:broadcast")],
        [InlineKeyboardButton("💾 Backup (JSON)", callback_data="admin:backup")],
        [InlineKeyboardButton("📥 Restore (JSON)", callback_data="admin:restore")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])


async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        if update.callback_query:
            await update.callback_query.answer("❌ Admin only", show_alert=True)
        else:
            await update.message.reply_text("❌ Admin only")
        return

    data, error = get_balance()
    if error:
        text = (
            "⚙️ <b>Admin Panel</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "❌ Melostore API Error\n"
            f"{html.escape(str(error))}"
        )
    else:
        info = data.get("data", {})
        balance = info.get("h2h_balance", 0)
        usd = info.get("h2h_balance_usd", 0)
        text = (
            "⚙️ <b>Admin Panel</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🪙 Melostore Balance: <b>{balance:,.2f} Coin</b>\n"
            f"💵 USD: <b>${usd:,.2f}</b>\n\n"
            f"🔔 Alert Group: <code>{ALERT_CHAT_ID}</code>\n"
            f"🧪 Sandbox: <b>{MELO_SANDBOX}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📌 Select an option below"
        )

    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=admin_panel_menu())
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=admin_panel_menu())


async def admin_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("⏳ <b>Backing up...</b>", parse_mode="HTML")

    json_str = create_backup_cookie()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"cookie_{timestamp}.json"

    file = io.BytesIO(json_str.encode("utf-8"))
    file.name = filename

    await context.bot.send_document(
        chat_id=query.from_user.id,
        document=file,
        filename=filename,
        caption=f"✅ <b>Backup completed.</b>\n\n📄 File: <code>{filename}</code>",
        parse_mode="HTML",
    )
    await query.edit_message_text(
        "✅ Backup completed.\n\n📄 File has been sent.",
        parse_mode="HTML",
        reply_markup=admin_panel_menu(),
    )


async def admin_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["state"] = "waiting_for_backup"
    await query.edit_message_text(
        "📥 <b>Restore</b>\n\n"
        "Send the Cookie JSON backup file to this chat.\n\n"
        "⚠️ Restore will overwrite existing data.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data="admin:panel")]
        ]),
    )


async def show_admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    conn = sqlite3.connect(USER_BALANCE_DB)
    total_users = conn.execute("SELECT COUNT(*) FROM user_balance").fetchone()[0]
    total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    total_balance = conn.execute("SELECT SUM(balance) FROM user_balance").fetchone()[0] or 0
    conn.close()

    text = (
        "📊 <b>Admin Dashboard</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Total Users: <b>{total_users}</b>\n"
        f"📋 Total Orders: <b>{total_orders}</b>\n"
        f"🪙 Total Balance: <b>{total_balance:.3f} Coin</b>\n"
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=admin_panel_menu())


async def show_admin_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    rows = get_all_manual_prices()
    if not rows:
        text = "💰 <b>Manual Prices</b>\n\n📭 No prices yet."
    else:
        lines = ["💰 <b>Manual Prices</b>\n━━━━━━━━━━━━━━━━━━━━"]
        current = None
        for srv, amt, mc in rows:
            if srv != current:
                lines.append(f"\n🌍 <b>{srv}</b>")
                current = srv
            lines.append(f"  💎 {amt} → <b>{mc * MC_PROFIT_MARGIN:.3f} Coin</b>")
        text = "\n".join(lines)

    await query.edit_message_text(text, parse_mode="HTML", reply_markup=admin_panel_menu())


async def show_admin_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    rows = get_all_manual_products()
    if not rows:
        text = "📦 <b>Manual Products</b>\n\n📭 No products yet."
    else:
        lines = ["📦 <b>Manual Products</b>\n━━━━━━━━━━━━━━━━━━━━"]
        current = None
        for srv, amt, sku, dn in rows:
            if srv != current:
                lines.append(f"\n🌍 <b>{srv}</b>")
                current = srv
            lines.append(f"  💎 <b>{amt}</b> → <code>{sku}</code>")
        text = "\n".join(lines)

    await query.edit_message_text(text, parse_mode="HTML", reply_markup=admin_panel_menu())


async def show_admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    conn = sqlite3.connect(ACCESS_DB)
    rows = conn.execute("SELECT user_id, username, first_name, status FROM bot_access ORDER BY requested_at DESC").fetchall()
    conn.close()

    if not rows:
        text = "👥 <b>Users</b>\n\n📭 No users yet."
    else:
        approved = sum(1 for r in rows if r[3] == "approved")
        pending = sum(1 for r in rows if r[3] == "pending")
        rejected = sum(1 for r in rows if r[3] == "rejected")
        text = (
            "👥 <b>All Users</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ Approved: <b>{approved}</b>\n"
            f"⏳ Pending: <b>{pending}</b>\n"
            f"❌ Rejected: <b>{rejected}</b>\n"
            f"📊 Total: <b>{len(rows)}</b>"
        )

    await query.edit_message_text(text, parse_mode="HTML", reply_markup=admin_panel_menu())


# ---------- Admin Text Commands ----------

async def add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("❌ <code>/addbalance USER_ID Coin</code>", parse_mode="HTML")
        return
    try:
        user_id = int(args[0])
        amount = float(args[1])
    except ValueError:
        await update.message.reply_text("❌ Must be a number.")
        return
    add_user_balance(user_id, amount)
    new_balance = get_user_balance(user_id)
    await update.message.reply_text(
        f"✅ <b>Balance added</b>\n\n🆔 <code>{user_id}</code>\n🪙 <b>{amount:.3f} Coin</b>\n🪙 New Balance: <b>{new_balance:.3f} Coin</b>",
        parse_mode="HTML",
    )


async def set_price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 3:
        await update.message.reply_text("❌ <code>/setprice SERVER AMOUNT Coin</code>", parse_mode="HTML")
        return
    server, amount = args[0], args[1]
    try:
        mc_price = float(args[2])
    except ValueError:
        await update.message.reply_text("❌ Coin must be a number.")
        return
    set_manual_price(server, amount, mc_price)
    final_mc = mc_price * MC_PROFIT_MARGIN
    await update.message.reply_text(
        f"✅ <b>Price set</b>\n\n🌍 {server}\n💎 {amount}\n💰 Final: <b>{final_mc:.3f} Coin</b>",
        parse_mode="HTML",
    )


async def block_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("❌ <code>/block USER_ID</code>", parse_mode="HTML")
        return
    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ User ID must be numeric.")
        return
    set_access_status(user_id, "rejected")
    await update.message.reply_text(f"✅ User <code>{user_id}</code> blocked.", parse_mode="HTML")


async def unblock_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("❌ <code>/unblock USER_ID</code>", parse_mode="HTML")
        return
    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ User ID must be numeric.")
        return
    set_access_status(user_id, "approved")
    await update.message.reply_text(f"✅ User <code>{user_id}</code> unblocked.", parse_mode="HTML")

# ============================================================
# Chapter 24 — Callback Router
# ============================================================

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""

    # ---------- Access Control ----------
    if data.startswith("access:"):
        await handle_access_callback(update, context)
        return

    # ---------- Admin Check ----------
    if data.startswith("admin:"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("❌ Admin only", show_alert=True)
            return

        if data == "admin:panel":
            await show_admin_panel(update, context)
        elif data == "admin:dashboard":
            await show_admin_dashboard(update, context)
        elif data == "admin:price":
            await show_admin_price(update, context)
        elif data == "admin:product":
            await show_admin_product(update, context)
        elif data == "admin:users":
            await show_admin_users(update, context)
        elif data == "admin:backup":
            await admin_backup(update, context)
        elif data == "admin:restore":
            await admin_restore(update, context)
        return

    # ---------- User Access Check ----------
    if get_access_status(query.from_user.id) != "approved":
        await query.answer("🔐 Approval required.", show_alert=True)
        return

    # ---------- Main Menu ----------
    if data == "menu:main":
        user_id = query.from_user.id
        balance = get_user_balance(user_id)
        text = (
            f"✨ <b>Welcome!</b> ✨\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "💎 <b>Eren's Diamond Bot</b>\n\n"
            f"🪙 <b>Balance:</b> {balance:.3f} Coin\n\n"
            "👇 Choose from the menu below"
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu())
        return

    if data == "menu:mlbb":
        await query.edit_message_text("🌍 Choose a Server.", reply_markup=server_keyboard())
        return

    if data == "menu:wallet":
        await show_wallet(update, context)
        return

    if data == "menu:dashboard":
        await show_dashboard(update, context)
        return

    if data == "menu:recharge":
        await show_recharge(update, context)
        return

    if data == "menu:referral":
        await show_referral(update, context)
        return

    if data == "menu:checkin":
        await show_checkin(update, context)
        return

    if data == "menu:mission":
        await show_mission(update, context)
        return

    # ---------- Recharge Methods ----------
    if data == "recharge:kpay":
        await show_kpay(update, context)
        return
    if data == "recharge:wave":
        await show_wave(update, context)
        return

    # ---------- Server Selection ----------
    if data == "back:servers":
        await query.edit_message_text("🌍 Choose a Server.", reply_markup=server_keyboard())
        return

    if data.startswith("server:"):
        server = data.split(":", 1)[1]
        if server not in PRODUCT_CACHE:
            await query.answer("❌ Invalid server", show_alert=True)
            return
        await query.edit_message_text("⏳ Loading...", parse_mode="HTML")
        products, load_error = ensure_server_products(server)
        if not products:
            await query.edit_message_text(
                f"❌ <b>{server}</b>\n\nNo products found.",
                parse_mode="HTML", reply_markup=server_keyboard(),
            )
            return
        total = len(get_unique_products(server))
        header = f"💎 <b>{html.escape(server)}</b>\n📦 {total} Products\n📄 Page 1"
        await query.edit_message_text(header, parse_mode="HTML", reply_markup=amount_keyboard(server, page=0))
        return

    if data.startswith("page:"):
        parts = data.split(":")
        server, page = parts[1], int(parts[2])
        total = len(get_unique_products(server))
        header = f"💎 <b>{html.escape(server)}</b>\n📦 {total} Products\n📄 Page {page + 1}"
        await query.edit_message_text(header, parse_mode="HTML", reply_markup=amount_keyboard(server, page=page))
        return

    if data.startswith("amount:"):
        parts = data.split(":")
        server, index = parts[1], int(parts[2])
        products = get_unique_products(server)
        if index < 0 or index >= len(products):
            await query.answer("❌ Product not found.", show_alert=True)
            return
        product = products[index]
        context.user_data["server"] = server
        context.user_data["product"] = product

        amount = product.get("display_name", product.get("amount", "?"))
        mc_price = get_mc_price(server, product.get("amount"), product)
        price_text = f"{mc_price:.3f} Coin" if mc_price else "No Price"
        user_id = query.from_user.id
        user_balance = get_user_balance(user_id)

        if server in ("TGS", "TGP"):
            if server == "TGP":
                prompt = "📧 <b>Email</b>\nExample: <code>email@gmail.com</code>"
            else:
                prompt = "🎯 <b>Telegram Username</b>\nExample: <code>@username</code>"
        else:
            prompt = "🆔 Enter <b>Player ID</b>.\nExample: <code>12345678</code>"

        text = (
            "💎 <b>Selected</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🌍 Server: <b>{html.escape(server)}</b>\n"
            f"💎 Product: <b>{html.escape(str(amount))}</b>\n"
            f"🪙 Price: <b>{html.escape(price_text)}</b>\n\n"
            f"🪙 Your Balance: <b>{user_balance:.3f} Coin</b>\n\n"
            f"{prompt}"
        )
        await query.edit_message_text(text, parse_mode="HTML")
        return

    # ---------- Order Confirm ----------
    if data == "ml:confirm":
        await handle_ml_confirm(update, context)
        return
    if data == "ml:reject":
        context.user_data.pop("ml_order", None)
        await query.edit_message_text("❌ <b>Order Cancelled</b>", parse_mode="HTML")
        return

    if data == "pg:confirm":
        await handle_pg_confirm(update, context)
        return
    if data == "pg:reject":
        context.user_data.pop("pg_order", None)
        await query.edit_message_text("❌ <b>PUBG Order Cancelled</b>", parse_mode="HTML")
        return

    if data == "tg:confirm":
        await handle_tg_confirm(update, context)
        return
    if data == "tg:reject":
        context.user_data.pop("tg_order", None)
        await query.edit_message_text("❌ <b>Telegram Order Cancelled</b>", parse_mode="HTML")
        return

    # ---------- Deposit Approve/Reject ----------
    if data.startswith("deposit:"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("❌ Admin only", show_alert=True)
            return
        parts = data.split(":")
        action, uid_text = parts[1], parts[2]
        try:
            user_id = int(uid_text)
        except ValueError:
            return
        if action == "approve":
            await query.answer("Use /addbalance.", show_alert=True)
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"💡 <code>/addbalance {user_id} 300</code>",
                parse_mode="HTML",
            )
        elif action == "reject":
            try:
                await query.edit_message_caption(caption=(query.message.caption or "") + "\n\n<b>❌ REJECTED</b>", parse_mode="HTML")
            except Exception:
                pass
            try:
                await context.bot.send_message(chat_id=user_id, text="❌ <b>Deposit rejected.</b>", parse_mode="HTML")
            except Exception as e:
                print("REJECT DM ERROR:", e)
        return

    # ---------- Reply to User ----------
    if data.startswith("reply:"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("❌ Admin only", show_alert=True)
            return
        try:
            user_id = int(data.split(":")[1])
        except Exception:
            return
        context.user_data["reply_to"] = user_id
        context.user_data["state"] = "admin_reply"
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"↩️ Reply to <code>{user_id}</code>\n\nType your reply.",
            parse_mode="HTML",
        )
        return

# ============================================================
# Chapter 25 — Main Function (Final)
# ============================================================

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.document:
        return
    if update.effective_user.id != ADMIN_ID:
        return

    document = update.message.document
    file_name = document.file_name or ""

    if file_name.endswith(".json"):
        await update.message.reply_text("⏳ <b>Restoring...</b>", parse_mode="HTML")
        try:
            file = await context.bot.get_file(document.file_id)
            json_bytes = await file.download_as_bytearray()
            json_str = bytes(json_bytes).decode("utf-8")

            success, error = restore_backup_cookie(json_str)
            if success:
                await update.message.reply_text(
                    "✅ <b>Restore successful.</b>\n\nPlease redeploy the Bot.",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(f"❌ Restore failed: {error}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {html.escape(str(e))}")
        context.user_data.clear()
        return

    await update.message.reply_text("❌ Please send a JSON file only.")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not await request_access(update, context):
        return

    text = update.message.text.strip()

    if text.lower().startswith(".ml "):
        parts = text.split()
        if len(parts) < 4:
            await update.message.reply_text("❌ <code>.ml PLAYER_ID ZONE_ID [SERVER] AMOUNT</code>", parse_mode="HTML")
            return
        context.args = parts[1:]
        await ml_command(update, context)
        return

    if text.lower().startswith(".pg "):
        parts = text.split()
        if len(parts) < 3:
            await update.message.reply_text("❌ <code>.pg PLAYER_ID AMOUNT</code>", parse_mode="HTML")
            return
        context.args = parts[1:]
        await pg_command(update, context)
        return

    if text.lower().startswith(".tg "):
        parts = text.split()
        if len(parts) < 3:
            await update.message.reply_text("❌ <code>.tg TARGET AMOUNT</code>", parse_mode="HTML")
            return
        context.args = parts[1:]
        await tg_command(update, context)
        return

    state = context.user_data.get("state")

    if state == "admin_reply":
        if update.effective_user.id != ADMIN_ID:
            return
        reply_to = context.user_data.get("reply_to")
        if not reply_to:
            return
        try:
            await context.bot.send_message(
                chat_id=reply_to,
                text=f"📩 <b>Admin Reply</b>\n\n{html.escape(text)}",
                parse_mode="HTML",
            )
            await update.message.reply_text("✅ Reply sent.")
        except Exception as e:
            print("REPLY SEND ERROR:", e)
        context.user_data.clear()
        return

    await update.message.reply_text("❓ Please use the menu.")


async def error_handler(update, context):
    print("BOT ERROR:", context.error)


async def post_init(application: Application):
    try:
        await application.bot.delete_my_commands()
    except Exception as e:
        print(f"⚠️ Could not clear menu: {e}")
    print("✅ Bot initialized!")
    print(f"📁 {DATA_DIR}")
    print(f"💹 MC Margin: {MC_PROFIT_MARGIN}")
    print(f"🔔 Alert Group: {ALERT_CHAT_ID}")
    print(f"🧪 Sandbox: {MELO_SANDBOX}")


async def post_shutdown(application: Application):
    print("🛑 Bot shutting down...")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not found.")

    init_all_db()

    print("🤖 Starting...")
    print(f"🧪 Sandbox: {MELO_SANDBOX}")
    print(f"🔔 Alert Chat ID: {ALERT_CHAT_ID}")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", show_admin_panel))
    app.add_handler(CommandHandler("addbalance", add_balance_command))
    app.add_handler(CommandHandler("setprice", set_price_command))
    app.add_handler(CommandHandler("block", block_user_command))
    app.add_handler(CommandHandler("unblock", unblock_user_command))

    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_error_handler(error_handler)

    print("✅ Bot is running!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
