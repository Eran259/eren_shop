import os
import logging
import requests

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ═══════════════════════════════════════
# ⚙️ CONFIG
# ═══════════════════════════════════════

BOT_TOKEN = os.environ["BOT_TOKEN"]

MELO_API_KEY = os.environ["MELO_API_KEY"]
MELO_SECRET_KEY = os.environ["MELO_SECRET_KEY"]

MELO_BASE_URL = "https://api.melostore.id"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# 🔐 MELOSTORE API
# ═══════════════════════════════════════

def melo_headers():
    return {
        "X-API-Key": MELO_API_KEY,
        "X-Secret-Key": MELO_SECRET_KEY,
    }


def get_profile():
    url = f"{MELO_BASE_URL}/api/v1/h2h/profile"

    response = requests.get(
        url,
        headers=melo_headers(),
        timeout=30,
    )

    response.raise_for_status()
    return response.json()


def get_balance():
    url = f"{MELO_BASE_URL}/api/v1/h2h/profile/balance"

    response = requests.get(
        url,
        headers=melo_headers(),
        timeout=30,
    )

    response.raise_for_status()
    return response.json()


def get_pricelists():
    url = f"{MELO_BASE_URL}/api/v1/h2h/pricelists"

    response = requests.get(
        url,
        headers=melo_headers(),
        params={"limit": 500},
        timeout=30,
    )

    response.raise_for_status()
    return response.json()


# ═══════════════════════════════════════
# 🏠 START
# ═══════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [
            InlineKeyboardButton(
                "💎 MLBB Diamonds",
                callback_data="products"
            )
        ],
        [
            InlineKeyboardButton(
                "💰 H2H Balance",
                callback_data="balance"
            )
        ],
        [
            InlineKeyboardButton(
                "🔌 API Status",
                callback_data="api_status"
            )
        ],
    ]

    text = """
✨ <b>Eren's Diamond Bot</b> ✨
━━━━━━━━━━━━━━━━━━━━

💎 <b>MLBB Diamond Top-Up</b>

🛒 Choose your service below.

━━━━━━━━━━━━━━━━━━━━
⚡ Powered by Melostore H2H
"""

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
        )

# ═══════════════════════════════════════
# 💰 H2H BALANCE
# ═══════════════════════════════════════

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    try:
        result = get_balance()

        if not result.get("success"):
            await query.edit_message_text(
                "❌ <b>Balance Check Failed</b>",
                parse_mode="HTML",
            )
            return

        data = result.get("data", {})

        balance_mc = float(data.get("h2h_balance", 0))
        balance_usd = float(data.get("h2h_balance_usd", 0))
        rate = float(data.get("usd_idr_rate", 0))

        sandbox = data.get(
            "is_sandbox_mode",
            False
        )

        mode = (
            "🧪 Sandbox Mode"
            if sandbox
            else "🚀 Production Mode"
        )

        text = f"""
💰 <b>H2H Balance</b>
━━━━━━━━━━━━━━━━━━━━

🪙 MC Balance
<b>{balance_mc:,.2f} MC</b>

💵 USD Value
<b>${balance_usd:,.2f}</b>

💱 USD / IDR Rate
<b>{rate:,.0f}</b>

⚙️ Mode
<b>{mode}</b>

━━━━━━━━━━━━━━━━━━━━
🔐 Melostore H2H
"""

        keyboard = [
            [
                InlineKeyboardButton(
                    "🔄 Refresh",
                    callback_data="balance"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 Home",
                    callback_data="home"
                )
            ],
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    except requests.HTTPError as e:

        logger.error(
            "Balance HTTP error: %s",
            e
        )

        await query.edit_message_text(
            "❌ <b>Balance API Error</b>\n\n"
            "⏳ Please try again later.",
            parse_mode="HTML",
        )

    except Exception as e:

        logger.error(
            "Balance error: %s",
            e
        )

        await query.edit_message_text(
            "❌ <b>Unable to check balance.</b>\n\n"
            "🔧 Please check Railway Variables.",
            parse_mode="HTML",
        )


# ═══════════════════════════════════════
# 📦 PRODUCT / PRICELIST
# ═══════════════════════════════════════

async def products(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "📦 <b>Loading Products...</b>\n\n"
        "⏳ Please wait...",
        parse_mode="HTML",
    )

    try:

        result = get_pricelists()

        if not result.get("success"):

            await query.edit_message_text(
                "❌ <b>Unable to load products.</b>",
                parse_mode="HTML",
            )
            return

        products_data = result.get(
            "data",
            []
        )

        meta = result.get(
            "meta",
            {}
        )

        brands = meta.get(
            "brands",
            []
        )

        # ═══════════════════════════════
        # 🔎 BRAND LOOKUP
        # ═══════════════════════════════

        brand_map = {}

        for brand in brands:

            brand_id = brand.get("id")

            brand_name = brand.get(
                "name",
                ""
            )

            brand_map[brand_id] = brand_name

        # ═══════════════════════════════
        # 💎 FIND MLBB PRODUCTS
        # ═══════════════════════════════

        ml_products = []

        for product in products_data:

            if product.get("status") != "active":
                continue

            brand_id = product.get(
                "brand_id"
            )

            brand_name = str(
                brand_map.get(
                    brand_id,
                    ""
                )
            ).lower()

            type_name = str(
                product.get(
                    "type_name",
                    ""
                )
            ).lower()

            product_name = str(
                product.get(
                    "name",
                    ""
                )
            ).lower()

            is_mlbb = (
                "mobile legends" in brand_name
                or "mobile legends" in type_name
                or "ml diamonds" in type_name
                or "mobile legends" in product_name
            )

            if is_mlbb:
                ml_products.append(product)

        # ═══════════════════════════════
        # ⚠️ NO MLBB PRODUCTS
        # ═══════════════════════════════

        if not ml_products:

            await query.edit_message_text(
                "⚠️ <b>MLBB Products Not Found</b>\n\n"
                "📦 No active Mobile Legends "
                "products were detected.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🔄 Refresh",
                            callback_data="products"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🏠 Home",
                            callback_data="home"
                        )
                    ],
                ]),
            )

            return

        # ═══════════════════════════════
        # 💰 SORT BY PRICE
        # ═══════════════════════════════

        def product_price(product):

            try:
                return float(
                    product.get(
                        "price",
                        0
                    )
                )

            except (TypeError, ValueError):
                return 0

        ml_products.sort(
            key=product_price
        )

        # Show maximum 20 products
        display_products = ml_products[:20]

        keyboard = []

        for product in display_products:

            name = product.get(
                "name",
                "Unknown Product"
            )

            price = product.get(
                "price",
                0
            )

            sku = product.get(
                "sku_code",
                ""
            )

            server = product.get(
                "server_code",
                ""
            )

            button_text = (
                f"💎 {name} "
                f"• {price:,.0f} MC"
            )

            if server:
                button_text += (
                    f" • {server}"
                )

            keyboard.append([
                InlineKeyboardButton(
                    button_text[:64],
                    callback_data=f"product:{sku}"
                )
            ])

        # ═══════════════════════════════
        # 🔄 BUTTONS
        # ═══════════════════════════════

        keyboard.append([
            InlineKeyboardButton(
                "🔄 Refresh",
                callback_data="products"
            ),
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="home"
            ),
        ])

        text = f"""
💎 <b>Mobile Legends Diamonds</b>
━━━━━━━━━━━━━━━━━━━━

📦 Available:
<b>{len(ml_products)}</b> products

✨ Choose your Diamond package:

━━━━━━━━━━━━━━━━━━━━
⚡ Live Melostore Pricelist
"""

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
            parse_mode="HTML",
        )

    except requests.HTTPError as e:

        logger.error(
            "Pricelist HTTP error: %s",
            e
        )

        status_code = (
            e.response.status_code
            if e.response is not None
            else 0
        )

        if status_code == 429:

            await query.edit_message_text(
                "⏳ <b>Too Many Requests</b>\n\n"
                "📦 Pricelist API rate limit "
                "reached.\n\n"
                "🔄 Please try again shortly.",
                parse_mode="HTML",
            )

        else:

            await query.edit_message_text(
                "❌ <b>Pricelist API Error</b>\n\n"
                "⏳ Please try again later.",
                parse_mode="HTML",
            )

    except Exception as e:

        logger.error(
            "Products error: %s",
            e
        )

        await query.edit_message_text(
            "❌ <b>Product Loading Failed</b>\n\n"
            "🔧 Please check your API settings.",
            parse_mode="HTML",
        )

# ═══════════════════════════════════════
# 🔌 API STATUS
# ═══════════════════════════════════════

async def api_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query
    await query.answer()

    try:

        result = get_profile()

        if not result.get("success"):
            raise Exception("API response failed")

        data = result.get("data", {})
        tier = data.get("tier", {})

        tier_name = tier.get(
            "name",
            "Unknown"
        )

        rate_limit = tier.get(
            "rate_limit",
            "Unknown"
        )

        max_ips = tier.get(
            "max_ips",
            "Unknown"
        )

        sandbox = data.get(
            "is_sandbox_mode",
            False
        )

        mode = (
            "🧪 Sandbox Mode"
            if sandbox
            else "🚀 Production Mode"
        )

        text = f"""
🔌 <b>Melostore H2H API</b>
━━━━━━━━━━━━━━━━━━━━

🟢 Connection
<b>ONLINE</b>

🏆 Tier
<b>{tier_name}</b>

⚡ Rate Limit
<b>{rate_limit} req/min</b>

🌐 Max IPs
<b>{max_ips}</b>

⚙️ Mode
<b>{mode}</b>

━━━━━━━━━━━━━━━━━━━━
✨ API Connection Healthy
"""

        keyboard = [
            [
                InlineKeyboardButton(
                    "🔄 Refresh",
                    callback_data="api_status"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 Home",
                    callback_data="home"
                )
            ],
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    except Exception as e:

        logger.error(
            "API status error: %s",
            e
        )

        await query.edit_message_text(
            """
🔴 <b>API OFFLINE</b>
━━━━━━━━━━━━━━━━━━━━

❌ Unable to connect to
Melostore H2H API.

🔧 Check your Railway Variables.
""",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔄 Try Again",
                        callback_data="api_status"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏠 Home",
                        callback_data="home"
                    )
                ],
            ]),
        )


# ═══════════════════════════════════════
# 🏠 HOME
# ═══════════════════════════════════════

async def home(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton(
                "💎 MLBB Diamonds",
                callback_data="products"
            )
        ],
        [
            InlineKeyboardButton(
                "💰 H2H Balance",
                callback_data="balance"
            )
        ],
        [
            InlineKeyboardButton(
                "🔌 API Status",
                callback_data="api_status"
            )
        ],
    ]

    text = """
✨ <b>Eren's Diamond Bot</b> ✨
━━━━━━━━━━━━━━━━━━━━

💎 <b>MLBB Diamond Top-Up</b>

🛒 Choose your service:

💎 Diamonds
💰 H2H Balance
🔌 API Status

━━━━━━━━━━━━━━━━━━━━
⚡ Powered by Melostore H2H
"""

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


# ═══════════════════════════════════════
# 🔘 CALLBACK ROUTER
# ═══════════════════════════════════════

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query
    data = query.data

    if data == "balance":

        await balance(
            update,
            context
        )

    elif data == "products":

        await products(
            update,
            context
        )

    elif data == "api_status":

        await api_status(
            update,
            context
        )

    elif data == "home":

        await home(
            update,
            context
        )

    elif data.startswith("product:"):

        sku = data.split(
            ":",
            1
        )[1]

        await query.answer(
            f"💎 Selected: {sku}",
            show_alert=True
        )


# ═══════════════════════════════════════
# 🚀 MAIN
# ═══════════════════════════════════════

def main():

    print(
        "🤖 Eren Diamond Bot is starting..."
    )

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # /start
    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # Inline buttons
    app.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    print(
        "✅ Bot is running!"
    )

    app.run_polling()


# ═══════════════════════════════════════
# ▶️ START BOT
# ═══════════════════════════════════════

if __name__ == "__main__":
    main()
