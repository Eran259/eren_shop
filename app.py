import os
import sqlite3
import requests
import json
import threading
import time
import secrets
import smtplib
import urllib.parse
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import (
    Flask, request, session, redirect, url_for, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

# ==================================================
# APP CONFIG
# ==================================================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE_THIS_RANDOM_SECRET")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

# ==================================================
# RAILWAY / ENV VARIABLES
# ==================================================
DB_FILE = os.environ.get("DB_FILE", "/data/website.db")
os.makedirs(os.path.dirname(DB_FILE) or ".", exist_ok=True)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GROUP_ID = int(os.environ.get("GROUP_ID", "0"))
OWNER_CHAT_ID = int(os.environ.get("OWNER_CHAT_ID", "0"))
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "Eren")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "eren1852001")

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")

# ==================================================
# WHO PLAYS API (ML ID CHECK)
# ==================================================
WHOPLAYS_API_URL = os.environ.get("WHOPLAYS_API_URL", "https://plays.doedja.com/api/check")
WHOPLAYS_API_KEY = os.environ.get("WHOPLAYS_API_KEY", "")

# ==================================================
# SMILE ONE API
# ==================================================
SMILE_ONE_API_URL = os.environ.get("SMILE_ONE_API_URL", "https://jcplays.com/smilecoin/api")
SMILE_ONE_UID = os.environ.get("SMILE_ONE_UID", "")
SMILE_ONE_API_KEY = os.environ.get("SMILE_ONE_API_KEY", "")

# ==================================================
# TIME
# ==================================================
def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ==================================================
# DATABASE
# ==================================================
def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT,
            password TEXT NOT NULL,
            balance INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            device_name TEXT DEFAULT 'Unknown'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            game TEXT,
            package TEXT,
            game_id TEXT,
            server_id TEXT,
            telegram_username TEXT,
            acc_mail TEXT,
            payment TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deposit_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            amount INTEGER NOT NULL,
            transaction_id TEXT NOT NULL,
            payment TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            created_at TEXT NOT NULL,
            telegram_username TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            token TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS telegram_users (
            chat_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game TEXT NOT NULL,
            package TEXT NOT NULL,
            price INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS telegram_forward_map (
            owner_message_id INTEGER PRIMARY KEY,
            customer_chat_id INTEGER NOT NULL,
            customer_message_id INTEGER,
            created_at TEXT NOT NULL
        )
    """)

    # Seed products
    cursor.execute("SELECT COUNT(*) FROM products")
    if cursor.fetchone()[0] == 0:
        seed_data = {
            "ML": ["86 💎 - 5,700 Ks", "172 💎 - 12,000 Ks", "257 💎 - 17,000 Ks", "706 💎 - 42,000 Ks", "2195 💎 - 135,000 Ks", "3688 💎 - 210,000 Ks", "5532 💎 - 320,000 Ks", "9288 💎 - 530,000 Ks", "Weekly Pass - 6,700 Ks", "Weekly Elit Bundle - 4,000 Ks", "Monthly Bundle - 19,000 Ks", "Twilight Pass - 36,000 Ks", "50 + 50 💎 - 3,900 Ks", "150 + 150 💎 - 12,000 Ks", "250 + 250 💎 - 17,000 Ks", "500 + 500 💎 - 36,000 Ks"],
            "PUBG": ["60 UC - 600 Ks", "325 UC - 3,250 Ks", "660 UC - 6,600 Ks", "1800 UC - 18,000 Ks", "3850 UC - 38,500 Ks"],
            "HOK": ["60 Tokens - 1,000 Ks", "120 Tokens - 2,000 Ks", "250 Tokens - 4,000 Ks", "500 Tokens - 8,000 Ks", "1000 Tokens - 15,000 Ks"],
            "TG Pre": ["3 Months - 3,000 Ks", "6 Months - 6,000 Ks", "12 Months - 12,000 Ks"],
            "Smile One Code BRL": ["30 BRL - 26,000 Ks", "100 BRL - 86,000 Ks", "500 BRL - 427,000 Ks"],
            "Smile One Coin PHP": ["280 PHP - 21,000 Ks", "560 PHP - 41,000 Ks"]
        }
        for game, packages in seed_data.items():
            for pkg in packages:
                price = int(pkg.split(" - ")[1].replace(" Ks", "").replace(",", ""))
                cursor.execute(
                    "INSERT INTO products (game, package, price, created_at) VALUES (?, ?, ?, ?)",
                    (game, pkg, price, now())
                )

    conn.commit()
    conn.close()
    print("✅ Database tables created successfully!")

init_db()

# ==================================================
# STYLE
# ==================================================
STYLE = """
<style>
* { box-sizing: border-box; }
body {
    margin: 0; padding: 20px;
    background: #0f172a;
    background-image: url('/static/wallpaper.png');
    background-size: cover;
    background-position: center;
    background-attachment: fixed;
    color: white;
    font-family: Arial, sans-serif;
    padding-bottom: 75px;
}
.box {
    width: 100%; max-width: 430px; margin: auto;
    background: #1e293b; padding: 20px;
    border-radius: 20px;
    box-shadow: 0 10px 30px rgba(0,0,0,.3);
}
h1 { text-align: center; color: #00e5ff; margin-bottom: 25px; }
h2 { color: #00e5ff; }
.card {
    background: #0f172a; padding: 16px;
    margin-top: 12px; border-radius: 14px;
}
input, select, button {
    width: 100%; min-height: 48px; margin-top: 10px;
    padding: 12px; border-radius: 10px; font-size: 16px;
}
input, select {
    background: #0f172a; color: white;
    border: 1px solid #475569;
}
button {
    border: 0; background: #00e5ff; color: #000;
    font-weight: bold; cursor: pointer;
}
.green { background: #22c55e; color: white; }
.red { background: #ef4444; color: white; }
.balance { text-align: center; font-size: 30px; font-weight: bold; color: #22c55e; padding: 15px; }
.success { color: #4ade80; margin-top: 15px; }
.error { color: #f87171; margin-top: 15px; }
a { color: #00e5ff; text-decoration: none; }
.small { color: #94a3b8; font-size: 13px; }
.hidden { display: none; }
.status { display: inline-block; padding: 6px 10px; border-radius: 8px; background: #f59e0b; color: #000; font-weight: bold; }
</style>
"""

# ==================================================
# ML ID CHECK (WhoPlays API)
# ==================================================
def check_ml_id(player_id, zone_id):
    """MLBB Player ID နဲ့ Zone ID မှန်/မမှန် စစ်ဆေးတဲ့ Function"""
    if not WHOPLAYS_API_KEY:
        return {"success": False, "error": "WhoPlays API Key မရှိပါ"}

    try:
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": WHOPLAYS_API_KEY
        }
        payload = {
            "game": "mobile-legends",
            "userId": str(player_id).strip(),
            "zoneId": str(zone_id).strip()
        }
        response = requests.post(WHOPLAYS_API_URL, json=payload, headers=headers, timeout=15)

        if response.status_code == 200:
            data = response.json()
            if data.get("success") or data.get("username") or data.get("name"):
                return {
                    "success": True,
                    "username": data.get("username") or data.get("name") or data.get("nickname") or "Unknown",
                    "raw": data
                }
            return {"success": False, "error": data.get("message", "Player မတွေ့ပါ"), "raw": data}
        elif response.status_code == 404:
            return {"success": False, "error": "Player မတွေ့ပါ (ID/Zone မှားနိုင်သည်)"}
        elif response.status_code == 429:
            return {"success": False, "error": "Rate limit ကျော်သွားပါပြီ။ ခဏစောင့်ပါ။"}
        else:
            return {"success": False, "error": f"API Error: {response.status_code}"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "API အချိန်ကုန်သွားပါပြီ"}
    except Exception as e:
        return {"success": False, "error": str(e)}

  # ==================================================
# SMILE ONE API
# ==================================================
def get_smile_one_code(amount, product_type, email=None):
    try:
        url = f"{SMILE_ONE_API_URL}/generate"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": SMILE_ONE_API_KEY,
            "X-UID": SMILE_ONE_UID
        }
        payload = {
            "uid": SMILE_ONE_UID,
            "amount": amount,
            "type": product_type
        }
        if email:
            payload["email"] = email

        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                return {"success": True, "code": data.get("code"), "message": data.get("message")}
            return {"success": False, "error": data.get("message", "Unknown error")}
        return {"success": False, "error": f"API Error: {response.status_code}"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "API request timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}

      # ==================================================
# TELEGRAM HELPERS
# ==================================================
def send_telegram_message(text, chat_id=None):
    target = chat_id if chat_id is not None else GROUP_ID
    if not BOT_TOKEN or target in (None, "", 0):
        print("❌ Telegram Error: BOT_TOKEN or chat_id missing")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": str(target), "text": str(text)}
    try:
        r = requests.post(url, data=payload, timeout=20)
        return r.ok and r.json().get("ok") is True
    except Exception as e:
        print(f"❌ Telegram Error: {e}")
        return False

def send_telegram_message_with_buttons(text, reply_markup=None):
    if not BOT_TOKEN:
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {"chat_id": GROUP_ID, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            data["reply_markup"] = reply_markup
        r = requests.post(url, data=data, timeout=20)
        return r.status_code == 200
    except Exception as e:
        print("Telegram Error:", e)
        return False

def send_message_to_user(username, text):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM telegram_users WHERE username = ? LIMIT 1",
                       (username.lstrip("@").strip(),))
        user = cursor.fetchone()
        if not user:
            cursor.execute("SELECT telegram_username FROM orders WHERE username=? AND telegram_username IS NOT NULL AND telegram_username != '' ORDER BY id DESC LIMIT 1", (username,))
            ou = cursor.fetchone()
            if not ou:
                cursor.execute("SELECT telegram_username FROM deposit_requests WHERE username=? AND telegram_username IS NOT NULL AND telegram_username != '' ORDER BY id DESC LIMIT 1", (username,))
                ou = cursor.fetchone()
            if ou and ou[0]:
                uname = str(ou[0]).strip().lstrip("@")
                r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/getChat",
                                  data={"chat_id": f"@{uname}"}, timeout=10)
                if r.status_code == 200 and r.json().get("ok"):
                    chat_id = r.json()["result"]["chat"]["id"]
                    cursor.execute("INSERT OR REPLACE INTO telegram_users (chat_id, username, first_name, created_at) VALUES (?, ?, ?, ?)",
                                   (chat_id, uname, "", now()))
                    conn.commit()
                    user = {"chat_id": chat_id}
                else:
                    conn.close()
                    return False
            else:
                conn.close()
                return False
        chat_id = user["chat_id"] if isinstance(user, dict) else user["chat_id"]
        conn.close()
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                          data={"chat_id": chat_id, "text": text}, timeout=20)
        return r.status_code == 200
    except Exception as e:
        print(f"Error sending to {username}: {e}")
        return False

    # ==================================================
# ROUTES: HOME / AUTH
# ==================================================
@app.route("/")
def home():
    if "username" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if not username or not email or not password:
            error = "⚠️ အကုန်ဖြည့်ပါ"
        elif len(username) < 3:
            error = "⚠️ Username အနည်းဆုံး 3 လုံး"
        elif len(password) < 6:
            error = "⚠️ Password အနည်းဆုံး 6 လုံး"
        elif password != confirm:
            error = "⚠️ Password မတူပါ"
        else:
            conn = get_db()
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO users (username, email, password, balance, created_at) VALUES (?, ?, ?, ?, ?)",
                               (username, email, generate_password_hash(password), 0, now()))
                conn.commit()
                conn.close()
                session["username"] = username
                msg = f"🆕 NEW USER\n━━━━━━━━━━━\n👤 {username}\n📧 {email}\n🕒 {now()}"
                send_telegram_message(msg, GROUP_ID)
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError:
                conn.close()
                error = "⚠️ ဒီ Username ရှိပြီးသားပါ"
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Register</title>{STYLE}</head><body><div class="box"><h1>👤 Create Account</h1><form method="POST"><input name="username" placeholder="👤 Username" required><input type="email" name="email" placeholder="📧 Gmail" required><input type="password" name="password" placeholder="🔒 Password" required><input type="password" name="confirm" placeholder="🔒 Confirm Password" required><button class="green" type="submit">✅ Register</button></form><p class="error">{error}</p><p>Account ရှိပြီးသားလား? <a href="/login">Login</a></p></div></body></html>"""

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()
        if user and check_password_hash(user['password'], password):
            session["username"] = username
            ua = request.headers.get('User-Agent', 'Unknown')
            device = ua.split('(')[1].split(')')[0] if '(' in ua and ')' in ua else ua[:30]
            cursor.execute("UPDATE users SET device_name = ? WHERE username = ?", (device, username))
            conn.commit()
            conn.close()
            return redirect(url_for("dashboard"))
        conn.close()
        error = "❌ Username သို့မဟုတ် Password မှားနေပါတယ်"
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Login</title>{STYLE}</head><body><div class="box"><h1>🔐 Login</h1><form method="POST"><input name="username" placeholder="👤 Username" required><input type="password" name="password" placeholder="🔒 Password" required><button type="submit">🔐 Login</button></form><p class="error">{error}</p><p>Account မရှိသေးပါသလား? <a href="/register">Register</a></p><p><a href="/forgot-password">🔑 Forgot Password?</a></p></div></body></html>"""

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ==================================================
# ✅ ML ID CHECK API ENDPOINT
# ==================================================
@app.route("/api/check-ml-id", methods=["POST"])
def api_check_ml_id():
    """Frontend ကနေ AJAX နဲ့ ခေါ်ပြီး ML ID စစ်ဆေးနိုင်တဲ့ API"""
    if "username" not in session:
        return jsonify({"success": False, "error": "Login ဝင်ပါ"}), 401
    try:
        data = request.get_json(silent=True) or {}
        player_id = str(data.get("player_id", "")).strip()
        zone_id = str(data.get("zone_id", "")).strip()
        if not player_id or not zone_id:
            return jsonify({"success": False, "error": "Player ID နဲ့ Zone ID ဖြည့်ပါ"})
        result = check_ml_id(player_id, zone_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

  # ==================================================
# DASHBOARD
# ==================================================
@app.route("/dashboard")
def dashboard():
    if "username" not in session:
        return redirect(url_for("login"))
    username = session["username"]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username, email, balance FROM users WHERE username=?", (username,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        session.clear()
        return redirect(url_for("login"))
    wallet_balance = int(user[2] or 0)

    cursor.execute("SELECT game, COUNT(*) FROM orders WHERE status IN ('Confirmed','Completed') GROUP BY game")
    sold_counts = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute("SELECT COUNT(*) FROM notifications WHERE username=? AND is_read=0", (username,))
    unread = cursor.fetchone()[0]
    cursor.execute("SELECT id, type, title, message, created_at FROM notifications WHERE username=? ORDER BY created_at DESC LIMIT 10", (username,))
    notifs = cursor.fetchall()
    cursor.execute("UPDATE notifications SET is_read=1 WHERE username=?", (username,))
    conn.commit()
    conn.close()

    ml_sold = sold_counts.get("ML", 0)
    pubg_sold = sold_counts.get("PUBG", 0)
    hok_sold = sold_counts.get("HOK", 0)
    tg_sold = sold_counts.get("TG Pre", 0)
    brl_sold = sold_counts.get("Smile One Code BRL", 0)
    php_sold = sold_counts.get("Smile One Coin PHP", 0)

    notice_html = ""
    for n in notifs:
        notice_html += f"""<div style="background:#1e293b;padding:14px;border-radius:12px;margin-bottom:10px;"><div style="font-weight:bold;color:#fff;">{n[2]}</div><div style="font-size:13px;color:#b0c4de;margin-top:4px;">{n[3]}</div><div style="font-size:11px;color:#6b7280;margin-top:6px;">{n[4]}</div></div>"""
    if not notice_html:
        notice_html = "<div style='color:#94a3b8;text-align:center;padding:20px;'>အကြောင်းကြားစာ မရှိသေးပါ။</div>"

    bell_dot = '<span style="position:absolute;top:-2px;right:-2px;width:10px;height:10px;background:#ef4444;border-radius:50%;border:2px solid #0d1117;"></span>' if unread > 0 else ''
    admin_link = '<a href="/admin" style="display:block;text-align:center;margin-top:15px;"><button>⚙️ Admin Panel</button></a>' if username == ADMIN_USERNAME else ""

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><title>Eren's Shop</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:Arial,sans-serif;background:#000;color:#fff;padding-bottom:80px;}}
.header{{background:#0d1117;padding:15px 20px;display:flex;justify-content:space-between;align-items:center;}}
.header .title{{font-size:20px;color:#14b8a6;font-weight:bold;}}
.header .right{{display:flex;align-items:center;gap:10px;}}
.header .balance{{background:#1e293b;padding:6px 16px;border-radius:20px;font-size:14px;color:#4ade80;font-weight:bold;}}
.bell-btn{{position:relative;background:transparent;border:none;color:#fff;font-size:24px;cursor:pointer;padding:0;}}
.modal-overlay{{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.85);display:none;justify-content:center;align-items:center;z-index:9999;}}
.modal-box{{background:#0d1117;width:92%;max-width:420px;border-radius:20px;padding:20px;border:1px solid #222;max-height:80vh;overflow-y:auto;position:relative;}}
.modal-box .close-btn{{position:absolute;top:10px;right:15px;font-size:28px;color:#94a3b8;cursor:pointer;background:none;border:none;}}
.modal-box h3{{color:#14b8a6;font-size:20px;margin-bottom:15px;padding-right:30px;}}
.banner-container{{position:relative;margin:15px;border-radius:12px;overflow:hidden;}}
.banner-image{{width:100%;display:block;}}
.banner-logo{{position:absolute;top:10px;left:10px;width:50px;height:50px;border-radius:50%;border:2px solid #fff;object-fit:cover;background:#fff;}}
.product-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;padding:15px;max-width:500px;margin:auto;}}
.product-card{{background:#14b8a6;border-radius:12px;padding:15px 10px;text-align:center;text-decoration:none;color:#fff;}}
.product-card img{{width:70%;height:70px;object-fit:contain;border-radius:6px;margin-bottom:8px;}}
.product-card .name{{font-weight:bold;font-size:14px;}}
.product-card .sold{{font-size:12px;color:rgba(255,255,255,0.9);margin-top:4px;display:block;}}
.bottom-nav{{position:fixed;bottom:0;left:0;right:0;background:#14b8a6;display:flex;justify-content:space-around;padding:8px 0 12px 0;z-index:999;}}
.bottom-nav a{{display:flex;flex-direction:column;align-items:center;text-decoration:none;color:#fff;font-size:11px;}}
.bottom-nav a .icon{{font-size:22px;margin-bottom:2px;}}
.bottom-nav a.active{{color:#0d1117;font-weight:bold;}}
</style></head><body>
<div class="header"><div class="title">Eren's Shop</div><div class="right"><div class="balance">💳 {wallet_balance:,} Ks</div><button class="bell-btn" onclick="openNotice()">🔔{bell_dot}</button></div></div>
<div class="banner-container"><img src="/static/ad_banner.png" class="banner-image"><img src="/static/logo.png" class="banner-logo"></div>
<div id="noticeModal" class="modal-overlay" onclick="closeNoticeOutside(event)"><div class="modal-box"><button class="close-btn" onclick="closeNotice()">×</button><h3>📢 အကြောင်းကြားစာများ</h3>{notice_html}</div></div>
<div class="product-grid">
<a href="/packages/ML" class="product-card"><img src="/static/ml.png"><div class="name">Mobile Legends</div><span class="sold">{ml_sold:,} Sold</span></a>
<a href="/packages/PUBG" class="product-card"><img src="/static/pubg.png"><div class="name">PUBG Mobile</div><span class="sold">{pubg_sold:,} Sold</span></a>
<a href="/packages/HOK" class="product-card"><img src="/static/hok.png"><div class="name">Honor Of Kings</div><span class="sold">{hok_sold:,} Sold</span></a>
<a href="/packages/TG Pre" class="product-card"><img src="/static/telegram.png"><div class="name">Telegram Premium</div><span class="sold">{tg_sold:,} Sold</span></a>
<div style="grid-column:1/-1;text-align:center;color:#14b8a6;font-weight:bold;margin-top:10px;">⚡ Auto System</div>
<a href="/packages/Smile One Code BRL" class="product-card" style="background:#f59e0b;"><img src="/static/smileone.png"><div class="name">Smile One BRL (Auto)</div><span class="sold">{brl_sold:,} Sold</span></a>
<a href="/packages/Smile One Coin PHP" class="product-card" style="background:#f59e0b;"><img src="/static/smileone.png"><div class="name">Smile One PHP (Auto)</div><span class="sold">{php_sold:,} Sold</span></a>
</div>
{admin_link}
<div class="bottom-nav">
<a href="/dashboard" class="active"><span class="icon">🏠</span>Shop</a>
<a href="/wallet"><span class="icon">💰</span>Recharge</a>
<a href="/orders"><span class="icon">📦</span>Orders</a>
<a href="/profile"><span class="icon">👤</span>Profile</a>
</div>
<script>
function openNotice(){{document.getElementById('noticeModal').style.display='flex';setTimeout(()=>location.reload(),3000);}}
function closeNotice(){{document.getElementById('noticeModal').style.display='none';}}
function closeNoticeOutside(e){{if(e.target===document.getElementById('noticeModal'))closeNotice();}}
</script>
</body></html>"""

# ==================================================
# WALLET
# ==================================================
@app.route("/wallet", methods=["GET", "POST"])
def wallet():
    if "username" not in session:
        return redirect(url_for("login"))
    username = session["username"]
    message = ""
    message_type = "success"
    active_tab = request.args.get("tab", "deposit")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username, email, balance FROM users WHERE username=?", (username,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        session.clear()
        return redirect(url_for("login"))
    try:
        wallet_balance = int(float(str(user[2] or 0).strip()))
    except Exception:
        wallet_balance = 0

    if request.method == "POST" and request.form.get("action") == "deposit":
        amount = request.form.get("amount", "").strip()
        transaction = request.form.get("transaction", "").strip()
        screenshot = request.files.get("screenshot")
        if not amount or not amount.isdigit() or int(amount) < 1000:
            message = "⚠️ အနည်းဆုံး 1,000 Ks"
            message_type = "error"
        elif not transaction.isdigit() or len(transaction) != 5:
            message = "⚠️ Transaction 5 လုံး"
            message_type = "error"
        elif not screenshot or not screenshot.filename:
            message = "⚠️ Screenshot ထည့်ပါ"
            message_type = "error"
        else:
            amount = int(amount)
            cursor.execute("INSERT INTO deposit_requests (username, amount, transaction_id, payment, status, created_at, telegram_username) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (username, amount, transaction, "Manual", "Pending", now(), None))
            deposit_id = cursor.lastrowid
            conn.commit()

            deposit_text = f"💰 NEW DEPOSIT\n━━━━━━━━━━━\n🆔 #{deposit_id}\n👤 {username}\n💵 {amount:,} Ks\n🔢 {transaction}"
            reply_markup = {"inline_keyboard": [[{"text": "✅ Confirm", "callback_data": f"confirm_deposit_{deposit_id}"}, {"text": "❌ Reject", "callback_data": f"reject_deposit_{deposit_id}"}]]}

            filename = f"{deposit_id}_{int(time.time())}.png"
            temp_path = os.path.join('/tmp', filename)
            screenshot.save(temp_path)

            def send_to_owner():
                try:
                    with open(temp_path, 'rb') as f:
                        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
                        data = {"chat_id": GROUP_ID, "caption": deposit_text}
                        if reply_markup:
                            data["reply_markup"] = json.dumps(reply_markup)
                        requests.post(url, data=data, files={"photo": f}, timeout=30)
                except Exception as e:
                    print(f"Send Photo Error: {e}")
            threading.Thread(target=send_to_owner, daemon=True).start()
            message = f"✅ Deposit #{deposit_id} ပို့ပြီးပါပြီ။"

    cursor.execute("""
        SELECT 'confirmed' as type, id, username, amount, description, created_at FROM wallet_transactions WHERE username=?
        UNION ALL
        SELECT 'pending', id, username, amount, status, created_at FROM deposit_requests WHERE username=? AND status='Pending'
        UNION ALL
        SELECT 'rejected', id, username, amount, status, created_at FROM deposit_requests WHERE username=? AND status='Rejected'
        ORDER BY created_at DESC LIMIT 30
    """, (username, username, username))
    history = cursor.fetchall()
    conn.close()

    history_html = ""
    for item in history:
        if item[0] == 'confirmed':
            is_dep = "DEPOSIT" in item[4].upper()
            sign = "+" if is_dep else "-"
            color = '#4ade80' if is_dep else '#f87171'
            history_html += f"""<div style="background:#0d1117;border:1px solid #222;border-radius:12px;padding:15px;margin-bottom:10px;"><b style="color:{color};">{sign}{item[3]:,} Ks</b><br><small style="color:#94a3b8;">{item[4]}</small><br><small>{item[5]}</small></div>"""
        elif item[0] == 'rejected':
            history_html += f"""<div style="background:#0d1117;border:1px solid #222;border-left:4px solid #ef4444;border-radius:12px;padding:15px;margin-bottom:10px;"><b style="color:#ef4444;">❌ Rejected {item[3]:,} Ks</b><br><small>{item[5]}</small></div>"""
        else:
            history_html += f"""<div style="background:#0d1117;border:1px solid #222;border-left:4px solid #f59e0b;border-radius:12px;padding:15px;margin-bottom:10px;"><b style="color:#f59e0b;">🟡 Pending {item[3]:,} Ks</b><br><small>{item[5]}</small></div>"""
    if not history_html:
        history_html = "<div style='text-align:center;color:#94a3b8;'>မှတ်တမ်း မရှိသေးပါ။</div>"

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><title>Recharge</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:Arial,sans-serif;background:#000;color:#fff;padding-bottom:80px;}}
.header{{background:#0d1117;padding:15px;border-bottom:1px solid #222;text-align:center;}}
.header h1{{font-size:20px;color:#14b8a6;}}
.container{{max-width:500px;margin:auto;padding:15px;}}
.notice-box{{background:#bae6fd;color:#0c4a6e;padding:15px;border-radius:10px;font-size:14px;margin-bottom:15px;text-align:center;}}
.tabs{{display:flex;gap:10px;margin-bottom:20px;}}
.tab-btn{{flex:1;padding:12px;border-radius:10px;text-align:center;font-weight:bold;text-decoration:none;display:block;}}
.tab-btn.active{{background:#1d4ed8;color:#fff;}}
.tab-btn.inactive{{background:#fff;color:#000;}}
.pay-card{{background:#0d1117;border:1px solid #222;border-radius:12px;padding:15px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;}}
.btn-copy{{background:#1e293b;color:#fff;border:none;padding:6px 15px;border-radius:6px;cursor:pointer;}}
input,select{{width:100%;padding:12px;margin-top:8px;border-radius:8px;border:1px solid #222;background:#0d1117;color:#fff;}}
.btn-green{{width:100%;padding:14px;background:#22c55e;border:none;border-radius:10px;font-weight:bold;color:#000;font-size:16px;margin-top:15px;cursor:pointer;}}
.bottom-nav{{position:fixed;bottom:0;left:0;right:0;background:#14b8a6;display:flex;justify-content:space-around;padding:8px 0 12px 0;z-index:999;}}
.bottom-nav a{{display:flex;flex-direction:column;align-items:center;text-decoration:none;color:#fff;font-size:11px;}}
.bottom-nav a .icon{{font-size:22px;}}
</style></head><body>
<div class="header"><h1>💰 Recharge</h1></div>
<div class="container">
<div class="notice-box">Deposit Order တင်ပြီးလျှင် Bot ကတစ်ဆင့် owner စီစာပို့ပေးပါ</div>
<div class="tabs">
<a href="/wallet?tab=deposit" class="tab-btn {'active' if active_tab=='deposit' else 'inactive'}">ငွေဖြည့်မည်</a>
<a href="/wallet?tab=history" class="tab-btn {'active' if active_tab=='history' else 'inactive'}">မှတ်တမ်း</a>
</div>
<div id="deposit" style="display:{'block' if active_tab=='deposit' else 'none'}">
<form id="depositForm" method="POST" enctype="multipart/form-data">
<input type="hidden" name="action" value="deposit">
<div class="pay-card"><div><strong>K Pay</strong><br><small>09766605879<br>Thet Naing Swan</small></div><button type="button" class="btn-copy" onclick="copyText('09766605879')">Copy</button></div>
<div class="pay-card"><div><strong>UAB Pay</strong><br><small>09425160424<br>Thet Naing Swan</small></div><button type="button" class="btn-copy" onclick="copyText('09425160424')">Copy</button></div>
<input type="number" name="amount" min="1000" placeholder="💵 ပမာဏ (1000 Ks)" required>
<input type="text" name="transaction" maxlength="5" placeholder="🔢 Transaction နောက်ဆုံး 5 လုံး" required>
<input type="file" name="screenshot" accept="image/*" required>
<button id="submitBtn" class="btn-green" type="submit">📤 Deposit Request ပို့မည်</button>
</form>
</div>
<div id="history" style="display:{'block' if active_tab=='history' else 'none'}">{history_html}</div>
</div>
<div class="bottom-nav">
<a href="/dashboard"><span class="icon">🏠</span>Shop</a>
<a href="/wallet" class="active"><span class="icon">💰</span>Recharge</a>
<a href="/orders"><span class="icon">📦</span>Orders</a>
<a href="/profile"><span class="icon">👤</span>Profile</a>
</div>
<script>
function copyText(t){{navigator.clipboard.writeText(t).then(()=>alert('Copied: '+t));}}
document.getElementById('depositForm').addEventListener('submit',function(e){{
  e.preventDefault();
  if(!this.checkValidity()){{this.reportValidity();return;}}
  const btn=document.getElementById('submitBtn');
  btn.disabled=true;btn.innerHTML='⏳ တင်နေပါသည်...';
  this.submit();
}});
</script>
</body></html>"""

# ==================================================
# PACKAGES
# ==================================================
@app.route("/packages/<game>", methods=["GET"])
def packages(game):
    if "username" not in session:
        return redirect(url_for("login"))
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT package FROM products WHERE game=? ORDER BY id", (game,))
    pkgs = [row[0] for row in cursor.fetchall()]
    conn.close()

    game_names = {"ML": "Mobile Legends", "PUBG": "PUBG Mobile", "HOK": "Honor Of Kings",
                  "TG Pre": "Telegram Premium", "Smile One Code BRL": "Smile One BRL",
                  "Smile One Coin PHP": "Smile One PHP"}
    display_name = game_names.get(game, game)

    normal = [p for p in pkgs if not any(x in p for x in ["50 + 50", "150 + 150", "250 + 250", "500 + 500"])]
    double = [p for p in pkgs if any(x in p for x in ["50 + 50", "150 + 150", "250 + 250", "500 + 500"])]

    def build_cards(items):
        html = ""
        for pkg in items:
            enc = urllib.parse.quote(pkg, safe='')
            html += f'<a href="/place_order?game={game}&package={enc}" class="card"><div class="name">{pkg}</div></a>'
        return html

    packages_html = ""
    if game == "ML":
        if normal:
            packages_html += f'<div class="section-header">Normal Diamond 💎</div><div class="grid-2">{build_cards(normal)}</div>'
        if double:
            packages_html += f'<div class="section-header" style="background:#ef4444;">Double Diamond 💎 (One Time One Acc)</div><div class="grid-2">{build_cards(double)}</div>'
    else:
        packages_html = f'<div class="grid-2">{build_cards(normal) + build_cards(double)}</div>'

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><title>{display_name}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:Arial,sans-serif;background:#000;color:#fff;padding-bottom:80px;}}
.header{{background:#0d1117;padding:15px;border-bottom:1px solid #222;display:flex;align-items:center;justify-content:center;position:relative;}}
.header .back-btn{{position:absolute;left:15px;color:#fff;text-decoration:none;font-size:18px;}}
.header h1{{font-size:20px;color:#14b8a6;}}
.container{{max-width:500px;margin:auto;padding:15px;}}
.section-header{{background:#14b8a6;color:#fff;font-weight:bold;padding:10px;border-radius:8px;margin:15px 0 10px;text-align:center;}}
.grid-2{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:10px;}}
.card{{background:#14b8a6;border-radius:12px;padding:15px 10px;text-align:center;text-decoration:none;color:#fff;}}
.card .name{{font-weight:bold;font-size:14px;}}
.bottom-nav{{position:fixed;bottom:0;left:0;right:0;background:#14b8a6;display:flex;justify-content:space-around;padding:8px 0 12px 0;z-index:999;}}
.bottom-nav a{{display:flex;flex-direction:column;align-items:center;text-decoration:none;color:#fff;font-size:11px;}}
.bottom-nav a .icon{{font-size:22px;}}
</style></head><body>
<div class="header"><a href="/order" class="back-btn">← Back</a><h1>📦 {display_name}</h1></div>
<div class="container">{packages_html}</div>
<div class="bottom-nav">
<a href="/dashboard"><span class="icon">🏠</span>Shop</a>
<a href="/wallet"><span class="icon">💰</span>Recharge</a>
<a href="/orders"><span class="icon">📦</span>Orders</a>
<a href="/profile"><span class="icon">👤</span>Profile</a>
</div>
</body></html>"""

# ==================================================
# PLACE ORDER (ML ID CHECK ပါဝင်သည်)
# ==================================================
@app.route("/place_order", methods=["GET", "POST"])
def place_order():
    if "username" not in session:
        return redirect(url_for("login"))
    username = session["username"]
    message = ""
    message_type = "success"
    game = request.args.get("game", "").strip()
    package = request.args.get("package", "").strip()

    if request.method == "POST":
        game = request.form.get("game", "").strip()
        package = request.form.get("package", "").strip()
        game_id = request.form.get("game_id", "").strip()
        server_id = request.form.get("server_id", "").strip()
        telegram_username = request.form.get("telegram_username", "").strip().lstrip("@")
        acc_mail = request.form.get("acc_mail", "").strip()
        payment = request.form.get("payment", "").strip()

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT price FROM products WHERE game=? AND package=?", (game, package))
        product = cursor.fetchone()
        conn.close()

        if not product:
            message = "⚠️ Product မတွေ့ပါ"
            message_type = "error"
        else:
            price = product[0]
            # ===== ML ID CHECK =====
            if game == "ML":
                if not game_id or not server_id:
                    message = "⚠️ ML Player ID နဲ့ Zone ID ထည့်ပါ"
                    message_type = "error"
                else:
                    check_result = check_ml_id(game_id, server_id)
                    if not check_result["success"]:
                        message = f"❌ ML ID မမှန်ပါ: {check_result['error']}"
                        message_type = "error"

            if message_type != "error":
                if game == "PUBG" and not game_id:
                    message = "⚠️ PUBG ID ထည့်ပါ"
                    message_type = "error"
                elif game == "HOK" and not game_id:
                    message = "⚠️ HOK UID ထည့်ပါ"
                    message_type = "error"
                elif game == "TG Pre" and not telegram_username:
                    message = "⚠️ Telegram Username ထည့်ပါ"
                    message_type = "error"
                elif game == "Smile One Coin PHP" and not acc_mail:
                    message = "⚠️ Account Mail ထည့်ပါ"
                    message_type = "error"
                elif not payment:
                    message = "⚠️ Payment ရွေးပါ"
                    message_type = "error"

            if message_type != "error":
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("SELECT balance FROM users WHERE username=?", (username,))
                bal_row = cursor.fetchone()
                if not bal_row:
                    message = "❌ User မတွေ့ပါ"
                    message_type = "error"
                else:
                    balance = float(bal_row[0] or 0)
                    if balance < price:
                        message = f"⚠️ Balance မလုံလောက်ပါ။ လိုအပ်: {price - balance:,.0f} Ks"
                        message_type = "error"
                    else:
                        if game == "Smile One Coin PHP":
                            result = get_smile_one_code(price, "PHP", email=acc_mail)
                            if result["success"]:
                                cursor.execute("INSERT INTO orders (username, game, package, status, created_at) VALUES (?, ?, ?, ?, ?)",
                                               (username, game, package, "Completed", now()))
                                conn.commit()
                                message = f"✅ PHP Coin ဖြည့်ပြီးပါပြီ"
                            else:
                                message = f"❌ {result['error']}"
                                message_type = "error"
                        elif game == "Smile One Code BRL":
                            result = get_smile_one_code(price, "BRL")
                            if result["success"]:
                                cursor.execute("INSERT INTO orders (username, game, package, status, created_at) VALUES (?, ?, ?, ?, ?)",
                                               (username, game, package, "Completed", now()))
                                conn.commit()
                                message = f"✅ Code: {result['code']}"
                            else:
                                message = f"❌ {result['error']}"
                                message_type = "error"
                        else:
                            cursor.execute("INSERT INTO orders (username, game, package, game_id, server_id, telegram_username, acc_mail, payment, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                           (username, game, package, game_id, server_id, telegram_username, acc_mail, payment, "Pending", now()))
                            order_id = cursor.lastrowid
                            conn.commit()
                            conn.close()
                            order_text = f"🛒 NEW ORDER\n━━━━━━━━━━━\n🆔 #{order_id}\n👤 {username}\n🎮 {game}\n📦 {package}\n💵 {price:,} Ks\n🆔 {game_id or '-'}\n🌎 {server_id or '-'}"
                            rm = {"inline_keyboard": [[{"text": "✅ Confirm", "callback_data": f"confirm_order_{order_id}"}, {"text": "❌ Reject", "callback_data": f"reject_order_{order_id}"}]]}
                            if send_telegram_message_with_buttons(order_text, json.dumps(rm)):
                                message = f"✅ Order #{order_id} တင်ပြီးပါပြီ"
                            else:
                                message = f"⚠️ Order #{order_id} သိမ်းပြီး Telegram မပို့ရပါ"
                                message_type = "error"

                              field_map = {
        "ML": ["gameIdBox", "serverIdBox"],
        "PUBG": ["gameIdBox"],
        "TG Pre": ["telegramBox"],
        "Smile One Coin PHP": ["mailBox"],
        "HOK": ["gameIdBox"]
    }
    req = field_map.get(game, [])
    gid_hidden = "hidden" if "gameIdBox" not in req else ""
    sid_hidden = "hidden" if "serverIdBox" not in req else ""
    tg_hidden = "hidden" if "telegramBox" not in req else ""
    mail_hidden = "hidden" if "mailBox" not in req else ""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Place Order</title>{STYLE}
<style>
body{{background:#0f172a;background-image:none !important;padding-bottom:80px;}}
.header{{background:#0d1117;padding:15px;border-bottom:1px solid #222;display:flex;align-items:center;justify-content:center;position:relative;}}
.header .back-btn{{position:absolute;left:15px;color:#fff;text-decoration:none;font-size:18px;}}
.header h1{{font-size:20px;color:#14b8a6;}}
.bottom-nav{{position:fixed;bottom:0;left:0;right:0;background:#14b8a6;display:flex;justify-content:space-around;padding:8px 0 12px 0;z-index:999;}}
.bottom-nav a{{display:flex;flex-direction:column;align-items:center;text-decoration:none;color:#fff;font-size:11px;}}
.bottom-nav a .icon{{font-size:22px;}}
.hidden{{display:none;}}
.id-result{{margin-top:8px;padding:10px;border-radius:8px;font-size:13px;display:none;}}
.id-ok{{background:#064e3b;color:#4ade80;border:1px solid #22c55e;}}
.id-bad{{background:#450a0a;color:#f87171;border:1px solid #ef4444;}}
</style></head><body>
<div class="header"><a href="javascript:history.back()" class="back-btn">← Back</a><h1>🛒 Place Order</h1></div>
<div class="box">
<div class="{message_type}">{message}</div>
<form method="POST">
<input type="hidden" name="game" value="{game}">
<input type="hidden" name="package" value="{package}">
<div id="gameIdBox" class="{gid_hidden}" style="margin-top:12px;">
<label style="color:#94a3b8;font-size:13px;display:block;margin-bottom:4px;">{'Account UID' if game=='HOK' else 'Game ID'}</label>
<input type="text" id="gameIdInput" name="game_id" placeholder="{'Account UID' if game=='HOK' else 'Enter Game ID'}" {"required" if "gameIdBox" in req else ""}>
</div>
<div id="serverIdBox" class="{sid_hidden}" style="margin-top:12px;">
<label style="color:#94a3b8;font-size:13px;display:block;margin-bottom:4px;">Server ID</label>
<input type="text" id="serverIdInput" name="server_id" placeholder="Enter Server ID" {"required" if "serverIdBox" in req else ""}>
</div>
{'<button type="button" id="checkBtn" style="margin-top:10px;background:#1d4ed8;color:#fff;padding:10px;border-radius:8px;border:none;font-weight:bold;cursor:pointer;">🔍 Check ML ID</button><div id="idResult" class="id-result"></div>' if game == 'ML' else ''}
<div id="telegramBox" class="{tg_hidden}" style="margin-top:12px;">
<label style="color:#94a3b8;font-size:13px;display:block;margin-bottom:4px;">Telegram Username</label>
<input type="text" name="telegram_username" placeholder="@username" {"required" if "telegramBox" in req else ""}>
</div>
<div id="mailBox" class="{mail_hidden}" style="margin-top:12px;">
<label style="color:#94a3b8;font-size:13px;display:block;margin-bottom:4px;">Account Mail</label>
<input type="email" name="acc_mail" placeholder="email@example.com" {"required" if "mailBox" in req else ""}>
</div>
<div style="margin-top:12px;">
<label style="color:#94a3b8;font-size:13px;display:block;margin-bottom:4px;">Payment</label>
<select name="payment" required><option value="">💳 ရွေးပါ</option><option value="Wallet">💰 Wallet</option></select>
</div>
<button type="submit" class="green" style="margin-top:20px;width:100%;padding:14px;font-size:16px;">🛒 Order တင်မည်</button>
</form>
</div>
<div class="bottom-nav">
<a href="/dashboard"><span class="icon">🏠</span>Shop</a>
<a href="/wallet"><span class="icon">💰</span>Recharge</a>
<a href="/orders"><span class="icon">📦</span>Orders</a>
<a href="/profile"><span class="icon">👤</span>Profile</a>
</div>
<script>
const checkBtn = document.getElementById('checkBtn');
if (checkBtn) {{
  checkBtn.addEventListener('click', async function() {{
    const pid = document.getElementById('gameIdInput').value.trim();
    const zid = document.getElementById('serverIdInput').value.trim();
    const res = document.getElementById('idResult');
    if (!pid || !zid) {{
      res.style.display='block';res.className='id-result id-bad';res.innerHTML='⚠️ Player ID နဲ့ Zone ID ဖြည့်ပါ';return;
    }}
    checkBtn.disabled = true; checkBtn.innerHTML = '⏳ စစ်ဆေးနေသည်...';
    try {{
      const r = await fetch('/api/check-ml-id', {{
        method: 'POST',
        headers: {{'Content-Type':'application/json'}},
        body: JSON.stringify({{player_id: pid, zone_id: zid}})
      }});
      const data = await r.json();
      res.style.display='block';
      if (data.success) {{
        res.className='id-result id-ok';
        res.innerHTML = '✅ Player: <b>' + (data.username || 'Found') + '</b>';
      }} else {{
        res.className='id-result id-bad';
        res.innerHTML = '❌ ' + (data.error || 'မတွေ့ပါ');
      }}
    }} catch(e) {{
      res.style.display='block';res.className='id-result id-bad';res.innerHTML='❌ Network Error';
    }}
    checkBtn.disabled = false; checkBtn.innerHTML = '🔍 Check ML ID';
  }});
}}
</script>
</body></html>"""

# ==================================================
# ORDERS
# ==================================================
@app.route("/orders")
def orders():
    if "username" not in session:
        return redirect(url_for("login"))
    username = session["username"]
    search = request.args.get("search", "").strip()
    conn = get_db()
    cursor = conn.cursor()
    if search:
        cursor.execute("SELECT id, game, package, game_id, server_id, status, created_at FROM orders WHERE username=? AND (game_id LIKE ? OR package LIKE ?) ORDER BY id DESC",
                       (username, f"%{search}%", f"%{search}%"))
    else:
        cursor.execute("SELECT id, game, package, game_id, server_id, status, created_at FROM orders WHERE username=? ORDER BY id DESC", (username,))
    rows = cursor.fetchall()
    conn.close()

    html = ""
    for r in rows:
        status = r[5]
        if status in ("Confirmed", "Completed"):
            color = "#22c55e"
        elif status == "Pending":
            color = "#f59e0b"
        else:
            color = "#ef4444"
        html += f"""<div style="display:flex;align-items:center;padding:12px 0;border-bottom:1px solid #f0f0f0;"><div style="width:30%;color:#1d4ed8;font-weight:bold;">{r[0]}<br><small style="color:#94a3b8;font-weight:normal;">ID: {r[3] or '-'}</small><br><small style="color:#94a3b8;font-weight:normal;">Svr: {r[4] or '-'}</small></div><div style="width:40%;font-size:14px;">{r[2]}</div><div style="width:30%;text-align:right;"><span style="background:{color};color:#fff;padding:4px 14px;border-radius:20px;font-size:12px;font-weight:bold;">{status.lower()}</span></div></div>"""
    if not html:
        html = "<div style='text-align:center;color:#94a3b8;padding:20px;'>Order မရှိသေးပါ။</div>"

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><title>Order History</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:Arial,sans-serif;background:#000;color:#fff;padding-bottom:80px;}}
.header{{background:#0d1117;padding:15px;border-bottom:1px solid #222;display:flex;align-items:center;}}
.header .back-btn{{color:#fff;text-decoration:none;font-size:18px;margin-right:15px;}}
.header h1{{font-size:20px;color:#14b8a6;}}
.container{{max-width:500px;margin:auto;padding:20px 15px;}}
.white-card{{background:#fff;border-radius:16px;padding:20px;color:#000;}}
.page-title{{text-align:center;font-weight:bold;font-size:18px;margin-bottom:20px;}}
.search-box{{display:flex;gap:10px;margin-bottom:20px;}}
.search-box input{{flex:1;padding:10px 15px;border:1px solid #ddd;border-radius:8px;font-size:14px;outline:none;}}
.search-box button{{background:#1d4ed8;color:#fff;border:none;padding:10px 20px;border-radius:8px;font-weight:bold;cursor:pointer;}}
.bottom-nav{{position:fixed;bottom:0;left:0;right:0;background:#14b8a6;display:flex;justify-content:space-around;padding:8px 0 12px 0;z-index:999;}}
.bottom-nav a{{display:flex;flex-direction:column;align-items:center;text-decoration:none;color:#fff;font-size:11px;}}
.bottom-nav a .icon{{font-size:22px;}}
</style></head><body>
<div class="header"><a href="/dashboard" class="back-btn">← Back</a><h1>မှတ်တမ်းများ</h1></div>
<div class="container">
<div class="white-card">
<div class="page-title">ဝယ်ယူမှုမှတ်တမ်းများ</div>
<form method="GET" action="/orders" class="search-box">
<input type="text" name="search" placeholder="Search by Game ID" value="{search}">
<button type="submit">Search</button>
</form>
{html}
</div>
</div>
<div class="bottom-nav">
<a href="/dashboard"><span class="icon">🏠</span>Shop</a>
<a href="/wallet"><span class="icon">💰</span>Recharge</a>
<a href="/orders" class="active"><span class="icon">📦</span>Orders</a>
<a href="/profile"><span class="icon">👤</span>Profile</a>
</div>
</body></html>"""

# ==================================================
# PROFILE
# ==================================================
@app.route("/profile")
def profile():
    if "username" not in session:
        return redirect(url_for("login"))
    username = session["username"]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username, email, balance, created_at, device_name FROM users WHERE username=?", (username,))
    user = cursor.fetchone()
    conn.close()
    device = user[4] if user[4] and user[4] != "Unknown" else "Unknown Device"
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><title>Profile</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:Arial,sans-serif;background:#000;color:#fff;padding-bottom:80px;}}
.header{{background:#0d1117;padding:15px;border-bottom:1px solid #222;text-align:center;}}
.header h1{{font-size:20px;color:#14b8a6;}}
.container{{max-width:500px;margin:auto;padding:20px;}}
.profile-card{{background:#0d1117;border:1px solid #222;border-radius:16px;padding:30px 20px;text-align:center;margin-bottom:20px;}}
.avatar{{width:100px;height:100px;border-radius:50%;object-fit:cover;margin:0 auto 15px;display:block;border:3px solid #14b8a6;}}
.username{{font-size:24px;font-weight:bold;color:#14b8a6;}}
.email{{color:#94a3b8;font-size:14px;margin-top:5px;}}
.balance-info{{color:#4ade80;font-size:18px;margin-top:10px;font-weight:bold;}}
.options-card{{background:#0d1117;border:1px solid #222;border-radius:16px;padding:15px 20px;margin-bottom:15px;}}
.row{{display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid #222;}}
.row:last-child{{border-bottom:none;}}
.btn-logout{{width:100%;padding:14px;background:#ef4444;border:none;border-radius:12px;font-weight:bold;color:#fff;font-size:16px;cursor:pointer;}}
.btn-contact{{width:100%;padding:14px;background:#14b8a6;border:none;border-radius:12px;font-weight:bold;color:#fff;font-size:16px;margin-bottom:10px;cursor:pointer;}}
.bottom-nav{{position:fixed;bottom:0;left:0;right:0;background:#14b8a6;display:flex;justify-content:space-around;padding:8px 0 12px 0;z-index:999;}}
.bottom-nav a{{display:flex;flex-direction:column;align-items:center;text-decoration:none;color:#fff;font-size:11px;}}
.bottom-nav a .icon{{font-size:22px;}}
</style></head><body>
<div class="header"><h1>👤 Profile</h1></div>
<div class="container">
<div class="profile-card">
<img src="/static/logo.png" class="avatar">
<div class="username">{user[0]}</div>
<div class="email">{user[1] or 'Not set'}</div>
<div class="balance-info">💰 {int(user[2] or 0):,} Ks</div>
</div>
<div class="options-card">
<div class="row"><div>📱 Device Log in</div><div style="color:#94a3b8;font-size:14px;">{device}</div></div>
<a href="/forgot-password" style="text-decoration:none;color:inherit;"><div class="row"><div>🔑 Change Password</div><div style="color:#14b8a6;">Edit ›</div></div></a>
</div>
<a href="https://t.me/erenIsNot4U" target="_blank" style="text-decoration:none;"><button class="btn-contact">📩 Contact Us</button></a>
<a href="/logout" style="text-decoration:none;"><button class="btn-logout">🚪 Logout</button></a>
</div>
<div class="bottom-nav">
<a href="/dashboard"><span class="icon">🏠</span>Shop</a>
<a href="/wallet"><span class="icon">💰</span>Recharge</a>
<a href="/orders"><span class="icon">📦</span>Orders</a>
<a href="/profile" class="active"><span class="icon">👤</span>Profile</a>
</div>
</body></html>"""

# ==================================================
# ADMIN
# ==================================================
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST" and "login" in request.form:
        u = request.form.get("admin_username", "").strip()
        p = request.form.get("admin_password", "").strip()
        if u == ADMIN_USERNAME and p == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin"))
        return "❌ Admin မှားနေပါတယ်", 403

    if not session.get("is_admin"):
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Admin</title>{STYLE}</head><body><div class="box"><h1>🔐 Admin Login</h1><form method="POST"><input type="hidden" name="login" value="1"><input type="text" name="admin_username" placeholder="Username" required><input type="password" name="admin_password" placeholder="Password" required><button class="green" type="submit">Login</button></form></div></body></html>"""

    message = ""
    conn = get_db()
    cursor = conn.cursor()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_price":
            pid = request.form.get("product_id")
            np = request.form.get("new_price", "").strip()
            if np.isdigit():
                cursor.execute("SELECT package FROM products WHERE id=?", (pid,))
                row = cursor.fetchone()
                if row:
                    base = row[0].rsplit(" - ", 1)[0] if " - " in row[0] else row[0]
                    new_pkg = f"{base} - {int(np):,} Ks"
                    cursor.execute("UPDATE products SET package=?, price=? WHERE id=?", (new_pkg, int(np), pid))
                    conn.commit()
                    message = f"✅ Update: {int(np):,} Ks"
        elif action == "add_product":
            g = request.form.get("game", "").strip()
            pkg = request.form.get("package", "").strip()
            pr = request.form.get("price", "").strip()
            if g and pkg and pr.isdigit():
                cursor.execute("INSERT INTO products (game, package, price, created_at) VALUES (?, ?, ?, ?)", (g, pkg, int(pr), now()))
                conn.commit()
                message = f"✅ Added: {pkg}"
        elif action == "delete_product":
            cursor.execute("DELETE FROM products WHERE id=?", (request.form.get("product_id"),))
            conn.commit()
            message = "✅ Deleted"

    cursor.execute("SELECT * FROM products ORDER BY game, id")
    products = cursor.fetchall()
    conn.close()

    grouped = {}
    for p in products:
        grouped.setdefault(p[1], []).append(p)

    game_html = ""
    for g, items in grouped.items():
        game_html += f"<h3 style='color:#14b8a6;font-size:14px;'>{g}</h3>"
        for it in items:
            game_html += f"""<div style='background:#1e293b;padding:6px;border-radius:6px;margin-bottom:4px;display:flex;justify-content:space-between;align-items:center;font-size:12px;gap:4px;'><div style='flex:1;'>{it[2]} ({it[3]:,} Ks)</div><form method='POST' style='display:flex;gap:3px;'><input type='hidden' name='product_id' value='{it[0]}'><input type='hidden' name='action' value='update_price'><input type='number' name='new_price' placeholder='New' style='width:60px;padding:3px;font-size:11px;'><button type='submit' class='green' style='padding:4px;font-size:11px;'>Up</button></form><form method='POST'><input type='hidden' name='product_id' value='{it[0]}'><input type='hidden' name='action' value='delete_product'><button type='submit' class='red' style='padding:4px;font-size:11px;'>Del</button></form></div>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Admin Panel</title>{STYLE}
<style>body{{background:#0f172a;background-image:none !important;padding-top:15px;font-size:13px;}}</style>
</head><body><div class="box">
<h1 style="font-size:18px;">⚙️ Admin Panel</h1>
<p class="success" style="font-size:12px;">{message}</p>
<div class="card"><h2 style="font-size:16px;">💰 Price Update</h2>{game_html}</div>
<div class="card"><h2 style="font-size:16px;">➕ Add Product</h2>
<form method="POST"><input type="hidden" name="action" value="add_product">
<select name="game" required><option value="">Game</option><option value="ML">ML</option><option value="PUBG">PUBG</option><option value="HOK">HOK</option><option value="TG Pre">TG Pre</option><option value="Smile One Code BRL">Smile BRL</option><option value="Smile One Coin PHP">Smile PHP</option></select>
<input type="text" name="package" placeholder="Package (e.g., 86 💎 - 5,700 Ks)" required>
<input type="number" name="price" placeholder="Price (Ks)" required>
<button type="submit" class="green">Add</button></form></div>
<a href="/admin/logout" style="text-decoration:none;"><button class="red" style="margin-top:10px;">🚪 Logout</button></a>
</div></body></html>"""

@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin"))

# ==================================================
# FORGOT / RESET PASSWORD
# ==================================================
def send_reset_email(email, token):
    try:
        base = os.environ.get("BASE_URL", "https://your-app.railway.app")
        link = f"{base}/reset-password/{token}"
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = email
        msg['Subject'] = "Password Reset - Eren's Shop"
        body = f"<h2>🔑 Reset Password</h2><p>Click: <a href='{link}'>{link}</a></p><p>Expires in 1 hour.</p>"
        msg.attach(MIMEText(body, 'html'))
        s = smtplib.SMTP('smtp.gmail.com', 587)
        s.starttls()
        s.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        s.send_message(msg)
        s.quit()
        return True
    except Exception as e:
        print(f"Email Error: {e}")
        return False

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    message = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email=?", (email,))
        user = cursor.fetchone()
        if not user:
            message = "❌ Email မတွေ့ပါ"
        else:
            token = secrets.token_urlsafe(32)
            exp = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("DELETE FROM password_resets WHERE email=?", (email,))
            cursor.execute("INSERT INTO password_resets (email, token, created_at, expires_at) VALUES (?, ?, ?, ?)", (email, token, now(), exp))
            conn.commit()
            message = "✅ Link ပို့ပြီးပါပြီ" if send_reset_email(email, token) else "❌ Email မပို့ရပါ"
        conn.close()
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Forgot</title>{STYLE}</head><body><div class="box"><h1>🔑 Forgot Password</h1><form method="POST"><input type="email" name="email" placeholder="📧 Email" required><button type="submit">Send Reset Link</button></form><p class="success">{message}</p><a href="/login"><button>⬅️ Back</button></a></div></body></html>"""

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM password_resets WHERE token=? AND expires_at > datetime('now')", (token,))
    reset = cursor.fetchone()
    conn.close()
    if not reset:
        return """<div class="box"><h1>❌ Link သက်တမ်းကုန်ပါပြီ</h1><a href="/forgot-password"><button>Try Again</button></a></div>"""
    message = ""
    if request.method == "POST":
        pw = request.form.get("password", "")
        cf = request.form.get("confirm", "")
        if len(pw) < 6:
            message = "⚠️ Password 6 လုံး"
        elif pw != cf:
            message = "⚠️ မတူပါ"
        else:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET password=? WHERE email=?", (generate_password_hash(pw), reset[1]))
            cursor.execute("DELETE FROM password_resets WHERE token=?", (token,))
            conn.commit()
            conn.close()
            return """<div class="box"><h1>✅ ပြောင်းပြီးပါပြီ</h1><a href="/login"><button>Login</button></a></div>"""
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Reset</title>{STYLE}</head><body><div class="box"><h1>🔑 Reset Password</h1><form method="POST"><input type="password" name="password" placeholder="New Password" required><input type="password" name="confirm" placeholder="Confirm" required><button type="submit">Reset</button></form><p class="error">{message}</p></div></body></html>"""

# ==================================================
# TELEGRAM CALLBACKS
# ==================================================
def confirm_deposit_from_telegram(deposit_id, chat_id, message_id):
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT * FROM deposit_requests WHERE id=?", (deposit_id,))
        dep = cursor.fetchone()
        if not dep or dep[5] != 'Pending':
            conn.close(); return
        username = dep[1]; amount = dep[2]
        cursor.execute("UPDATE deposit_requests SET status='Confirmed' WHERE id=?", (deposit_id,))
        cursor.execute("UPDATE users SET balance = balance + ? WHERE username=?", (amount, username))
        cursor.execute("INSERT INTO wallet_transactions (username, type, amount, description, created_at) VALUES (?, ?, ?, ?, ?)",
                       (username, 'deposit', amount, 'Deposit Confirmed', now()))
        conn.commit(); conn.close()
        txt = f"✅ DEPOSIT CONFIRMED\n#{deposit_id}\n{username}\n{amount:,} Ks"
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", data={"chat_id": chat_id, "message_id": message_id, "text": txt, "reply_markup": ""}, timeout=20)
        send_message_to_user(username, f"✅ Deposit #{deposit_id} အတည်ပြုပြီး {amount:,} Ks")
    except Exception as e:
        print(f"Confirm Deposit Error: {e}")

def reject_deposit_from_telegram(deposit_id, chat_id, message_id):
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT * FROM deposit_requests WHERE id=?", (deposit_id,))
        dep = cursor.fetchone()
        if not dep or dep[5] != 'Pending':
            conn.close(); return
        username = dep[1]
        cursor.execute("UPDATE deposit_requests SET status='Rejected' WHERE id=?", (deposit_id,))
        conn.commit(); conn.close()
        txt = f"❌ DEPOSIT REJECTED\n#{deposit_id}\n{username}"
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", data={"chat_id": chat_id, "message_id": message_id, "text": txt, "reply_markup": ""}, timeout=20)
        send_message_to_user(username, f"❌ Deposit #{deposit_id} ပယ်ဖျက်လိုက်ပါပြီ")
    except Exception as e:
        print(f"Reject Deposit Error: {e}")

def confirm_order_from_telegram(order_id, chat_id, message_id):
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE id=?", (order_id,))
        o = cursor.fetchone()
        if not o:
            conn.close(); return
        username = o[1]
        cursor.execute("UPDATE orders SET status='Confirmed' WHERE id=?", (order_id,))
        conn.commit(); conn.close()
        txt = f"✅ ORDER CONFIRMED\n#{order_id}\n{username}\n{o[2]}\n{o[3]}"
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", data={"chat_id": chat_id, "message_id": message_id, "text": txt, "reply_markup": ""}, timeout=20)
        send_message_to_user(username, f"✅ Order #{order_id} အတည်ပြုပြီးပါပြီ")
    except Exception as e:
        print(f"Confirm Order Error: {e}")

def reject_order_from_telegram(order_id, chat_id, message_id):
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE id=?", (order_id,))
        o = cursor.fetchone()
        if not o:
            conn.close(); return
        username = o[1]
        cursor.execute("UPDATE orders SET status='Rejected' WHERE id=?", (order_id,))
        conn.commit(); conn.close()
        txt = f"❌ ORDER REJECTED\n#{order_id}\n{username}\n{o[2]}\n{o[3]}"
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", data={"chat_id": chat_id, "message_id": message_id, "text": txt, "reply_markup": ""}, timeout=20)
        send_message_to_user(username, f"❌ Order #{order_id} ပယ်ဖျက်လိုက်ပါပြီ")
    except Exception as e:
        print(f"Reject Order Error: {e}")

@app.route("/telegram_callback", methods=["POST"])
def telegram_callback():
    try:
        data = request.get_json(silent=True) or {}
        cb = data.get("callback_query") or {}
        cb_data = cb.get("data", "")
        cb_msg = cb.get("message") or {}
        cb_msg_id = cb_msg.get("message_id")
        cb_chat_id = (cb_msg.get("chat") or {}).get("id")
        cb_id = cb.get("id")

        if cb_id:
            try:
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", data={"callback_query_id": cb_id}, timeout=10)
            except Exception:
                pass

        if cb_data.startswith("confirm_deposit_"):
            confirm_deposit_from_telegram(int(cb_data.rsplit("_", 1)[1]), cb_chat_id, cb_msg_id)
        elif cb_data.startswith("reject_deposit_"):
            reject_deposit_from_telegram(int(cb_data.rsplit("_", 1)[1]), cb_chat_id, cb_msg_id)
        elif cb_data.startswith("confirm_order_"):
            confirm_order_from_telegram(int(cb_data.rsplit("_", 1)[1]), cb_chat_id, cb_msg_id)
        elif cb_data.startswith("reject_order_"):
            reject_order_from_telegram(int(cb_data.rsplit("_", 1)[1]), cb_chat_id, cb_msg_id)

        msg = data.get("message")
        if msg:
            chat_id = (msg.get("chat") or {}).get("id")
            msg_id = msg.get("message_id")
            text = (msg.get("text") or msg.get("caption") or "").strip()
            reply_to = msg.get("reply_to_message") or {}

            if chat_id == OWNER_CHAT_ID and msg_id and reply_to.get("message_id"):
                conn = get_db(); cursor = conn.cursor()
                cursor.execute("SELECT customer_chat_id FROM telegram_forward_map WHERE owner_message_id=?", (reply_to.get("message_id"),))
                m = cursor.fetchone()
                conn.close()
                if m and m[0]:
                    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/copyMessage",
                                  data={"chat_id": m[0], "from_chat_id": OWNER_CHAT_ID, "message_id": msg_id}, timeout=20)
                    return "OK", 200

            if text == "/start":
                conn = get_db(); cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO telegram_users (chat_id, username, first_name, created_at) VALUES (?, ?, ?, ?)",
                               (chat_id, msg.get("from", {}).get("username", ""), msg.get("from", {}).get("first_name", ""), now()))
                conn.commit(); conn.close()
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                              data={"chat_id": chat_id, "text": "Hello, Eren's Shop 🛒 မှ ကြိုဆိုပါတယ်။\n#Bot_Owner - t.me/erenIsNot4U"}, timeout=20)
            elif chat_id and msg_id:
                fr = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/forwardMessage",
                                   data={"chat_id": OWNER_CHAT_ID, "from_chat_id": chat_id, "message_id": msg_id}, timeout=20)
                if fr.status_code == 200:
                    fwd_id = fr.json().get("result", {}).get("message_id")
                    if fwd_id:
                        conn = get_db(); cursor = conn.cursor()
                        cursor.execute("INSERT OR REPLACE INTO telegram_forward_map (owner_message_id, customer_chat_id, customer_message_id, created_at) VALUES (?, ?, ?, ?)",
                                       (int(fwd_id), int(chat_id), int(msg_id), now()))
                        conn.commit(); conn.close()
                    sent = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                         data={"chat_id": chat_id, "text": "Message Sent To Owner ✅"}, timeout=20)
                    if sent.status_code == 200:
                        cmid = sent.json().get("result", {}).get("message_id")
                        def del_msg():
                            time.sleep(3)
                            if cmid:
                                try:
                                    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage",
                                                  data={"chat_id": chat_id, "message_id": cmid}, timeout=10)
                                except Exception:
                                    pass
                        threading.Thread(target=del_msg, daemon=True).start()
        return "OK", 200
    except Exception as e:
        print(f"Callback error: {e}")
        return "OK", 200

# ==================================================
# HEALTH CHECK (Railway အတွက်)
# ==================================================
@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": now()})

# ==================================================
# RUN
# ==================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
