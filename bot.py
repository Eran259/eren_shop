import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from playwright.async_api import async_playwright

BOT_TOKEN = os.getenv("BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Eren ML Dia Bot\n\n"
        "✅ Bot is online!\n"
        "💎 Auto Recharge System is preparing..."
    )


async def browser_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌐 Opening Smile One...")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox"]
            )

            page = await browser.new_page()

            await page.goto(
                "https://www.smile.one/",
                wait_until="domcontentloaded",
                timeout=60000
            )

            title = await page.title()

            await browser.close()

        await update.message.reply_text(
            f"✅ Browser works!\n\n"
            f"🌐 Smile One\n"
            f"📄 Title: {title}"
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Browser Error\n\n{str(e)[:3000]}"
        )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", browser_test))

    print("🤖 Eren ML Dia Bot is starting...")
    print("✅ Bot is running!")

    app.run_polling()


if __name__ == "__main__":
    main()
