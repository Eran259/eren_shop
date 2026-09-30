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

# =========================================================
# CONFIG
# =========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MELO_API_KEY = os.getenv("MELO_API_KEY", "")
MELO_SECRET_KEY = os.getenv("MELO_SECRET_KEY", "")
MELO_BASE_URL = "https://api.melostore.id"

MELO_SANDBOX = os.getenv("MELO_SANDBOX", "true").lower() == "true"

LICENSE_KEY = os.getenv("LICENSE_KEY", "")
LICENSE_SECRET = "EREN_SHOP_SECRET_2026"

# =========================================================
# MC PRICE CONFIG
# =========================================================
MC_PROFIT_MARGIN = 1.20
MC_ALERT_THRESHOLD = 100

ADMIN_ID = 5698123475

ACCESS_DB = "access.db"

def init_access_db():
    conn = sqlite3.connect(ACCESS_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS bot_access (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
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
        username=excluded.username,
        first_name=excluded.first_name,
        status='pending',
        requested_at=CURRENT_TIMESTAMP
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

USER_BALANCE_DB = "user_balance.db"

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
        balance = balance + ?,
        updated_at = CURRENT_TIMESTAMP
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

SUBSCRIPTION_DB = "subscription.db"

def init_subscription_db():
    conn = sqlite3.connect(SUBSCRIPTION_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
        user_id INTEGER PRIMARY KEY,
        expiry_date TEXT,
        status TEXT DEFAULT 'active',
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
        ON CONFLICT(user_id) DO UPDATE SET
        expiry_date = ?,
        status = 'active'
    """, (int(user_id), expiry, expiry))
    conn.commit()
    conn.close()
    return expiry

def is_subscription_active(user_id):
    sub = get_subscription(user_id)
    if not sub:
        return False
    try:
        expiry = datetime.strptime(sub["expiry_date"], "%Y-%m-%d")
        return datetime.now() <= expiry and sub["status"] == "active"
    except Exception:
        return False

def generate_license_key(user_id, expiry_date):
    data = f"{user_id}|{expiry_date}"
    signature = hmac.new(
        LICENSE_SECRET.encode(),
        data.encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    key = base64.b64encode(f"{data}|{signature}".encode()).decode()
    return key

def validate_license_key(license_key):
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

USER_API_DB = "user_api.db"

def init_user_api_db():
    conn = sqlite3.connect(USER_API_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS user_api (
        user_id INTEGER PRIMARY KEY,
        api_key TEXT,
        secret_key TEXT,
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

def set_user_api(user_id, api_key, secret_key):
    conn = sqlite3.connect(USER_API_DB)
    conn.execute("""INSERT INTO user_api (user_id, api_key, secret_key, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
        api_key = ?,
        secret_key = ?,
        updated_at = CURRENT_TIMESTAMP
    """, (int(user_id), api_key, secret_key, api_key, secret_key))
    conn.commit()
    conn.close()

MANUAL_PRICE_DB = "manual_price.db"

def init_manual_price_db():
    conn = sqlite3.connect(MANUAL_PRICE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS manual_price (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server TEXT NOT NULL,
        amount TEXT NOT NULL,
        mc_price REAL NOT NULL,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(server, amount)
    )""")
    conn.commit()
    conn.close()

def get_manual_price(server, amount):
    conn = sqlite3.connect(MANUAL_PRICE_DB)
    row = conn.execute(
        "SELECT mc_price FROM manual_price WHERE server=? AND amount=?",
        (server, amount)
    ).fetchone()
    conn.close()
    if row:
        return {"mc_price": row[0]}
    return None

def set_manual_price(server, amount, mc_price):
    conn = sqlite3.connect(MANUAL_PRICE_DB)
    conn.execute("""INSERT INTO manual_price (server, amount, mc_price, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(server, amount) DO UPDATE SET
        mc_price = ?,
        updated_at = CURRENT_TIMESTAMP
    """, (server, amount, float(mc_price), float(mc_price)))
    conn.commit()
    conn.close()

def get_all_manual_prices(server=None):
    conn = sqlite3.connect(MANUAL_PRICE_DB)
    if server:
        rows = conn.execute(
            "SELECT server, amount, mc_price FROM manual_price WHERE server=? ORDER BY amount",
            (server,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT server, amount, mc_price FROM manual_price ORDER BY server, amount"
        ).fetchall()
    conn.close()
    return rows

def delete_manual_price(server, amount):
    conn = sqlite3.connect(MANUAL_PRICE_DB)
    conn.execute("DELETE FROM manual_price WHERE server=? AND amount=?", (server, amount))
    conn.commit()
    conn.close()

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
                chat_id=ADMIN_ID,
                text=admin_text,
                parse_mode="HTML",
                reply_markup=access_request_keyboard(user.id),
            )
            print(f"✅ Register Request Sent: {user.id} ({user.first_name})")
        except Exception as e:
            print("ACCESS REQUEST SEND ERROR:", e)

    if status == "rejected" and not force_request:
        msg = (
            "❌ <b>Access Denied</b>\n\n"
            "Admin က ဒီ Bot ကိုအသုံးပြုခွင့် မပေးသေးပါ။\n\n"
            "/start နှိပ်ပြီး Request ပြန်ပို့နိုင်ပါတယ်။"
        )
        if update.message:
            await update.message.reply_text(msg, parse_mode="HTML")
        return False

    if status == "pending":
        msg = (
            "⏳ <b>Access Pending</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "သင့် Request ကို Admin ဆီ ပို့ထားပါတယ်။\n"
            "Approve ဖြစ်တဲ့အခါ Bot ကို အသုံးပြုနိုင်ပါမယ်။"
        )
        if update.message:
            await update.message.reply_text(msg, parse_mode="HTML")
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
        await query.answer("Invalid request", show_alert=True)
        return True

    action, uid_text = parts[1], parts[2]
    try:
        user_id = int(uid_text)
    except ValueError:
        await query.answer("Invalid user ID", show_alert=True)
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
        await query.edit_message_text(
            (query.message.text or "") + f"\n\n<b>{label}</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass

    if status == "approved":
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "✅ <b>Access Approved!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    "✨ Eren's Diamond Bot ကို အသုံးပြုခွင့် ရပါပြီ။\n\n"
                    "/start နှိပ်ပြီး စတင်ပါ။"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            print("APPROVAL DM ERROR:", e)
        await query.answer("User approved ✅")
    else:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "❌ <b>Access Denied</b>\n\n"
                    "Admin က ဒီ Bot ကိုအသုံးပြုခွင့် မပေးသေးပါ။\n\n"
                    "/start နှိပ်ပြီး Request ပြန်ပို့နိုင်ပါတယ်။"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            print("REJECTION DM ERROR:", e)
        await query.answer("User rejected ❌")

    return True

MMK_PRICES = {
    "Global": {},
    "Malaysia": {},
    "Singapore": {},
    "Turkey": {},
    "Philippines": {},
    "Brazil": {},
}

PRODUCT_CACHE = {
    "Global": [],
    "Malaysia": [],
    "Singapore": [],
    "Turkey": [],
    "Philippines": [],
    "Brazil": [],
}
LAST_PRODUCTS_LOAD = 0
PRODUCT_CACHE_TTL = 300
PRODUCT_LOAD_LOCK = threading.Lock()
PRODUCT_LAST_ERROR = {}


def api_headers(user_id=None):
    if user_id:
        user_api = get_user_api(user_id)
        if user_api:
            return {
                "X-API-Key": user_api["api_key"],
                "X-Secret-Key": user_api["secret_key"],
            }
    return {
        "X-API-Key": MELO_API_KEY,
        "X-Secret-Key": MELO_SECRET_KEY,
    }


def api_get(path, params=None, user_id=None, retries=3):
    url = MELO_BASE_URL + path
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=api_headers(user_id), params=params, timeout=60)
            if response.status_code >= 400:
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                if "text/html" in response.headers.get("Content-Type", ""):
                    return None, f"HTTP {response.status_code} - API Error"
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
                if "text/html" in response.headers.get("Content-Type", ""):
                    return None, f"HTTP {response.status_code} - API Error"
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


def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


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

    print(f"🏷️ Brand Map for {server}: {brand_map}")
    print(f"📦 API returned {len(rows)} products for {server}")

    products = []
    for product in rows:
        brand_id = str(product.get("brand_id", ""))
        brand_name = brand_map.get(brand_id, "")
        name_text = f"{brand_name} {product.get('name', '')} {product.get('type_name', '')}".lower()

        if "ml diamonds" not in name_text and "mobile legends" not in name_text:
            continue

        product_server = None
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

        if product_server != server:
            continue

        # ✅ Product Name ကနေ amount ဆွဲထုတ် (ဦးစားပေး)
        sku = str(product.get("sku_code", ""))
        name = str(product.get("name", ""))

        # Double Diamond (50+50, 156+16) ကို အရင်စစ်
        dd_match = re.search(r"(\d+)\s*\+\s*(\d+)\s*Diamonds?", name, re.IGNORECASE)
        if dd_match:
            a, b = dd_match.group(1), dd_match.group(2)
            amount = f"{a}+{b}"
        else:
            # Name ကနေ ရိုးရိုး နံပါတ် ဆွဲထုတ် (86 Diamonds → 86)
            name_match = re.search(r"(\d+)\s*Diamonds?", name, re.IGNORECASE)
            if name_match:
                amount = name_match.group(1)
            else:
                # SKU ရဲ့ အဆုံးက နံပါတ်ကို ဆွဲထုတ်
                sku_match = re.search(r"(\d+)$", sku)
                if sku_match:
                    amount = sku_match.group(1)
                else:
                    # Weekly Pass, Twilight Pass လိုမျိုး
                    amount = re.sub(r"(?i)\bmobile\s*legends?\b", "", name)
                    amount = re.sub(r"(?i)\bdiamonds?\b", "", amount)
                    amount = amount.replace(" ", "").strip() or "unknown"

        item = dict(product)
        item["server"] = server
        item["amount"] = amount
        item["sku_code"] = sku
        products.append(item)

    print(f"✅ Filtered {len(products)} MLBB products for {server}")
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
                print(f"Pricelist error [{name}]: {error}")
                continue
            PRODUCT_CACHE[name] = products
            print(f"Products cached [{name}]: {len(products)}")
        LAST_PRODUCTS_LOAD = now
    return PRODUCT_CACHE


def ensure_server_products(server):
    now = time.time()
    if PRODUCT_CACHE.get(server) and (now - LAST_PRODUCTS_LOAD) < PRODUCT_CACHE_TTL:
        return PRODUCT_CACHE[server], None
    refresh_products(server=server, force=True)
    products = PRODUCT_CACHE.get(server, [])
    return products, PRODUCT_LAST_ERROR.get(server) if not products else None


def get_mc_price(server, amount, product=None):
    manual = get_manual_price(server, amount)
    if manual:
        base_mc = manual["mc_price"]
        final_mc = base_mc * MC_PROFIT_MARGIN
        return round(final_mc, 3)
    return None


def format_mc(price):
    if price is None:
        return "Price မသတ်မှတ်ရသေး"
    try:
        return f"{float(price):.3f} MC"
    except Exception:
        return f"{price} MC"


async def check_mc_balance_alert(context, current_mc):
    if current_mc < MC_ALERT_THRESHOLD:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "⚠️ <b>MC BALANCE ALERT!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🪙 လက်ရှိ MC Balance: <b>{current_mc:,.2f} MC</b>\n"
                    f"⚠️ သတ်မှတ်ထားတဲ့ ပမာဏ ({MC_ALERT_THRESHOLD} MC) အောက် ရောက်နေပါတယ်။\n\n"
                    "💳 Melostore MC Balance ဖြည့်ဖို့ လိုအပ်ပါတယ်။"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            print("MC ALERT ERROR:", e)

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["💎 MLBB Diamonds", "🔍 Check ML ID"],
            ["💰 My Balance", "💳 Deposit"],
            ["📞 Contact Admin", "📊 Admin Panel"],
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
        ]
    )


def get_unique_products(server):
    products = PRODUCT_CACHE.get(server, [])
    seen_amounts = set()
    unique_products = []
    for product in products:
        amount = product.get("amount", "?")
        if amount in seen_amounts:
            continue
        seen_amounts.add(amount)
        unique_products.append(product)
    return unique_products


def amount_keyboard(server, is_admin=False, page=0, per_page=15):
    unique_products = get_unique_products(server)

    total = len(unique_products)
    start = page * per_page
    end = start + per_page
    page_items = unique_products[start:end]

    buttons = []
    row = []

    for index, product in enumerate(page_items):
        amount = product.get("amount", "?")
        display_amount = format_amount_for_display(amount)
        mc_price = get_mc_price(server, amount, product)

        if mc_price is None:
            price_text = "No Price"
        else:
            price_text = format_mc(mc_price)

        button_text = f"💎 {display_amount} • {price_text}"
        real_index = start + index
        button = InlineKeyboardButton(button_text, callback_data=f"amount:{server}:{real_index}")
        row.append(button)
        if len(row) == 1:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

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
            "💎 <b>Eren's Diamond Bot</b> မှ ကြိုဆိုပါတယ်။\n\n"
            f"👑 <b>Status:</b> Admin\n"
            f"🪙 <b>Balance:</b> {balance:.3f} MC\n\n"
            "🛒 <b>Service များ</b>\n"
            "💎 MLBB Diamonds\n"
            "🔍 Check ML ID\n"
            "💰 My Balance\n"
            "💳 Deposit\n"
            "📞 Contact Admin\n\n"
            "⚡ Powered by Eren"
        )
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_keyboard())
        return

    status = get_access_status(user_id)

    if status == "approved":
        status_text = "✅ <b>Active</b>"
        footer = (
            "🛒 <b>Service များ</b>\n"
            "💎 MLBB Diamonds\n"
            "🔍 Check ML ID\n"
            "💰 My Balance\n"
            "💳 Deposit\n"
            "📞 Contact Admin"
        )
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
        f"{footer}\n\n"
        "⚡ Powered by Eren"
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
            text = (
                "💰 <b>Balance</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🪙 <b>User Balance (Your MC)</b>\n"
                f"<b>{user_balance:.3f} MC</b>\n\n"
                f"🪙 <b>Melostore MC Balance</b>\n"
                f"<b>{mc_balance:,.2f} MC</b>\n\n"
                f"💵 USD Value\n"
                f"<b>${usd:,.2f}</b>\n\n"
                "💳 ငွေဖြည့်ချင်ရင် <b>Deposit</b> ကို နှိပ်ပါ။"
            )
        else:
            text = (
                "💰 <b>Balance</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🪙 <b>User Balance (Your MC)</b>\n"
                f"<b>{user_balance:.3f} MC</b>\n\n"
                f"🪙 <b>Melostore MC Balance</b>\n"
                f"<i>Error: {html.escape(str(error)[:50])}</i>"
            )
    else:
        text = (
            "💰 <b>သင့်ရဲ့ Balance</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🪙 Balance: <b>{user_balance:.3f} MC</b>\n\n"
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
        "📊 <b>Admin Panel</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🪙 Melostore MC Balance: <b>{balance:,.2f} MC</b>\n"
        f"💵 USD Value: <b>${usd:,.2f}</b>\n\n"
        "💡 <b>Balance Commands</b>\n"
        "/addbalance USER_ID MC — User MC Balance ဖြည့်\n"
        "/checkbalance USER_ID — User MC Balance ကြည့်\n"
        "/addsub USER_ID — Subscription ဖြည့်\n"
        "/checksub USER_ID — Subscription ကြည့်\n\n"
        "💰 <b>Price Commands</b>\n"
        "/setprice SERVER AMOUNT MC — MC ဈေးသတ်မှတ်\n"
        "/delprice SERVER AMOUNT — MC ဈေးဖျက်\n"
        "/listprices SERVER — MC ဈေးစာရင်း\n\n"
        f"📐 <b>Formula:</b> Final MC = Base MC × {MC_PROFIT_MARGIN}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def show_deposit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💳 <b>ငွေဖြည့်ရန် (Deposit)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 <b>ငွေလွှဲရန် နံပါတ်များ</b>\n\n"
        "💙 <b>K Pay</b>\n"
        "<code>09766605879</code>\n"
        "👤 TNS\n\n"
        "💛 <b>AYA Pay</b>\n"
        "<code>09678664100</code>\n"
        "👤 HHS\n\n"
        "💚 <b>UAB Pay</b>\n"
        "<code>09425160424</code>\n"
        "👤 TNS\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📸 ငွေလွှဲပြီးရင် <b>Screenshot</b> ကို ဒီ Chat မှာ ပို့ပါ။\n"
        "Admin က စစ်ဆေးပြီး MC Balance ဖြည့်ပေးပါမယ်။"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def open_mlbb(update: Update):
    await update.message.reply_text(
        "💎 <b>MLBB Diamond Top-Up</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌍 Server ရွေးပါ။",
        parse_mode="HTML",
        reply_markup=server_keyboard(),
    )


async def show_api_status(update: Update):
    data, error = get_profile()
    if error:
        await update.message.reply_text(
            f"🔴 <b>API Offline / Error</b>\n\n{html.escape(str(error))}",
            parse_mode="HTML",
        )
        return
    info = data.get("data", {})
    sandbox = info.get("is_sandbox_mode", False)
    status = "🧪 Sandbox Mode" if sandbox else "🟢 Production Mode"
    text = (
        "🔌 <b>Melostore API Status</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🟢 Connection: <b>Connected</b>\n"
        f"🏷️ Tier: <b>Eren's API</b>\n"
        f"⚙️ Mode: <b>{status}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ Powered by Eren"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def start_check_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["state"] = "check_id_player"
    text = (
        "🔍 <b>MLBB ID Checker</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🆔 <b>Player ID</b> ထည့်ပါ။\n\n"
        "ဥပမာ:\n<code>12345678</code>\n\n"
        "❌ Cancel လုပ်ချင်ရင် /start"
    )
    await update.message.reply_text(text, parse_mode="HTML")


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
        await update.message.reply_text(
            "❌ Zone ID မှာ နံပါတ်ပဲ ထည့်ပါ။\n\nဥပမာ: <code>2039</code>",
            parse_mode="HTML",
        )
        return

    await update.message.reply_text("🔍 <b>Checking MLBB ID...</b>\nခဏစောင့်ပါ...", parse_mode="HTML")
    data, error = check_ml_nickname(player_id, zone_id)

    if error:
        await update.message.reply_text(
            f"❌ <b>Check ID Failed</b>\n\n{html.escape(str(error))}",
            parse_mode="HTML",
        )
        context.user_data.clear()
        return

    info = data.get("data", {})
    nickname = info.get("username") or info.get("nickname") or info.get("name") or "-"
    region = info.get("region") or info.get("region_name") or "-"

    text = (
        "🔍 <b>MLBB ID Result</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Nickname: <b>{html.escape(str(nickname))}</b>\n"
        f"🆔 Player ID: <code>{html.escape(str(player_id))}</code>\n"
        f"🌐 Zone ID: <code>{html.escape(str(zone_id))}</code>\n"
        f"🌍 Region: <b>{html.escape(str(region))}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ <b>ID Verified</b>"
    )
    context.user_data.clear()
    await update.message.reply_text(text, parse_mode="HTML")


async def process_order_player_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    player_id = update.message.text.strip()
    if not player_id.isdigit():
        await update.message.reply_text("❌ Player ID မှာ နံပါတ်ပဲ ထည့်ပါ။")
        return
    context.user_data["player_id"] = player_id
    context.user_data["state"] = "order_zone_id"
    await update.message.reply_text(
        "🌐 <b>Zone ID</b> ထည့်ပါ။\n\nဥပမာ: <code>2039</code>",
        parse_mode="HTML",
    )


async def process_order_zone_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    zone_id = update.message.text.strip()
    if not zone_id.isdigit():
        await update.message.reply_text("❌ Zone ID မှာ နံပါတ်ပဲ ထည့်ပါ။")
        return
    player_id = context.user_data.get("player_id")
    context.user_data["zone_id"] = zone_id
    await update.message.reply_text("🔍 <b>Checking Nickname...</b>\nခဏစောင့်ပါ...", parse_mode="HTML")

    data, error = check_ml_nickname(player_id, zone_id)
    if error:
        await update.message.reply_text(
            f"❌ <b>ID Check Failed</b>\n\n{html.escape(str(error))}",
            parse_mode="HTML",
        )
        context.user_data.clear()
        return

    info = data.get("data", {})
    nickname = info.get("username") or info.get("nickname") or info.get("name") or "-"
    context.user_data["nickname"] = nickname

    server = context.user_data.get("server", "Global")
    product = context.user_data.get("product", {})
    amount = product.get("amount", "?")
    display_amount = format_amount_for_display(amount)
    mc_price = get_mc_price(server, amount, product)
    price_text = format_mc(mc_price)

    user_id = update.effective_user.id
    user_balance = get_user_balance(user_id)
    balance_warning = ""
    if mc_price and user_balance < mc_price:
        balance_warning = (
            f"\n⚠️ <b>MC Balance မလုံလောက်ပါ။</b>\n"
            f"🪙 လက်ရှိ: <b>{user_balance:.3f} MC</b>\n"
            f"💳 Deposit လုပ်ဖို့ လိုအပ်ပါတယ်။\n"
        )

    text = (
        "🔍 <b>Account Verified</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Nickname: <b>{html.escape(str(nickname))}</b>\n"
        f"🆔 Player ID: <code>{html.escape(str(player_id))}</code>\n"
        f"🌐 Zone ID: <code>{html.escape(str(zone_id))}</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🌍 Server: <b>{html.escape(server)}</b>\n"
        f"💎 Diamond: <b>{html.escape(display_amount)}</b>\n"
        f"🪙 MC Price: <b>{html.escape(price_text)}</b>\n\n"
        f"🪙 သင့် Balance: <b>{user_balance:.3f} MC</b>\n"
        f"{balance_warning}\n"
        "အချက်အလက်မှန်ကန်ရင် Order တင်နိုင်ပါတယ်။"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm Order", callback_data="order:confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="order:cancel"),
        ]
    ])
    context.user_data["state"] = "order_confirm"
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


def create_transaction(product, player_id, zone_id):
    sku = product.get("sku_code")
    buyer_trx_id = "EREN-" + uuid.uuid4().hex[:20].upper()
    payload = {
        "sku_code": sku,
        "customer_target": str(player_id),
        "customer_target_zone": str(zone_id),
        "buyer_trx_id": buyer_trx_id,
        "sandbox_mode": MELO_SANDBOX,
    }
    return api_post("/api/v1/h2h/transaction", payload)


async def confirm_order(query, context):
    server = context.user_data.get("server")
    product = context.user_data.get("product")
    player_id = context.user_data.get("player_id")
    zone_id = context.user_data.get("zone_id")
    nickname = context.user_data.get("nickname", "-")
    user_id = query.from_user.id

    if not product or not player_id or not zone_id:
        await query.edit_message_text("❌ Order information မပြည့်စုံပါ။\n/start နဲ့ ပြန်စပါ။")
        context.user_data.clear()
        return

    amount = product.get("amount", "?")
    display_amount = format_amount_for_display(amount)
    mc_price = get_mc_price(server, amount, product)

    if mc_price is None:
        await query.edit_message_text("⚠️ <b>Price မသတ်မှတ်ရသေးပါ။</b>", parse_mode="HTML")
        context.user_data.clear()
        return

    user_balance = get_user_balance(user_id)
    if user_balance < mc_price:
        await query.edit_message_text(
            f"❌ <b>MC Balance မလုံလောက်ပါ။</b>\n\n"
            f"🪙 လက်ရှိ: <b>{user_balance:.3f} MC</b>\n"
            f"💰 လိုအပ်: <b>{mc_price:.3f} MC</b>\n\n"
            f"💳 Deposit လုပ်ပြီးမှ Order တင်ပါ။",
            parse_mode="HTML",
        )
        context.user_data.clear()
        return

    await query.edit_message_text("🛒 <b>Creating Order...</b>\nခဏစောင့်ပါ...", parse_mode="HTML")
    data, error = create_transaction(product, player_id, zone_id)

    if error:
        await query.edit_message_text(
            f"❌ <b>Order Failed</b>\n\n{html.escape(str(error))}",
            parse_mode="HTML",
        )
        context.user_data.clear()
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
        "🛒 <b>Order Created</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Nickname: <b>{html.escape(str(nickname))}</b>\n"
        f"🆔 Player ID: <code>{html.escape(str(player_id))}</code>\n"
        f"🌐 Zone ID: <code>{html.escape(str(zone_id))}</code>\n\n"
        f"🌍 Server: <b>{html.escape(str(server))}</b>\n"
        f"💎 Diamond: <b>{html.escape(display_amount)}</b>\n"
        f"🪙 MC Price: <b>{mc_price:.3f} MC</b>\n\n"
        f"🆔 Transaction: <code>{html.escape(str(transaction_id))}</code>\n"
        f"⏳ Status: <b>{html.escape(str(status).upper())}</b>\n\n"
        f"🪙 လက်ကျန် MC: <b>{new_balance:.3f} MC</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ Powered by Eren"
    )
    await query.edit_message_text(text, parse_mode="HTML")

    try:
        user_obj = query.from_user
        username = f"@{user_obj.username}" if user_obj.username else "—"
        first_name = user_obj.first_name or "User"

        alarm_text = (
            "🔔 <b>NEW DIAMOND ORDER!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Name: <b>{html.escape(first_name)}</b>\n"
            f"🔗 Username: <b>{html.escape(username)}</b>\n"
            f"🆔 User ID: <code>{user_id}</code>\n\n"
            f"🌍 Server: <b>{html.escape(str(server))}</b>\n"
            f"👤 Nickname: <b>{html.escape(str(nickname))}</b>\n"
            f"🆔 Player ID: <code>{html.escape(str(player_id))}</code>\n"
            f"🌐 Zone ID: <code>{html.escape(str(zone_id))}</code>\n\n"
            f"💎 Diamond: <b>{html.escape(display_amount)}</b>\n"
            f"🪙 MC Price: <b>{mc_price:.3f} MC</b>\n\n"
            f"🧾 Trx ID: <code>{html.escape(str(transaction_id))}</code>\n"
            f"⏳ Status: <b>{html.escape(str(status).upper())}</b>\n"
            f"⏰ Time: <code>{order_time}</code>"
        )

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=alarm_text,
            parse_mode="HTML",
        )
    except Exception as e:
        print("ORDER ALARM ERROR:", e)

    context.user_data.clear()

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""

    if data == "back:servers":
        await query.edit_message_text(
            "💎 <b>MLBB Diamond Top-Up</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🌍 Server ရွေးပါ။",
            parse_mode="HTML",
            reply_markup=server_keyboard(),
        )
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

        await query.answer("Reply ရိုက်ပါ", show_alert=True)
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"↩️ <b>Reply to User</b> <code>{user_id}</code>\n\n"
                "Reply စာကို ရိုက်ထည့်ပါ။\n\n"
                "❌ Cancel လုပ်ချင်ရင် /start"
            ),
            parse_mode="HTML",
        )
        return

    if data.startswith("page:"):
        parts = data.split(":")
        if len(parts) != 3:
            return
        server = parts[1]
        try:
            page = int(parts[2])
        except Exception:
            return

        is_admin = (query.from_user.id == ADMIN_ID)
        total = len(get_unique_products(server))

        if is_admin:
            header = (
                f"💎 <b>{html.escape(server)} Server</b> (Admin View)\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📦 {total} Packages Available\n\n"
                f"📄 Page {page + 1}\n\n"
                "👇 အောက်က Button ကနေ Amount ရွေးပါ။"
            )
        else:
            header = (
                f"💎 <b>{html.escape(server)} Server</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📦 {total} Packages Available\n\n"
                f"📄 Page {page + 1}\n\n"
                "👇 အောက်က Button ကနေ Amount ရွေးပါ။"
            )

        await query.edit_message_text(
            header,
            parse_mode="HTML",
            reply_markup=amount_keyboard(server, is_admin=is_admin, page=page),
        )
        return

    if data.startswith("server:"):
        server = data.split(":", 1)[1]
        if server not in PRODUCT_CACHE:
            await query.answer("❌ Invalid server", show_alert=True)
            return

        if query.from_user.id != ADMIN_ID:
            bal_data, bal_error = get_balance()
            if not bal_error:
                bal_info = bal_data.get("data", {})
                current_mc = bal_info.get("h2h_balance", 0)
                if current_mc < MC_ALERT_THRESHOLD:
                    await check_mc_balance_alert(context, current_mc)
                    await query.edit_message_text(
                        "⚠️ <b>Out of Stock</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━\n\n"
                        "လက်ရှိ Diamond ပမာဏ ကုန်ဆုံးနေပါတယ်။\n"
                        "ခဏနေမှ ပြန်လာကြည့်ပါ။",
                        parse_mode="HTML",
                        reply_markup=server_keyboard(),
                    )
                    return

        await query.edit_message_text("⏳ <b>Loading Diamond Products...</b>\nခဏစောင့်ပါ...", parse_mode="HTML")
        products, load_error = ensure_server_products(server)

        if not products:
            error_msg = str(load_error)[:150] if load_error else "Pricelist empty ဖြစ်နေပါတယ်။"
            await query.edit_message_text(
                f"❌ <b>{html.escape(server)} Server</b>\n\n"
                "ဒီ server အတွက် MLBB product မတွေ့ပါ။\n\n"
                f"API: {html.escape(error_msg)}",
                parse_mode="HTML",
                reply_markup=server_keyboard(),
            )
            return

        is_admin = (query.from_user.id == ADMIN_ID)
        total = len(get_unique_products(server))

        if is_admin:
            header = (
                f"💎 <b>{html.escape(server)} Server</b> (Admin View)\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📦 {total} Packages Available\n\n"
                "📄 Page 1\n\n"
                "👇 အောက်က Button ကနေ Amount ရွေးပါ။"
            )
        else:
            header = (
                f"💎 <b>{html.escape(server)} Server</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📦 {total} Packages Available\n\n"
                "📄 Page 1\n\n"
                "👇 အောက်က Button ကနေ Amount ရွေးပါ။"
            )

        await query.edit_message_text(
            header,
            parse_mode="HTML",
            reply_markup=amount_keyboard(server, is_admin=is_admin, page=0),
        )
        return

    if data.startswith("amount:"):
        parts = data.split(":")
        if len(parts) != 3:
            return
        server = parts[1]
        try:
            index = int(parts[2])
        except Exception:
            return

        products = get_unique_products(server)

        if index < 0 or index >= len(products):
            await query.answer("❌ Product မတွေ့ပါ။", show_alert=True)
            return

        product = products[index]
        context.user_data["server"] = server
        context.user_data["product"] = product
        amount = product.get("amount", "?")
        display_amount = format_amount_for_display(amount)
        mc_price = get_mc_price(server, amount, product)
        sku = product.get("sku_code", "")
        context.user_data["sku"] = sku
        price_text = format_mc(mc_price)

        user_id = query.from_user.id
        user_balance = get_user_balance(user_id)

        text = (
            "💎 <b>Selected Product</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🌍 Server: <b>{html.escape(server)}</b>\n"
            f"💎 Amount: <b>{html.escape(display_amount)}</b>\n"
            f"🪙 MC Price: <b>{html.escape(price_text)}</b>\n\n"
            f"🪙 သင့် Balance: <b>{user_balance:.3f} MC</b>\n\n"
            "🆔 <b>Player ID</b> ထည့်ပါ။\n"
            "ဥပမာ: <code>12345678</code>"
        )

        context.user_data["state"] = "order_player_id"
        await query.edit_message_text(text, parse_mode="HTML")
        return


async def handle_callback_actions(update, context):
    query = update.callback_query
    data = query.data or ""

    if data == "order:confirm":
        await query.answer("Order တင်နေပါတယ်...")
        await confirm_order(query, context)
        return True

    if data == "order:cancel":
        context.user_data.clear()
        await query.edit_message_text(
            "❌ <b>Order Cancelled</b>\n\n/start နဲ့ Main Menu ပြန်သွားနိုင်ပါတယ်။",
            parse_mode="HTML",
        )
        return True

    return False


async def handle_deposit_callback(update, context):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Admin only", show_alert=True)
        return

    parts = (query.data or "").split(":")
    if len(parts) != 3:
        return
    action, uid_text = parts[1], parts[2]
    try:
        user_id = int(uid_text)
    except ValueError:
        return

    if action == "approve":
        await query.answer("Admin က /addbalance ရိုက်ပြီး ဖြည့်ပါ။", show_alert=True)
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"💡 <b>MC Balance ဖြည့်ရန် Command</b>\n\n"
                f"<code>/addbalance {user_id} 300</code>\n\n"
                f"(300 နေရာမှာ ဖြည့်ချင်တဲ့ MC ပမာဏ ထည့်ပါ)"
            ),
            parse_mode="HTML",
        )
        return

    if action == "reject":
        await query.edit_message_caption(
            caption=(query.message.caption or "") + "\n\n<b>❌ REJECTED</b>",
            parse_mode="HTML",
        )
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ <b>Deposit ပယ်ဖျက်ခံရပါတယ်။</b>\n\nScreenshot မှာ မှားယွင်းနေပါတယ်။ ပြန်ပို့ပါ။",
                parse_mode="HTML",
            )
        except Exception as e:
            print("REJECT DM ERROR:", e)
        await query.answer("Rejected ❌")
        return


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
        await query.answer("🔐 Admin approval လိုအပ်ပါတယ်။", show_alert=True)
        return

    if data.startswith("order:"):
        handled = await handle_callback_actions(update, context)
        if handled:
            return

    await callback_handler(update, context)

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo:
        return

    user = update.effective_user
    file_id = update.message.photo[-1].file_id

    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=file_id,
            caption=(
                "💳 <b>NEW DEPOSIT REQUEST</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 Name: <b>{html.escape(user.first_name or '—')}</b>\n"
                f"🔗 Username: @{user.username or '—'}\n"
                f"🆔 User ID: <code>{user.id}</code>\n\n"
                "⚠️ ဒီ Screenshot ကို စစ်ပြီး MC Balance ဖြည့်ပေးပါ။"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ ဖြည့်မယ်", callback_data=f"deposit:approve:{user.id}"),
                InlineKeyboardButton("❌ ပယ်ဖျက်", callback_data=f"deposit:reject:{user.id}"),
            ]]),
        )
        await update.message.reply_text(
            "✅ <b>Screenshot ရပါပြီ။</b>\n\n"
            "Admin က စစ်ဆေးပြီး MC Balance ဖြည့်ပေးပါမယ်။\n"
            "ခဏစောင့်ပါ။"
        )
    except Exception as e:
        print("DEPOSIT SEND ERROR:", e)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not await request_access(update, context):
        return

    text = update.message.text.strip()

    if text == "💎 MLBB Diamonds":
        await open_mlbb(update)
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
            "📞 <b>Contact Admin</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Admin ဆီ ပို့ချင်တဲ့ စာကို ရိုက်ထည့်ပါ။\n\n"
            "❌ Cancel လုပ်ချင်ရင် /start",
            parse_mode="HTML",
        )
        return
    if text == "📊 Admin Panel":
        await show_admin_panel(update, context)
        return
    if text == "🔌 API Status":
        if update.effective_user.id == ADMIN_ID:
            await show_api_status(update)
        else:
            await update.message.reply_text("❌ Admin only")
        return

    state = context.user_data.get("state")

    if state == "check_id_player":
        if not text.isdigit():
            await update.message.reply_text("❌ Player ID မှာ နံပါတ်ပဲ ထည့်ပါ။")
            return
        context.user_data["check_player_id"] = text
        context.user_data["state"] = "check_id_zone"
        await update.message.reply_text(
            "🌐 <b>Zone ID</b> ထည့်ပါ။\n\nဥပမာ: <code>2039</code>",
            parse_mode="HTML",
        )
        return

    if state == "check_id_zone":
        await process_check_id(update, context)
        return

    if state == "order_player_id":
        await process_order_player_id(update, context)
        return

    if state == "order_zone_id":
        await process_order_zone_id(update, context)
        return

    if state == "contact_admin":
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "User"
        username = f"@{update.effective_user.username}" if update.effective_user.username else "—"

        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "📞 <b>NEW USER MESSAGE</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"👤 Name: <b>{html.escape(user_name)}</b>\n"
                    f"🔗 Username: <b>{html.escape(username)}</b>\n"
                    f"🆔 User ID: <code>{user_id}</code>\n\n"
                    f"💬 <b>Message:</b>\n"
                    f"{html.escape(text)}"
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Reply", callback_data=f"reply:{user_id}"),
                ]]),
            )
            await update.message.reply_text(
                "✅ <b>Message ပို့ပြီးပါပြီ။</b>\n\n"
                "Admin က ပြန်ဖြေပါမယ်။",
                parse_mode="HTML",
                reply_markup=main_keyboard(),
            )
        except Exception as e:
            print("CONTACT SEND ERROR:", e)
            await update.message.reply_text("❌ Message ပို့လို့မရပါ။ နောက်မှ ပြန်စမ်းပါ။")

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
                text=(
                    "📩 <b>Admin Reply</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{html.escape(text)}"
                ),
                parse_mode="HTML",
                reply_markup=main_keyboard(),
            )
            await update.message.reply_text(
                "✅ <b>Reply ပို့ပြီးပါပြီ။</b>",
                reply_markup=main_keyboard(),
            )
        except Exception as e:
            print("REPLY SEND ERROR:", e)
            await update.message.reply_text("❌ Reply ပို့လို့မရပါ။")

        context.user_data.clear()
        return

    await update.message.reply_text("❓ Menu ကနေရွေးပေးပါ။", reply_markup=main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await request_access(update, context):
        return
    text = (
        "📖 <b>Help</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💎 MLBB Diamonds — Diamond Top-Up\n"
        "🔍 Check ML ID — Nickname စစ်ရန်\n"
        "💰 My Balance — User MC Balance\n"
        "💳 Deposit — ငွေဖြည့်ရန်\n"
        "📞 Contact Admin — Admin ဆီ စာပို့ရန်\n"
        "📊 Admin Panel — Admin Commands\n\n"
        "/start — Main Menu"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_keyboard())


async def add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "❌ အသုံးပြုနည်း: <code>/addbalance USER_ID MC_AMOUNT</code>\n"
            "ဥပမာ: <code>/addbalance 7738726467 300</code>",
            parse_mode="HTML",
        )
        return
    try:
        user_id = int(args[0])
        amount = float(args[1])
    except ValueError:
        await update.message.reply_text("❌ User ID နဲ့ Amount က နံပါတ် ဖြစ်ရပါမယ်။")
        return

    add_user_balance(user_id, amount)
    new_balance = get_user_balance(user_id)

    await update.message.reply_text(
        f"✅ <b>User MC Balance ဖြည့်ပြီးပါပြီ။</b>\n\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"🪙 ဖြည့် MC: <b>{amount:.3f} MC</b>\n"
        f"🪙 လက်ကျန်: <b>{new_balance:.3f} MC</b>",
        parse_mode="HTML",
    )

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ <b>MC Balance ဖြည့်ပြီးပါပြီ။</b>\n\n"
                f"🪙 ဖြည့် MC: <b>{amount:.3f} MC</b>\n"
                f"🪙 လက်ကျန်: <b>{new_balance:.3f} MC</b>\n\n"
                "အခု Diamond ဝယ်လို့ရပါပြီ။"
            ),
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
    except Exception as e:
        print("BALANCE NOTIFY ERROR:", e)


async def check_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "❌ အသုံးပြုနည်း: <code>/checkbalance USER_ID</code>",
            parse_mode="HTML",
        )
        return
    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ User ID က နံပါတ် ဖြစ်ရပါမယ်။")
        return

    balance = get_user_balance(user_id)
    await update.message.reply_text(
        f"💰 <b>User MC Balance</b>\n\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"🪙 Balance: <b>{balance:.3f} MC</b>",
        parse_mode="HTML",
    )


async def add_subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "❌ အသုံးပြုနည်း: <code>/addsub USER_ID</code>\n"
            "ဥပမာ: <code>/addsub 7738726467</code>\n\n"
            "(30 ရက် သက်တမ်း သတ်မှတ်ပေးပါမယ်)",
            parse_mode="HTML",
        )
        return
    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ User ID က နံပါတ် ဖြစ်ရပါမယ်။")
        return

    expiry = set_subscription(user_id, days=30)
    await update.message.reply_text(
        f"✅ <b>Subscription သတ်မှတ်ပြီးပါပြီ။</b>\n\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"📅 သက်တမ်းကုန်ဆုံးရက်: <b>{expiry}</b>",
        parse_mode="HTML",
    )
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ <b>Bot အသုံးပြုခွင့် ရပါပြီ။</b>\n\n"
                f"📅 သက်တမ်းကုန်ဆုံးရက်: <b>{expiry}</b>\n\n"
                "🛒 <b>Service များ</b>\n"
                "💎 MLBB Diamonds\n"
                "🔍 Check ML ID\n"
                "💰 My Balance\n"
                "💳 Deposit\n"
                "📞 Contact Admin\n\n"
                "👇 အောက်က Button ကနေ ရွေးပါ။"
            ),
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
    except Exception as e:
        print("SUB NOTIFY ERROR:", e)


async def check_subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "❌ အသုံးပြုနည်း: <code>/checksub USER_ID</code>",
            parse_mode="HTML",
        )
        return
    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ User ID က နံပါတ် ဖြစ်ရပါမယ်။")
        return

    sub = get_subscription(user_id)
    if not sub:
        await update.message.reply_text(
            f"❌ User ID <code>{user_id}</code> အတွက် Subscription မရှိပါ။",
            parse_mode="HTML",
        )
        return

    await update.message.reply_text(
        f"📋 <b>Subscription Info</b>\n\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"📅 Expiry: <b>{sub['expiry_date']}</b>\n"
        f"📌 Status: <b>{sub['status']}</b>\n"
        f"✅ Active: <b>{is_subscription_active(user_id)}</b>",
        parse_mode="HTML",
    )


async def set_price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 3:
        await update.message.reply_text(
            "❌ အသုံးပြုနည်း: <code>/setprice SERVER AMOUNT MC</code>\n\n"
            "ဥပမာ: <code>/setprice Global 86 1.660</code>\n"
            "ဥပမာ: <code>/setprice Global 50+50 13.865</code>",
            parse_mode="HTML",
        )
        return

    server = args[0]
    amount = args[1]
    try:
        mc_price = float(args[2])
    except ValueError:
        await update.message.reply_text("❌ MC က နံပါတ် ဖြစ်ရပါမယ်။")
        return

    valid_servers = ["Global", "Malaysia", "Singapore", "Turkey", "Philippines", "Brazil"]
    if server not in valid_servers:
        await update.message.reply_text(f"❌ Server မှားနေတယ်။ ရွေးနိုင်တာ: {', '.join(valid_servers)}")
        return

    set_manual_price(server, amount, mc_price)

    final_mc = mc_price * MC_PROFIT_MARGIN

    await update.message.reply_text(
        f"✅ <b>Price သတ်မှတ်ပြီးပါပြီ။</b>\n\n"
        f"🌍 Server: <b>{server}</b>\n"
        f"💎 Amount: <b>{amount}</b>\n"
        f"🪙 Base MC: <b>{mc_price:.3f} MC</b>\n"
        f"💰 Final MC (20% profit): <b>{final_mc:.3f} MC</b>\n\n"
        f"📐 <b>Formula:</b> {mc_price:.3f} × {MC_PROFIT_MARGIN:.2f} = {final_mc:.3f} MC",
        parse_mode="HTML",
    )


async def delete_price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "❌ အသုံးပြုနည်း: <code>/delprice SERVER AMOUNT</code>\n"
            "ဥပမာ: <code>/delprice Global 86</code>",
            parse_mode="HTML",
        )
        return

    server = args[0]
    amount = args[1]
    delete_manual_price(server, amount)

    await update.message.reply_text(
        f"✅ <b>Price ဖျက်ပြီးပါပြီ။</b>\n\n"
        f"🌍 Server: <b>{server}</b>\n"
        f"💎 Amount: <b>{amount}</b>",
        parse_mode="HTML",
    )


async def list_prices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    server = args[0] if args else None

    rows = get_all_manual_prices(server)

    if not rows:
        await update.message.reply_text("📭 Price မရှိသေးပါ။")
        return

    lines = ["💰 <b>Manual MC Prices</b>\n━━━━━━━━━━━━━━━━━━━━"]
    current_server = None
    for srv, amt, mc in rows:
        if srv != current_server:
            lines.append(f"\n🌍 <b>{srv}</b>")
            current_server = srv
        final_mc = mc * MC_PROFIT_MARGIN
        lines.append(f"  💎 {amt} → Base: {mc:.3f} MC → Final: <b>{final_mc:.3f} MC</b>")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def error_handler(update, context):
    error = context.error
    print("BOT ERROR:", error)

    if "Conflict" in str(error):
        print("⚠️ Conflict Error: Bot Token ကို နေရာနှစ်ခုမှာ Run နေပါတယ်။")
        print("⚠️ Bot Token ကို Revoke လုပ်ပြီး အသစ်ယူပါ။")


async def post_init(application: Application):
    print("✅ Bot initialized successfully!")


async def post_shutdown(application: Application):
    print("🛑 Bot shutting down...")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN မတွေ့ပါ။ Railway Variables မှာ BOT_TOKEN ထည့်ပါ။")
    if not MELO_API_KEY:
        print("⚠️ MELO_API_KEY မတွေ့ပါ။")
    if not MELO_SECRET_KEY:
        print("⚠️ MELO_SECRET_KEY မတွေ့ပါ။")

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
            print(f"✅ License Valid: {license_info['user_id']} (Expiry: {license_info['expiry_date']})")
        except Exception as e:
            print(f"❌ License Error: {e}")
            return

    init_access_db()
    init_balance_db()
    init_subscription_db()
    init_user_api_db()
    init_manual_price_db()

    print("🤖 Eren's Diamond Bot is starting...")
    print("🧪 Sandbox:", MELO_SANDBOX)
    print(f"💹 MC Profit Margin: {MC_PROFIT_MARGIN:.2f}x")
    print(f"⚠️ MC Alert Threshold: {MC_ALERT_THRESHOLD} MC")

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
    app.add_handler(CommandHandler("addsub", add_subscription_command))
    app.add_handler(CommandHandler("checksub", check_subscription_command))
    app.add_handler(CommandHandler("setprice", set_price_command))
    app.add_handler(CommandHandler("delprice", delete_price_command))
    app.add_handler(CommandHandler("listprices", list_prices_command))

    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_error_handler(error_handler)

    print("✅ Bot is running!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
