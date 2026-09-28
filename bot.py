import os
import re
import asyncio

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from playwright.async_api import async_playwright


BOT_TOKEN = os.getenv("BOT_TOKEN")

SMILE_EMAIL = os.getenv("SMILE_EMAIL")
SMILE_PASSWORD = os.getenv("SMILE_PASSWORD")

SMILE_URL = "https://www.smile.one/br/merchant/mobilelegends"

browser_lock = asyncio.Lock()


async def open_browser():
    pw = await async_playwright().start()

    browser = await pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )

    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        locale="pt-BR",
    )

    page = await context.new_page()

    return pw, browser, context, page


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Eren ML Dia Bot\n\n"
        "✅ Bot is online!\n\n"
        "💎 MLBB Auto Recharge\n"
        "🌐 Smile One Browser System\n\n"
        "Commands:\n"
        "/product - MLBB Packages\n"
        "/balance - Smile Coin Balance\n"
        "/checkid ID SERVER - Check Player"
    )


async def product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔄 Smile One MLBB Products ဖတ်နေပါတယ်..."
    )

    async with browser_lock:
        try:
            pw, browser, context_browser, page = await open_browser()

            await page.goto(
                SMILE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await page.wait_for_timeout(3000)

            # Main product area
            body_text = await page.locator("body").inner_text()

            lines = [
                x.strip()
                for x in body_text.splitlines()
                if x.strip()
            ]

            products = []

            # Diamond package pattern
            pattern = re.compile(
                r"Diamond[×x]\s*([\d,]+)(?:\+([\d,]+))?",
                re.IGNORECASE,
            )

            for i, line in enumerate(lines):
                match = pattern.search(line)

                if not match:
                    continue

                base = match.group(1).replace(",", "")
                bonus = match.group(2)

                # Look backwards for price
                price = ""

                for j in range(max(0, i - 4), i):
                    if "R$" in lines[j]:
                        price = lines[j]
                
                diamond_text = base

                if bonus:
                    diamond_text += f"+{bonus}"

                products.append(
                    {
                        "diamond": diamond_text,
                        "price": price,
                    }
                )

            await browser.close()
            await pw.stop()

            if not products:
                await update.message.reply_text(
                    "❌ Product မတွေ့ပါဘူး။\n\n"
                    "Smile One page structure ပြောင်းထားနိုင်ပါတယ်။"
                )
                return

            # Remove duplicates
            unique = []
            seen = set()

            for item in products:
                key = (
                    item["diamond"],
                    item["price"],
                )

                if key not in seen:
                    seen.add(key)
                    unique.append(item)

            text = "💎 MLBB DIAMOND PRODUCTS\n"
            text += "━━━━━━━━━━━━━━━━━━\n\n"

            for item in unique:
                text += (
                    f"💎 {item['diamond']} Diamonds\n"
                    f"💰 {item['price']}\n\n"
                )

            text += "━━━━━━━━━━━━━━━━━━\n"
            text += "🌐 Smile One Brazil"

            # Telegram message max safety
            if len(text) > 4000:
                text = text[:3950] + "\n..."

            await update.message.reply_text(text)

        except Exception as e:
            try:
                await browser.close()
                await pw.stop()
            except Exception:
                pass

            await update.message.reply_text(
                "❌ Product Error\n\n"
                + str(e)[:3000]
            )


async def check_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text(
            "❌ Format မမှန်ပါဘူး\n\n"
            "အသုံးပြုပုံ:\n"
            "/checkid 123456789 1234"
        )
        return

    game_id = context.args[0]
    server_id = context.args[1]

    await update.message.reply_text(
        "🔍 Checking MLBB ID...\n\n"
        f"🆔 ID: {game_id}\n"
        f"🌐 Server: {server_id}"
    )

    async with browser_lock:
        try:
            pw, browser, context_browser, page = await open_browser()

            await page.goto(
                SMILE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await page.wait_for_timeout(2500)

            inputs = page.locator("input")
            count = await inputs.count()

            user_input = None
            zone_input = None

            for i in range(count):
                inp = inputs.nth(i)

                try:
                    placeholder = (
                        await inp.get_attribute("placeholder")
                    ) or ""

                    name = (
                        await inp.get_attribute("name")
                    ) or ""

                    ph = placeholder.lower()
                    nm = name.lower()

                    if (
                        "user" in ph
                        or "uid" in ph
                        or "user" in nm
                        or "uid" in nm
                    ):
                        user_input = inp

                    if (
                        "zone" in ph
                        or "server" in ph
                        or "sid" in ph
                        or "zone" in nm
                        or "server" in nm
                        or "sid" in nm
                    ):
                        zone_input = inp

                except Exception:
                    pass

            # Fallback: first two useful inputs
            if user_input is None and count >= 1:
                user_input = inputs.nth(0)

            if zone_input is None and count >= 2:
                zone_input = inputs.nth(1)

            if user_input is None or zone_input is None:
                await browser.close()
                await pw.stop()

                await update.message.reply_text(
                    "❌ Smile One ID fields မတွေ့ပါဘူး။"
                )
                return

            await user_input.fill(game_id)
            await zone_input.fill(server_id)

            # Give Smile One JS time to verify
            await page.wait_for_timeout(3500)

            body = await page.locator("body").inner_text()

            await browser.close()
            await pw.stop()

            # Search likely nickname indicators
            nickname = None

            nickname_patterns = [
                r"nickname\s*[:：]\s*(.+)",
                r"player\s*name\s*[:：]\s*(.+)",
                r"nome\s*[:：]\s*(.+)",
                r"apelido\s*[:：]\s*(.+)",
            ]

            for pattern in nickname_patterns:
                m = re.search(
                    pattern,
                    body,
                    re.IGNORECASE,
                )

                if m:
                    nickname = m.group(1).strip()
                    break

            if nickname:
                await update.message.reply_text(
                    "✅ PLAYER FOUND\n\n"
                    f"👤 Player: {nickname}\n"
                    f"🆔 ID: {game_id}\n"
                    f"🌐 Server: {server_id}"
                )
            else:
                # Show a small useful result for debugging
                relevant = []

                for line in body.splitlines():
                    line = line.strip()

                    if not line:
                        continue

                    lower = line.lower()

                    if any(
                        x in lower
                        for x in [
                            "não existe",
                            "no existe",
                            "invalid",
                            "incorrect",
                            "error",
                            "nickname",
                            "player",
                            "nome",
                        ]
                    ):
                        relevant.append(line)

                msg = (
                    "⚠️ Player result မရသေးပါဘူး\n\n"
                    f"🆔 ID: {game_id}\n"
                    f"🌐 Server: {server_id}"
                )

                if relevant:
                    msg += "\n\n📄 Smile One:\n"
                    msg += "\n".join(relevant[:8])

                await update.message.reply_text(msg)

        except Exception as e:
            try:
                await browser.close()
                await pw.stop()
            except Exception:
                pass

            await update.message.reply_text(
                "❌ Check ID Error\n\n"
                + str(e)[:3000]
            )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not SMILE_EMAIL or not SMILE_PASSWORD:
        await update.message.reply_text(
            "⚠️ Smile One Login မထည့်ရသေးပါဘူး။\n\n"
            "Railway Variables မှာ:\n"
            "SMILE_EMAIL\n"
            "SMILE_PASSWORD\n"
            "ထည့်ပေးပါ။"
        )
        return

    await update.message.reply_text(
        "🔄 Smile One Account Login စစ်နေပါတယ်..."
    )

    async with browser_lock:
        pw = None
        browser = None

        try:
            pw, browser, context_browser, page = await open_browser()

            await page.goto(
                "https://www.smile.one/customer/account/accountlogin",
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await page.wait_for_timeout(2000)

            email_input = page.locator(
                'input[type="email"]'
            ).first

            password_input = page.locator(
                'input[type="password"]'
            ).first

            await email_input.fill(SMILE_EMAIL)
            await password_input.fill(SMILE_PASSWORD)

            # Login button
            buttons = page.locator("button")
            button_count = await buttons.count()

            clicked = False

            for i in range(button_count):
                btn = buttons.nth(i)

                try:
                    txt = (
                        await btn.inner_text()
                    ).strip().lower()

                    if (
                        "entrar" in txt
                        or "login" in txt
                    ):
                        await btn.click()
                        clicked = True
                        break

                except Exception:
                    pass

            if not clicked:
                await password_input.press("Enter")

            await page.wait_for_timeout(5000)

            current_url = page.url
            body = await page.locator("body").inner_text()

            # Find Smile Coin related lines
            balance_lines = []

            for line in body.splitlines():
                line = line.strip()

                if not line:
                    continue

                lower = line.lower()

                if (
                    "smilecoin" in lower
                    or "smile coin" in lower
                    or "moeda smile" in lower
                ):
                    balance_lines.append(line)

            await browser.close()
            await pw.stop()

            if (
                "login" in current_url.lower()
                or "accountlogin" in current_url.lower()
            ):
                await update.message.reply_text(
                    "❌ Smile One Login မအောင်မြင်ပါဘူး။\n\n"
                    "Email / Password ကို Railway Variables မှာ "
                    "စစ်ပေးပါ။"
                )
                return

            if balance_lines:
                await update.message.reply_text(
                    "🪙 SMILE COIN BALANCE\n\n"
                    + "\n".join(balance_lines[:10])
                )
            else:
                await update.message.reply_text(
                    "⚠️ Login အောင်မြင်ပေမယ့် "
                    "Smile Coin balance ကို page မှာ "
                    "မတွေ့သေးပါဘူး။\n\n"
                    f"Current page:\n{current_url}"
                )

        except Exception as e:
            try:
                await browser.close()
                await pw.stop()
            except Exception:
                pass

            await update.message.reply_text(
                "❌ Balance Error\n\n"
                + str(e)[:3000]
            )


async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌐 Opening Smile One..."
    )

    async with browser_lock:
        try:
            pw, browser, context_browser, page = await open_browser()

            await page.goto(
                "https://www.smile.one/",
                wait_until="domcontentloaded",
                timeout=60000,
            )

            title = await page.title()

            await browser.close()
            await pw.stop()

            await update.message.reply_text(
                "✅ Browser works!\n\n"
                "🌐 Smile One\n"
                f"📄 Title: {title}"
            )

        except Exception as e:
            await update.message.reply_text(
                "❌ Browser Error\n\n"
                + str(e)[:3000]
            )


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing"
        )

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("product", product)
    )

    app.add_handler(
        CommandHandler("balance", balance)
    )

    app.add_handler(
        CommandHandler("checkid", check_id)
    )

    app.add_handler(
        CommandHandler("test", test)
    )

    print(
        "🤖 Eren ML Dia Bot is starting..."
    )
    print("✅ Bot is running!")

    app.run_polling()


if __name__ == "__main__":
    main()
