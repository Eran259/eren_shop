import os
import re
import uuid
import html
import sqlite3
import requests
import time
import threading
import hashlib
import hmac
import base64
import shutil
import zipfile
import io
from collections import defaultdict
from datetime import datetime, timedelta

from telegram import (
    Update,
    ReplyKeyboardMarkup,
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
MELO_API_KEY = os.getenv("MELO_API_KEY", "")
MELO_SECRET_KEY = os.getenv("MELO_SECRET_KEY", "")
MELO_BASE_URL = "https://api.melostore.id"

MELO_SANDBOX = os.getenv("MELO_SANDBOX", "true").lower() == "true"

LICENSE_KEY = os.getenv("LICENSE_KEY", "")
LICENSE_SECRET = "EREN_SHOP_SECRET_2026"

MC_PROFIT_MARGIN = 1.0058
MC_ALERT_THRESHOLD = 100

MC_PER_USD = 17.98786
KS_PER_USD = 4450

ADMIN_ID = 5698123475

AMOUNT_ALIASES = {
    "wp": "weeklypass",
    "tp": "twilightpass",
    "web": "weeklyelitebundle",
    "meb": "monthlyepicbundle",
}

SERVER_MAP = {
    "gl": "Global", "global": "Global", "id": "Global",
    "my": "Malaysia", "malaysia": "Malaysia",
    "sg": "Singapore", "singapore": "Singapore",
    "ttr": "Turkey", "tr": "Turkey", "turkey": "Turkey",
    "php": "Philippines", "ph": "Philippines", "philippines": "Philippines",
    "brl": "Brazil", "br": "Brazil", "brazil": "Brazil",
}

SERVER_FLAGS = {
    "Global": "🌍", "Malaysia": "🇲🇾", "Singapore": "🇸🇬",
    "Turkey": "🇹🇷", "Philippines": "🇵🇭", "Brazil": "🇧🇷",
    "PUBG Global": "🎮",
    "Telegram Stars": "⭐",
    "Telegram Premium": "👑",
}

# ✅ PUBG Fallback SKUs (Server 12A → 7 → 13 → 11 → 10)
PUBG_FALLBACK_SKUS = {
    "60": [
        "PUBGMGL60U-S12A",
        "PUBGMGL60U-S7",
        "PUBGMGL60U-S13",
        "PUBGMGL60UCO-S11",
        "PUBGMGL60U-S10",
    ],
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


def mc_to_ks(mc_amount):
    return mc_amount * (KS_PER_USD / MC_PER_USD)

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

def init_balance_db():
    conn = sqlite3.connect(USER_BALANCE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS user_balance (
        user_id INTEGER PRIMARY KEY,
        balance REAL DEFAULT 0.0,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()


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

def init_subscription_db():
    conn = sqlite3.connect(SUBSCRIPTION_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
        user_id INTEGER PRIMARY KEY,
        expiry_date TEXT, status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()


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
    try:
        decoded = base64.b64decode(license_key).decode()
        parts = decoded.split("|")
        if len(parts) != 3:
            return None
        user_id, expiry_date, signature = parts
        expected_sig = hmac.new(LICENSE_SECRET.encode(), f"{user_id}|{expiry_date}".encode(), hashlib.sha256).hexdigest()[:16]
        if signature != expected_sig:
            return None
        return {"user_id": user_id, "expiry_date": expiry_date}
    except Exception:
        return None

def init_user_api_db():
    conn = sqlite3.connect(USER_API_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS user_api (
        user_id INTEGER PRIMARY KEY,
        api_key TEXT, secret_key TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()


def get_user_api(user_id):
    conn = sqlite3.connect(USER_API_DB)
    row = conn.execute("SELECT api_key, secret_key FROM user_api WHERE user_id=?", (int(user_id),)).fetchone()
    conn.close()
    if row:
        return {"api_key": row[0], "secret_key": row[1]}
    return None

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
        # ✅ Game Type သတ်မှတ်
        if srv in ("Global", "Malaysia", "Singapore", "Turkey", "Philippines", "Brazil"):
            game_type = "MLBB"
        elif "PUBG" in srv:
            game_type = "PUBG"
        elif "Telegram" in srv:
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

def create_backup_zip():
    try:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for db_file in [ACCESS_DB, USER_BALANCE_DB, SUBSCRIPTION_DB, USER_API_DB, MANUAL_PRICE_DB, MANUAL_PRODUCT_DB]:
                if os.path.exists(db_file):
                    zipf.write(db_file, os.path.basename(db_file))
        zip_buffer.seek(0)
        return zip_buffer
    except Exception as e:
        print(f"Backup ZIP Error: {e}")
        return None


def restore_backup_zip(zip_bytes):
    try:
        zip_buffer = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(zip_buffer, 'r') as zipf:
            for file_name in zipf.namelist():
                if file_name.endswith('.db'):
                    target_path = os.path.join(DATA_DIR, file_name)
                    with open(target_path, 'wb') as f:
                        f.write(zipf.read(file_name))
        return True
    except Exception as e:
        print(f"Restore Error: {e}")
        return False


def backup_databases():
    try:
        backup_dir = os.path.join(DATA_DIR, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for db_file in [ACCESS_DB, USER_BALANCE_DB, SUBSCRIPTION_DB, USER_API_DB, MANUAL_PRICE_DB, MANUAL_PRODUCT_DB]:
            if os.path.exists(db_file):
                backup_file = os.path.join(backup_dir, f"{os.path.basename(db_file)}_{timestamp}.bak")
                shutil.copy2(db_file, backup_file)
        print(f"✅ Backup: {backup_dir}")
    except Exception as e:
        print(f"⚠️ Backup failed: {e}")

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
            "⚠️ ဒီ user ကို Bot အသုံးပြုခွင့်ပေးမလား?"
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
                "❌ <b>Access Denied</b>\n\n/start နှိပ်ပြီး Request ပြန်ပို့နိုင်ပါတယ်။",
                parse_mode="HTML",
            )
        return False

    if status == "pending":
        if update.message:
            await update.message.reply_text(
                "⏳ <b>Access Pending</b>\n\nAdmin ဆီ Request ပို့ထားပါတယ်။",
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
                text="✅ <b>Access Approved!</b>\n\n/start နှိပ်ပြီး စတင်ပါ။",
                parse_mode="HTML",
            )
        except Exception as e:
            print("APPROVAL DM ERROR:", e)
        await query.answer("Approved ✅")
    else:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ <b>Access Denied</b>\n\n/start နှိပ်ပြီး Request ပြန်ပို့နိုင်ပါတယ်။",
                parse_mode="HTML",
            )
        except Exception as e:
            print("REJECTION DM ERROR:", e)
        await query.answer("Rejected ❌")

    return True

PRODUCT_CACHE = {
    "Global": [], "Malaysia": [], "Singapore": [],
    "Turkey": [], "Philippines": [], "Brazil": [],
    "PUBG Global": [],
    "Telegram Stars": [],
    "Telegram Premium": [],
}
LAST_PRODUCTS_LOAD = 0
PRODUCT_CACHE_TTL = 300
PRODUCT_LOAD_LOCK = threading.Lock()
PRODUCT_LAST_ERROR = {}


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

        # ✅ Game Filter
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

        # ✅ Server Mapping
        product_server = None

        if game_type == "MLBB":
            if "mobile legends (indonesia)" in name_text or "(id)" in name_text:
                product_server = "Global"
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
            product_server = "PUBG Global"

        elif game_type == "Telegram":
            # ✅ Star နဲ့ Premium ခွဲ (မရောအောင်)
            if "premium" in name_text or "gift card" in name_text or "gazette" in name_text:
                product_server = "Telegram Premium"
            elif "star" in name_text:
                product_server = "Telegram Stars"
            else:
                product_server = "Telegram Stars"

        if product_server != server:
            continue

        sku = str(product.get("sku_code", ""))
        name = str(product.get("name", ""))

        # ✅ Amount & Display Name
        if game_type == "PUBG":
            num_match = re.search(r"(\d+)", name)
            amount = num_match.group(1) if num_match else name.strip()
            display_name = name.strip()
        elif game_type == "Telegram":
            # Premium အတွက် Display Name က "3 Months" လို
            if product_server == "Telegram Premium":
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

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["💎 MLBB Diamonds", "🎮 PUBG UC"],
            ["⭐ Telegram Stars", "👑 Telegram Premium"],
            ["🌍 Global", "🇲🇾 Malaysia"],
            ["🇸🇬 Singapore", "🇹🇷 Turkey"],
            ["🇵🇭 Philippines", "🇧🇷 Brazil"],
            ["💰 My Balance", "💳 Deposit"],
            ["📞 Contact Admin", "⚙️ Admin Panel"],
            ["🔌 API Status"],
        ],
        resize_keyboard=True,
    )


def server_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🌍 Global Server", callback_data="server:Global")],
            [InlineKeyboardButton("🇲🇾 Malaysia Server", callback_data="server:Malaysia")],
            [InlineKeyboardButton("🇸🇬 Singapore Server", callback_data="server:Singapore")],
            [InlineKeyboardButton("🇹🇷 Turkey Server", callback_data="server:Turkey")],
            [InlineKeyboardButton("🇵🇭 Philippines Server", callback_data="server:Philippines")],
            [InlineKeyboardButton("🇧🇷 Brazil Server", callback_data="server:Brazil")],
            [InlineKeyboardButton("🎮 PUBG Global", callback_data="server:PUBG Global")],
            [InlineKeyboardButton("⭐ Telegram Stars", callback_data="server:Telegram Stars")],
            [InlineKeyboardButton("👑 Telegram Premium", callback_data="server:Telegram Premium")],
        ]
    )


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
        price_text = f"{mc_price:.3f} MC" if mc_price else "No Price"

        game_type = product.get("game_type", "MLBB")
        if game_type == "PUBG":
            label = f"🎮 {display_amount} • {price_text}"
        elif game_type == "Telegram":
            if server == "Telegram Premium":
                label = f"👑 {display_amount} • {price_text}"
            else:
                label = f"⭐ {display_amount} • {price_text}"
        else:
            label = f"💎 {format_amount_for_display(display_amount)} • {price_text}"

        real_index = start + index
        button = InlineKeyboardButton(label, callback_data=f"amount:{server}:{real_index}")
        buttons.append([button])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page:{server}:{page-1}"))
    if end < total:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"page:{server}:{page+1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton("⬅️ Server ပြန်ရွေးမယ်", callback_data="back:servers")])
    return InlineKeyboardMarkup(buttons)

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
            f"🪙 <b>Balance:</b> {balance:.3f} MC\n\n"
            "🛒 <b>Services</b>\n"
            "💎 MLBB Diamonds\n🎮 PUBG UC\n"
            "⭐ Telegram Stars\n💰 My Balance\n💳 Deposit"
        )
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_keyboard())
        return

    status = get_access_status(user_id)

    if status == "approved":
        status_text = "✅ <b>Active</b>"
        footer = "🛒 <b>Services</b>\n💎 MLBB Diamonds\n🎮 PUBG UC\n⭐ Telegram Stars\n💰 My Balance\n💳 Deposit"
        show_keyboard = True
    elif status == "pending":
        status_text = "⏳ <b>Pending</b>"
        footer = "ခဏစောင့်ပါ။ Admin Approve ဖြစ်တဲ့အခါ Bot ကို သုံးလို့ရပါမယ်။"
        show_keyboard = False
    elif status == "rejected":
        status_text = "❌ <b>Rejected</b>"
        footer = "/start နှိပ်ပြီး Request ပြန်ပို့နိုင်ပါတယ်။"
        show_keyboard = False
    else:
        await request_access(update, context, force_request=True)
        status_text = "⏳ <b>Pending Approval</b>"
        footer = "Approve ဖြစ်တဲ့အခါ Bot ကို သုံးလို့ရပါမယ်။"
        show_keyboard = False

    text = (
        f"✨ <b>Welcome, {html.escape(first_name)}!</b> ✨\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💎 <b>Eren's Diamond Bot</b>\n\n"
        f"👤 <b>Status:</b> {status_text}\n"
        f"🪙 <b>Balance:</b> {balance:.3f} MC\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{footer}\n\n⚡ Powered by Eren"
    )

    if show_keyboard:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_keyboard())
    else:
        await update.message.reply_text(text, parse_mode="HTML")


async def show_my_balance(update: Update):
    user_id = update.effective_user.id
    user_balance = get_user_balance(user_id)

    if user_id == ADMIN_ID:
        data, error = get_balance()
        if not error:
            info = data.get("data", {})
            mc_balance = info.get("h2h_balance", 0)
            usd = info.get("h2h_balance_usd", 0)
            user_ks = mc_to_ks(user_balance)
            mc_ks = mc_to_ks(mc_balance)
            text = (
                "💰 <b>Balance</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🪙 <b>User Balance</b>\n<b>{user_balance:.3f} MC</b>\n💵 ≈ <b>{user_ks:,.0f} Ks</b>\n\n"
                f"🪙 <b>Melostore Balance</b>\n<b>{mc_balance:,.2f} MC</b>\n💵 ≈ <b>{mc_ks:,.0f} Ks</b>\n\n"
                f"💵 USD: <b>${usd:,.2f}</b>"
            )
        else:
            user_ks = mc_to_ks(user_balance)
            text = (
                "💰 <b>Balance</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🪙 <b>User Balance</b>\n<b>{user_balance:.3f} MC</b>\n💵 ≈ <b>{user_ks:,.0f} Ks</b>\n\n"
                f"🪙 <b>Melostore</b>: <i>Error</i>"
            )
    else:
        ks_balance = mc_to_ks(user_balance)
        text = (
            "💰 <b>သင့်ရဲ့ Balance</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🪙 Balance: <b>{user_balance:.3f} MC</b>\n"
            f"💵 ≈ <b>{ks_balance:,.0f} Ks</b>\n\n"
            "💳 ငွေဖြည့်ချင်ရင် <b>Deposit</b> ကို နှိပ်ပါ။"
        )

    await update.message.reply_text(text, parse_mode="HTML")


async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only")
        return

    data, error = get_balance()
    if error:
        await update.message.reply_text(f"❌ Error: {html.escape(str(error))}")
        return

    info = data.get("data", {})
    balance = info.get("h2h_balance", 0)
    usd = info.get("h2h_balance_usd", 0)

    text = (
        "📊 <b>Admin Panel</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🪙 Melostore MC: <b>{balance:,.2f} MC</b>\n"
        f"💵 USD: <b>${usd:,.2f}</b>\n\n"
        "💡 <b>Commands</b>\n"
        "/addbalance USER_ID MC\n"
        "/checkbalance USER_ID\n"
        "/setprice SERVER AMOUNT MC\n"
        "/delprice SERVER AMOUNT\n"
        "/listprices [SERVER]\n"
        "/addproduct SERVER AMOUNT [SKU]\n"
        "/delproduct SERVER AMOUNT\n"
        "/listproducts [SERVER]\n"
        "/backup\n/restore"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def show_deposit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💳 <b>ငွေဖြည့်ရန် (Deposit)</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        "💙 <b>K Pay</b>: <code>09766605879</code>\n"
        "💛 <b>AYA Pay</b>: <code>09678664100</code>\n"
        "💚 <b>UAB Pay</b>: <code>09425160424</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚠️ <b>အနည်းဆုံး 100 MC ဖြည့်ပါ။</b>\n\n"
        "📸 Screenshot ကို ဒီ Chat မှာ ပို့ပါ။"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def show_api_status(update: Update):
    data, error = get_profile()
    if error:
        await update.message.reply_text(f"🔴 <b>API Offline</b>\n\n{html.escape(str(error))}", parse_mode="HTML")
        return
    info = data.get("data", {})
    sandbox = info.get("is_sandbox_mode", False)
    status = "🧪 Sandbox" if sandbox else "🟢 Production"
    text = (
        "🔌 <b>API Status</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🟢 Connection: <b>Connected</b>\n"
        f"⚙️ Mode: <b>{status}</b>\n\n⚡ Powered by Eren"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def start_check_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["state"] = "check_id_player"
    await update.message.reply_text(
        "🔍 <b>MLBB ID Checker</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        "🆔 <b>Player ID</b> ထည့်ပါ။\n\n❌ Cancel: /start",
        parse_mode="HTML",
    )


def check_ml_nickname(player_id, zone_id):
    payload = {
        "game_code": "mobile-legends",
        "customer_target": str(player_id),
        "customer_target_zone": str(zone_id),
    }
    return api_post("/api/v1/h2h/check-nickname", payload)


async def process_check_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    player_id = context.user_data.get("check_player_id")
    zone_id = update.message.text.strip()
    if not zone_id.isdigit():
        await update.message.reply_text("❌ Zone ID နံပါတ်ပဲ ထည့်ပါ။")
        return

    await update.message.reply_text("🔍 <b>Checking...</b>", parse_mode="HTML")
    data, error = check_ml_nickname(player_id, zone_id)

    if error:
        await update.message.reply_text(f"❌ <b>Failed</b>\n\n{html.escape(str(error))}", parse_mode="HTML")
        context.user_data.clear()
        return

    info = data.get("data", {})
    nickname = info.get("username") or info.get("nickname") or info.get("name") or "-"

    text = (
        "🔍 <b>Result</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Nickname: <b>{html.escape(str(nickname))}</b>\n"
        f"🆔 Player ID: <code>{html.escape(str(player_id))}</code>\n"
        f"🌐 Zone ID: <code>{html.escape(str(zone_id))}</code>"
    )
    context.user_data.clear()
    await update.message.reply_text(text, parse_mode="HTML")


async def server_product_shortcut(update: Update, context: ContextTypes.DEFAULT_TYPE, server: str):
    products, error = ensure_server_products(server)
    if not products:
        await update.message.reply_text(f"❌ <b>{server}</b>\n\nProduct List ရယူလို့ မရပါ။", parse_mode="HTML")
        return

    unique_products = get_unique_products(server)
    if not unique_products:
        await update.message.reply_text(f"📭 <b>{server}</b>\n\nProduct မရှိသေးပါ။", parse_mode="HTML")
        return

    flag = SERVER_FLAGS.get(server, "🌍")

    lines = ["📦 <b>Products</b>", "━━━━━━━━━━━━━━━━━━━━", "", f"{flag} <b>{server}</b>", ""]

    for p in unique_products:
        amount = p.get("amount", "?")
        display_amount = p.get("display_name", amount)
        mc_price = get_mc_price(server, amount, p)
        price_text = f"{mc_price:.3f} MC" if mc_price else "No Price"

        game_type = p.get("game_type", "MLBB")
        if game_type == "PUBG":
            lines.append(f"  🎮 <b>{html.escape(str(display_amount))}</b> • {price_text}")
        elif game_type == "Telegram":
            if server == "Telegram Premium":
                lines.append(f"  👑 <b>{html.escape(str(display_amount))}</b> • {price_text}")
            else:
                lines.append(f"  ⭐ <b>{html.escape(str(display_amount))}</b> • {price_text}")
        else:
            lines.append(f"  💎 <b>{html.escape(str(display_amount))}</b> • {price_text}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    if server == "PUBG Global":
        lines.append("")
        lines.append("💡 <b>Order:</b> <code>.pg PLAYER_ID AMOUNT</code>")
        lines.append("")
        lines.append(f"📌 <b>ဥပမာ:</b> <code>.pg 5123456789 {unique_products[0].get('amount', '60')}</code>")
    elif server == "Telegram Stars":
        lines.append("")
        lines.append("💡 <b>Order (Direct):</b> <code>.tg TARGET AMOUNT</code>")
        lines.append("")
        lines.append(f"📌 <b>ဥပမာ:</b> <code>.tg @username {unique_products[0].get('amount', '50')}</code>")
    elif server == "Telegram Premium":
        lines.append("")
        lines.append("💡 <b>Order (Gift Card):</b> <code>.tg TARGET AMOUNT</code>")
        lines.append("")
        lines.append(f"📌 <b>ဥပမာ:</b> <code>.tg @username {unique_products[0].get('amount', '3 Months')}</code>")
        lines.append("")
        lines.append("⚠️ <i>Gift Card ဖြစ်တဲ့အတွက် Code ပေးပါမယ်။</i>")
    else:
        lines.append("")
        lines.append("💡 <b>Order:</b> <code>.ml PLAYER_ID ZONE_ID AMOUNT</code>")
        lines.append("")
        lines.append("📌 <b>Server Codes:</b> gl, my, sg, ttr, php, brl")
        lines.append("")
        lines.append(f"📌 <b>ဥပမာ:</b> <code>.ml 12345678 2039 {unique_products[0].get('amount', '5')}</code>")

    text = "\n".join(lines)

    if len(text) > 4000:
        for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
            await update.message.reply_text(chunk, parse_mode="HTML")
    else:
        await update.message.reply_text(text, parse_mode="HTML")

async def ml_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """.ml PLAYER_ID ZONE_ID [SERVER] AMOUNT"""
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
                "❌ <b>Server မမှန်ပါ။</b>\n\n"
                "<code>gl</code>, <code>my</code>, <code>sg</code>, <code>ttr</code>, <code>php</code>, <code>brl</code>",
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
            "❌ <b>အသုံးပြုနည်း</b>\n\n"
            "<code>.ml PLAYER_ID ZONE_ID AMOUNT</code>\n"
            "<code>.ml PLAYER_ID ZONE_ID SERVER AMOUNT</code>",
            parse_mode="HTML",
        )
        return

    if not player_id.isdigit() or not zone_id.isdigit():
        await update.message.reply_text("❌ Player ID / Zone ID နံပါတ်ပဲ ထည့်ပါ။")
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
            f"❌ <b>Product မတွေ့ပါ။</b>\n\n"
            f"💡 <b>ရနိုင်တာ:</b>\n<code>{', '.join(available[:20])}</code>",
            parse_mode="HTML",
        )
        return

    amount = matched_product.get("amount", "?")
    display_amount = matched_product.get("display_name", amount)
    mc_price = get_mc_price(server, amount, matched_product)

    if mc_price is None:
        await update.message.reply_text("⚠️ <b>Price မသတ်မှတ်ရသေးပါ။</b>", parse_mode="HTML")
        return

    user_balance = get_user_balance(user_id)
    if user_balance < mc_price:
        await update.message.reply_text(
            f"❌ <b>Balance မလုံလောက်ပါ။</b>\n\n"
            f"🪙 လက်ရှိ: <b>{user_balance:.3f} MC</b>\n"
            f"💰 လိုအပ်: <b>{mc_price:.3f} MC</b>",
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

    await checking_msg.edit_text("🛒 <b>Creating Order...</b>", parse_mode="HTML")

    product = dict(matched_product)
    data, error = create_transaction(product, player_id, zone_id)

    if error:
        await checking_msg.edit_text(f"❌ <b>Order Failed</b>\n\n{html.escape(str(error))}", parse_mode="HTML")
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
        f"🪙 MC Price: <b>{mc_price:.3f} MC</b>\n\n"
        f"🆔 Trx: <code>{html.escape(str(transaction_id))}</code>\n"
        f"⏳ Status: <b>{html.escape(str(status).upper())}</b>\n\n"
        f"🪙 လက်ကျန် MC: <b>{new_balance:.3f} MC</b>"
    )
    await checking_msg.edit_text(text, parse_mode="HTML")

    try:
        username = f"@{user.username}" if user.username else "—"
        first_name = user.first_name or "User"
        alarm_text = (
            "🔔 <b>NEW ORDER!</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Name: <b>{html.escape(first_name)}</b>\n"
            f"🔗 Username: <b>{html.escape(username)}</b>\n"
            f"🆔 User ID: <code>{user_id}</code>\n\n"
            f"🌍 Server: <b>{html.escape(server)}</b>\n"
            f"👤 Nickname: <b>{html.escape(str(nickname))}</b>\n"
            f"🆔 Player ID: <code>{html.escape(str(player_id))}</code>\n"
            f"🌐 Zone ID: <code>{html.escape(str(zone_id))}</code>\n\n"
            f"💎 Product: <b>{html.escape(str(display_amount))}</b>\n"
            f"🪙 MC Price: <b>{mc_price:.3f} MC</b>\n\n"
            f"🧾 Trx: <code>{html.escape(str(transaction_id))}</code>\n"
            f"⏰ Time: <code>{order_time}</code>"
        )
        await context.bot.send_message(chat_id=ADMIN_ID, text=alarm_text, parse_mode="HTML")
    except Exception as e:
        print("ORDER ALARM ERROR:", e)

async def pg_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """.pg PLAYER_ID AMOUNT"""
    if not update.message:
        return
    if not await request_access(update, context):
        return

    user = update.effective_user
    user_id = user.id
    args = context.args

    if len(args) != 2:
        await update.message.reply_text(
            "❌ <b>အသုံးပြုနည်း</b>\n\n"
            "<code>.pg PLAYER_ID AMOUNT</code>\n\n"
            "<b>ဥပမာ:</b>\n<code>.pg 5123456789 60</code>",
            parse_mode="HTML",
        )
        return

    player_id = args[0].strip()
    amount_input = args[1].strip()

    if not player_id.isdigit():
        await update.message.reply_text("❌ Player ID နံပါတ်ပဲ ထည့်ပါ။")
        return

    if amount_input not in PUBG_FALLBACK_SKUS:
        available = ", ".join(PUBG_FALLBACK_SKUS.keys())
        await update.message.reply_text(
            f"❌ <b>Amount မတွေ့ပါ။</b>\n\n"
            f"💡 <b>ရနိုင်တာ:</b> <code>{available}</code>",
            parse_mode="HTML",
        )
        return

    mc_price = get_mc_price("PUBG Global", amount_input, None)
    if mc_price is None:
        await update.message.reply_text("⚠️ <b>Price မသတ်မှတ်ရသေးပါ။</b>", parse_mode="HTML")
        return

    user_balance = get_user_balance(user_id)
    if user_balance < mc_price:
        await update.message.reply_text(
            f"❌ <b>Balance မလုံလောက်ပါ။</b>\n\n"
            f"🪙 လက်ရှိ: <b>{user_balance:.3f} MC</b>\n"
            f"💰 လိုအပ်: <b>{mc_price:.3f} MC</b>",
            parse_mode="HTML",
        )
        return

    # Balance ဖြတ်
    if not deduct_user_balance(user_id, mc_price):
        await update.message.reply_text("❌ Balance ဖြတ်လို့ မရပါ။")
        return

    checking_msg = await update.message.reply_text(
        "🔄 <b>Processing...</b>\nServer စမ်းနေပါတယ်...",
        parse_mode="HTML",
    )

    # ✅ Fallback
    skus = PUBG_FALLBACK_SKUS[amount_input]
    last_error = None
    data = None
    error = None
    used_sku = None

    for idx, sku in enumerate(skus, 1):
        print(f"🔄 Trying SKU {idx}/{len(skus)}: {sku}")
        product = {"sku_code": sku, "amount": amount_input, "server": "PUBG Global"}
        data, error = create_transaction(product, player_id, "")
        if not error:
            used_sku = sku
            print(f"✅ Success: {sku}")
            break
        else:
            print(f"❌ Failed: {sku} → {error}")
            last_error = error

    if error:
        add_user_balance(user_id, mc_price)
        await checking_msg.edit_text(
            f"❌ <b>Order Failed</b>\n\n"
            f"Server အားလုံး Fail ဖြစ်ပါတယ်။\n"
            f"Balance ပြန်ထည့်ပြီးပါပြီ။\n\n"
            f"Error: <code>{html.escape(str(last_error)[:150])}</code>",
            parse_mode="HTML",
        )
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
        f"🪙 MC Price: <b>{mc_price:.3f} MC</b>\n\n"
        f"🆔 Trx: <code>{html.escape(str(transaction_id))}</code>\n"
        f"⏳ Status: <b>{html.escape(str(status).upper())}</b>\n\n"
        f"🪙 လက်ကျန် MC: <b>{new_balance:.3f} MC</b>"
    )
    await checking_msg.edit_text(text, parse_mode="HTML")

    try:
        username = f"@{user.username}" if user.username else "—"
        first_name = user.first_name or "User"
        alarm_text = (
            "🔔 <b>NEW PUBG ORDER!</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Name: <b>{html.escape(first_name)}</b>\n"
            f"🔗 Username: <b>{html.escape(username)}</b>\n"
            f"🆔 User ID: <code>{user_id}</code>\n\n"
            f"🆔 Player ID: <code>{html.escape(player_id)}</code>\n\n"
            f"🎮 Product: <b>{html.escape(amount_input)} UC</b>\n"
            f"🪙 MC Price: <b>{mc_price:.3f} MC</b>\n"
            f"📦 SKU: <code>{html.escape(str(used_sku))}</code>\n\n"
            f"🧾 Trx: <code>{html.escape(str(transaction_id))}</code>\n"
            f"⏰ Time: <code>{order_time}</code>"
        )
        await context.bot.send_message(chat_id=ADMIN_ID, text=alarm_text, parse_mode="HTML")
    except Exception as e:
        print("ORDER ALARM ERROR:", e)

async def tg_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """.tg TARGET AMOUNT"""
    if not update.message:
        return
    if not await request_access(update, context):
        return

    user = update.effective_user
    user_id = user.id
    args = context.args

    if len(args) != 2:
        await update.message.reply_text(
            "❌ <b>အသုံးပြုနည်း</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            "<code>.tg TARGET AMOUNT</code>\n\n"
            "⭐ <b>Stars:</b>\n<code>.tg @username 50</code>\n\n"
            "👑 <b>Premium:</b>\n<code>.tg @username 3 Months</code>",
            parse_mode="HTML",
        )
        return

    target = args[0].strip()
    amount_input = args[1].strip()

    # ✅ Star နဲ့ Premium နှစ်ခုလုံးမှာ ရှာ (မရောအောင်)
    matched_product = None
    matched_server = None

    for srv in ["Telegram Stars", "Telegram Premium"]:
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
        star_products, _ = ensure_server_products("Telegram Stars")
        prem_products, _ = ensure_server_products("Telegram Premium")

        star_amounts = sorted(set(str(p.get("amount", "?")) for p in star_products))
        prem_names = sorted(set(str(p.get("display_name", "?")) for p in prem_products))

        text = "❌ <b>Product မတွေ့ပါ။</b>\n\n"
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
        await update.message.reply_text(
            f"⚠️ <b>Price မသတ်မှတ်ရသေးပါ။</b>\n\nProduct: <code>{html.escape(str(display_amount))}</code>",
            parse_mode="HTML",
        )
        return

    user_balance = get_user_balance(user_id)
    if user_balance < mc_price:
        await update.message.reply_text(
            f"❌ <b>Balance မလုံလောက်ပါ။</b>\n\n"
            f"🪙 လက်ရှိ: <b>{user_balance:.3f} MC</b>\n"
            f"💰 လိုအပ်: <b>{mc_price:.3f} MC</b>",
            parse_mode="HTML",
        )
        return

    checking_msg = await update.message.reply_text("🛒 <b>Creating Order...</b>", parse_mode="HTML")

    product = dict(matched_product)
    data, error = create_transaction(product, target, "")

    if error:
        await checking_msg.edit_text(f"❌ <b>Order Failed</b>\n\n{html.escape(str(error))}", parse_mode="HTML")
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

    if server == "Telegram Premium":
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
        f"🪙 MC Price: <b>{mc_price:.3f} MC</b>\n\n"
        f"🆔 Trx: <code>{html.escape(str(transaction_id))}</code>\n"
        f"⏳ Status: <b>{html.escape(str(status).upper())}</b>\n"
        f"{code_section}\n"
        f"🪙 လက်ကျန် MC: <b>{new_balance:.3f} MC</b>"
    )
    await checking_msg.edit_text(text, parse_mode="HTML")

    try:
        username = f"@{user.username}" if user.username else "—"
        first_name = user.first_name or "User"
        alarm_text = (
            f"🔔 <b>NEW {label.upper()} ORDER!</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Name: <b>{html.escape(first_name)}</b>\n"
            f"🔗 Username: <b>{html.escape(username)}</b>\n"
            f"🆔 User ID: <code>{user_id}</code>\n\n"
            f"🎯 Target: <code>{html.escape(target)}</code>\n\n"
            f"{emoji} Product: <b>{html.escape(str(display_amount))}</b>\n"
            f"🪙 MC Price: <b>{mc_price:.3f} MC</b>\n\n"
        )
        if serial_number:
            alarm_text += f"🎁 Gift Code: <code>{html.escape(str(serial_number))}</code>\n\n"
        alarm_text += (
            f"🧾 Trx: <code>{html.escape(str(transaction_id))}</code>\n"
            f"⏰ Time: <code>{order_time}</code>"
        )
        await context.bot.send_message(chat_id=ADMIN_ID, text=alarm_text, parse_mode="HTML")
    except Exception as e:
        print("ORDER ALARM ERROR:", e)


def create_transaction(product, player_id, zone_id):
    sku = product.get("sku_code")
    buyer_trx_id = "EREN-" + uuid.uuid4().hex[:20].upper()
    payload = {
        "sku_code": sku,
        "customer_target": str(player_id),
        "customer_target_zone": str(zone_id) if zone_id else "",
        "buyer_trx_id": buyer_trx_id,
        "sandbox_mode": MELO_SANDBOX,
    }
    return api_post("/api/v1/h2h/transaction", payload)

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo:
        return

    user = update.effective_user
    file_id = update.message.photo[-1].file_id

    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID, photo=file_id,
            caption=(
                "💳 <b>NEW DEPOSIT</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 Name: <b>{html.escape(user.first_name or '—')}</b>\n"
                f"🔗 Username: @{user.username or '—'}\n"
                f"🆔 User ID: <code>{user.id}</code>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ ဖြည့်မယ်", callback_data=f"deposit:approve:{user.id}"),
                InlineKeyboardButton("❌ ပယ်ဖျက်", callback_data=f"deposit:reject:{user.id}"),
            ]]),
        )
        await update.message.reply_text("✅ <b>Screenshot ရပါပြီ။</b>\n\nAdmin စစ်ပြီး Balance ဖြည့်ပေးပါမယ်။")
    except Exception as e:
        print("DEPOSIT SEND ERROR:", e)


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.document:
        return
    if update.effective_user.id != ADMIN_ID:
        return

    document = update.message.document
    if not (document.file_name or "").endswith('.zip'):
        await update.message.reply_text("❌ ZIP ဖိုင်ပဲ ပို့ပါ။")
        return

    await update.message.reply_text("⏳ <b>Restore...</b>", parse_mode="HTML")
    try:
        file = await context.bot.get_file(document.file_id)
        zip_bytes = await file.download_as_bytearray()
        if restore_backup_zip(bytes(zip_bytes)):
            await update.message.reply_text("✅ <b>Restore အောင်မြင်ပါပြီ။</b>\n\nBot ကို Redeploy လုပ်ပါ။")
        else:
            await update.message.reply_text("❌ Restore လုပ်လို့ မရပါ။")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {html.escape(str(e))}")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not await request_access(update, context):
        return

    text = update.message.text.strip()

    # ✅ Commands
    if text.lower().startswith(".ml "):
        parts = text.split()
        if len(parts) < 4:
            await update.message.reply_text(
                "❌ <code>.ml PLAYER_ID ZONE_ID [SERVER] AMOUNT</code>\n\n"
                "📌 <b>ဥပမာ:</b> <code>.ml 12345678 2039 wp</code>",
                parse_mode="HTML",
            )
            return
        context.args = parts[1:]
        await ml_command(update, context)
        return

    if text.lower().startswith(".pg "):
        parts = text.split()
        if len(parts) < 3:
            await update.message.reply_text(
                "❌ <code>.pg PLAYER_ID AMOUNT</code>\n\n"
                "📌 <b>ဥပမာ:</b> <code>.pg 5123456789 60</code>",
                parse_mode="HTML",
            )
            return
        context.args = parts[1:]
        await pg_command(update, context)
        return

    if text.lower().startswith(".tg "):
        parts = text.split()
        if len(parts) < 3:
            await update.message.reply_text(
                "❌ <code>.tg TARGET AMOUNT</code>\n\n"
                "📌 <b>ဥပမာ:</b> <code>.tg @username 50</code>",
                parse_mode="HTML",
            )
            return
        context.args = parts[1:]
        await tg_command(update, context)
        return

    # ✅ Buttons
    if text == "💎 MLBB Diamonds":
        await server_product_shortcut(update, context, "Global")
        return
    if text == "🎮 PUBG UC":
        await server_product_shortcut(update, context, "PUBG Global")
        return
    if text == "⭐ Telegram Stars":
        await server_product_shortcut(update, context, "Telegram Stars")
        return
    if text == "👑 Telegram Premium":
        await server_product_shortcut(update, context, "Telegram Premium")
        return

    if text == "🌍 Global":
        await server_product_shortcut(update, context, "Global")
        return
    if text == "🇲🇾 Malaysia":
        await server_product_shortcut(update, context, "Malaysia")
        return
    if text == "🇸🇬 Singapore":
        await server_product_shortcut(update, context, "Singapore")
        return
    if text == "🇹🇷 Turkey":
        await server_product_shortcut(update, context, "Turkey")
        return
    if text == "🇵🇭 Philippines":
        await server_product_shortcut(update, context, "Philippines")
        return
    if text == "🇧🇷 Brazil":
        await server_product_shortcut(update, context, "Brazil")
        return

    if text == "🔍 Check ML ID":
        await start_check_id(update, context)
        return
    if text == "💰 My Balance":
        await show_my_balance(update)
        return
    if text == "💳 Deposit":
        await show_deposit_menu(update, context)
        return
    if text == "📞 Contact Admin":
        context.user_data["state"] = "contact_admin"
        await update.message.reply_text(
            "📞 <b>Contact Admin</b>\n\nAdmin ဆီ ပို့ချင်တဲ့ စာကို ရိုက်ထည့်ပါ။\n\n❌ Cancel: /start",
            parse_mode="HTML",
        )
        return
    if text == "⚙️ Admin Panel":
        await show_admin_panel(update, context)
        return
    if text == "🔌 API Status":
        if update.effective_user.id == ADMIN_ID:
            await show_api_status(update)
        else:
            await update.message.reply_text("❌ Admin only")
        return

    # ✅ States
    state = context.user_data.get("state")

    if state == "check_id_player":
        if not text.isdigit():
            await update.message.reply_text("❌ Player ID နံပါတ်ပဲ ထည့်ပါ။")
            return
        context.user_data["check_player_id"] = text
        context.user_data["state"] = "check_id_zone"
        await update.message.reply_text("🌐 <b>Zone ID</b> ထည့်ပါ။", parse_mode="HTML")
        return

    if state == "check_id_zone":
        await process_check_id(update, context)
        return

    if state == "contact_admin":
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "User"
        username = f"@{update.effective_user.username}" if update.effective_user.username else "—"
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "📞 <b>NEW USER MESSAGE</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"👤 Name: <b>{html.escape(user_name)}</b>\n"
                    f"🔗 Username: <b>{html.escape(username)}</b>\n"
                    f"🆔 User ID: <code>{user_id}</code>\n\n"
                    f"💬 {html.escape(text)}"
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Reply", callback_data=f"reply:{user_id}"),
                ]]),
            )
            await update.message.reply_text("✅ <b>Message ပို့ပြီးပါပြီ။</b>", parse_mode="HTML", reply_markup=main_keyboard())
        except Exception as e:
            print("CONTACT SEND ERROR:", e)
        context.user_data.clear()
        return

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
                reply_markup=main_keyboard(),
            )
            await update.message.reply_text("✅ <b>Reply ပို့ပြီးပါပြီ။</b>", reply_markup=main_keyboard())
        except Exception as e:
            print("REPLY SEND ERROR:", e)
        context.user_data.clear()
        return

    await update.message.reply_text("❓ Menu ကနေရွေးပေးပါ။", reply_markup=main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await request_access(update, context):
        return
    text = (
        "📖 <b>Help</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        "💎 MLBB Diamonds\n🎮 PUBG UC\n"
        "⭐ Telegram Stars\n💰 My Balance\n💳 Deposit\n\n"
        "🔹 <b>Order:</b>\n"
        "<code>.ml ID ZONE AMOUNT</code>\n"
        "<code>.pg USER_ID AMOUNT</code>\n"
        "<code>.tg TARGET AMOUNT</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_keyboard())


async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("⏳ <b>Backup...</b>", parse_mode="HTML")
    zip_buffer = create_backup_zip()
    if not zip_buffer:
        await update.message.reply_text("❌ Backup ဆွဲလို့ မရပါ။")
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    await update.message.reply_document(
        document=zip_buffer,
        filename=f"eren_backup_{timestamp}.zip",
        caption="✅ <b>Backup ဆွဲပြီးပါပြီ။</b>",
        parse_mode="HTML",
    )


async def restore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("📦 Backup ZIP ဖိုင်ကို ဒီ Chat မှာ ပို့ပါ။", parse_mode="HTML")


async def add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("❌ <code>/addbalance USER_ID MC</code>", parse_mode="HTML")
        return
    try:
        user_id = int(args[0])
        amount = float(args[1])
    except ValueError:
        await update.message.reply_text("❌ နံပါတ် ဖြစ်ရပါမယ်။")
        return
    add_user_balance(user_id, amount)
    new_balance = get_user_balance(user_id)
    await update.message.reply_text(
        f"✅ <b>Balance ဖြည့်ပြီး</b>\n\n🆔 <code>{user_id}</code>\n🪙 <b>{amount:.3f} MC</b>\n🪙 လက်ကျန်: <b>{new_balance:.3f} MC</b>",
        parse_mode="HTML",
    )
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ <b>MC Balance ဖြည့်ပြီးပါပြီ။</b>\n\n🪙 <b>{new_balance:.3f} MC</b>",
            parse_mode="HTML", reply_markup=main_keyboard(),
        )
    except Exception as e:
        print("BALANCE NOTIFY ERROR:", e)


async def check_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("❌ <code>/checkbalance USER_ID</code>", parse_mode="HTML")
        return
    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ User ID နံပါတ် ဖြစ်ရပါမယ်။")
        return
    balance = get_user_balance(user_id)
    await update.message.reply_text(f"💰 <b>User Balance</b>\n\n🆔 <code>{user_id}</code>\n🪙 <b>{balance:.3f} MC</b>", parse_mode="HTML")


async def set_price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 3:
        await update.message.reply_text("❌ <code>/setprice SERVER AMOUNT MC</code>", parse_mode="HTML")
        return
    server, amount = args[0], args[1]
    try:
        mc_price = float(args[2])
    except ValueError:
        await update.message.reply_text("❌ MC နံပါတ် ဖြစ်ရပါမယ်။")
        return
    set_manual_price(server, amount, mc_price)
    final_mc = mc_price * MC_PROFIT_MARGIN
    await update.message.reply_text(
        f"✅ <b>Price သတ်မှတ်ပြီး</b>\n\n🌍 {server}\n💎 {amount}\n💰 Final: <b>{final_mc:.3f} MC</b>",
        parse_mode="HTML",
    )


async def delete_price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("❌ <code>/delprice SERVER AMOUNT</code>", parse_mode="HTML")
        return
    delete_manual_price(args[0], args[1])
    await update.message.reply_text("✅ <b>Price ဖျက်ပြီး</b>", parse_mode="HTML")


async def list_prices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    server = args[0] if args else None
    rows = get_all_manual_prices(server)
    if not rows:
        await update.message.reply_text("📭 Price မရှိသေးပါ။")
        return
    lines = ["💰 <b>Manual Prices</b>\n━━━━━━━━━━━━━━━━━━━━"]
    current = None
    for srv, amt, mc in rows:
        if srv != current:
            lines.append(f"\n🌍 <b>{srv}</b>")
            current = srv
        lines.append(f"  💎 {amt} → <b>{mc * MC_PROFIT_MARGIN:.3f} MC</b>")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def add_product_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("❌ <code>/addproduct SERVER AMOUNT [SKU]</code>", parse_mode="HTML")
        return
    server, amount = args[0], args[1]
    sku = args[2] if len(args) > 2 else amount
    if add_manual_product(server, amount, sku):
        PRODUCT_CACHE[server] = []
        refresh_products(server=server, force=True)
        await update.message.reply_text(
            f"✅ <b>Product ထည့်ပြီး</b>\n\n🌍 {server}\n💎 {amount}\n🔗 <code>{sku}</code>",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text("❌ ထည့်လို့မရပါ။")


async def del_product_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("❌ <code>/delproduct SERVER AMOUNT</code>", parse_mode="HTML")
        return
    if delete_manual_product(args[0], args[1]):
        PRODUCT_CACHE[args[0]] = []
        refresh_products(server=args[0], force=True)
        await update.message.reply_text("✅ <b>Product ဖျက်ပြီး</b>", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ ဖျက်လို့မရပါ။")


async def list_products_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    server = args[0] if args else None
    rows = get_all_manual_products(server)
    if not rows:
        await update.message.reply_text("📭 Manual Product မရှိသေးပါ။")
        return
    lines = ["📦 <b>Manual Products</b>\n━━━━━━━━━━━━━━━━━━━━"]
    current = None
    for srv, amount, sku, dn in rows:
        if srv != current:
            lines.append(f"\n🌍 <b>{srv}</b>")
            current = srv
        lines.append(f"  💎 <b>{amount}</b> → <code>{sku}</code>")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""

    if data == "back:servers":
        await query.edit_message_text("🌍 Server ရွေးပါ။", reply_markup=server_keyboard())
        return

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
            text=f"↩️ Reply to <code>{user_id}</code>\n\nReply စာ ရိုက်ပါ။",
            parse_mode="HTML",
        )
        return

    if data.startswith("page:"):
        parts = data.split(":")
        server, page = parts[1], int(parts[2])
        total = len(get_unique_products(server))
        header = f"💎 <b>{html.escape(server)}</b>\n📦 {total} Products\n📄 Page {page + 1}"
        await query.edit_message_text(header, parse_mode="HTML", reply_markup=amount_keyboard(server, page=page))
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
                f"❌ <b>{server}</b>\n\nProduct မတွေ့ပါ။",
                parse_mode="HTML", reply_markup=server_keyboard(),
            )
            return
        total = len(get_unique_products(server))
        header = f"💎 <b>{html.escape(server)}</b>\n📦 {total} Products\n📄 Page 1"
        await query.edit_message_text(header, parse_mode="HTML", reply_markup=amount_keyboard(server, page=0))
        return

    if data.startswith("amount:"):
        parts = data.split(":")
        server, index = parts[1], int(parts[2])
        products = get_unique_products(server)
        if index < 0 or index >= len(products):
            await query.answer("❌ Product မတွေ့ပါ။", show_alert=True)
            return
        product = products[index]
        context.user_data["server"] = server
        context.user_data["product"] = product

        amount = product.get("display_name", product.get("amount", "?"))
        mc_price = get_mc_price(server, product.get("amount"), product)
        price_text = f"{mc_price:.3f} MC" if mc_price else "No Price"
        user_id = query.from_user.id
        user_balance = get_user_balance(user_id)

        if server == "Telegram Stars":
            prompt = "🎯 <b>Telegram Username</b> ထည့်ပါ။\n\nဥပမာ: <code>@username</code>"
        elif server == "Telegram Premium":
            prompt = "🎯 <b>Telegram Username</b> ထည့်ပါ။\n\nဥပမာ: <code>@username</code>"
        else:
            prompt = "🆔 <b>Player ID</b> ထည့်ပါ။\nဥပမာ: <code>12345678</code>"

        text = (
            "💎 <b>Selected</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🌍 Server: <b>{html.escape(server)}</b>\n"
            f"💎 Product: <b>{html.escape(str(amount))}</b>\n"
            f"🪙 Price: <b>{html.escape(price_text)}</b>\n\n"
            f"🪙 သင့် Balance: <b>{user_balance:.3f} MC</b>\n\n"
            f"{prompt}"
        )
        await query.edit_message_text(text, parse_mode="HTML")
        return


async def handle_deposit_callback(update, context):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Admin only", show_alert=True)
        return
    parts = (query.data or "").split(":")
    action, uid_text = parts[1], parts[2]
    try:
        user_id = int(uid_text)
    except ValueError:
        return
    if action == "approve":
        await query.answer("Admin က /addbalance ရိုက်ပါ။", show_alert=True)
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💡 <code>/addbalance {user_id} 300</code>",
            parse_mode="HTML",
        )
        return
    if action == "reject":
        await query.edit_message_caption(caption=(query.message.caption or "") + "\n\n<b>❌ REJECTED</b>", parse_mode="HTML")
        try:
            await context.bot.send_message(chat_id=user_id, text="❌ <b>Deposit ပယ်ဖျက်ခံရပါတယ်။</b>", parse_mode="HTML")
        except Exception as e:
            print("REJECT DM ERROR:", e)
        await query.answer("Rejected ❌")


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    data = query.data or ""
    if data.startswith("access:"):
        await handle_access_callback(update, context)
        return
    if data.startswith("deposit:"):
        await handle_deposit_callback(update, context)
        return
    if get_access_status(query.from_user.id) != "approved":
        await query.answer("🔐 Approval လိုအပ်ပါတယ်။", show_alert=True)
        return
    await callback_handler(update, context)


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


async def post_shutdown(application: Application):
    print("🛑 Bot shutting down...")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN မတွေ့ပါ။")

    if LICENSE_KEY:
        license_info = validate_license_key(LICENSE_KEY)
        if not license_info:
            print("❌ LICENSE_KEY မှားနေပါတယ်။")
            return
        try:
            expiry = datetime.strptime(license_info["expiry_date"], "%Y-%m-%d")
            if datetime.now() > expiry:
                print("❌ LICENSE_KEY သက်တမ်းကုန်သွားပါပြီ။")
                return
            print(f"✅ License Valid: {license_info['expiry_date']}")
        except Exception as e:
            print(f"❌ License Error: {e}")
            return

    init_access_db()
    init_balance_db()
    init_subscription_db()
    init_user_api_db()
    init_manual_price_db()
    init_manual_product_db()
    backup_databases()

    print("🤖 Starting...")
    print(f"🧪 Sandbox: {MELO_SANDBOX}")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("addbalance", add_balance_command))
    app.add_handler(CommandHandler("checkbalance", check_balance_command))
    app.add_handler(CommandHandler("setprice", set_price_command))
    app.add_handler(CommandHandler("delprice", delete_price_command))
    app.add_handler(CommandHandler("listprices", list_prices_command))
    app.add_handler(CommandHandler("addproduct", add_product_command))
    app.add_handler(CommandHandler("delproduct", del_product_command))
    app.add_handler(CommandHandler("listproducts", list_products_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("restore", restore_command))

    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_error_handler(error_handler)

    print("✅ Bot is running!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
