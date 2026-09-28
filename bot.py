import os
import re
import uuid
import html
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

# Admin Telegram ID
ADMIN_ID = 5698123475

MELO_API_KEY = os.getenv("MELO_API_KEY", "")
MELO_SECRET_KEY = os.getenv("MELO_SECRET_KEY", "")

MELO_BASE_URL = "https://api.melostore.id"

# Railway မှာ true ထားချင်ရင်
# MELO_SANDBOX=true
MELO_SANDBOX = os.getenv("MELO_SANDBOX", "true").lower() == "true"


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
    """
    S1/S2 ကို Global လို့ မခန့်မှန်းဘူး။

    API ရဲ့ actual brand/server/name data ကို
    အခြေခံပြီး ခွဲတယ်။
    """

    values = [
        clean_text(product.get("name")),
        clean_text(product.get("type_name")),
        clean_text(product.get("server_name")),
        clean_text(product.get("server_code")),
        clean_text(brand_name),
        clean_text(product.get("brand_name")),
        clean_text(product.get("description")),
    ]

    text = " ".join(values).lower()

    # Indonesia
    indonesia_words = [
        "indonesia",
        "indonesian",
        "(id)",
        " id ",
        "-id",
        "_id",
    ]

    if any(word in text for word in indonesia_words):
        return "Indonesia"

    # Malaysia
    malaysia_words = [
        "malaysia",
        "malaysian",
        "(my)",
        " my ",
        "-my",
        "_my",
    ]

    if any(word in text for word in malaysia_words):
        return "Malaysia"

    # Global
    global_words = [
        "global",
        "worldwide",
        "international",
        "global server",
        "(gl)",
    ]

    if any(word in text for word in global_words):
        return "Global"

    return None


# =========================================================
# LOAD REGULAR PRICELIST
# =========================================================

def load_all_ml_products():
    """
    Melostore regular pricelist ကို pagination နဲ့ယူတယ်။

    limit = 1000
    max pages = 30
    """

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
            print("Pricelist error:", error)
            break

        if not data:
            break

        rows = data.get("data", [])

        meta = data.get("meta", {})

        brands = meta.get("brands", [])

        brand_map = {
            str(x.get("id")): x.get("name", "")
            for x in brands
        }

        for product in rows:

            if clean_text(product.get("status")).lower() != "active":
                continue

            if not is_mlbb_product(product):
                continue

            brand_name = brand_map.get(
                str(product.get("brand_id")),
                "",
            )

            server = classify_ml_server(
                product,
                brand_name,
            )

            if not server:
                continue

            item = dict(product)

            item["brand_name"] = brand_name
            item["server"] = server
            item["amount"] = normalize_product_name(
                product.get("name", "")
            )

            all_products.append(item)

        pagination = meta.get("pagination", {})

        if not pagination.get("has_more"):
            break

        cursor = pagination.get("next_cursor")

        if not cursor:
            break

    return all_products


# =========================================================
# BUILD SERVER CACHE
# =========================================================

def refresh_products():
    global PRODUCT_CACHE

    products = load_all_ml_products()

    grouped = {
        "Global": [],
        "Malaysia": [],
        "Indonesia": [],
    }

    for product in products:
        server = product.get("server")

        if server in grouped:
            grouped[server].append(product)

    # Same amount duplicate တွေကို customer UI မှာ မပြ။
    #
    # အတူတူ amount ရှိရင် API cost နည်းတဲ့ active SKU
    # တစ်ခုကိုရွေးထားမယ်။

    for server in grouped:

        unique = {}

        for product in grouped[server]:

            amount = product.get("amount")

            if not amount:
                continue

            old = unique.get(amount)

            if old is None:
                unique[amount] = product
                continue

            try:
                new_price = float(
                    product.get("price", 999999999)
                )
            except Exception:
                new_price = 999999999

            try:
                old_price = float(
                    old.get("price", 999999999)
                )
            except Exception:
                old_price = 999999999

            if new_price < old_price:
                unique[amount] = product

        grouped[server] = sorted(
            unique.values(),
            key=diamond_sort_key,
        )

    PRODUCT_CACHE = grouped

    print(
        "Products:",
        {k: len(v) for k, v in PRODUCT_CACHE.items()}
    )

    return PRODUCT_CACHE


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

async def send_new_user_alarm(update, context):
    """Send a fresh admin notification on every /start."""
    user = update.effective_user
    if not user or user.id == ADMIN_ID:
        return

    name = html.escape(user.full_name or "Unknown")
    username = (
        f"@{html.escape(user.username)}"
        if user.username else "No Username"
    )

    alarm = (
        "🆕 <b>NEW USER STARTED BOT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Name: <b>{name}</b>\n"
        f"🔹 Username: {username}\n"
        f"🆔 Telegram ID: <code>{user.id}</code>\n\n"
        "⚡ User pressed /start"
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=alarm,
            parse_mode="HTML",
        )
    except Exception as e:
        print("NEW USER ALARM ERROR:", e)

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data.clear()

    # Always create a fresh admin alarm on /start.
    await send_new_user_alarm(update, context)

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

        # Product cache မရှိရင် refresh
        if not PRODUCT_CACHE.get(server):

            await query.edit_message_text(
                "⏳ <b>Loading Diamond Products...</b>",
                parse_mode="HTML",
            )

            refresh_products()

        products = PRODUCT_CACHE.get(
            server,
            [],
        )

        if not products:

            await query.edit_message_text(
                f"❌ <b>{html.escape(server)} Server</b>\n\n"
                "ဒီ server အတွက် MLBB product မတွေ့ပါ။",
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

    text = update.message.text.strip()

    # -----------------------------------------------------
    # MAIN MENU
    # -----------------------------------------------------

    if text == "💎 MLBB Diamonds":
        try:
            await open_mlbb(update)
        except Exception as e:
            print("MLBB BUTTON ERROR:", e)
            await update.message.reply_text(
                "❌ MLBB menu ဖွင့်မရပါ။\n\n"
                f"Error: {html.escape(str(e))}"
            )
        return

    if text == "🔍 Check ML ID":
        try:
            await start_check_id(update, context)
        except Exception as e:
            print("CHECK ID BUTTON ERROR:", e)
            await update.message.reply_text(
                "❌ Check ML ID ဖွင့်မရပါ။\n\n"
                f"Error: {html.escape(str(e))}"
            )
        return

    if text == "💰 Balance":
        try:
            await show_balance(update)
        except Exception as e:
            print("BALANCE BUTTON ERROR:", e)
            await update.message.reply_text(
                "❌ Balance ဖွင့်မရပါ။\n\n"
                f"Error: {html.escape(str(e))}"
            )
        return

    if text == "🔌 API Status":
        try:
            await show_api_status(update)
        except Exception as e:
            print("API STATUS BUTTON ERROR:", e)
            await update.message.reply_text(
                "❌ API Status ဖွင့်မရပါ။\n\n"
                f"Error: {html.escape(str(e))}"
            )
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
