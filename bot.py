import os
import re
import asyncio
import html

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from playwright.async_api import async_playwright


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
SMILE_PROFILE = "/data/smile-profile"
SMILE_URL = "https://www.smile.one/br/merchant/mobilelegends"
SMILE_LOGIN_URL = "https://www.smile.one/customer/account/accountlogin"


# =========================================================
# GLOBAL BROWSER
# =========================================================

browser_lock = asyncio.Lock()
_playwright = None
_browser_context = None
_page = None


# =========================================================
# OPEN / REUSE SMILE BROWSER
# =========================================================

async def open_browser():
    global _playwright
    global _browser_context
    global _page

    if (_browser_context is not None and _page is not None and not _page.is_closed()):
        return _playwright, _browser_context, _page

    os.makedirs(SMILE_PROFILE, exist_ok=True)
    _playwright = await async_playwright().start()
    _browser_context = await _playwright.chromium.launch_persistent_context(
        user_data_dir=SMILE_PROFILE,
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-setuid-sandbox",
        ],
        viewport={"width": 1366, "height": 900},
        locale="pt-BR",
    )

    if _browser_context.pages:
        _page = _browser_context.pages[0]
    else:
        _page = await _browser_context.new_page()

    return _playwright, _browser_context, _page


# =========================================================
# CLOSE BROWSER
# =========================================================

async def close_browser():
    global _playwright
    global _browser_context
    global _page

    try:
        if _browser_context:
            await _browser_context.close()
    except Exception:
        pass

    try:
        if _playwright:
            await _playwright.stop()
    except Exception:
        pass

    _playwright = None
    _browser_context = None
    _page = None


# =========================================================
# SAFE PAGE TEXT
# =========================================================

async def get_page_text(page):
    try:
        text = await page.locator("body").inner_text(timeout=10000)
        return text.strip()
    except Exception:
        return ""


# =========================================================
# LOGIN CHECK
# =========================================================

async def is_login_page(page):
    try:
        url = page.url.lower()
        if "account/accountlogin" in url:
            return True

        text = (await get_page_text(page)).lower()
        login_words = ["sign in with google", "log in with email", "sign in", "login"]
        found = 0
        for word in login_words:
            if word in text:
                found += 1

        if found >= 2:
            return True
        return False
    except Exception:
        return False


# =========================================================
# /START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 <b>Eren ML Dia Bot</b>\n\n"
        "💎 Mobile Legends Diamond Bot\n\n"
        "📦 /product\n"
        "🪙 /balance\n"
        "🔍 /checkid ID SERVER\n"
        "🔐 /login\n"
        "🧪 /test\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚡ Smile One Browser System"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# =========================================================
# /TEST
# =========================================================

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🌐 Smile One ကိုဖွင့်နေပါတယ်...")
    try:
        async with browser_lock:
            pw, browser_context, page = await open_browser()
            await page.goto(SMILE_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)
            title = await page.title()
            url = page.url

        text = (
            "✅ <b>Browser works!</b>\n\n"
            "🌐 Smile One\n"
            f"📄 Title: <code>{html.escape(title)}</code>\n"
            f"🔗 URL: <code>{html.escape(url)}</code>"
        )
        await msg.edit_text(text, parse_mode="HTML")
    except Exception as e:
        await msg.edit_text(
            "❌ <b>Browser Error</b>\n\n"
            f"<code>{html.escape(str(e)[:1500])}</code>",
            parse_mode="HTML"
        )


# =========================================================
# SMILE COIN PAYMENT SELECTOR
# =========================================================

async def select_smile_coin(page):
    selectors = ["text=Moeda Smile", "text=SmileCoin", "text=Smile Coin"]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() > 0:
                await locator.click(timeout=5000)
                await page.wait_for_timeout(1000)
                return True
        except Exception:
            pass

    try:
        elements = page.locator("label, div, span")
        count = await elements.count()
        for i in range(min(count, 500)):
            try:
                el = elements.nth(i)
                text = (await el.inner_text(timeout=1000)).strip()
                lower = text.lower()
                if ("moeda smile" in lower or "smilecoin" in lower or "smile coin" in lower):
                    await el.click(timeout=3000)
                    await page.wait_for_timeout(1000)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


# =========================================================
# EXTRACT SMILE COIN PRODUCTS (NEW)
# =========================================================

async def extract_products(page):
    products = []
    text = await get_page_text(page)
    if not text:
        return []

    lines = [x.strip() for x in text.splitlines() if x.strip()]
    
    # ၁။ စိန် ပမာဏတွေကို ရှာမယ်
    diamond_pattern = re.compile(
        r"(\d[\d,.]*)\s*(?:\+\s*(\d[\d,.]*))?\s*"
        r"(?:diamonds?|diamantes?)",
        re.IGNORECASE
    )

    for index, line in enumerate(lines):
        match = diamond_pattern.search(line)
        if not match:
            continue

        base = match.group(1)
        bonus = match.group(2)

        if bonus:
            diamond_name = f"{base}+{bonus} Diamonds"
        else:
            diamond_name = f"{base} Diamonds"

        products.append({"name": diamond_name, "coin": None})

    # ၂။ Smile Coin ဈေးနှုန်းကို ရှာမယ် (Payment Method အောက်မှာ ရှိတယ်)
    coin_price = None
    for line in lines:
        if "smile coin" in line.lower():
            match = re.search(r"([\d.,]+)", line)
            if match:
                coin_price = match.group(1)
                break

    # ၃။ Product တွေအားလုံးအတွက် Smile Coin ထည့်မယ်
    if coin_price:
        for item in products:
            item["coin"] = coin_price

    # Duplicate ဖျောက်မယ်
    unique = []
    seen = set()
    for item in products:
        key = item["name"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return unique


# =========================================================
# /PRODUCT (NEW)
# =========================================================

async def product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "💎 <b>MLBB Products</b>\n\n🌐 Smile One ကိုဖွင့်နေပါတယ်...",
        parse_mode="HTML"
    )

    try:
        async with browser_lock:
            pw, browser_context, page = await open_browser()
            await page.goto(SMILE_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)

            if await is_login_page(page):
                await msg.edit_text(
                    "🔐 <b>Smile One Login လိုအပ်ပါတယ်</b>\n\n"
                    "Google နဲ့ Smile One ထဲဝင်ပြီးမှ\n"
                    "/product ကို ပြန်သုံးပါ။\n\n📌 /login",
                    parse_mode="HTML"
                )
                return

            # Smile Coin payment ကို ရွေးမယ်
            await select_smile_coin(page)
            products = await extract_products(page)

        if not products:
            await msg.edit_text("⚠️ <b>Product data မတွေ့သေးပါဘူး</b>", parse_mode="HTML")
            return

        lines = [
            "💎 <b>MLBB DIAMOND PRODUCTS</b>",
            "━━━━━━━━━━━━━━━━━━",
            ""
        ]

        for item in products[:30]:
            coin = item["coin"]
            if coin:
                coin_text = f"🪙 Smile Coin: <b>{coin}</b>"
            else:
                coin_text = "🪙 Smile Coin: ⚠️ Not detected"

            lines.append(f"💎 <b>{html.escape(item['name'])}</b>")
            lines.append(coin_text)
            lines.append("")

        await msg.edit_text("\n".join(lines), parse_mode="HTML")

    except Exception as e:
        await msg.edit_text(
            "❌ <b>Product Error</b>\n\n"
            f"<code>{html.escape(str(e)[:1500])}</code>",
            parse_mode="HTML"
)

# =========================================================
# /LOGIN
# =========================================================

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "🔐 <b>Smile One Login</b>\n\n🌐 Login page ကိုဖွင့်နေပါတယ်...",
        parse_mode="HTML"
    )

    try:
        async with browser_lock:
            pw, browser_context, page = await open_browser()
            await page.goto(SMILE_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)

        await msg.edit_text(
            "🔐 <b>Smile One Login Page ဖွင့်ပြီးပါပြီ</b>\n\n"
            "Google နဲ့ Smile One ကို Login ဝင်ပေးပါ။\n\n"
            "⚠️ ဒီ bot က Google password / OTP ကို မတောင်းပါဘူး။\n\n"
            "Login ပြီးသွားရင်\n"
            "👉 /balance\n"
            "👉 /product\n"
            "ကို ပြန်စမ်းပါ။",
            parse_mode="HTML"
        )

    except Exception as e:
        await msg.edit_text(
            "❌ <b>Login Page Error</b>\n\n"
            f"<code>{html.escape(str(e)[:1500])}</code>",
            parse_mode="HTML"
        )


# =========================================================
# /BALANCE
# =========================================================

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "🪙 <b>Smile Coin Balance</b>\n\n🔍 စစ်ဆေးနေပါတယ်...",
        parse_mode="HTML"
    )

    try:
        async with browser_lock:
            pw, browser_context, page = await open_browser()
            await page.goto(SMILE_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)

            if await is_login_page(page):
                await msg.edit_text(
                    "🔐 <b>Smile One Login မဝင်ရသေးပါဘူး</b>\n\n"
                    "Google နဲ့ Login ဝင်ပြီးမှ\n"
                    "/balance ကို ပြန်သုံးပါ။\n\n📌 /login",
                    parse_mode="HTML"
                )
                return

            text = await get_page_text(page)

        lines = [x.strip() for x in text.splitlines() if x.strip()]
        balance_value = None

        patterns = [
            re.compile(r"(?:smile\s*coin|smilecoin|moeda\s*smile)\s*[:\-]?\s*([\d.,]+)", re.IGNORECASE),
            re.compile(r"([\d.,]+)\s*(?:smile\s*coin|smilecoin|moeda\s*smile)", re.IGNORECASE),
            re.compile(r"balance\s*[:\-]?\s*([\d.,]+)", re.IGNORECASE),
        ]

        for line in lines:
            for pattern in patterns:
                match = pattern.search(line)
                if match:
                    balance_value = match.group(1)
                    break
            if balance_value:
                break

        if not balance_value:
            try:
                elements = page.locator("span, div, p, a")
                count = await elements.count()
                for i in range(min(count, 1000)):
                    try:
                        el = elements.nth(i)
                        value = (await el.inner_text(timeout=500)).strip()
                        if not value:
                            continue
                        lower = value.lower()
                        if not ("smile coin" in lower or "smilecoin" in lower or "moeda smile" in lower):
                            continue
                        for pattern in patterns:
                            match = pattern.search(value)
                            if match:
                                balance_value = match.group(1)
                                break
                        if balance_value:
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        if balance_value:
            await msg.edit_text(
                "🪙 <b>Smile Coin Balance</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                f"💰 Balance: <b>{html.escape(balance_value)}</b>\n\n"
                "✅ Smile One session active",
                parse_mode="HTML"
            )
        else:
            await msg.edit_text(
                "⚠️ <b>Smile Coin Balance မတွေ့သေးပါဘူး</b>\n\n"
                "Login session ရှိနေပါတယ်။\n"
                "ဒါပေမယ့် page ထဲက Coin balance ကို မဖတ်နိုင်သေးပါဘူး။",
                parse_mode="HTML"
            )

    except Exception as e:
        await msg.edit_text(
            "❌ <b>Balance Error</b>\n\n"
            f"<code>{html.escape(str(e)[:1500])}</code>",
            parse_mode="HTML"
        )


# =========================================================
# PLAYER NICKNAME FINDER
# =========================================================

async def find_player_nickname(page):
    selectors = [
        '[class*="nickname"]', '[class*="NickName"]',
        '[class*="player-name"]', '[class*="playerName"]',
        '[class*="role-name"]', '[class*="roleName"]',
        '[class*="user-name"]', '[class*="userName"]',
    ]

    bad_words = [
        "mobile legends", "mobile legend", "moonton", "diamond",
        "diamonds", "smile one", "smilecoin", "smile coin",
        "server", "player", "online battle arena", "moba",
    ]

    for selector in selectors:
        try:
            elements = page.locator(selector)
            count = await elements.count()
            for i in range(min(count, 50)):
                try:
                    value = (await elements.nth(i).inner_text(timeout=1000)).strip()
                    if not value:
                        continue
                    if len(value) > 80:
                        continue
                    lower = value.lower()
                    if any(word in lower for word in bad_words):
                        continue
                    if re.fullmatch(r"[\d\s.,+-]+", value):
                        continue
                    return value
                except Exception:
                    continue
        except Exception:
            continue
    return None


# =========================================================
# /CHECKID
# =========================================================

async def checkid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "❌ <b>Format မှားနေပါတယ်</b>\n\n"
            "အသုံးပြုပုံ:\n"
            "<code>/checkid GAME_ID SERVER_ID</code>\n\n"
            "ဥပမာ:\n"
            "<code>/checkid 1662307694 18012</code>",
            parse_mode="HTML"
        )
        return

    game_id = args[0]
    server_id = args[1]

    msg = await update.message.reply_text(
        "🔍 <b>Checking Mobile Legends ID...</b>\n\n"
        f"🆔 ID: <code>{html.escape(game_id)}</code>\n"
        f"🌐 Server: <code>{html.escape(server_id)}</code>",
        parse_mode="HTML"
    )

    try:
        async with browser_lock:
            pw, browser_context, page = await open_browser()
            await page.goto(SMILE_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)

            if await is_login_page(page):
                await msg.edit_text(
                    "🔐 <b>Smile One Login လိုအပ်ပါတယ်</b>\n\n"
                    "Google နဲ့ Login ဝင်ပြီးမှ /checkid ကို ပြန်သုံးပါ။",
                    parse_mode="HTML"
                )
                return

            # Fill Game ID
            filled_id = False
            id_selectors = [
                'input[name="uid"]', 'input[name="user_id"]',
                'input[name="userid"]', 'input[name="game_id"]',
                'input[placeholder*="ID"]', 'input[placeholder*="id"]',
            ]
            for selector in id_selectors:
                try:
                    loc = page.locator(selector).first
                    if await loc.count() > 0:
                        await loc.fill(game_id, timeout=3000)
                        filled_id = True
                        break
                except Exception:
                    continue

            # Fill Server ID
            filled_server = False
            server_selectors = [
                'input[name="server"]', 'input[name="server_id"]',
                'input[name="zone"]', 'input[name="zone_id"]',
                'input[placeholder*="Server"]', 'input[placeholder*="server"]',
            ]
            for selector in server_selectors:
                try:
                    loc = page.locator(selector).first
                    if await loc.count() > 0:
                        await loc.fill(server_id, timeout=3000)
                        filled_server = True
                        break
                except Exception:
                    continue

            # Click verification button
            clicked = False
            buttons = page.locator("button, a")
            count = await buttons.count()
            for i in range(min(count, 300)):
                try:
                    button = buttons.nth(i)
                    text = (await button.inner_text(timeout=500)).strip()
                    lower = text.lower()
                    if any(key in lower for key in ["check", "verify", "confirm", "search", "verificar", "consultar"]):
                        await button.click(timeout=3000)
                        clicked = True
                        await page.wait_for_timeout(2500)
                        break
                except Exception:
                    continue

            nickname = await find_player_nickname(page)

        if nickname:
            await msg.edit_text(
                "✅ <b>PLAYER FOUND</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 Player: <b>{html.escape(nickname)}</b>\n"
                f"🆔 ID: <code>{html.escape(game_id)}</code>\n"
                f"🌐 Server: <code>{html.escape(server_id)}</code>\n\n"
                "✅ ID verification result found.",
                parse_mode="HTML"
            )
        else:
            status = []
            if filled_id:
                status.append("🆔 Game ID entered")
            if filled_server:
                status.append("🌐 Server ID entered")
            if clicked:
                status.append("🔍 Verification attempted")

            status_text = "\n".join(status) if status else "⚠️ ID input field ကို မတွေ့သေးပါဘူး။"

            await msg.edit_text(
                "⚠️ <b>Player result မရသေးပါဘူး</b>\n\n"
                f"🆔 ID: <code>{html.escape(game_id)}</code>\n"
                f"🌐 Server: <code>{html.escape(server_id)}</code>\n\n"
                f"{status_text}\n\n"
                "📌 ဒီ result က ID invalid လို့ ဆိုလိုတာမဟုတ်ပါဘူး။\n"
                "Smile One page layout ကြောင့် nickname selector မတွေ့တာ ဖြစ်နိုင်ပါတယ်။",
                parse_mode="HTML"
            )

    except Exception as e:
        await msg.edit_text(
            "❌ <b>Check ID Error</b>\n\n"
            f"<code>{html.escape(str(e)[:1500])}</code>",
            parse_mode="HTML"
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    try:
        print("BOT ERROR:", repr(context.error))
    except Exception:
        pass


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN environment variable မရှိပါဘူး။")
        return

    print("======================================")
    print("🤖 Eren ML Dia Bot is starting...")
    print("🌐 Smile One Browser System")
    print("💎 Product / Balance / CheckID")
    print("======================================")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CommandHandler("product", product))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("checkid", checkid))

    app.add_error_handler(error_handler)

    print("✅ Bot is running!")
    app.run_polling(drop_pending_updates=True)


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":
    main()
