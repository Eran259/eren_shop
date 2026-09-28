import os
import re
import uuid
import html
import sqlite3
import requests
from collections import defaultdict

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

# Railway မှာ true ထားချင်ရင်
# MELO_SANDBOX=true
MELO_SANDBOX = os.getenv("MELO_SANDBOX", "true").lower() == "true"


# =========================================================
# BOT ACCESS CONTROL
# =========================================================
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

async def request_access(update, context, force_request=False):
    user = update.effective_user
    if not user:
        return False
    if user.id == ADMIN_ID:
        return True

    status = get_access_status(user.id)
    if status == "approved":
        return True

    if status is None or (force_request and status in ("pending", "rejected")):
        save_access_request(user.id, user.username, user.first_name)
        username = f"@{user.username}" if user.username else "—"
        admin_text = (
            "🔔 <b>NEW USER ACCESS REQUEST</b>\n"
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
        except Exception as e:
            print("ACCESS REQUEST SEND ERROR:", e)

    if status == "rejected" and not force_request:
        msg = "❌ <b>Access Denied</b>\n\nAdmin က ဒီ Bot ကိုအသုံးပြုခွင့် မပေးသေးပါ။\n\n/start နှိပ်ပြီး Request ပြန်ပို့နိုင်ပါတယ်။"
    else:
        msg = (
            "🔐 <b>Access Approval Required</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "ဒီ Bot ကိုအသုံးပြုရန် Admin Approval လိုအပ်ပါတယ်။\n\n"
            "⏳ Request ကို Admin ဆီပို့ထားပါတယ်။\n"
            "Approve ဖြစ်တဲ့အခါ Bot ကိုအသုံးပြုနိုင်ပါမယ်။"
        )
    if update.message:
        await update.message.reply_text(msg, parse_mode="HTML")
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
    elif action == "reject":
        status = "rejected"
    else:
        return True
    set_access_status(user_id, status)
    label = "✅ APPROVED" if status == "approved" else "❌ REJECTED"
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
                text="✅ <b>Access Approved!</b>\n\n✨ Eren's Diamond Bot ကို အခုအသုံးပြုနိုင်ပါပြီ။\n/start နှိပ်ပြီး စတင်ပါ။",
                parse_mode="HTML",
                reply_markup=main_keyboard(),
            )
        except Exception as e:
            print("APPROVAL DM ERROR:", e)
        await query.answer("User approved ✅")
    else:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ <b>Access Denied</b>\n\nAdmin က ဒီ Bot ကိုအသုံးပြုခွင့် မပေးသေးပါ။",
                parse_mode="HTML",
            )
        except Exception as e:
            print("REJECTION DM ERROR:", e)
        await query.answer("User rejected ❌")
    return True



# =========================================================
# CUSTOMER MMK PRICE
# =========================================================
#
# ဒီနေရာမှာ မင်းရောင်းမယ့် MMK price တွေ ထည့်မယ်။
#
# ဥပမာ:
#
# MMK_PRICES = {
#     "Global": {
#         "78+8": 5000,
#         "86": 5600,
#     },
#     "Malaysia": {
#         "78+8": 5200,
#     },
#     "Indonesia": {
#         "78+8": 5500,
#     },
# }
#
# အခု မင်း price မပေးသေးလို့ empty ထားထားတယ်။
#


MMK_PRICES = {
    "Global": {},
    "Malaysia": {},
    "Indonesia": {},
}


# =========================================================
# RUNTIME CACHE
# =========================================================

PRODUCT_CACHE = {
    "Global": [],
    "Malaysia": [],
    "Indonesia": [],
}

LAST_PRODUCTS_LOAD = 0
PRODUCT_CACHE_TTL = 300
PRODUCT_LOAD_LOCK = __import__("threading").Lock()
PRODUCT_LAST_ERROR = {}


# =========================================================
# API HELPERS
# =========================================================

def api_headers():
    return {
        "X-API-Key": MELO_API_KEY,
        "X-Secret-Key": MELO_SECRET_KEY,
    }


def api_get(path, params=None):
    url = MELO_BASE_URL + path

    try:
        response = requests.get(
            url,
            headers=api_headers(),
            params=params,
            timeout=30,
        )

        try:
            data = response.json()
        except Exception:
            data = {
                "success": False,
                "message": response.text,
            }

        if response.status_code >= 400:
            return None, (
                data.get("message")
                or f"HTTP {response.status_code}"
            )

        return data, None

    except requests.RequestException as e:
        return None, str(e)


def api_post(path, payload):
    url = MELO_BASE_URL + path

    headers = api_headers()
    headers["Content-Type"] = "application/json"

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )

        try:
            data = response.json()
        except Exception:
            data = {
                "success": False,
                "message": response.text,
            }

        if response.status_code >= 400:
            return None, (
                data.get("message")
                or f"HTTP {response.status_code}"
            )

        return data, None

    except requests.RequestException as e:
        return None, str(e)


# =========================================================
# PROFILE / BALANCE
# =========================================================

def get_profile():
    return api_get("/api/v1/h2h/profile")


def get_balance():
    return api_get("/api/v1/h2h/profile/balance")


# =========================================================
# TEXT HELPERS
# =========================================================

def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


def normalize_product_name(name):
    """
    Customer ပြမယ့် Dia amount ကို normalize လုပ်တယ်။

    ဥပမာ:
    78 + 8 Diamonds
    78+8 Diamonds
    78+8

    => 78+8
    """

    name = clean_text(name)

    name = re.sub(
        r"(?i)\bdiamonds?\b",
        "",
        name,
    )

    name = name.replace(" ", "")

    # 78+8, 78+8D etc.
    match = re.search(
        r"(\d+(?:\.\d+)?)\+(\d+(?:\.\d+)?)",
        name,
    )

    if match:
        a = match.group(1)
        b = match.group(2)

        def fmt(x):
            try:
                f = float(x)
                if f.is_integer():
                    return str(int(f))
                return str(f)
            except Exception:
                return x

        return f"{fmt(a)}+{fmt(b)}"

    # 86 Diamonds
    match = re.search(
        r"(\d+(?:\.\d+)?)",
        name,
    )

    if match:
        value = match.group(1)

        try:
            f = float(value)

            if f.is_integer():
                return str(int(f))

        except Exception:
            pass

        return value

    return name


def diamond_sort_key(product):
    amount = product.get("amount", "")

    match = re.search(
        r"(\d+(?:\.\d+)?)",
        str(amount),
    )

    if match:
        try:
            return float(match.group(1))
        except Exception:
            pass

    return 999999999


# =========================================================
# MLBB DETECTION
# =========================================================

def is_mlbb_product(product):
    text = " ".join(
        [
            clean_text(product.get("name")),
            clean_text(product.get("type_name")),
            clean_text(product.get("category_name")),
            clean_text(product.get("server_name")),
        ]
    ).lower()

    return (
        "mobile legends" in text
        or "mobile legend" in text
        or "mlbb" in text
    )


# =========================================================
# SERVER CLASSIFICATION
# =========================================================

def classify_ml_server(product, brand_name=""):
    """Classify a product using explicit Melostore server/name data.
    Direct server filtering is preferred; this remains only as a fallback.
    """
    text = " ".join([
        clean_text(product.get("name")),
        clean_text(product.get("type_name")),
        clean_text(product.get("server_name")),
        clean_text(product.get("server_code")),
        clean_text(brand_name),
        clean_text(product.get("brand_name")),
        clean_text(product.get("description")),
    ]).lower()
    if "indonesia" in text or "indonesian" in text or "mobile legends (indonesia)" in text:
        return "Indonesia"
    if "malaysia" in text or "malaysian" in text or "mobile legends (malaysia)" in text:
        return "Malaysia"
    if "global" in text or "worldwide" in text or "international" in text:
        return "Global"
    return None


SERVER_API_CODE = {
    "Global": "Legacy",
    "Malaysia": "MY",
    "Indonesia": "ID",
}


def _normalize_api_products(rows, meta, server):
    brands = meta.get("brands", []) if isinstance(meta, dict) else []
    brand_map = {str(x.get("id")): x.get("name", "") for x in brands if isinstance(x, dict)}
    out = []
    for product in rows or []:
        if clean_text(product.get("status")).lower() != "active":
            continue
        if not is_mlbb_product(product):
            continue
        brand_name = brand_map.get(str(product.get("brand_id")), "")
        # Legacy is a shared catalog bucket. For Global, keep only the
        # Mobile Legends (Global) brand so ID/MY products are not mislabeled.
        if server == "Global":
            brand_text = f"{brand_name} {product.get('name', '')} {product.get('description', '')}".lower()
            if "mobile legends (global)" not in brand_text and "global" not in brand_text:
                continue
        item = dict(product)
        item["brand_name"] = brand_name
        item["server"] = server
        item["amount"] = normalize_product_name(product.get("name", ""))
        if item["amount"]:
            out.append(item)
    return out


def _dedupe_products(products):
    unique = {}
    for product in products:
        amount = product.get("amount")
        if not amount:
            continue
        old = unique.get(amount)
        if old is None:
            unique[amount] = product
            continue
        try:
            new_price = float(product.get("price", 999999999))
        except Exception:
            new_price = 999999999
        try:
            old_price = float(old.get("price", 999999999))
        except Exception:
            old_price = 999999999
        if new_price < old_price:
            unique[amount] = product
    return sorted(unique.values(), key=diamond_sort_key)


def load_server_products(server):
    """Fetch only one MLBB server from Melostore.
    This avoids downloading the whole catalog repeatedly and stays under the
    documented 20 pricelist requests/minute quota.
    """
    api_server = SERVER_API_CODE.get(server)
    if not api_server:
        return [], "Invalid server"

    data, error = api_get(
        "/api/v1/h2h/pricelists",
        params={"server": api_server, "limit": 1000},
    )
    if error:
        PRODUCT_LAST_ERROR[server] = error
        return [], error

    rows = data.get("data", []) if isinstance(data, dict) else []
    meta = data.get("meta", {}) if isinstance(data, dict) else {}
    products = _normalize_api_products(rows, meta, server)

    # If the API returns no products with the explicit server filter, do not
    # silently classify unrelated products as another server.
    return _dedupe_products(products), None


def refresh_products(server=None, force=False):
    global PRODUCT_CACHE, LAST_PRODUCTS_LOAD

    servers = [server] if server else list(SERVER_API_CODE.keys())
    now = __import__("time").time()

    with PRODUCT_LOAD_LOCK:
        for name in servers:
            if not force and PRODUCT_CACHE.get(name) and (now - LAST_PRODUCTS_LOAD) < PRODUCT_CACHE_TTL:
                continue

            products, error = load_server_products(name)
            if error:
                print(f"Pricelist error [{name}]: {error}")
                # Never erase a working cache because one refresh failed.
                continue
            PRODUCT_CACHE[name] = products
            print(f"Products [{name}]: {len(products)}")
        LAST_PRODUCTS_LOAD = now

    return PRODUCT_CACHE


def ensure_server_products(server):
    now = __import__("time").time()
    if PRODUCT_CACHE.get(server) and (now - LAST_PRODUCTS_LOAD) < PRODUCT_CACHE_TTL:
        return PRODUCT_CACHE[server], None
    refresh_products(server=server, force=True)
    products = PRODUCT_CACHE.get(server, [])
    return products, PRODUCT_LAST_ERROR.get(server) if not products else None


# =========================================================
# PRICE DISPLAY
# =========================================================

def get_mmk_price(server, amount):
    price = MMK_PRICES.get(server, {}).get(amount)

    if price is None:
        return None

    try:
        return int(price)
    except Exception:
        return price


def format_mmk(price):
    if price is None:
        return "Price မသတ်မှတ်ရသေး"

    try:
        return f"{int(price):,} MMK"
    except Exception:
        return f"{price} MMK"


# =========================================================
# MAIN REPLY KEYBOARD
# =========================================================

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [
                "💎 MLBB Diamonds",
                "🔍 Check ML ID",
            ],
            [
                "💰 Balance",
                "🔌 API Status",
            ],
        ],
        resize_keyboard=True,
    )


# =========================================================
# SERVER INLINE KEYBOARD
# =========================================================

def server_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🌍 Global Server",
                    callback_data="server:Global",
                )
            ],
            [
                InlineKeyboardButton(
                    "🇲🇾 Malaysia Server",
                    callback_data="server:Malaysia",
                )
            ],
            [
                InlineKeyboardButton(
                    "🇮🇩 Indonesia Server",
                    callback_data="server:Indonesia",
                )
            ],
        ]
    )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await request_access(update, context, force_request=True):
        return

    context.user_data.clear()

    text = (
        "✨ <b>Eren's Diamond Bot</b> ✨\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💎 MLBB Diamond Top-Up\n\n"
        "🛒 Choose your service:\n\n"
        "💎 Diamonds\n"
        "🔍 Check ML ID\n"
        "💰 Balance\n"
        "🔌 API Status\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ Powered by Eren"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# =========================================================
# BALANCE
# =========================================================

async def show_balance(
    update: Update,
):

    data, error = get_balance()

    if error:
        await update.message.reply_text(
            "❌ Balance ရယူလို့မရပါဘူး။\n\n"
            f"Error: {html.escape(str(error))}"
        )
        return

    info = data.get("data", {})

    balance = info.get(
        "h2h_balance",
        0,
    )

    usd = info.get(
        "h2h_balance_usd",
        0,
    )

    rate = info.get(
        "usd_idr_rate",
        0,
    )

    sandbox = info.get(
        "is_sandbox_mode",
        False,
    )

    mode = (
        "🧪 Sandbox Mode"
        if sandbox
        else "🟢 Production Mode"
    )

    text = (
        "💰 <b>Bot Balance</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🪙 MC Balance\n"
        f"<b>{balance:,.2f} MC</b>\n\n"
        f"💵 USD Value\n"
        f"<b>${usd:,.2f}</b>\n\n"
        f"💱 USD / IDR Rate\n"
        f"<b>{rate:,.0f}</b>\n\n"
        f"⚙️ Mode\n"
        f"<b>{mode}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎴 Eren Shop"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )

# =========================================================
# API STATUS
# =========================================================

async def show_api_status(
    update: Update,
):

    data, error = get_profile()

    if error:
        await update.message.reply_text(
            "🔴 <b>API Offline / Error</b>\n\n"
            f"{html.escape(str(error))}",
            parse_mode="HTML",
        )
        return

    info = data.get("data", {})

    tier = info.get("tier", {})

    tier_name = tier.get(
        "name",
        "Unknown",
    )

    sandbox = info.get(
        "is_sandbox_mode",
        False,
    )

    status = (
        "🧪 Sandbox Mode"
        if sandbox
        else "🟢 Production Mode"
    )

    text = (
        "🔌 <b>Melostore API Status</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🟢 Connection: <b>Connected</b>\n"
        f"🏷️ Tier: <b>{html.escape(str(tier_name))}</b>\n"
        f"⚙️ Mode: <b>{status}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ Powered by Eren"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# =========================================================
# MLBB SERVER PAGE
# =========================================================

async def open_mlbb(
    update: Update,
):

    await update.message.reply_text(
        "💎 <b>MLBB Diamond Top-Up</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌍 Server ရွေးပါ။",
        parse_mode="HTML",
        reply_markup=server_keyboard(),
    )


# =========================================================
# DIAMOND LIST MESSAGE
# =========================================================

def build_amount_text(server):

    products = PRODUCT_CACHE.get(
        server,
        [],
    )

    if not products:
        return (
            f"💎 <b>{html.escape(server)} Server</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "❌ Diamond products မတွေ့ပါ။"
        )

    lines = [
        f"💎 <b>{html.escape(server)} Server</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "💎 <b>Diamond Amounts</b>",
        "",
    ]

    for product in products:

        amount = product.get(
            "amount",
            "?",
        )

        price = get_mmk_price(
            server,
            amount,
        )

        lines.append(
            f"💎 {html.escape(str(amount))} "
            f"— <b>{format_mmk(price)}</b>"
        )

    lines.extend(
        [
            "",
            "👇 အောက်က Button ကနေ Amount ရွေးပါ။",
        ]
    )

    return "\n".join(lines)


# =========================================================
# AMOUNT BUTTONS
# =========================================================

def amount_keyboard(server):

    products = PRODUCT_CACHE.get(
        server,
        [],
    )

    buttons = []

    row = []

    for index, product in enumerate(products):

        amount = product.get(
            "amount",
            "?",
        )

        button = InlineKeyboardButton(
            f"💎 {amount}",
            callback_data=f"amount:{server}:{index}",
        )

        row.append(button)

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append(
        [
            InlineKeyboardButton(
                "⬅️ Server ပြန်ရွေးမယ်",
                callback_data="back:servers",
            )
        ]
    )

    return InlineKeyboardMarkup(buttons)


# =========================================================
# CHECK ID MAIN PAGE
# =========================================================

async def start_check_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data.clear()

    context.user_data["state"] = "check_id_player"

    text = (
        "🔍 <b>MLBB ID Checker</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🆔 <b>Player ID</b> ထည့်ပါ။\n\n"
        "ဥပမာ:\n"
        "<code>12345678</code>\n\n"
        "❌ Cancel လုပ်ချင်ရင် /start"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# =========================================================
# CHECK ID → API
# =========================================================

def check_ml_nickname(
    player_id,
    zone_id,
):

    payload = {
        "game_code": "mobile-legends",
        "customer_target": str(player_id),
        "customer_target_zone": str(zone_id),
    }

    return api_post(
        "/api/v1/h2h/check-nickname",
        payload,
    )


# =========================================================
# CHECK ID RESULT
# =========================================================

async def process_check_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    player_id = context.user_data.get(
        "check_player_id"
    )

    zone_id = update.message.text.strip()

    if not zone_id.isdigit():
        await update.message.reply_text(
            "❌ Zone ID မှာ နံပါတ်ပဲ ထည့်ပါ။\n\n"
            "ဥပမာ: <code>2039</code>",
            parse_mode="HTML",
        )
        return

    await update.message.reply_text(
        "🔍 <b>Checking MLBB ID...</b>\n"
        "ခဏစောင့်ပါ...",
        parse_mode="HTML",
    )

    data, error = check_ml_nickname(
        player_id,
        zone_id,
    )

    if error:
        await update.message.reply_text(
            "❌ <b>Check ID Failed</b>\n\n"
            f"{html.escape(str(error))}",
            parse_mode="HTML",
        )

        context.user_data.clear()

        return

    info = data.get(
        "data",
        {},
    )

    # API response format က version အလိုက်
    # field location နည်းနည်းကွာနိုင်လို့ fallback ထားထားတယ်။

    nickname = (
        info.get("username")
        or info.get("nickname")
        or info.get("name")
        or "-"
    )

    region = (
        info.get("region")
        or info.get("region_name")
        or "-"
    )

    region_type = info.get(
        "region_type",
        "",
    )

    billing = info.get(
        "billing",
        {},
    )

    charged_mc = billing.get(
        "charged_mc",
        0,
    )

    free_remaining = billing.get(
        "free_remaining_today",
        0,
    )

    text = (
        "🔍 <b>MLBB ID Result</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Nickname: <b>{html.escape(str(nickname))}</b>\n"
        f"🆔 Player ID: <code>{html.escape(str(player_id))}</code>\n"
        f"🌐 Zone ID: <code>{html.escape(str(zone_id))}</code>\n"
        f"🌍 Region: <b>{html.escape(str(region))}</b>\n"
    )

    if region_type:
        text += (
            f"🏷️ Region Type: "
            f"<b>{html.escape(str(region_type))}</b>\n"
        )

    text += (
        "\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ <b>ID Verified</b>"
    )

    # Billing ကို customer UI မှာ မပြဘူး။
    # charged_mc / free_remaining_today က backend
    # information အဖြစ်ပဲထားတယ်။

    context.user_data.clear()

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# =========================================================
# SERVER CALLBACK
# =========================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    data = query.data or ""

    # -----------------------------------------------------
    # BACK TO SERVERS
    # -----------------------------------------------------

    if data == "back:servers":

        await query.edit_message_text(
            "💎 <b>MLBB Diamond Top-Up</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🌍 Server ရွေးပါ။",
            parse_mode="HTML",
            reply_markup=server_keyboard(),
        )

        return

    # -----------------------------------------------------
    # SERVER SELECT
    # -----------------------------------------------------

    if data.startswith("server:"):

        server = data.split(
            ":",
            1,
        )[1]

        if server not in (
            "Global",
            "Malaysia",
            "Indonesia",
        ):
            await query.answer(
                "❌ Invalid server",
                show_alert=True,
            )
            return

        await query.edit_message_text(
            "⏳ <b>Loading Diamond Products...</b>\n"
            "ခဏစောင့်ပါ...",
            parse_mode="HTML",
        )

        products, load_error = ensure_server_products(server)

        if not products:

            await query.edit_message_text(
                f"❌ <b>{html.escape(server)} Server</b>\n\n"
                "ဒီ server အတွက် MLBB product မတွေ့ပါ။\n\n"
                + (f"API: {html.escape(str(load_error))}" if load_error else "Pricelist empty ဖြစ်နေပါတယ်။"),
                parse_mode="HTML",
                reply_markup=server_keyboard(),
            )

            return

        text = build_amount_text(
            server
        )

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=amount_keyboard(server),
        )

        return

    # -----------------------------------------------------
    # AMOUNT SELECT
    # -----------------------------------------------------

    if data.startswith("amount:"):

        parts = data.split(":")

        if len(parts) != 3:
            return

        server = parts[1]

        try:
            index = int(parts[2])
        except Exception:
            return

        products = PRODUCT_CACHE.get(
            server,
            [],
        )

        if index < 0 or index >= len(products):
            await query.answer(
                "❌ Product မတွေ့ပါ။",
                show_alert=True,
            )
            return

        product = products[index]

        context.user_data["server"] = server
        context.user_data["product"] = product

        amount = product.get(
            "amount",
            "?",
        )

        price = get_mmk_price(
            server,
            amount,
        )

        sku = product.get(
            "sku_code",
            "",
        )

        context.user_data["sku"] = sku

        price_text = format_mmk(price)

        text = (
            "💎 <b>Selected Product</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🌍 Server: <b>{html.escape(server)}</b>\n"
            f"💎 Amount: <b>{html.escape(str(amount))}</b>\n"
            f"💰 Price: <b>{html.escape(price_text)}</b>\n\n"
            "🆔 <b>Player ID</b> ထည့်ပါ။\n"
            "ဥပမာ: <code>12345678</code>"
        )

        context.user_data["state"] = (
            "order_player_id"
        )

        await query.edit_message_text(
            text,
            parse_mode="HTML",
        )

        return

# =========================================================
# ORDER → CHECK NICKNAME
# =========================================================

async def process_order_player_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    player_id = update.message.text.strip()

    if not player_id.isdigit():
        await update.message.reply_text(
            "❌ Player ID မှာ နံပါတ်ပဲ ထည့်ပါ။"
        )
        return

    context.user_data["player_id"] = player_id
    context.user_data["state"] = "order_zone_id"

    await update.message.reply_text(
        "🌐 <b>Zone ID</b> ထည့်ပါ။\n\n"
        "ဥပမာ: <code>2039</code>",
        parse_mode="HTML",
    )


# =========================================================
# ORDER → ZONE ID
# =========================================================

async def process_order_zone_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    zone_id = update.message.text.strip()

    if not zone_id.isdigit():
        await update.message.reply_text(
            "❌ Zone ID မှာ နံပါတ်ပဲ ထည့်ပါ။"
        )
        return

    player_id = context.user_data.get(
        "player_id"
    )

    context.user_data["zone_id"] = zone_id

    await update.message.reply_text(
        "🔍 <b>Checking Nickname...</b>\n"
        "ခဏစောင့်ပါ...",
        parse_mode="HTML",
    )

    data, error = check_ml_nickname(
        player_id,
        zone_id,
    )

    if error:
        await update.message.reply_text(
            "❌ <b>ID Check Failed</b>\n\n"
            f"{html.escape(str(error))}",
            parse_mode="HTML",
        )

        context.user_data.clear()

        return

    info = data.get(
        "data",
        {},
    )

    nickname = (
        info.get("username")
        or info.get("nickname")
        or info.get("name")
        or "-"
    )

    context.user_data["nickname"] = nickname

    server = context.user_data.get(
        "server",
        "Global",
    )

    product = context.user_data.get(
        "product",
        {},
    )

    amount = product.get(
        "amount",
        "?",
    )

    price = get_mmk_price(
        server,
        amount,
    )

    price_text = format_mmk(price)

    text = (
        "🔍 <b>Account Verified</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Nickname: <b>{html.escape(str(nickname))}</b>\n"
        f"🆔 Player ID: <code>{html.escape(str(player_id))}</code>\n"
        f"🌐 Zone ID: <code>{html.escape(str(zone_id))}</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🌍 Server: <b>{html.escape(server)}</b>\n"
        f"💎 Diamond: <b>{html.escape(str(amount))}</b>\n"
        f"💰 Price: <b>{html.escape(price_text)}</b>\n\n"
        "အချက်အလက်မှန်ကန်ရင် Order တင်နိုင်ပါတယ်။"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirm Order",
                    callback_data="order:confirm",
                ),
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data="order:cancel",
                ),
            ]
        ]
    )

    context.user_data["state"] = (
        "order_confirm"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )


# =========================================================
# CREATE TRANSACTION
# =========================================================

def create_transaction(
    product,
    player_id,
    zone_id,
):

    sku = product.get(
        "sku_code"
    )

    buyer_trx_id = (
        "EREN-"
        + uuid.uuid4().hex[:20].upper()
    )

    payload = {
        "sku_code": sku,
        "customer_target": str(player_id),
        "customer_target_zone": str(zone_id),
        "buyer_trx_id": buyer_trx_id,
        "sandbox_mode": MELO_SANDBOX,
    }

    return api_post(
        "/api/v1/h2h/transaction",
        payload,
    )


# =========================================================
# CONFIRM ORDER
# =========================================================

async def confirm_order(
    query,
    context,
):

    server = context.user_data.get(
        "server"
    )

    product = context.user_data.get(
        "product"
    )

    player_id = context.user_data.get(
        "player_id"
    )

    zone_id = context.user_data.get(
        "zone_id"
    )

    nickname = context.user_data.get(
        "nickname",
        "-",
    )

    if not product or not player_id or not zone_id:
        await query.edit_message_text(
            "❌ Order information မပြည့်စုံပါ။\n"
            "/start နဲ့ ပြန်စပါ။"
        )

        context.user_data.clear()

        return

    amount = product.get(
        "amount",
        "?",
    )

    price = get_mmk_price(
        server,
        amount,
    )

    # MMK price မသတ်မှတ်ရသေးရင်
    # မတော်တဆ order မတင်အောင် block လုပ်ထားတယ်။

    if price is None:

        await query.edit_message_text(
            "⚠️ <b>Price မသတ်မှတ်ရသေးပါ။</b>\n\n"
            f"💎 {html.escape(str(amount))}\n"
            f"🌍 {html.escape(str(server))}\n\n"
            "Admin က MMK price ထည့်ပြီးမှ "
            "order တင်နိုင်ပါမယ်။",
            parse_mode="HTML",
        )

        context.user_data.clear()

        return

    await query.edit_message_text(
        "🛒 <b>Creating Order...</b>\n"
        "ခဏစောင့်ပါ...",
        parse_mode="HTML",
    )

    data, error = create_transaction(
        product,
        player_id,
        zone_id,
    )

    if error:

        await query.edit_message_text(
            "❌ <b>Order Failed</b>\n\n"
            f"{html.escape(str(error))}",
            parse_mode="HTML",
        )

        context.user_data.clear()

        return

    result = data.get(
        "data",
        {},
    )

    transaction_id = result.get(
        "id",
        "-"
    )

    status = result.get(
        "status",
        "pending",
    )

    text = (
        "🛒 <b>Order Created</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Nickname: <b>{html.escape(str(nickname))}</b>\n"
        f"🆔 Player ID: <code>{html.escape(str(player_id))}</code>\n"
        f"🌐 Zone ID: <code>{html.escape(str(zone_id))}</code>\n\n"
        f"🌍 Server: <b>{html.escape(str(server))}</b>\n"
        f"💎 Diamond: <b>{html.escape(str(amount))}</b>\n"
        f"💰 Price: <b>{format_mmk(price)}</b>\n\n"
        f"🆔 Transaction: <code>{html.escape(str(transaction_id))}</code>\n"
        f"⏳ Status: <b>{html.escape(str(status).upper())}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ Powered by Eren"
    )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
    )

    context.user_data.clear()


# =========================================================
# CALLBACK CONTINUE
# =========================================================

async def handle_callback_actions(
    update,
    context,
):

    query = update.callback_query
    data = query.data or ""

    # Confirm
    if data == "order:confirm":

        await query.answer(
            "Order တင်နေပါတယ်..."
        )

        await confirm_order(
            query,
            context,
        )

        return True

    # Cancel
    if data == "order:cancel":

        context.user_data.clear()

        await query.edit_message_text(
            "❌ <b>Order Cancelled</b>\n\n"
            "/start နဲ့ Main Menu ပြန်သွားနိုင်ပါတယ်။",
            parse_mode="HTML",
        )

        return True

    return False


# =========================================================
# COMBINED CALLBACK HANDLER
# =========================================================

async def callback_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if data.startswith("access:"):
        await handle_access_callback(update, context)
        return

    if get_access_status(query.from_user.id) != "approved":
        await query.answer("🔐 Admin approval လိုအပ်ပါတယ်။", show_alert=True)
        return

    if data.startswith("order:"):

        handled = await handle_callback_actions(
            update,
            context,
        )

        if handled:
            return

    await callback_handler(
        update,
        context,
    )


# =========================================================
# TEXT HANDLER
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    if not await request_access(update, context):
        return

    text = update.message.text.strip()

    # -----------------------------------------------------
    # MAIN MENU
    # -----------------------------------------------------

    if text == "💎 MLBB Diamonds":

        await open_mlbb(update)

        return

    if text == "🔍 Check ML ID":

        await start_check_id(
            update,
            context,
        )

        return

    if text == "💰 Balance":

        await show_balance(update)

        return

    if text == "🔌 API Status":

        await show_api_status(update)

        return

    # -----------------------------------------------------
    # CHECK ID FLOW
    # -----------------------------------------------------

    state = context.user_data.get(
        "state"
    )

    if state == "check_id_player":

        if not text.isdigit():

            await update.message.reply_text(
                "❌ Player ID မှာ နံပါတ်ပဲ ထည့်ပါ။"
            )

            return

        context.user_data[
            "check_player_id"
        ] = text

        context.user_data[
            "state"
        ] = "check_id_zone"

        await update.message.reply_text(
            "🌐 <b>Zone ID</b> ထည့်ပါ။\n\n"
            "ဥပမာ: <code>2039</code>",
            parse_mode="HTML",
        )

        return

    if state == "check_id_zone":

        await process_check_id(
            update,
            context,
        )

        return

    # -----------------------------------------------------
    # ORDER FLOW
    # -----------------------------------------------------

    if state == "order_player_id":

        await process_order_player_id(
            update,
            context,
        )

        return

    if state == "order_zone_id":

        await process_order_zone_id(
            update,
            context,
        )

        return

    # -----------------------------------------------------
    # UNKNOWN
    # -----------------------------------------------------

    await update.message.reply_text(
        "❓ Menu ကနေရွေးပေးပါ။",
        reply_markup=main_keyboard(),
    )


# =========================================================
# COMMANDS
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await request_access(update, context):
        return

    text = (
        "📖 <b>Help</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💎 MLBB Diamonds — Diamond Top-Up\n"
        "🔍 Check ML ID — Nickname စစ်ရန်\n"
        "💰 Balance — API Balance\n"
        "🔌 API Status — API Connection\n\n"
        "/start — Main Menu"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update,
    context,
):

    print(
        "BOT ERROR:",
        context.error,
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN မတွေ့ပါ။ Railway Variables မှာ BOT_TOKEN ထည့်ပါ။"
        )

    if not MELO_API_KEY:
        print(
            "⚠️ MELO_API_KEY မတွေ့ပါ။"
        )

    if not MELO_SECRET_KEY:
        print(
            "⚠️ MELO_SECRET_KEY မတွေ့ပါ။"
        )

    init_access_db()

    print(
        "🤖 Eren's Diamond Bot is starting..."
    )

    print(
        "🧪 Sandbox:",
        MELO_SANDBOX,
    )

    # Startup မှာ products မဆွဲသေးဘူး။
    # Server ရွေးတဲ့အချိန်မှ API ကိုခေါ်မယ်။

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    # Inline buttons
    app.add_handler(
        CallbackQueryHandler(
            callback_router,
        )
    )

    # Reply keyboard / text
    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            text_handler,
        )
    )

    app.add_error_handler(
        error_handler
    )

    print(
        "✅ Bot is running!"
    )

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
