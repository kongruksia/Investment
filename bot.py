import os
import anthropic
import finnhub
import requests
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
finnhub_client = finnhub.Client(api_key=os.environ["FINNHUB_API_KEY"])
NEWS_API_KEY = os.environ["NEWS_API_KEY"]
BANGKOK = pytz.timezone("Asia/Bangkok")

user_data = {}

def get_user(user_id):
    if user_id not in user_data:
        user_data[user_id] = {"watchlist": [], "chat_id": user_id}
    return user_data[user_id]

def main_menu():
    keyboard = [
        [KeyboardButton("📊 Market Overview"), KeyboardButton("⭐ My Watchlist")],
        [KeyboardButton("📰 Top News"), KeyboardButton("💡 AI Insight")],
        [KeyboardButton("➕ Add Asset"), KeyboardButton("❌ Remove Asset")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_stock_price(symbol):
    try:
        quote = finnhub_client.quote(symbol.upper())
        if quote and quote.get('c'):
            return {
                "price": quote['c'],
                "change": quote['d'],
                "change_pct": quote['dp'],
                "high": quote['h'],
                "low": quote['l'],
                "prev_close": quote['pc']
            }
    except Exception:
        pass
    return None

def get_crypto_price(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol.upper()}USDT"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        data = r.json()
        if 'lastPrice' in data:
            return {
                "price": float(data['lastPrice']),
                "change": float(data['priceChange']),
                "change_pct": float(data['priceChangePercent']),
                "high": float(data['highPrice']),
                "low": float(data['lowPrice']),
                "volume": float(data['volume'])
            }
    except Exception:
        pass
    return None

def get_news(query, count=1):
    try:
        url = f"https://newsapi.org/v2/everything?q={query}&sortBy=publishedAt&pageSize={count}&apiKey={NEWS_API_KEY}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        return r.json().get('articles', [])
    except Exception:
        return []

def get_top_news():
    try:
        url = f"https://newsapi.org/v2/top-headlines?language=en&pageSize=1&apiKey={NEWS_API_KEY}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        return r.json().get('articles', [])
    except Exception:
        return []

async def analyze_asset(symbol, asset_type="stock"):
    if asset_type == "crypto":
        data = get_crypto_price(symbol)
        news = get_news(f"{symbol} cryptocurrency", 3)
    else:
        data = get_stock_price(symbol)
        news = get_news(f"{symbol} stock", 3)

    if not data:
        return f"❌ Could not fetch data for {symbol}. Please check the symbol."

    news_text = "\n".join([f"- {a['title']}" for a in news[:3]]) if news else "No recent news found."
    trend = "📈" if data['change_pct'] > 0 else "📉"

    prev_close = data.get('prev_close', 'N/A')
    prev_close_str = f"${prev_close:.2f}" if isinstance(prev_close, (int, float)) else str(prev_close)

    prompt = f"""You are an advanced financial analyst. Analyze {symbol} ({asset_type}) with this data:

Current Price: ${data['price']:.2f}
24h Change: {data['change_pct']:+.2f}%
24h High: ${data['high']:.2f}
24h Low: ${data['low']:.2f}
Previous Close: {prev_close_str}

Recent News:
{news_text}

Provide a detailed technical analysis with:
1. 📊 TECHNICAL INDICATORS - RSI estimate, trend direction, momentum
2. 📈 SUPPORT & RESISTANCE - key price levels
3. 🐂 BULL CASE - top 2 reasons to buy
4. 🐻 BEAR CASE - top 2 reasons to sell/avoid
5. ⚠️ RISK LEVEL - Low/Medium/High with explanation
6. 💡 AI RECOMMENDATION - Buy/Hold/Sell with confidence %
7. 🎯 PRICE TARGETS - short term (1 week) and medium term (1 month)

Be concise but detailed. Use emojis. Format cleanly."""

    try:
        response = claude.messages.create(
            model="claude-opus-4-7",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        analysis = response.content[0].text
    except Exception as e:
        return f"❌ AI analysis failed for {symbol}. Please try again later."

    header = (
        f"{trend} *{symbol.upper()} Analysis*\n"
        f"💰 Price: ${data['price']:.2f} ({data['change_pct']:+.2f}%)\n"
        f"📊 H: ${data['high']:.2f} | L: ${data['low']:.2f}\n\n"
    )

    return header + analysis

async def send_morning_brief(app):
    markets = {
        "S&P 500": get_stock_price("SPY"),
        "NASDAQ": get_stock_price("QQQ"),
        "Gold": get_stock_price("GLD"),
    }
    btc = get_crypto_price("BTC")
    eth = get_crypto_price("ETH")

    market_text = ""
    for name, data in markets.items():
        if data:
            arrow = "🟢" if data['change_pct'] > 0 else "🔴"
            market_text += f"{arrow} {name}: ${data['price']:.2f} ({data['change_pct']:+.2f}%)\n"

    if btc:
        arrow = "🟢" if btc['change_pct'] > 0 else "🔴"
        market_text += f"{arrow} BTC: ${btc['price']:,.0f} ({btc['change_pct']:+.2f}%)\n"
    if eth:
        arrow = "🟢" if eth['change_pct'] > 0 else "🔴"
        market_text += f"{arrow} ETH: ${eth['price']:,.0f} ({eth['change_pct']:+.2f}%)\n"

    if not market_text:
        market_text = "Market data unavailable.\n"

    top_news = get_top_news()
    finance_news = get_news("stock market finance", 1)
    tech_news = get_news("technology AI", 1)
    world_news = get_news("world politics economy", 1)

    news_top = top_news[0]['title'] if top_news else "No news available"
    news_finance = finance_news[0]['title'] if finance_news else "No finance news"
    news_tech = tech_news[0]['title'] if tech_news else "No tech news"
    news_world = world_news[0]['title'] if world_news else "No world news"

    ai_prompt = f"""Based on today's market data:
{market_text}
Top news: {news_top}

Give ONE key insight for investors today in 2-3 sentences. Be direct and actionable."""

    try:
        ai_response = claude.messages.create(
            model="claude-opus-4-7",
            max_tokens=200,
            messages=[{"role": "user", "content": ai_prompt}]
        )
        ai_insight = ai_response.content[0].text
    except Exception:
        ai_insight = "AI insight unavailable right now."

    brief = (
        f"🌅 *Good Morning! Market Brief — {datetime.now(BANGKOK).strftime('%d %b %Y')}*\n\n"
        f"📈 *MARKET OVERVIEW:*\n{market_text}\n"
        f"📰 *TOP STORY:*\n{news_top}\n\n"
        f"💹 *FINANCE:* {news_finance}\n\n"
        f"💻 *TECH:* {news_tech}\n\n"
        f"🌍 *WORLD:* {news_world}\n\n"
        f"🤖 *AI INSIGHT:*\n{ai_insight}"
    )

    for uid, udata in user_data.items():
        try:
            await app.bot.send_message(
                chat_id=udata['chat_id'],
                text=brief,
                parse_mode="Markdown"
            )
        except Exception:
            pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_user(update.effective_user.id)
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"📈 *Welcome {name} to Investment Advisor Bot!*\n\n"
        f"🤖 Powered by Claude AI + Real-time market data\n\n"
        f"*Commands:*\n"
        f"• /analyze AAPL — deep stock analysis\n"
        f"• /crypto BTC — crypto analysis\n"
        f"• /price NVDA — quick price check\n"
        f"• /watchlist — manage your assets\n"
        f"• /brief — get market brief now\n\n"
        f"📬 Daily brief sent at *9:00 AM Bangkok time*\n\n"
        f"Let's make smart investments! 💰🚀",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /analyze AAPL")
        return
    symbol = context.args[0].upper()
    await update.message.reply_text(f"🔍 Analyzing {symbol}... please wait ⏳")
    result = await analyze_asset(symbol, "stock")
    await update.message.reply_text(result, parse_mode="Markdown")

async def cmd_crypto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /crypto BTC")
        return
    symbol = context.args[0].upper()
    await update.message.reply_text(f"🔍 Analyzing {symbol}... please wait ⏳")
    result = await analyze_asset(symbol, "crypto")
    await update.message.reply_text(result, parse_mode="Markdown")

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /price AAPL")
        return
    symbol = context.args[0].upper()
    data = get_stock_price(symbol)
    if not data:
        data = get_crypto_price(symbol)
    if not data:
        await update.message.reply_text(f"❌ Could not find price for {symbol}")
        return
    arrow = "🟢" if data['change_pct'] > 0 else "🔴"
    await update.message.reply_text(
        f"{arrow} *{symbol}*\n"
        f"💰 ${data['price']:.2f}\n"
        f"📊 {data['change_pct']:+.2f}% today\n"
        f"📈 H: ${data['high']:.2f} | L: ${data['low']:.2f}",
        parse_mode="Markdown"
    )

async def cmd_brief(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Generating your market brief... ⏳")
    await send_morning_brief(context.application)

async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u['watchlist']:
        await update.message.reply_text(
            "⭐ Your watchlist is empty!\n\nUse /add AAPL to add assets.",
            reply_markup=main_menu()
        )
        return
    text = "⭐ *Your Watchlist:*\n\n"
    for asset in u['watchlist']:
        data = get_stock_price(asset) or get_crypto_price(asset)
        if data:
            arrow = "🟢" if data['change_pct'] > 0 else "🔴"
            text += f"{arrow} {asset}: ${data['price']:.2f} ({data['change_pct']:+.2f}%)\n"
        else:
            text += f"• {asset}: N/A\n"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /add AAPL")
        return
    u = get_user(update.effective_user.id)
    symbol = context.args[0].upper()
    if symbol not in u['watchlist']:
        u['watchlist'].append(symbol)
        await update.message.reply_text(f"✅ Added {symbol} to your watchlist!", reply_markup=main_menu())
    else:
        await update.message.reply_text(f"⚠️ {symbol} is already in your watchlist!")

async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /remove AAPL")
        return
    u = get_user(update.effective_user.id)
    symbol = context.args[0].upper()
    if symbol in u['watchlist']:
        u['watchlist'].remove(symbol)
        await update.message.reply_text(f"❌ Removed {symbol} from watchlist!", reply_markup=main_menu())
    else:
        await update.message.reply_text(f"⚠️ {symbol} not found in watchlist!")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    get_user(update.effective_user.id)

    if msg == "📊 Market Overview":
        await cmd_brief(update, context)
    elif msg == "⭐ My Watchlist":
        await cmd_watchlist(update, context)
    elif msg == "📰 Top News":
        news = get_top_news() + get_news("finance market", 2)
        if news:
            text_out = "📰 *Latest News:*\n\n"
            for a in news[:3]:
                text_out += f"• {a['title']}\n\n"
            await update.message.reply_text(text_out, parse_mode="Markdown", reply_markup=main_menu())
        else:
            await update.message.reply_text("❌ Could not fetch news right now.", reply_markup=main_menu())
    elif msg == "💡 AI Insight":
        await update.message.reply_text("🤖 Generating AI market insight... ⏳")
        try:
            response = claude.messages.create(
                model="claude-opus-4-7",
                max_tokens=300,
                messages=[{"role": "user", "content": "Give me one actionable investment insight for today's market in 3-4 sentences. Focus on a specific opportunity or risk."}]
            )
            insight = response.content[0].text
        except Exception:
            insight = "AI insight unavailable right now. Please try again later."
        await update.message.reply_text(f"💡 *AI Insight:*\n\n{insight}", parse_mode="Markdown", reply_markup=main_menu())
    elif msg == "➕ Add Asset":
        await update.message.reply_text("Type: /add SYMBOL\nExample: /add AAPL or /add BTC")
    elif msg == "❌ Remove Asset":
        await update.message.reply_text("Type: /remove SYMBOL\nExample: /remove AAPL")
    else:
        await update.message.reply_text(
            "Use the menu buttons or commands:\n/analyze AAPL\n/crypto BTC\n/price NVDA",
            reply_markup=main_menu()
        )

async def post_init(application):
    scheduler = AsyncIOScheduler(timezone=BANGKOK)
    scheduler.add_job(
        send_morning_brief,
        CronTrigger(hour=9, minute=0, timezone=BANGKOK),
        args=[application]
    )
    scheduler.start()

if __name__ == "__main__":
    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("crypto", cmd_crypto))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("brief", cmd_brief))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()
