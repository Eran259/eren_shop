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

MELO_SANDBOX = os.getenv(
    "MELO_SANDBOX",
    "true"
).lower() == "true"


# =========================================================
# BOT ACCESS CONTROL
# =========================================================

ADMIN_ID = 5698123475
ACCESS_DB = "access.db"


def init_access_db():
    conn = sqlite3.connect(ACCESS_DB)

    conn.execute(
        """CREATE TABLE IF NOT EXISTS bot_access (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            requested_at TEXT DEFAULT CURRENT_TIMESTAMP
        )"""
    )

    conn.commit()
    conn.close()


def get_access_status(user_id):

    if int(user_id) == ADMIN_ID:
        return "approved"

    conn = sqlite3.connect(ACCESS_DB)

    row = conn.execute(
        "SELECT status FROM bot_access WHERE user_id=?",
        (int(user_id),)
    ).fetchone()

    conn.close()

    return row[0] if row else None


def save_access_request(
    user_id,
    username,
    first_name,
):

    conn = sqlite3.connect(ACCESS_DB)

    conn.execute(
        """INSERT INTO bot_access
        (user_id, username, first_name, status, requested_at)
        VALUES (?, ?, ?, 'pending', CURRENT_TIMESTAMP)

        ON CONFLICT(user_id) DO UPDATE SET
        username=excluded.username,
        first_name=excluded.first_name,
        status='pending',
        requested_at=CURRENT_TIMESTAMP
        """,
        (
            int(user_id),
            username or "",
            first_name or "",
        )
    )

    conn.commit()
    conn.close()


def set_access_status(
    user_id,
    status,
):

    conn = sqlite3.connect(ACCESS_DB)

    conn.execute(
        "UPDATE bot_access SET status=? WHERE user_id=?",
        (
            status,
            int(user_id),
        )
    )

    conn.commit()
    conn.close()


def access_request_keyboard(user_id):

    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=f"access:approve:{user_id}",
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"access:reject:{user_id}",
            ),
        ]]
    )


async def request_access(
    update,
    context,
):

    user = update.effective_user

    if not user:
        return False

    if user.id == ADMIN_ID:
        return True

    status = get_access_status(user.id)

    if status == "approved":
        return True

    if status is None:

        save_access_request(
            user.id,
            user.username,
            user.first_name,
        )

        username = (
            f"@{user.username}"
            if user.username
            else "—"
        )

        admin_text = (
            "🔔 <b>NEW USER ACCESS REQUEST</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Name: "
            f"<b>{html.escape(user.first_name or '—')}</b>\n"
            f"🔗 Username: "
            f"<b>{html.escape(username)}</b>\n"
            f"🆔 User ID: "
            f"<code>{user.id}</code>\n\n"
            "⚠️ ဒီ user ကို Bot အသုံးပြုခွင့်ပေးမလား?"
        )

        try:

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text,
                parse_mode="HTML",
                reply_markup=access_request_keyboard(
                    user.id
                ),
            )

        except Exception as e:

            print(
                "ACCESS REQUEST SEND ERROR:",
                e,
            )

    if status == "rejected":

        msg = (
            "❌ <b>Access Denied</b>\n\n"
            "Admin က ဒီ Bot ကိုအသုံးပြုခွင့် "
            "မပေးသေးပါ။"
        )

    else:

        msg = (
            "🔐 <b>Access Approval Required</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "ဒီ Bot ကိုအသုံးပြုရန် "
            "Admin Approval လိုအပ်ပါတယ်။\n\n"
            "⏳ Request ကို Admin ဆီပို့ထားပါတယ်။\n"
            "Approve ဖြစ်တဲ့အခါ Bot ကိုအသုံးပြုနိုင်ပါမယ်။"
        )

    if update.message:

        await update.message.reply_text(
            msg,
            parse_mode="HTML",
        )

    return False


async def handle_access_callback(
    update,
    context,
):

    query = update.callback_query

    if query.from_user.id != ADMIN_ID:

        await query.answer(
            "❌ Admin only",
            show_alert=True,
        )

        return True

    parts = (
        query.data or ""
    ).split(":")

    if len(parts) != 3:

        await query.answer(
            "Invalid request",
            show_alert=True,
        )

        return True

    action = parts[1]
    uid_text = parts[2]

    try:

        user_id = int(uid_text)

    except ValueError:

        await query.answer(
            "Invalid user ID",
            show_alert=True,
        )

        return True

    if action == "approve":

        status = "approved"

    elif action == "reject":

        status = "rejected"

    else:

        return True

    set_access_status(
        user_id,
        status,
    )

    label = (
        "✅ APPROVED"
        if status == "approved"
        else "❌ REJECTED"
    )

    try:

        await query.edit_message_text(
            (query.message.text or "")
            + f"\n\n<b>{label}</b>",
            parse_mode="HTML",
        )

    except Exception:

        pass

    if status == "approved":

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "✅ <b>Access Approved!</b>\n\n"
                    "✨ Eren's Diamond Bot ကို "
                    "အခုအသုံးပြုနိုင်ပါပြီ။\n"
                    "/start နှိပ်ပြီး စတင်ပါ။"
                ),
                parse_mode="HTML",
                reply_markup=main_keyboard(),
            )

        except Exception as e:

            print(
                "APPROVAL DM ERROR:",
                e,
            )

        await query.answer(
            "User approved ✅"
        )

    else:

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "❌ <b>Access Denied</b>\n\n"
                    "Admin က ဒီ Bot ကိုအသုံးပြုခွင့် "
                    "မပေးသေးပါ။"
                ),
                parse_mode="HTML",
            )

        except Exception as e:

            print(
                "REJECTION DM ERROR:",
                e,
            )

        await query.answer(
            "User rejected ❌"
        )

    return True


# =========================================================
# CUSTOMER MMK PRICE
# =========================================================

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


# =========================================================
# API HELPERS
# =========================================================

def api_headers():

    return {
        "X-API-Key": MELO_API_KEY,
        "X-Secret-Key": MELO_SECRET_KEY,
    }


def api_get(
    path,
    params=None,
):

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


def api_post(
    path,
    payload,
):

    url = MELO_BASE_URL + path

    headers = api_headers()

    headers["Content-Type"] = (
        "application/json"
    )

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

    return api_get(
        "/api/v1/h2h/profile"
    )


def get_balance():

    return api_get(
        "/api/v1/h2h/profile/balance"
    )


# =========================================================
# TEXT HELPERS
# =========================================================

def clean_text(value):

    if value is None:
        return ""

    return str(value).strip()


def normalize_product_name(name):

    name = clean_text(name)

    name = re.sub(
        r"(?i)\bdiamonds?\b",
        "",
        name,
    )

    name = name.replace(
        " ",
        "",
    )

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

    match = re.search(
        r"(\d+(?:\.\d+)?)",
        name,
    )

    if match:

        value = match.group(1)

        try:

            f = float(value)

            if f.is_integer():

                return str(
                    int(f)
                )

        except Exception:

            pass

        return value

    return name


def diamond_sort_key(product):

    amount = product.get(
        "amount",
        "",
    )

    match = re.search(
        r"(\d+(?:\.\d+)?)",
        str(amount),
    )

    if match:

        try:

            return float(
                match.group(1)
            )

        except Exception:

            pass

    return 999999999


# =========================================================
# MLBB DETECTION
# =========================================================

def is_mlbb_product(product):

    text = " ".join(
        [
            clean_text(
                product.get("name")
            ),
            clean_text(
                product.get("type_name")
            ),
            clean_text(
                product.get("category_name")
            ),
            clean_text(
                product.get("server_name")
            ),
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

def classify_ml_server(
    product,
    brand_name="",
):

    values = [
        clean_text(
            product.get("name")
        ),
        clean_text(
            product.get("type_name")
        ),
        clean_text(
            product.get("server_name")
        ),
        clean_text(
            product.get("server_code")
        ),
        clean_text(
            brand_name
        ),
        clean_text(
            product.get("brand_name")
        ),
        clean_text(
            product.get("description")
        ),
    ]

    text = " ".join(
        values
    ).lower()

    indonesia_words = [
        "indonesia",
        "indonesian",
        "(id)",
        " id ",
        "-id",
        "_id",
    ]

    if any(
        word in text
        for word in indonesia_words
    ):

        return "Indonesia"

    malaysia_words = [
        "malaysia",
        "malaysian",
        "(my)",
        " my ",
        "-my",
        "_my",
    ]

    if any(
        word in text
        for word in malaysia_words
    ):

        return "Malaysia"

    global_words = [
        "global",
        "worldwide",
        "international",
        "global server",
        "(gl)",
    ]

    if any(
        word in text
        for word in global_words
    ):

        return "Global"

    return None


# =========================================================
# LOAD REGULAR PRICELIST
# =========================================================

def load_all_ml_products():

    all_products = []

    cursor = None

    for _ in range(30):

        params = {
            "limit": 1000,
        }

        if cursor:

            params["cursor"] = cursor

        data, error = api_get(
            "/api/v1/h2h/pricelists",
            params=params,
        )

        if error:

            print(
                "Pricelist error:",
                error,
            )

            break

        if not data:
            break

        rows = data.get(
            "data",
            []
        )

        meta = data.get(
            "meta",
            {}
        )

        brands = meta.get(
            "brands",
            []
        )

        brand_map = {
            str(x.get("id")):
            x.get("name", "")
            for x in brands
        }

        for product in rows:

            if clean_text(
                product.get("status")
            ).lower() != "active":

                continue

            if not is_mlbb_product(
                product
            ):

                continue

            brand_name = brand_map.get(
                str(
                    product.get(
                        "brand_id"
                    )
                ),
                "",
            )

            server = classify_ml_server(
                product,
                brand_name,
            )

            if not server:
                continue

            item = dict(
                product
            )

            item["brand_name"] = (
                brand_name
            )

            item["server"] = (
                server
            )

            item["amount"] = (
                normalize_product_name(
                    product.get(
                        "name",
                        ""
                    )
                )
            )

            all_products.append(
                item
            )

        pagination = meta.get(
            "pagination",
            {}
        )

        if not pagination.get(
            "has_more"
        ):

            break

        cursor = pagination.get(
            "next_cursor"
        )

        if not cursor:
            break

    return all_products


# =========================================================
# BUILD SERVER CACHE
# =========================================================

def refresh_products():

    global PRODUCT_CACHE

    products = (
        load_all_ml_products()
    )

    grouped = {
        "Global": [],
        "Malaysia": [],
        "Indonesia": [],
    }

    for product in products:

        server = product.get(
            "server"
        )

        if server in grouped:

            grouped[
                server
            ].append(product)

    for server in grouped:

        unique = {}

        for product in grouped[
            server
        ]:

            amount = product.get(
                "amount"
            )

            if not amount:
                continue

            old = unique.get(
                amount
            )

            if old is None:

                unique[
                    amount
                ] = product

                continue

            try:

                new_price = float(
                    product.get(
                        "price",
                        999999999
                    )
                )

            except Exception:

                new_price = 999999999

            try:

                old_price = float(
                    old.get(
                        "price",
                        999999999
                    )
                )

            except Exception:

                old_price = 999999999

            if new_price < old_price:

                unique[
                    amount
                ] = product

        grouped[
            server
        ] = sorted(
            unique.values(),
            key=diamond_sort_key,
        )

    PRODUCT_CACHE = grouped

    print(
        "Products:",
        {
            k: len(v)
            for k, v in PRODUCT_CACHE.items()
        }
    )

    return PRODUCT_CACHE

# =========================================================
# PRODUCT CACHE SETTINGS
# =========================================================

PRODUCT_CACHE_TTL = 300  # 5 minutes
PRODUCT_LOADING = False


def get_cached_products():
    """
    Pricelist ကို request တိုင်း မခေါ်ဘဲ cache သုံးမယ်။
    5 minutes မပြည့်သေးရင် API မခေါ်ဘူး။
    """

    global LAST_PRODUCTS_LOAD

    now = __import__("time").time()

    if PRODUCT_CACHE_READY():
        return PRODUCT_CACHE

    if LAST_PRODUCTS_LOAD:
        age = now - LAST_PRODUCTS_LOAD

        if age < PRODUCT_CACHE_TTL:
            return PRODUCT_CACHE

    return refresh_products_safe()


def PRODUCT_CACHE_READY():
    return any(
        len(PRODUCT_CACHE.get(server, [])) > 0
        for server in (
            "Global",
            "Malaysia",
            "Indonesia",
        )
    )


def refresh_products_safe():
    global LAST_PRODUCTS_LOAD
    global PRODUCT_LOADING

    if PRODUCT_LOADING:
        return PRODUCT_CACHE

    PRODUCT_LOADING = True

    try:
        print("🔄 Loading Melostore products...")

        old_cache = PRODUCT_CACHE.copy()

        products = load_all_ml_products()

        # API fail / empty ဖြစ်ရင်
        # ရှိပြီးသား cache ကို မဖျက်ဘူး။
        if not products:

            print(
                "⚠️ Product API returned empty."
            )

            if PRODUCT_CACHE_READY():
                return old_cache

            return PRODUCT_CACHE

        grouped = {
            "Global": [],
            "Malaysia": [],
            "Indonesia": [],
        }

        for product in products:

            server = product.get("server")

            if server not in grouped:
                continue

            amount = product.get("amount")

            if not amount:
                continue

            grouped[server].append(product)

        # Duplicate amount ဖယ်မယ်
        for server in grouped:

            unique = {}

            for product in grouped[server]:

                amount = product.get("amount")

                if amount not in unique:
                    unique[amount] = product
                    continue

                try:
                    new_price = float(
                        product.get(
                            "price",
                            999999999,
                        )
                    )
                except Exception:
                    new_price = 999999999

                try:
                    old_price = float(
                        unique[amount].get(
                            "price",
                            999999999,
                        )
                    )
                except Exception:
                    old_price = 999999999

                if new_price < old_price:
                    unique[amount] = product

            grouped[server] = sorted(
                unique.values(),
                key=diamond_sort_key,
            )

        # အနည်းဆုံး product တစ်ခုရှိမှ cache update
        if any(grouped.values()):

            PRODUCT_CACHE = grouped
            LAST_PRODUCTS_LOAD = (
                __import__("time").time()
            )

            print(
                "✅ Products loaded:",
                {
                    k: len(v)
                    for k, v in PRODUCT_CACHE.items()
                },
            )

        return PRODUCT_CACHE

    except Exception as e:

        print(
            "❌ Product refresh error:",
            repr(e),
        )

        return PRODUCT_CACHE

    finally:
        PRODUCT_LOADING = False


# =========================================================
# LOAD PRODUCTS ONLY WHEN NEEDED
# =========================================================

def ensure_products_loaded():

    if not PRODUCT_CACHE_READY():

        print(
            "📦 Product cache empty → loading..."
        )

        return refresh_products_safe()

    return PRODUCT_CACHE


# =========================================================
# IMPROVED SERVER PRODUCT GETTER
# =========================================================

def get_server_products(server):

    ensure_products_loaded()

    products = PRODUCT_CACHE.get(
        server,
        [],
    )

    return products


# =========================================================
# IMPROVED AMOUNT KEYBOARD
# =========================================================

def amount_keyboard(server):

    products = get_server_products(server)

    buttons = []
    row = []

    for index, product in enumerate(products):

        amount = product.get(
            "amount",
            "?",
        )

        price = get_mmk_price(
            server,
            amount,
        )

        # Price မရှိရင်လည်း button ပြမယ်
        # order မှာတော့ block လုပ်ထားပြီးသား
        label = (
            f"💎 {amount}"
            if price is None
            else f"💎 {amount} • {format_mmk(price)}"
        )

        row.append(
            InlineKeyboardButton(
                label,
                callback_data=(
                    f"amount:{server}:{index}"
                ),
            )
        )

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
# IMPROVED DIAMOND PAGE
# =========================================================

async def show_server_products(
    query,
    server,
):

    products = get_server_products(server)

    if not products:

        await query.edit_message_text(
            "⚠️ <b>Products မတွေ့သေးပါ။</b>\n\n"
            "🔄 API Product List ကို "
            "ခဏအကြာမှာ ပြန်စစ်ပေးပါမယ်။",
            parse_mode="HTML",
        )

        return

    text = (
        f"💎 <b>{html.escape(server)} Server</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💎 <b>Diamond Amount</b>\n"
        "👇 ဝယ်ချင်တဲ့ Amount ကိုရွေးပါ။"
    )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=amount_keyboard(server),
    )


# =========================================================
# SERVER CALLBACK
# =========================================================

async def handle_server_callback(
    query,
    context,
):

    server = query.data.split(
        ":",
        1,
    )[1]

    context.user_data["server"] = server

    await query.answer()

    await query.edit_message_text(
        "🔄 <b>Loading Products...</b>\n\n"
        "ခဏစောင့်ပါ...",
        parse_mode="HTML",
    )

    await show_server_products(
        query,
        server,
    )


# =========================================================
# AMOUNT CALLBACK
# =========================================================

async def handle_amount_callback(
    query,
    context,
):

    parts = query.data.split(":")

    if len(parts) != 3:
        await query.answer(
            "❌ Invalid product",
            show_alert=True,
        )
        return

    server = parts[1]

    try:
        index = int(parts[2])
    except ValueError:
        await query.answer(
            "❌ Invalid product",
            show_alert=True,
        )
        return

    products = get_server_products(server)

    if index < 0 or index >= len(products):

        await query.answer(
            "❌ Product မတွေ့ပါ",
            show_alert=True,
        )

        return

    product = products[index]

    amount = product.get(
        "amount",
        "?",
    )

    price = get_mmk_price(
        server,
        amount,
    )

    if price is None:

        await query.answer(
            "⚠️ ဒီ Amount အတွက် MMK price မရှိသေးပါ",
            show_alert=True,
        )

        return

    context.user_data["server"] = server
    context.user_data["product"] = product

    context.user_data["state"] = (
        "order_player_id"
    )

    await query.answer()

    await query.edit_message_text(
        "🛒 <b>Order Information</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🌍 Server: <b>{html.escape(server)}</b>\n"
        f"💎 Diamond: <b>{html.escape(str(amount))}</b>\n"
        f"💰 Price: <b>{format_mmk(price)}</b>\n\n"
        "🆔 <b>Player ID</b> ထည့်ပါ။\n\n"
        "ဥပမာ: <code>12345678</code>",
        parse_mode="HTML",
        )
    # =========================================================
# ADMIN / USER ACCESS
# =========================================================

ADMIN_ID = 5698123475


def is_admin(user_id):
    return int(user_id) == ADMIN_ID


def access_allowed(user_id):
    if is_admin(user_id):
        return True

    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_access (
                user_id INTEGER PRIMARY KEY,
                status TEXT DEFAULT 'pending'
            )
        """)

        cur.execute(
            "SELECT status FROM bot_access WHERE user_id=?",
            (int(user_id),)
        )

        row = cur.fetchone()
        conn.commit()
        conn.close()

        return row and row[0] == "approved"

    except Exception as e:
        print("Access check error:", e)
        return False


def create_access_request(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_access (
            user_id INTEGER PRIMARY KEY,
            status TEXT DEFAULT 'pending'
        )
    """)

    cur.execute("""
        INSERT OR IGNORE INTO bot_access
        (user_id, status)
        VALUES (?, 'pending')
    """, (int(user_id),))

    conn.commit()
    conn.close()


async def send_access_request(
    update,
    context,
):

    user = update.effective_user

    create_access_request(
        user.id
    )

    name = html.escape(
        user.full_name or "Unknown"
    )

    username = (
        f"@{html.escape(user.username)}"
        if user.username
        else "No Username"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=f"approve:{user.id}",
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"reject:{user.id}",
            ),
        ]
    ])

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🔔 <b>NEW USER ACCESS REQUEST</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 Name: <b>{name}</b>\n"
                f"🔹 Username: {username}\n"
                f"🆔 ID: <code>{user.id}</code>\n\n"
                "အောက်က button နဲ့ Access ခွင့်ပြုပါ။"
            ),
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception as e:
        print("Admin request error:", e)


# =========================================================
# START
# =========================================================

async def start_command(
    update,
    context,
):

    user = update.effective_user

    if not is_admin(user.id):

        if not access_allowed(user.id):

            create_access_request(
                user.id
            )

            await update.message.reply_text(
                "🔐 <b>Access Request</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "ဒီ Bot ကိုအသုံးပြုရန် "
                "Admin Approval လိုအပ်ပါတယ်။\n\n"
                "⏳ Request ကို Admin ဆီ "
                "ပို့ထားပါတယ်။\n"
                "✅ Approve ဖြစ်ရင် Bot ကို "
                "အသုံးပြုနိုင်ပါမယ်။",
                parse_mode="HTML",
            )

            await send_access_request(
                update,
                context,
            )

            return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💎 Diamonds",
                callback_data="menu:diamonds",
            )
        ],
        [
            InlineKeyboardButton(
                "💰 Balance",
                callback_data="menu:balance",
            ),
            InlineKeyboardButton(
                "🔌 API Status",
                callback_data="menu:api",
            )
        ]
    ])

    await update.message.reply_text(
        "✨ <b>Eren's Diamond Bot</b> ✨\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💎 <b>MLBB Diamond Top-Up</b>\n\n"
        "🛒 <b>Choose your service:</b>",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


# =========================================================
# ADMIN APPROVE / REJECT
# =========================================================

async def access_callback(
    update,
    context,
):

    query = update.callback_query

    if not is_admin(query.from_user.id):
        await query.answer(
            "❌ Admin only",
            show_alert=True,
        )
        return

    action, user_id = query.data.split(
        ":",
        1,
    )

    user_id = int(user_id)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_access (
            user_id INTEGER PRIMARY KEY,
            status TEXT DEFAULT 'pending'
        )
    """)

    if action == "approve":

        cur.execute("""
            INSERT INTO bot_access
            (user_id, status)
            VALUES (?, 'approved')
            ON CONFLICT(user_id)
            DO UPDATE SET status='approved'
        """, (user_id,))

        message = (
            "✅ <b>ACCESS APPROVED</b>\n"
            f"🆔 <code>{user_id}</code>"
        )

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🎉 <b>Access Approved!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    "✅ Admin က သင့်ကို "
                    "Bot အသုံးပြုခွင့်ပေးလိုက်ပါပြီ။\n\n"
                    "👉 /start ကိုနှိပ်ပြီး "
                    "စတင်အသုံးပြုနိုင်ပါတယ်။"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            print("User notify error:", e)

    else:

        cur.execute("""
            INSERT INTO bot_access
            (user_id, status)
            VALUES (?, 'rejected')
            ON CONFLICT(user_id)
            DO UPDATE SET status='rejected'
        """, (user_id,))

        message = (
            "❌ <b>ACCESS REJECTED</b>\n"
            f"🆔 <code>{user_id}</code>"
        )

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "❌ <b>Access Rejected</b>\n\n"
                    "Admin မှ Bot အသုံးပြုခွင့် "
                    "မပြုသေးပါ။"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            print("User notify error:", e)

    conn.commit()
    conn.close()

    await query.answer()

    await query.edit_message_text(
        message,
        parse_mode="HTML",
    )


# =========================================================
# HANDLERS
# =========================================================

application.add_handler(
    CommandHandler(
        "start",
        start_command,
    )
)

application.add_handler(
    CallbackQueryHandler(
        access_callback,
        pattern=r"^(approve|reject):\d+$",
    )
)

# =========================================================
# MAIN — RUN BOT
# =========================================================

if __name__ == "__main__":

    print("✨ Eren's Diamond Bot Starting...")
    print("👑 Admin ID:", ADMIN_ID)
    print("🚀 Bot is running...")

    application.run_polling(
        drop_pending_updates=True
)
