import os
import re
import time
import logging
import requests

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
MELO_API_KEY = os.environ["MELO_API_KEY"]
MELO_SECRET_KEY = os.environ["MELO_SECRET_KEY"]

MELO_BASE_URL = "https://api.melostore.id"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================
# API
# =========================

def melo_headers():
    return {
        "X-API-Key": MELO_API_KEY,
        "X-Secret-Key": MELO_SECRET_KEY,
        "Content-Type": "application/json",
    }


def api_get(path, params=None, timeout=30):
    try:
        r = requests.get(
            MELO_BASE_URL + path,
            headers=melo_headers(),
            params=params,
            timeout=timeout,
        )

        try:
            data = r.json()
        except Exception:
            data = {}

        return r.status_code, data

    except Exception as e:
        logger.exception("GET API error")
        return 0, {
            "success": False,
            "message": str(e),
        }


def api_post(path, payload, timeout=30):
    try:
        r = requests.post(
            MELO_BASE_URL + path,
            headers=melo_headers(),
            json=payload,
            timeout=timeout,
        )

        try:
            data = r.json()
        except Exception:
            data = {}

        return r.status_code, data

    except Exception as e:
        logger.exception("POST API error")
        return 0, {
            "success": False,
            "message": str(e),
        }


def get_profile():
    return api_get("/api/v1/h2h/profile")


def get_balance():
    return api_get("/api/v1/h2h/profile/balance")


# =========================
# PRICE CACHE
# =========================

PRICE_CACHE = {
    "time": 0,
    "products": [],
}

CACHE_SECONDS = 60


def is_mlbb_product(product, brand_name=""):
    name = str(product.get("name", "")).lower()
    type_name = str(product.get("type_name", "")).lower()
    category = str(product.get("category_name", "")).lower()
    brand = str(brand_name).lower()

    text = f"{name} {type_name} {category} {brand}"

    return (
        "mobile legends" in text
        or "mlbb" in text
        or "ml diamonds" in text
    )


def classify_server(product, brand_name=""):
    name = str(product.get("name", "")).lower()
    server_name = str(
        product.get("server_name", "")
    ).lower()
    server_code = str(
        product.get("server_code", "")
    ).lower()
    brand = str(brand_name).lower()

    text = (
        f"{name} "
        f"{server_name} "
        f"{server_code} "
        f"{brand}"
    )

    if (
        "indonesia" in text
        or "(id)" in text
        or server_code.startswith("id")
    ):
        return "Indonesia"

    if (
        "malaysia" in text
        or "(my)" in text
        or server_code.startswith("my")
    ):
        return "Malaysia"

    if (
        "global" in text
        or "worldwide" in text
        or "international" in text
        or "(gl)" in text
        or server_code.startswith("gl")
    ):
        return "Global"

    return None


def extract_diamond_amount(name):
    match = re.search(
        r"([\d.,]+)\s*(?:diamonds?|dia)",
        str(name),
        re.IGNORECASE,
    )

    if not match:
        return 999999999

    raw = match.group(1)
    raw = raw.replace(".", "")
    raw = raw.replace(",", "")

    try:
        return int(raw)
    except Exception:
        return 999999999


def load_all_ml_products(force=False):
    now = time.time()

    if (
        not force
        and PRICE_CACHE["products"]
        and now - PRICE_CACHE["time"] < CACHE_SECONDS
    ):
        return PRICE_CACHE["products"]

    all_products = []
    cursor = None

    for _ in range(30):

        params = {
            "limit": 1000,
        }

        if cursor:
            params["cursor"] = cursor

        status, data = api_get(
            "/api/v1/h2h/pricelists",
            params=params,
            timeout=30,
        )

        if status != 200 or not data.get("success"):
            logger.error(
                "Pricelist error: %s %s",
                status,
                data,
            )
            break

        rows = data.get("data", [])
        meta = data.get("meta", {})

        brands = meta.get("brands", [])
        brand_map = {}

        for brand in brands:
            try:
                brand_map[
                    int(brand.get("id"))
                ] = brand.get("name", "")
            except Exception:
                pass

        for product in rows:

            if product.get("status") != "active":
                continue

            brand_id = product.get("brand_id")

            try:
                brand_name = brand_map.get(
                    int(brand_id),
                    "",
                )
            except Exception:
                brand_name = ""

            if not is_mlbb_product(
                product,
                brand_name,
            ):
                continue

            item = dict(product)

            item["_brand_name"] = brand_name

            item["_server_label"] = classify_server(
                product,
                brand_name,
            )

            all_products.append(item)

        pagination = meta.get(
            "pagination",
            {},
        )

        if not pagination.get("has_more"):
            break

        next_cursor = pagination.get(
            "next_cursor"
        )

        if not next_cursor:
            break

        cursor = next_cursor

        time.sleep(0.15)

    PRICE_CACHE["products"] = all_products
    PRICE_CACHE["time"] = time.time()

    logger.info(
        "Loaded %s MLBB products",
        len(all_products),
    )

    return all_products

# =========================
# KEYBOARDS
# =========================

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("💎 Diamonds")],
            [
                KeyboardButton("💰 Balance"),
                KeyboardButton("🔌 API Status"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def server_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🌎 Global Server")],
            [KeyboardButton("🇲🇾 Malaysia Server")],
            [KeyboardButton("🇮🇩 Indonesia Server")],
            [
                KeyboardButton("🔙 Back"),
                KeyboardButton("🏠 Home"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def package_keyboard(products, context):
    buttons = []
    package_map = {}

    for index, product in enumerate(products):

        name = product.get(
            "name",
            "Diamonds",
        )

        price = product.get(
            "price",
            0,
        )

        try:
            price_text = f"{float(price):,.0f}"
        except Exception:
            price_text = str(price)

        button_text = (
            f"💎 {name} • "
            f"{price_text} MC"
        )

        if button_text in package_map:
            button_text += f" #{index + 1}"

        package_map[button_text] = product

        buttons.append(
            KeyboardButton(button_text)
        )

    context.user_data[
        "package_map"
    ] = package_map

    keyboard = []

    for i in range(0, len(buttons), 2):
        keyboard.append(
            buttons[i:i + 2]
        )

    keyboard.append(
        [
            KeyboardButton("🔙 Servers"),
            KeyboardButton("🏠 Home"),
        ]
    )

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True,
    )


def id_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("❌ Cancel")]
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def confirm_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("✅ Confirm Order")],
            [KeyboardButton("❌ Cancel")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


# =========================
# START
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data.clear()

    text = (
        "✨ <b>Eren's Diamond Bot</b> ✨\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💎 <b>MLBB Diamond Top-Up</b>\n\n"
        "🛒 Choose your service:\n\n"
        "💎 Diamonds\n"
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


# =========================
# BALANCE
# =========================

async def show_balance(update):

    status, data = get_balance()

    if (
        status != 200
        or not data.get("success")
    ):
        await update.message.reply_text(
            "❌ Balance မရယူနိုင်ပါ။\n\n"
            "ခဏနေပြီး ပြန်စမ်းကြည့်ပါ။",
            reply_markup=main_keyboard(),
        )
        return

    d = data.get(
        "data",
        data,
    )

    mc = d.get(
        "h2h_balance",
        0,
    )

    usd = d.get(
        "h2h_balance_usd",
        0,
    )

    rate = d.get(
        "usd_idr_rate",
        0,
    )

    sandbox = d.get(
        "is_sandbox_mode",
        False,
    )

    try:
        mc_text = f"{float(mc):,.2f}"
    except Exception:
        mc_text = str(mc)

    try:
        usd_text = f"${float(usd):,.2f}"
    except Exception:
        usd_text = str(usd)

    try:
        rate_text = f"{float(rate):,.0f}"
    except Exception:
        rate_text = str(rate)

    mode = (
        "🧪 Sandbox Mode"
        if sandbox
        else "🚀 Production Mode"
    )

    text = (
        "💰 <b>Bot Balance</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🪙 <b>MC Balance</b>\n"
        f"{mc_text} MC\n\n"
        "💵 <b>USD Value</b>\n"
        f"{usd_text}\n\n"
        "💱 <b>USD / IDR Rate</b>\n"
        f"{rate_text}\n\n"
        "⚙️ <b>Mode</b>\n"
        f"{mode}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎴 Eren Shop"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# =========================
# API STATUS
# =========================

async def show_api_status(update):

    status, data = get_profile()

    if (
        status == 200
        and data.get("success")
    ):

        d = data.get(
            "data",
            data,
        )

        sandbox = d.get(
            "is_sandbox_mode",
            d.get(
                "sandbox_mode",
                False,
            ),
        )

        mode = (
            "🧪 Sandbox"
            if sandbox
            else "🚀 Production"
        )

        text = (
            "🔌 <b>API Status</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🟢 API Connection: "
            "<b>Online</b>\n"
            f"⚙️ Mode: <b>{mode}</b>\n"
            "🔐 Authentication: "
            "<b>OK</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ Powered by Eren"
        )

    else:

        text = (
            "🔌 <b>API Status</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔴 API Connection: "
            "<b>Offline / Error</b>\n\n"
            "ခဏနေပြီး ပြန်စမ်းကြည့်ပါ။"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# =========================
# SERVER SELECTION
# =========================

async def show_servers(
    update,
    context,
):

    context.user_data.clear()

    text = (
        "🌍 <b>Choose Server</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌎 Global Server\n"
        "🇲🇾 Malaysia Server\n"
        "🇮🇩 Indonesia Server\n\n"
        "💡 Server အလိုက် Dia Package "
        "နဲ့ Price သီးခြားစီပြပေးပါမယ်။\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ Powered by Eren"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=server_keyboard(),
    )


# =========================
# SHOW PACKAGES
# =========================

async def show_packages(
    update,
    context,
    server_label,
):

    await update.message.reply_text(
        "⏳ <b>Dia Packages ရှာနေပါတယ်...</b>",
        parse_mode="HTML",
    )

    products = load_all_ml_products()

    server_products = [
        p for p in products
        if p.get("_server_label")
        == server_label
    ]

    server_products.sort(
        key=lambda p: (
            extract_diamond_amount(
                p.get("name", "")
            ),
            float(
                p.get("price", 0)
                or 0
            ),
        )
    )

    if not server_products:

        await update.message.reply_text(
            "⚠️ ဒီ Server အတွက် "
            "Dia Package မတွေ့ပါ။\n\n"
            "API ထဲက server/brand "
            "name ကိုစစ်ဖို့လိုပါတယ်။",
            reply_markup=server_keyboard(),
        )
        return

    context.user_data[
        "selected_server"
    ] = server_label

    context.user_data[
        "stage"
    ] = "select_package"

    text = (
        f"💎 <b>{server_label} Server</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 <b>{len(server_products)}</b> "
        "Packages Available\n\n"
        "ကိုယ်လိုချင်တဲ့ Dia Amount "
        "ကိုရွေးပါ 👇\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ Powered by Eren"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=package_keyboard(
            server_products,
            context,
        ),
    )


# =========================
# ASK PLAYER ID
# =========================

async def ask_player_id(
    update,
    context,
):

    context.user_data[
        "stage"
    ] = "player_id"

    await update.message.reply_text(
        "🆔 <b>Player ID ထည့်ပါ</b>\n\n"
        "ဥပမာ - <code>47486147</code>\n\n"
        "Player ID ပဲထည့်ပါ။",
        parse_mode="HTML",
        reply_markup=id_keyboard(),
    )


async def ask_zone_id(
    update,
    context,
):

    context.user_data[
        "stage"
    ] = "zone_id"

    await update.message.reply_text(
        "🌐 <b>Zone ID ထည့်ပါ</b>\n\n"
        "ဥပမာ - <code>2076</code>\n\n"
        "Zone ID ပဲထည့်ပါ။",
        parse_mode="HTML",
        reply_markup=id_keyboard(),
    )


# =========================
# NICKNAME CHECK
# =========================

def check_nickname(
    player_id,
    zone_id,
):

    payload = {
        "game_code": "mobile-legends",
        "customer_target": player_id,
        "customer_target_zone": zone_id,
    }

    return api_post(
        "/api/v1/h2h/check-nickname",
        payload,
    )


# =========================
# PURCHASE LIMIT
# =========================

def check_purchase_limit(
    player_id,
    zone_id,
):

    payload = {
        "customer_target": player_id,
        "customer_target_zone": zone_id,
    }

    return api_post(
        "/api/v1/h2h/mobile-legends/purchase-limit",
        payload,
    )

# =========================
# LIMIT CHECK
# =========================

def limit_reached_for_product(
    limit_data,
    product,
):
    sku = str(
        product.get("sku_code", "")
    ).lower()

    amount = extract_diamond_amount(
        product.get("name", "")
    )

    items = []

    weekly = limit_data.get(
        "weekly_pass",
        {},
    )

    double = limit_data.get(
        "double_diamonds",
        {},
    )

    items.extend(
        weekly.get("items", [])
        or []
    )

    items.extend(
        double.get("items", [])
        or []
    )

    for item in items:

        code = str(
            item.get(
                "package_code",
                "",
            )
        ).lower()

        if not code:
            continue

        if (
            code == sku
            and item.get(
                "limit_reached"
            )
        ):
            return True

        digits = re.findall(
            r"\d+",
            code,
        )

        if digits:
            try:
                if (
                    int(digits[-1])
                    == amount
                    and item.get(
                        "limit_reached"
                    )
                ):
                    return True
            except Exception:
                pass

    return False


# =========================
# CONFIRMATION
# =========================

async def show_confirmation(
    update,
    context,
):

    product = context.user_data.get(
        "product"
    )

    if not product:
        await update.message.reply_text(
            "❌ Product session မတွေ့ပါ။",
            reply_markup=main_keyboard(),
        )
        return

    server = context.user_data.get(
        "selected_server",
        "Unknown",
    )

    player_id = context.user_data.get(
        "player_id",
        "",
    )

    zone_id = context.user_data.get(
        "zone_id",
        "",
    )

    nickname = context.user_data.get(
        "nickname",
        "Unknown",
    )

    price = product.get(
        "price",
        0,
    )

    try:
        price_text = f"{float(price):,.0f}"
    except Exception:
        price_text = str(price)

    text = (
        "🛒 <b>Confirm Order</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🌍 Server: <b>{server}</b>\n"
        f"💎 Package: <b>{product.get('name')}</b>\n"
        f"💰 Price: <b>{price_text} MC</b>\n\n"
        f"🆔 Player ID: "
        f"<code>{player_id}</code>\n"
        f"🌐 Zone ID: "
        f"<code>{zone_id}</code>\n"
        f"👤 Nickname: "
        f"<b>{nickname}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "အချက်အလက်မှန်ကန်ရင် "
        "Confirm လုပ်ပါ။"
    )

    context.user_data[
        "stage"
    ] = "confirm"

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=confirm_keyboard(),
    )


# =========================
# CREATE TRANSACTION
# =========================

def create_transaction(
    product,
    player_id,
    zone_id,
    buyer_trx_id,
):

    payload = {
        "sku_code": product.get(
            "sku_code"
        ),
        "customer_target": player_id,
        "customer_target_zone": zone_id,
        "buyer_trx_id": buyer_trx_id,
    }

    return api_post(
        "/api/v1/h2h/transaction",
        payload,
        timeout=40,
    )


# =========================
# TRANSACTION STATUS
# =========================

def get_transaction_status(
    transaction_id,
):

    return api_get(
        f"/api/v1/h2h/transaction/{transaction_id}",
        timeout=20,
    )


# =========================
# MESSAGE HANDLER
# =========================

async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if (
        not update.message
        or not update.message.text
    ):
        return

    text = update.message.text.strip()

    stage = context.user_data.get(
        "stage",
        "",
    )

    # MAIN MENU
    if text == "💎 Diamonds":

        await show_servers(
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

    if text == "🏠 Home":

        context.user_data.clear()

        await start(
            update,
            context,
        )
        return

    # BACK
    if text == "🔙 Back":

        await start(
            update,
            context,
        )
        return

    if text == "🔙 Servers":

        await show_servers(
            update,
            context,
        )
        return

    # SERVERS
    if text == "🌎 Global Server":

        await show_packages(
            update,
            context,
            "Global",
        )
        return

    if text == "🇲🇾 Malaysia Server":

        await show_packages(
            update,
            context,
            "Malaysia",
        )
        return

    if text == "🇮🇩 Indonesia Server":

        await show_packages(
            update,
            context,
            "Indonesia",
        )
        return

    # CANCEL
    if text == "❌ Cancel":

        context.user_data.clear()

        await update.message.reply_text(
            "❌ <b>Order Cancelled</b>",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    # PACKAGE
    if stage == "select_package":

        package_map = context.user_data.get(
            "package_map",
            {},
        )

        product = package_map.get(text)

        if not product:
            return

        context.user_data[
            "product"
        ] = product

        await ask_player_id(
            update,
            context,
        )
        return

    # PLAYER ID
    if stage == "player_id":

        if not text.isdigit():

            await update.message.reply_text(
                "❌ Player ID က "
                "နံပါတ်ပဲ ဖြစ်ရပါမယ်။\n\n"
                "ဥပမာ - "
                "<code>47486147</code>",
                parse_mode="HTML",
                reply_markup=id_keyboard(),
            )
            return

        context.user_data[
            "player_id"
        ] = text

        await ask_zone_id(
            update,
            context,
        )
        return

    # ZONE ID
    if stage == "zone_id":

        if not text.isalnum():

            await update.message.reply_text(
                "❌ Zone ID မမှန်ပါ။\n\n"
                "ဥပမာ - <code>2076</code>",
                parse_mode="HTML",
                reply_markup=id_keyboard(),
            )
            return

        context.user_data[
            "zone_id"
        ] = text

        await update.message.reply_text(
            "🔍 <b>Nickname စစ်နေပါတယ်...</b>",
            parse_mode="HTML",
        )

        player_id = context.user_data[
            "player_id"
        ]

        status, data = check_nickname(
            player_id,
            text,
        )

        if (
            status != 200
            or not data.get("success")
        ):

            message = data.get(
                "message",
                "Nickname check failed",
            )

            await update.message.reply_text(
                "❌ <b>Nickname Check Failed</b>\n\n"
                f"{message}\n\n"
                "Player ID / Zone ID "
                "ကို ပြန်စစ်ပါ။",
                parse_mode="HTML",
                reply_markup=id_keyboard(),
            )

            context.user_data[
                "stage"
            ] = "player_id"

            return

        d = data.get(
            "data",
            {},
        )

        nickname = d.get(
            "username",
            "Unknown",
        )

        region = d.get(
            "region",
            "-",
        )

        context.user_data[
            "nickname"
        ] = nickname

        context.user_data[
            "region"
        ] = region

        # PURCHASE LIMIT
        await update.message.reply_text(
            "📋 <b>Purchase Limit စစ်နေပါတယ်...</b>",
            parse_mode="HTML",
        )

        limit_status, limit_response = (
            check_purchase_limit(
                player_id,
                text,
            )
        )

        if (
            limit_status != 200
            or not limit_response.get(
                "success"
            )
        ):

            await update.message.reply_text(
                "⚠️ Purchase Limit "
                "စစ်မရပါ။\n\n"
                "ခဏနေပြီး ပြန်စမ်းပါ။",
                reply_markup=main_keyboard(),
            )

            context.user_data.clear()

            return

        limit_data = limit_response.get(
            "data",
            {},
        )

        product = context.user_data.get(
            "product"
        )

        if limit_reached_for_product(
            limit_data,
            product,
        ):

            await update.message.reply_text(
                "❌ <b>Purchase Limit Reached</b>\n\n"
                f"👤 Nickname: "
                f"<b>{nickname}</b>\n"
                f"🌍 Region: "
                f"<b>{region}</b>\n\n"
                "ဒီ Package ကို "
                "လက်ရှိဝယ်လို့မရပါ။",
                parse_mode="HTML",
                reply_markup=main_keyboard(),
            )

            context.user_data.clear()

            return

        await show_confirmation(
            update,
            context,
        )

        return

    # CONFIRM ORDER
    if text == "✅ Confirm Order":

        if stage != "confirm":
            return

        product = context.user_data.get(
            "product"
        )

        player_id = context.user_data.get(
            "player_id"
        )

        zone_id = context.user_data.get(
            "zone_id"
        )

        if (
            not product
            or not player_id
            or not zone_id
        ):

            await update.message.reply_text(
                "❌ Order information "
                "မပြည့်စုံပါ။",
                reply_markup=main_keyboard(),
            )

            context.user_data.clear()

            return

        user_id = update.effective_user.id
        timestamp = int(time.time())

        buyer_trx_id = (
            f"eren_{user_id}_{timestamp}"
        )

        await update.message.reply_text(
            "🛒 <b>Order တင်နေပါတယ်...</b>\n\n"
            "⏳ ကျေးဇူးပြုပြီး ခဏစောင့်ပါ။",
            parse_mode="HTML",
        )

        status, data = create_transaction(
            product,
            player_id,
            zone_id,
            buyer_trx_id,
        )

        if status not in (200, 201):

            message = data.get(
                "message",
                "Transaction failed",
            )

            await update.message.reply_text(
                "❌ <b>Order Failed</b>\n\n"
                f"{message}",
                parse_mode="HTML",
                reply_markup=main_keyboard(),
            )

            context.user_data.clear()

            return

        if not data.get(
            "success",
            True,
        ):

            await update.message.reply_text(
                "❌ <b>Order Failed</b>\n\n"
                f"{data.get('message', 'Unknown error')}",
                parse_mode="HTML",
                reply_markup=main_keyboard(),
            )

            context.user_data.clear()

            return

        transaction = data.get(
            "data",
            data,
        )

        transaction_id = transaction.get(
            "id",
            buyer_trx_id,
        )

        product_name = product.get(
            "name",
            "MLBB Diamonds",
        )

        nickname = context.user_data.get(
            "nickname",
            "-",
        )

        await update.message.reply_text(
            "✅ <b>Order Created</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💎 {product_name}\n"
            f"👤 {nickname}\n"
            f"🆔 Player ID: "
            f"<code>{player_id}</code>\n"
            f"🌐 Zone ID: "
            f"<code>{zone_id}</code>\n"
            f"🧾 Order ID: "
            f"<code>{buyer_trx_id}</code>\n\n"
            "⏳ <b>Status: Pending</b>\n\n"
            "⚡ Powered by Eren",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )

        # Immediate status check
        time.sleep(1)

        check_status, check_data = (
            get_transaction_status(
                transaction_id
            )
        )

        if (
            check_status == 200
            and check_data.get("success")
        ):

            td = check_data.get(
                "data",
                {},
            )

            final_status = td.get(
                "status",
                "pending",
            )

            if final_status == "success":

                serial = td.get(
                    "serial_number",
                    "-",
                )

                await update.message.reply_text(
                    "🎉 <b>TOP-UP SUCCESS</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"💎 {product_name}\n"
                    f"👤 {nickname}\n"
                    f"🆔 <code>{player_id}</code>\n"
                    f"🌐 <code>{zone_id}</code>\n\n"
                    f"🎫 Serial: "
                    f"<code>{serial}</code>\n\n"
                    "⚡ Powered by Eren",
                    parse_mode="HTML",
                    reply_markup=main_keyboard(),
                )

            elif final_status == "failed":

                error_message = td.get(
                    "message",
                    "Transaction failed",
                )

                await update.message.reply_text(
                    "❌ <b>TOP-UP FAILED</b>\n\n"
                    f"{error_message}\n\n"
                    "⚡ Powered by Eren",
                    parse_mode="HTML",
                    reply_markup=main_keyboard(),
                )

        context.user_data.clear()

        return


# =========================
# MAIN
# =========================

def main():

    print(
        "🤖 Eren's Diamond Bot "
        "is starting..."
    )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            message_handler,
        )
    )

    print(
        "✅ Bot is running!"
    )

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
