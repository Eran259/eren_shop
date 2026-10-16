# ============================================================
# RME Bot — RomeoSaveMe Recharge Bot
# ============================================================

import os
import re
import json
import uuid
import html
import sqlite3
import requests
import asyncio
import io
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
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

# ---------- Config ----------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = 5698123475
ALERT_CHAT_ID = int(os.getenv("ALERT_CHAT_ID", "0"))

RME_BASE_URL = "https://romeosaveme.com"
RME_API_KEY = os.getenv("RME_API_KEY", "")
MARGIN = 1.00827  # 0.827% Margin

# ---------- Data Directory ----------
DATA_DIR = os.getenv("DATA_DIR", ".")
if not os.path.exists(DATA_DIR):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        DATA_DIR = "."

USER_DB = os.path.join(DATA_DIR, "users.db")
ACCESS_DB = os.path.join(DATA_DIR, "access.db")
PRICE_DB = os.path.join(DATA_DIR, "prices.db")

print(f"📁 DATA_DIR: {DATA_DIR}")
print(f"🔔 ALERT_CHAT_ID: {ALERT_CHAT_ID}")
print(f"🌐 RME API: {RME_BASE_URL}")


# ---------- Database Init ----------
def init_db():
    # Users
    conn = sqlite3.connect(USER_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        balance REAL DEFAULT 0.0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        game TEXT,
        product TEXT,
        player_id TEXT,
        zone_id TEXT,
        price REAL,
        status TEXT DEFAULT 'pending',
        transaction_id TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

    # Access
    conn = sqlite3.connect(ACCESS_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS bot_access (
        user_id INTEGER PRIMARY KEY,
        status TEXT DEFAULT 'pending',
        requested_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

    # Manual Prices
    conn = sqlite3.connect(PRICE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS manual_price (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        name TEXT,
        price REAL,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()


init_db()

# ============================================================
# Part 2 — RomeoSaveMe API Functions
# ============================================================

def rme_headers():
    return {
        "Authorization": f"Bearer {RME_API_KEY}",
        "Content-Type": "application/json",
    }


def rme_get(path, params=None, retries=3):
    url = RME_BASE_URL + path
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=rme_headers(), params=params, timeout=120)
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


def rme_post(path, payload, retries=3):
    url = RME_BASE_URL + path
    for attempt in range(retries):
        try:
            response = requests.post(url, headers=rme_headers(), json=payload, timeout=120)
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


def rme_get_games():
    return rme_get("/api/v1/games")


def rme_get_products(slug):
    return rme_get(f"/api/v1/games/{slug}/products")


def rme_get_wallet():
    return rme_get("/api/v1/wallet")


def rme_check_player(slug, player_id, zone_id):
    inputs = [str(player_id)]
    if zone_id:
        inputs.append(str(zone_id))
    payload = {
        "gameSlug": slug,
        "inputs": inputs,
    }
    return rme_post("/api/v1/check-player", payload)


def rme_ml_region_check(player_id, zone_id):
    payload = {
        "playerId": str(player_id),
        "zoneId": str(zone_id),
        "game": "mobile_legends",
    }
    return rme_post("/api/v1/ml-region-check", payload)


def rme_create_order(product_code, player_id, zone_id):
    inputs = [str(player_id)]
    if zone_id:
        inputs.append(str(zone_id))
    payload = {
        "productCode": product_code,
        "inputs": inputs,
        "clientRef": "RME-" + uuid.uuid4().hex[:16].upper(),
    }
    return rme_post("/api/v1/orders", payload)


def rme_get_order(order_id):
    return rme_get(f"/api/v1/orders/{order_id}")


def get_final_price(base_price):
    return round(float(base_price) * MARGIN)

# ============================================================
# Part 3 — Balance System + Keyboards + Game/Package List
# ============================================================

def get_user_balance(user_id):
    conn = sqlite3.connect(USER_DB)
    row = conn.execute("SELECT balance FROM users WHERE user_id=?", (int(user_id),)).fetchone()
    conn.close()
    return row[0] if row else 0.0


def add_user_balance(user_id, amount):
    conn = sqlite3.connect(USER_DB)
    conn.execute("""INSERT INTO users (user_id, balance, created_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
        balance = balance + ?
    """, (int(user_id), float(amount), float(amount)))
    conn.commit()
    conn.close()


def deduct_user_balance(user_id, amount):
    conn = sqlite3.connect(USER_DB)
    conn.execute("""UPDATE users SET balance = balance - ?
        WHERE user_id = ? AND balance >= ?
    """, (float(amount), int(user_id), float(amount)))
    affected = conn.total_changes
    conn.commit()
    conn.close()
    return affected > 0


def save_order(user_id, game, product, player_id, zone_id, price, status, transaction_id):
    conn = sqlite3.connect(USER_DB)
    conn.execute("""INSERT INTO orders
        (user_id, game, product, player_id, zone_id, price, status, transaction_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (int(user_id), game, product, str(player_id), str(zone_id),
          float(price), status, str(transaction_id)))
    conn.commit()
    conn.close()


def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["💎 Mobile Legends", "🎮 PUBG"],
            ["🔍 Check ID", "💰 My Balance"],
            ["📦 My Orders", "💳 Deposit"],
            ["📞 Contact Admin"],
        ],
        resize_keyboard=True,
    )


def cancel_keyboard():
    return ReplyKeyboardMarkup(
        [["❌ Cancel Order"]],
        resize_keyboard=True,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.effective_user

    if not await request_access(update, context, force_request=True):
        return

    balance = get_user_balance(user.id)

    await update.message.reply_text(
        f"✨ <b>Welcome, {html.escape(user.first_name or 'User')}!</b> ✨\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🎮 <b>Game Recharge Bot</b>\n\n"
        f"💰 Balance: <b>{balance:,.0f} MMK</b>\n\n"
        "👇 Choose from the menu below",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    balance = get_user_balance(user.id)
    await update.message.reply_text(
        f"💰 <b>My Balance</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 {html.escape(user.first_name or 'User')}\n"
        f"💰 Balance: <b>{balance:,.0f} MMK</b>",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


async def show_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect(USER_DB)
    rows = conn.execute("""SELECT game, product, player_id, price, status, created_at
        FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 10
    """, (user.id,)).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text(
            "📦 <b>My Orders</b>\n\n📭 No orders yet",
            parse_mode="HTML", reply_markup=main_keyboard(),
        )
        return

    lines = ["📦 <b>My Orders</b>", "━━━━━━━━━━━━━━━━━━━━", ""]
    for game, product, player_id, price, status, created_at in rows:
        emoji = {"completed": "✅", "pending": "⏳", "failed": "❌"}.get(status, "❓")
        lines.append(f"{emoji} <b>{html.escape(game)}</b> — {html.escape(product)}")
        lines.append(f"   🆔 {html.escape(str(player_id))} | 💰 {price:,.0f} MMK")
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=main_keyboard())


async def show_game_products(update: Update, context: ContextTypes.DEFAULT_TYPE, slug: str, name: str):
    await update.message.reply_text("⏳ <b>Loading...</b>", parse_mode="HTML")
    data, error = rme_get_products(slug)
    if error:
        await update.message.reply_text(
            f"❌ <b>Error</b>\n\n{html.escape(str(error))}",
            parse_mode="HTML", reply_markup=main_keyboard(),
        )
        return

    products = data.get("products", [])
    if not products:
        await update.message.reply_text(
            f"📭 <b>{name}</b>\n\nNo products available",
            parse_mode="HTML", reply_markup=main_keyboard(),
        )
        return

    context.user_data["game_slug"] = slug
    context.user_data["game_name"] = name
    context.user_data["products"] = products

    buttons = []
    for p in products:
        code = p.get("code", "")
        pname = p.get("name", "?")
        base_price = p.get("price", 0)
        price = get_final_price(base_price)
        buttons.append([f"{pname} — {price:,.0f} Ks"])

    buttons.append(["🏠 Main Menu"])

    await update.message.reply_text(
        f"🎮 <b>{name}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 {len(products)} Packages\n\n"
        "👇 Choose a package",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True),
  )

  # ============================================================
# Part 4 — Order Flow + Check ID + Double Diamond
# ============================================================

async def show_check_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "check_id_game"
    await update.message.reply_text(
        "🔍 <b>Check ID</b>\n\n"
        "Choose a game:\n\n"
        "• <code>ml</code> — Mobile Legends\n"
        "• <code>pubg</code> — PUBG",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


async def show_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 <b>Deposit / Add Balance</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💙 <b>K Pay</b>\n"
        "   <code>09766605879</code> (Thet Naing Swan)\n\n"
        "💚 <b>UAB Pay</b>\n"
        "   <code>09425160424</code> (Thet Naing Swan)\n\n"
        "❤️ <b>AYA Pay</b>\n"
        "   <code>09678664100</code> (Hnin Hnin Soe)\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📸 After transferring, send the screenshot to this chat.\n\n"
        "⚠️ Admin will review and add balance.",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


async def process_check_id_zone(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    slug = context.user_data.get("check_slug")
    player_id = context.user_data.get("check_player_id")
    zone_id = text

    await update.message.reply_text("🔍 <b>Checking...</b>", parse_mode="HTML")

    data, error = rme_check_player(slug, player_id, zone_id)
    if error:
        await update.message.reply_text(
            f"❌ <b>Failed</b>\n\n{html.escape(str(error))}",
            parse_mode="HTML", reply_markup=main_keyboard(),
        )
        context.user_data.clear()
        return

    nickname = data.get("nickname") or data.get("username") or data.get("name") or "-"
    region = data.get("region") or "-"

    dd_text = ""
    if slug == "mobile-legends":
        region_data, region_err = rme_ml_region_check(player_id, zone_id)
        if not region_err and region_data:
            bonuses = region_data.get("bonuses", [])
            if bonuses:
                dd_lines = ["", "💎 <b>Double Diamond</b>"]
                for b in bonuses:
                    amount = b.get("amount", "?")
                    eligible = b.get("eligible", False)
                    emoji = "🟢" if eligible else "🔴"
                    dd_lines.append(f"{emoji} <b>{amount}</b>")
                dd_text = "\n".join(dd_lines) + "\n"

    await update.message.reply_text(
        "🔍 <b>ID Result</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Nickname: <b>{html.escape(str(nickname))}</b>\n"
        f"🆔 Player ID: <code>{html.escape(str(player_id))}</code>\n"
        f"🌐 Zone ID: <code>{html.escape(str(zone_id))}</code>\n"
        f"🌍 Region: <b>{html.escape(str(region))}</b>\n"
        f"{dd_text}\n"
        "✅ <b>ID Verified</b>",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )
    context.user_data.clear()


async def process_order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user = update.effective_user

    if text == "❌ Cancel Order":
        context.user_data.clear()
        await update.message.reply_text("❌ Order cancelled", reply_markup=main_keyboard())
        return

    if text == "❌ No, cancel":
        context.user_data.clear()
        await update.message.reply_text("❌ Order cancelled", reply_markup=main_keyboard())
        return

    if text == "✅ Yes, order":
        product = context.user_data.get("selected_product", {})
        game_name = context.user_data.get("game_name", "")
        player_id = context.user_data.get("player_id")
        zone_id = context.user_data.get("zone_id")
        base_price = product.get("price", 0)
        price = get_final_price(base_price)
        pname = product.get("name", "?")
        code = product.get("code", "")

        await update.message.reply_text("⏳ <b>Processing...</b>", parse_mode="HTML")

        if not deduct_user_balance(user.id, price):
            await update.message.reply_text("❌ Failed to deduct balance", reply_markup=main_keyboard())
            context.user_data.clear()
            return

        data, error = rme_create_order(code, player_id, zone_id)
        if error:
            add_user_balance(user.id, price)
            await update.message.reply_text(
                f"❌ <b>Order Failed</b>\n\n{html.escape(str(error))}\n\n💰 Refunded",
                parse_mode="HTML", reply_markup=main_keyboard(),
            )
            context.user_data.clear()
            return

        result = data.get("data", {})
        order_id = result.get("orderId") or result.get("id", "-")
        status = result.get("status", "pending")

        save_order(user.id, game_name, pname, player_id, zone_id, price, status, order_id)

        new_balance = get_user_balance(user.id)
        await update.message.reply_text(
            "✅ <b>Order Created</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎮 {html.escape(game_name)}\n"
            f"📦 {html.escape(pname)}\n"
            f"🆔 {html.escape(str(player_id))}\n\n"
            f"🆔 Order ID: <code>{html.escape(str(order_id))}</code>\n"
            f"⏳ Status: <b>{html.escape(str(status).upper())}</b>\n\n"
            f"💰 Balance: <b>{new_balance:,.0f} MMK</b>",
            parse_mode="HTML", reply_markup=main_keyboard(),
        )

        try:
            await context.bot.send_message(
                chat_id=ALERT_CHAT_ID if ALERT_CHAT_ID else ADMIN_ID,
                text=(
                    f"🔔 <b>NEW ORDER</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"👤 {html.escape(user.first_name or 'User')}\n"
                    f"🆔 <code>{user.id}</code>\n\n"
                    f"🎮 {html.escape(game_name)}\n"
                    f"📦 {html.escape(pname)}\n"
                    f"🆔 {html.escape(str(player_id))}\n"
                    f"🌐 {html.escape(str(zone_id))}\n\n"
                    f"💰 {price:,.0f} MMK\n"
                    f"🆔 <code>{html.escape(str(order_id))}</code>"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

        context.user_data.clear()
        return

# ============================================================
# Part 5 — Admin + Access Control + Text Handler + Main
# ============================================================

# ---------- Access Control ----------
def get_access_status(user_id):
    if int(user_id) == ADMIN_ID:
        return "approved"
    conn = sqlite3.connect(ACCESS_DB)
    row = conn.execute("SELECT status FROM bot_access WHERE user_id=?", (int(user_id),)).fetchone()
    conn.close()
    return row[0] if row else None


def save_access_request(user_id):
    conn = sqlite3.connect(ACCESS_DB)
    conn.execute("""INSERT INTO bot_access (user_id, status, requested_at)
        VALUES (?, 'pending', CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
        status='pending', requested_at=CURRENT_TIMESTAMP
    """, (int(user_id),))
    conn.commit()
    conn.close()


def set_access_status(user_id, status):
    conn = sqlite3.connect(ACCESS_DB)
    conn.execute("""INSERT INTO bot_access (user_id, status, requested_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET status=?
    """, (int(user_id), status, status))
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
        save_access_request(user.id)
        username = f"@{user.username}" if user.username else "-"
        admin_text = (
            "🔔 <b>NEW USER REGISTER REQUEST</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Name: <b>{html.escape(user.first_name or '-')}</b>\n"
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
        except Exception:
            pass
        await query.answer("Approved ✅")
    else:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ <b>Access Denied</b>\n\nPress /start to send a new request.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        await query.answer("Rejected ❌")

    return True


# ---------- Admin Commands ----------
async def add_balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("❌ <code>/addbalance USER_ID AMOUNT</code>", parse_mode="HTML")
        return
    try:
        user_id = int(args[0])
        amount = float(args[1])
    except ValueError:
        await update.message.reply_text("❌ Must be a number")
        return
    add_user_balance(user_id, amount)
    new_bal = get_user_balance(user_id)
    await update.message.reply_text(
        f"✅ Balance added\n\n🆔 {user_id}\n💰 +{amount:,.0f} MMK\n💰 New: <b>{new_bal:,.0f} MMK</b>",
        parse_mode="HTML",
    )


async def deduct_balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("❌ <code>/deductbalance USER_ID AMOUNT</code>", parse_mode="HTML")
        return
    try:
        user_id = int(args[0])
        amount = float(args[1])
    except ValueError:
        await update.message.reply_text("❌ Must be a number")
        return
    if deduct_user_balance(user_id, amount):
        new_bal = get_user_balance(user_id)
        await update.message.reply_text(
            f"✅ Balance deducted\n\n🆔 {user_id}\n💰 -{amount:,.0f} MMK\n💰 New: <b>{new_bal:,.0f} MMK</b>",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text("❌ Insufficient balance")


# ---------- Text Handler ----------
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user

    # Main Menu
    if text == "🏠 Main Menu":
        context.user_data.clear()
        await start(update, context)
        return

    if text == "💰 My Balance":
        await show_balance(update, context)
        return

    if text == "📦 My Orders":
        await show_orders(update, context)
        return

    if text == "💎 Mobile Legends":
        await show_game_products(update, context, "mobile-legends", "Mobile Legends")
        return

    if text == "🎮 PUBG":
        await show_game_products(update, context, "pubg", "PUBG Package")
        return

    if text == "🔍 Check ID":
        await show_check_id(update, context)
        return

    if text == "💳 Deposit":
        await show_deposit(update, context)
        return

    if text == "📞 Contact Admin":
        await update.message.reply_text(
            "📞 <b>Contact Admin</b>\n\n"
            "👤 @erenIsNot4U\n"
            "💬 https://t.me/erenIsNot4U",
            parse_mode="HTML", reply_markup=main_keyboard(),
        )
        return

    if text == "❌ Cancel Order":
        context.user_data.clear()
        await start(update, context)
        return

    # Package Selection
    products = context.user_data.get("products", [])
    if products:
        for p in products:
            pname = p.get("name", "?")
            base_price = p.get("price", 0)
            price = get_final_price(base_price)
            label = f"{pname} — {price:,.0f} Ks"
            if text == label:
                context.user_data["selected_product"] = p
                context.user_data["state"] = "awaiting_player_id"
                await update.message.reply_text(
                    f"🛒 <b>Order</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🎮 {html.escape(context.user_data.get('game_name', ''))}\n"
                    f"📦 {html.escape(pname)}\n"
                    f"💰 {price:,.0f} Ks\n\n"
                    "🆔 Enter <b>Player ID</b>",
                    parse_mode="HTML", reply_markup=cancel_keyboard(),
                )
                return

    state = context.user_data.get("state")

    # Check ID Flow
    if state == "check_id_game":
        slug = None
        if text.lower() == "ml":
            slug = "mobile-legends"
        elif text.lower() == "pubg":
            slug = "pubg"
        else:
            await update.message.reply_text("❌ Type <code>ml</code> or <code>pubg</code>", parse_mode="HTML")
            return
        context.user_data["check_slug"] = slug
        context.user_data["state"] = "check_id_player"
        await update.message.reply_text(
            "🆔 Enter <b>Player ID</b>",
            parse_mode="HTML", reply_markup=cancel_keyboard(),
        )
        return

    if state == "check_id_player":
        if not text.isdigit():
            await update.message.reply_text("❌ Player ID must be numeric")
            return
        context.user_data["check_player_id"] = text
        context.user_data["state"] = "check_id_zone"
        await update.message.reply_text(
            "🌐 Enter <b>Zone ID</b> (PUBG: type 0)",
            parse_mode="HTML", reply_markup=cancel_keyboard(),
        )
        return

    if state == "check_id_zone":
        if not text.isdigit():
            await update.message.reply_text("❌ Zone ID must be numeric")
            return
        await process_check_id_zone(update, context, text)
        return

    # Order Flow
    if state == "awaiting_player_id":
        if not text.isdigit():
            await update.message.reply_text("❌ Player ID must be numeric")
            return
        context.user_data["player_id"] = text
        context.user_data["state"] = "awaiting_zone_id"
        await update.message.reply_text(
            "🌐 Enter <b>Zone ID</b> (PUBG: type 0)",
            parse_mode="HTML", reply_markup=cancel_keyboard(),
        )
        return

    if state == "awaiting_zone_id":
        if not text.isdigit():
            await update.message.reply_text("❌ Zone ID must be numeric")
            return
        context.user_data["zone_id"] = text

        slug = context.user_data.get("game_slug")
        player_id = context.user_data.get("player_id")
        product = context.user_data.get("selected_product", {})
        base_price = product.get("price", 0)
        price = get_final_price(base_price)
        pname = product.get("name", "?")

        await update.message.reply_text("🔍 <b>Checking...</b>", parse_mode="HTML")

        data, error = rme_check_player(slug, player_id, text)
        nickname = "-"
        if not error and data:
            nickname = data.get("nickname") or data.get("username") or data.get("name") or "-"

        balance = get_user_balance(user.id)
        if balance < price:
            await update.message.reply_text(
                f"❌ <b>Insufficient Balance</b>\n\n"
                f"💰 Balance: <b>{balance:,.0f} MMK</b>\n"
                f"💰 Required: <b>{price:,.0f} MMK</b>",
                parse_mode="HTML", reply_markup=main_keyboard(),
            )
            context.user_data.clear()
            return

        keyboard = ReplyKeyboardMarkup(
            [["✅ Yes, order", "❌ No, cancel"]],
            resize_keyboard=True,
        )
        await update.message.reply_text(
            "🛒 <b>Order Confirm</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎮 {html.escape(context.user_data.get('game_name', ''))}\n"
            f"📦 {html.escape(pname)}\n"
            f"🆔 Player ID: {html.escape(player_id)}\n"
            f"🌐 Zone ID: {html.escape(text)}\n"
            f"👤 In-Game: <b>{html.escape(nickname)}</b>\n\n"
            f"💰 Price: <b>{price:,.0f} Ks</b>\n\n"
            "Confirm order?",
            parse_mode="HTML", reply_markup=keyboard,
        )
        context.user_data["state"] = "awaiting_confirm"
        return

    if state == "awaiting_confirm":
        await process_order_confirm(update, context, text)
        return

    await update.message.reply_text("❓ Please use the menu", reply_markup=main_keyboard())


# ---------- Error Handler ----------
async def error_handler(update, context):
    print("BOT ERROR:", context.error)


# ---------- Main ----------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not found.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addbalance", add_balance_cmd))
    app.add_handler(CommandHandler("deductbalance", deduct_balance_cmd))
    app.add_handler(CallbackQueryHandler(handle_access_callback, pattern=r"^access:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_error_handler(error_handler)

    print("✅ Bot is running!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

        
