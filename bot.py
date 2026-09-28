import os
import re
import asyncio

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

SMILE_EMAIL = os.getenv("SMILE_EMAIL")
SMILE_PASSWORD = os.getenv("SMILE_PASSWORD")

SMILE_URL = "https://www.smile.one/br/merchant/mobilelegends"
SMILE_LOGIN_URL = "https://www.smile.one/customer/account/accountlogin"

browser_lock = asyncio.Lock()


# =========================================================
# BROWSER
# =========================================================

async def open_browser():
    pw = await async_playwright().start()

    browser = await pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    )

    browser_context = await browser.new_context(
        viewport={
            "width": 1366,
            "height": 900,
        },
        locale="pt-BR",
    )

    page = await browser_context.new_page()

    return pw, browser, browser_context, page


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🤖 Eren ML Dia Bot\n\n"
        "✅ Bot is online!\n"
        "🌐 Smile One Browser System\n\n"
        "💎 Commands\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "/product - MLBB Products\n"
        "/balance - Smile Coin Balance\n"
        "/checkid ID SERVER - Check Player\n"
        "/test - Browser Test"
    )


# =========================================================
# TEST
# =========================================================

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🌐 Opening Smile One..."
    )

    async with browser_lock:

        pw = None
        browser = None

        try:
            pw, browser, browser_context, page = (
                await open_browser()
            )

            await page.goto(
                "https://www.smile.one/",
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await page.wait_for_timeout(3000)

            title = await page.title()

            await browser.close()
            await pw.stop()

            await update.message.reply_text(
                "✅ Browser works!\n\n"
                "🌐 Smile One\n"
                f"📄 Title: {title}"
            )

        except Exception as e:

            try:
                if browser:
                    await browser.close()

                if pw:
                    await pw.stop()
            except Exception:
                pass

            await update.message.reply_text(
                "❌ Browser Error\n\n"
                + str(e)[:3000]
            )


# =========================================================
# SELECT SMILE COIN
# =========================================================

async def select_smile_coin(page):

    selectors = [
        "text=Moeda Smile",
        "text=SmileCoin",
        "text=Smile Coin",
    ]

    for selector in selectors:

        try:
            loc = page.locator(selector)

            count = await loc.count()

            for i in range(count):

                item = loc.nth(i)

                try:
                    if await item.is_visible():

                        await item.click(
                            timeout=5000
                        )

                        await page.wait_for_timeout(
                            2500
                        )

                        return True

                except Exception:
                    continue

        except Exception:
            continue

    try:
        labels = page.locator("label")

        count = await labels.count()

        for i in range(count):

            label = labels.nth(i)

            try:

                txt = (
                    await label.inner_text()
                ).strip().lower()

                if (
                    "moeda smile" in txt
                    or "smilecoin" in txt
                    or "smile coin" in txt
                ):

                    await label.click(
                        timeout=5000
                    )

                    await page.wait_for_timeout(
                        2500
                    )

                    return True

            except Exception:
                continue

    except Exception:
        pass

    return False


# =========================================================
# EXTRACT PRODUCTS
# =========================================================

async def extract_products(page):

    body = await page.locator(
        "body"
    ).inner_text()

    lines = [
        line.strip()
        for line in body.splitlines()
        if line.strip()
    ]

    products = []

    diamond_pattern = re.compile(
        r"(\d[\d,]*)\s*"
        r"(?:\+\s*(\d[\d,]*))?"
        r"\s*"
        r"(?:Diamond|Diamonds)",
        re.IGNORECASE,
    )

    for index, line in enumerate(lines):

        match = diamond_pattern.search(line)

        if not match:
            continue

        base = match.group(1).replace(
            ",", ""
        )

        bonus = match.group(2)

        diamond = base

        if bonus:
            diamond += "+" + bonus

        nearby = lines[
            max(0, index - 5):
            min(len(lines), index + 6)
        ]

        joined = " | ".join(nearby)

        coin = None

        coin_patterns = [
            r"SmileCoin\s*[:\-]?\s*([\d,]+)",
            r"Smile\s*Coin\s*[:\-]?\s*([\d,]+)",
            r"([\d,]+)\s*SmileCoin",
            r"([\d,]+)\s*Smile\s*Coin",
        ]

        for pattern in coin_patterns:

            m = re.search(
                pattern,
                joined,
                re.IGNORECASE,
            )

            if m:

                coin = (
                    m.group(1)
                    .replace(",", "")
                )

                break

        if coin is None:

            try:

                diamond_loc = page.get_by_text(
                    re.compile(
                        re.escape(diamond),
                        re.IGNORECASE,
                    )
                ).first

                if await diamond_loc.count() > 0:

                    element = diamond_loc

                    for _ in range(6):

                        try:

                            element = (
                                element.locator(
                                    ".."
                                )
                            )

                            txt = (
                                await element.inner_text()
                            )

                            dom_patterns = [
                                r"([\d,]+)\s*Smile\s*Coin",
                                r"Smile\s*Coin\s*[:\-]?\s*([\d,]+)",
                                r"([\d,]+)\s*SmileCoin",
                                r"SmileCoin\s*[:\-]?\s*([\d,]+)",
                            ]

                            for pattern in dom_patterns:

                                m = re.search(
                                    pattern,
                                    txt,
                                    re.IGNORECASE,
                                )

                                if m:

                                    coin = (
                                        m.group(1)
                                        .replace(",", "")
                                    )

                                    break

                            if coin:
                                break

                        except Exception:
                            break

            except Exception:
                pass

        products.append({
            "diamond": diamond,
            "coin": coin,
        })

    unique = []
    seen = set()

    for item in products:

        key = (
            item["diamond"],
            item["coin"],
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(item)

    return unique


# =========================================================
# PRODUCT
# =========================================================

async def product(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🔄 Smile One MLBB Products ဖတ်နေပါတယ်...\n\n"
        "🪙 Smile Coin payment ကိုရွေးပြီး\n"
        "live coin amount ကိုစစ်နေပါတယ်..."
    )

    async with browser_lock:

        pw = None
        browser = None

        try:

            pw, browser, browser_context, page = (
                await open_browser()
            )

            await page.goto(
                SMILE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await page.wait_for_timeout(
                3500
            )

            smile_clicked = (
                await select_smile_coin(page)
            )

            if not smile_clicked:

                await browser.close()
                await pw.stop()

                await update.message.reply_text(
                    "❌ Smile Coin payment option "
                    "ကိုမရွေးနိုင်သေးပါဘူး။\n\n"
                    "R$ price ကို မပြပါဘူး။\n"
                    "Coin amount မှန်မှန်ရမှပဲ ပြပါမယ်။"
                )

                return

            products = await extract_products(
                page
            )

            await browser.close()
            await pw.stop()

            if not products:

                await update.message.reply_text(
                    "❌ MLBB products မတွေ့ပါဘူး။"
                )

                return

            text = (
                "💎 MLBB DIAMOND PRODUCTS\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
            )

            for item in products:

                text += (
                    f"💎 {item['diamond']} Diamonds\n"
                )

                if item["coin"]:

                    text += (
                        f"🪙 Smile Coin: "
                        f"{item['coin']}\n\n"
                    )

                else:

                    text += (
                        "🪙 Smile Coin: "
                        "⚠️ Not detected\n\n"
                    )

            text += (
                "━━━━━━━━━━━━━━━━━━\n"
                "🌐 Smile One Brazil"
            )

            if len(text) > 4000:
                text = text[:3950] + "\n..."

            await update.message.reply_text(
                text
            )

        except Exception as e:

            try:
                if browser:
                    await browser.close()

                if pw:
                    await pw.stop()
            except Exception:
                pass

            await update.message.reply_text(
                "❌ Product Error\n\n"
                + str(e)[:3000]
    )

# =========================================================
# BALANCE
# =========================================================

async def balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not SMILE_EMAIL or not SMILE_PASSWORD:

        await update.message.reply_text(
            "❌ Smile One Login မသတ်မှတ်ထားပါဘူး။\n\n"
            "Railway Variables မှာ\n"
            "SMILE_EMAIL\n"
            "SMILE_PASSWORD\n"
            "ထည့်ထားရပါမယ်။"
        )

        return

    await update.message.reply_text(
        "🔄 Smile One Login စစ်နေပါတယ်..."
    )

    async with browser_lock:

        pw = None
        browser = None

        try:

            pw, browser, browser_context, page = (
                await open_browser()
            )

            await page.goto(
                SMILE_LOGIN_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await page.wait_for_timeout(3000)

            # ---------------------------------------------
            # EMAIL
            # ---------------------------------------------

            email_input = page.locator(
                'input[placeholder="Email"]'
            ).first

            password_input = page.locator(
                'input[placeholder="Senha"]'
            ).first

            # Fallback
            if await email_input.count() == 0:

                inputs = page.locator("input")

                count = await inputs.count()

                if count >= 2:

                    email_input = inputs.nth(0)
                    password_input = inputs.nth(1)

                else:

                    raise Exception(
                        "Login input fields မတွေ့ပါဘူး"
                    )

            await email_input.fill(
                SMILE_EMAIL
            )

            await password_input.fill(
                SMILE_PASSWORD
            )

            # ---------------------------------------------
            # LOGIN BUTTON
            # ---------------------------------------------

            clicked = False

            buttons = page.locator("button")

            button_count = await buttons.count()

            for i in range(button_count):

                btn = buttons.nth(i)

                try:

                    txt = (
                        await btn.inner_text()
                    ).strip().lower()

                    if (
                        "entrar" in txt
                        or "login" in txt
                        or "sign in" in txt
                    ):

                        await btn.click(
                            timeout=5000
                        )

                        clicked = True
                        break

                except Exception:
                    continue

            if not clicked:

                await password_input.press(
                    "Enter"
                )

            await page.wait_for_timeout(
                6000
            )

            body = await page.locator(
                "body"
            ).inner_text()

            lower_body = body.lower()

            # ---------------------------------------------
            # LOGIN ERROR CHECK
            # ---------------------------------------------

            login_errors = [
                "senha incorreta",
                "email ou senha",
                "invalid password",
                "incorrect password",
                "wrong password",
                "login failed",
            ]

            for error_text in login_errors:

                if error_text in lower_body:

                    await browser.close()
                    await pw.stop()

                    await update.message.reply_text(
                        "❌ Smile One Login Failed\n\n"
                        "Email / Password မှားနေပါတယ်။"
                    )

                    return

            # ---------------------------------------------
            # FIND SMILE COIN BALANCE
            # ---------------------------------------------

            lines = [
                line.strip()
                for line in body.splitlines()
                if line.strip()
            ]

            balance_lines = []

            for line in lines:

                low = line.lower()

                if (
                    "smilecoin" in low
                    or "smile coin" in low
                    or "moeda smile" in low
                ):

                    balance_lines.append(
                        line
                    )

            await browser.close()
            await pw.stop()

            if balance_lines:

                result = (
                    "🪙 SMILE COIN BALANCE\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                )

                for line in balance_lines[:10]:

                    result += (
                        f"💰 {line}\n"
                    )

                result += (
                    "\n━━━━━━━━━━━━━━━━━━"
                )

                await update.message.reply_text(
                    result
                )

            else:

                await update.message.reply_text(
                    "⚠️ Login ဝင်ပြီးပါပြီ။\n\n"
                    "🪙 Smile Coin Balance ကို "
                    "page ထဲမှာ မတွေ့သေးပါဘူး။\n\n"
                    "Balance page structure ကို "
                    "ထပ်စစ်ဖို့လိုပါတယ်။"
                )

        except Exception as e:

            try:

                if browser:
                    await browser.close()

                if pw:
                    await pw.stop()

            except Exception:
                pass

            await update.message.reply_text(
                "❌ Balance Error\n\n"
                + str(e)[:3000]
            )


# =========================================================
# CHECK PLAYER ID
# =========================================================

async def checkid(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if len(context.args) < 2:

        await update.message.reply_text(
            "❌ Usage:\n\n"
            "/checkid GAME_ID SERVER_ID\n\n"
            "Example:\n"
            "/checkid 1662307694 18012"
        )

        return

    game_id = context.args[0]
    server_id = context.args[1]

    await update.message.reply_text(
        "🔍 Player ID စစ်နေပါတယ်...\n\n"
        f"🆔 ID: {game_id}\n"
        f"🌐 Server: {server_id}"
    )

    async with browser_lock:

        pw = None
        browser = None

        try:

            pw, browser, browser_context, page = (
                await open_browser()
            )

            await page.goto(
                SMILE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await page.wait_for_timeout(
                3000
            )

            # ---------------------------------------------
            # FIND INPUTS
            # ---------------------------------------------

            inputs = page.locator("input")

            input_count = await inputs.count()

            if input_count < 2:

                await browser.close()
                await pw.stop()

                await update.message.reply_text(
                    "⚠️ Game ID / Server ID input "
                    "မတွေ့ပါဘူး။"
                )

                return

            game_input = None
            server_input = None

            # Search by placeholder/name first
            for i in range(input_count):

                inp = inputs.nth(i)

                try:

                    placeholder = (
                        await inp.get_attribute(
                            "placeholder"
                        )
                        or ""
                    )

                    name = (
                        await inp.get_attribute(
                            "name"
                        )
                        or ""
                    )

                    text = (
                        placeholder + " " + name
                    ).lower()

                    if (
                        "user" in text
                        or "uid" in text
                        or "id" in text
                    ):

                        if game_input is None:
                            game_input = inp

                    if (
                        "server" in text
                        or "zone" in text
                    ):

                        if server_input is None:
                            server_input = inp

                except Exception:
                    continue

            # Fallback
            if game_input is None:
                game_input = inputs.nth(0)

            if server_input is None:

                if input_count >= 2:
                    server_input = inputs.nth(1)

            await game_input.fill(
                game_id
            )

            await server_input.fill(
                server_id
            )

            await page.wait_for_timeout(
                1000
            )

            # Trigger validation
            try:
                await server_input.press(
                    "Tab"
                )
            except Exception:
                pass

            await page.wait_for_timeout(
                5000
            )

            # ---------------------------------------------
            # FIND PLAYER/NICKNAME
            # ---------------------------------------------

            selectors = [
                '[class*="nickname"]',
                '[class*="NickName"]',
                '[class*="player-name"]',
                '[class*="playerName"]',
                '[class*="role-name"]',
                '[class*="roleName"]',
                '[class*="user-name"]',
                '[class*="userName"]',
            ]

            nickname = None

            for selector in selectors:

                try:

                    loc = page.locator(
                        selector
                    )

                    count = await loc.count()

                    for i in range(count):

                        item = loc.nth(i)

                        if not await item.is_visible():
                            continue

                        txt = (
                            await item.inner_text()
                        ).strip()

                        if not txt:
                            continue

                        if len(txt) > 100:
                            continue

                        low = txt.lower()

                        # Don't accept generic page text
                        blocked = [
                            "mobile legends",
                            "online battle arena",
                            "moonton",
                            "diamond",
                            "smile one",
                            "server",
                            "player",
                        ]

                        if any(
                            word in low
                            for word in blocked
                        ):
                            continue

                        nickname = txt
                        break

                    if nickname:
                        break

                except Exception:
                    continue

            await browser.close()
            await pw.stop()

            if nickname:

                await update.message.reply_text(
                    "✅ PLAYER FOUND\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                    f"👤 Player: {nickname}\n"
                    f"🆔 ID: {game_id}\n"
                    f"🌐 Server: {server_id}\n\n"
                    "━━━━━━━━━━━━━━━━━━"
                )

            else:

                await update.message.reply_text(
                    "⚠️ Player result မရသေးပါဘူး\n\n"
                    f"🆔 ID: {game_id}\n"
                    f"🌐 Server: {server_id}\n\n"
                    "Smile One က verification result "
                    "ကို မပြသေးတာ ဖြစ်နိုင်ပါတယ်။"
                )

        except Exception as e:

            try:

                if browser:
                    await browser.close()

                if pw:
                    await pw.stop()

            except Exception:
                pass

            await update.message.reply_text(
                "❌ Check ID Error\n\n"
                + str(e)[:3000]
            )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN မတွေ့ပါဘူး။ "
            "Railway Variables မှာ BOT_TOKEN ထည့်ပါ။"
        )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "test",
            test
        )
    )

    app.add_handler(
        CommandHandler(
            "product",
            product
        )
    )

    app.add_handler(
        CommandHandler(
            "balance",
            balance
        )
    )

    app.add_handler(
        CommandHandler(
            "checkid",
            checkid
        )
    )

    print(
        "🤖 Eren ML Dia Bot is starting..."
    )

    print(
        "✅ Bot is running!"
    )

    app.run_polling()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
