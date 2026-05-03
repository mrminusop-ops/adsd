# database.py - MongoDB database handlers
from motor.motor_asyncio import AsyncIOMotorClient
import os
from datetime import datetime, timedelta

# MongoDB connection
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "shopify_checker")

client = AsyncIOMotorClient(MONGODB_URL)
db = client[DB_NAME]

# Collections
users_col = db.users
keys_col = db.keys
proxies_col = db.proxies
sites_col = db.sites
cards_col = db.cards
global_sites_col = db.global_sites

async def init_db():
    """Initialize database indexes"""
    await users_col.create_index("user_id", unique=True)
    await keys_col.create_index("key", unique=True)
    await proxies_col.create_index([("user_id", 1), ("ip", 1), ("port", 1)], unique=True)
    await sites_col.create_index([("user_id", 1), ("site", 1)], unique=True)
    await cards_col.create_index("card", unique=True)
    print("✅ Database indexes created")

async def ensure_user(user_id):
    """Ensure user exists in database"""
    existing = await users_col.find_one({"user_id": user_id})
    if not existing:
        await users_col.insert_one({
            "user_id": user_id,
            "plan": "free",
            "plan_expiry": datetime.utcnow() + timedelta(days=365),
            "banned": False,
            "banned_by": None,
            "banned_at": None,
            "created_at": datetime.utcnow()
        })
    return True

async def get_user_plan(user_id):
    """Get user's plan"""
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        return "free"
    if user.get("plan_expiry") and user["plan_expiry"] < datetime.utcnow():
        if user["plan"] != "free":
            await users_col.update_one(
                {"user_id": user_id},
                {"$set": {"plan": "free", "plan_expiry": datetime.utcnow() + timedelta(days=365)}}
            )
        return "free"
    return user.get("plan", "free")

async def set_user_plan(user_id, plan_type, days):
    """Set user's plan"""
    expiry = datetime.utcnow() + timedelta(days=days)
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"plan": plan_type, "plan_expiry": expiry}}
    )
    return True

async def is_premium_user(user_id):
    """Check if user has premium plan"""
    plan = await get_user_plan(user_id)
    return plan in ["pro", "toji"]

async def is_banned_user(user_id):
    """Check if user is banned"""
    user = await users_col.find_one({"user_id": user_id})
    return user.get("banned", False) if user else False

async def ban_user(user_id, admin_id):
    """Ban a user"""
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"banned": True, "banned_by": admin_id, "banned_at": datetime.utcnow()}}
    )
    return True

async def unban_user(user_id):
    """Unban a user"""
    result = await users_col.update_one(
        {"user_id": user_id, "banned": True},
        {"$set": {"banned": False}}
    )
    return result.modified_count > 0

async def add_proxy_db(user_id, proxy_data):
    """Add proxy to user's list"""
    try:
        await proxies_col.insert_one({
            "user_id": user_id,
            **proxy_data,
            "created_at": datetime.utcnow()
        })
        return True
    except:
        return False

async def get_all_user_proxies(user_id):
    """Get all proxies for a user"""
    cursor = proxies_col.find({"user_id": user_id})
    return await cursor.to_list(length=None)

async def get_proxy_count(user_id):
    """Get count of user's proxies"""
    return await proxies_col.count_documents({"user_id": user_id})

async def get_random_proxy(user_id):
    """Get a random proxy for user"""
    proxies = await get_all_user_proxies(user_id)
    if not proxies:
        return None
    return random.choice(proxies)

async def remove_proxy_by_index(user_id, index):
    """Remove proxy by index"""
    proxies = await get_all_user_proxies(user_id)
    if 0 <= index < len(proxies):
        await proxies_col.delete_one({"_id": proxies[index]["_id"]})
        return proxies[index]
    return None

async def remove_proxy_by_url(user_id, proxy_url):
    """Remove proxy by URL"""
    result = await proxies_col.delete_one({"user_id": user_id, "proxy_url": proxy_url})
    return result.deleted_count > 0

async def clear_all_proxies(user_id):
    """Remove all proxies for user"""
    result = await proxies_col.delete_many({"user_id": user_id})
    return result.deleted_count

async def add_site_db(user_id, site):
    """Add site to user's list"""
    try:
        await sites_col.insert_one({
            "user_id": user_id,
            "site": site,
            "created_at": datetime.utcnow()
        })
        return True
    except:
        return False

async def get_user_sites(user_id):
    """Get all sites for a user"""
    cursor = sites_col.find({"user_id": user_id})
    sites = await cursor.to_list(length=None)
    return [s["site"] for s in sites]

async def remove_site_db(user_id, site):
    """Remove site from user's list"""
    result = await sites_col.delete_one({"user_id": user_id, "site": site})
    return result.deleted_count > 0

async def add_global_site(site):
    """Add global site"""
    try:
        await global_sites_col.insert_one({"site": site, "created_at": datetime.utcnow()})
        return True
    except:
        return False

async def get_global_sites():
    """Get all global sites"""
    cursor = global_sites_col.find({})
    sites = await cursor.to_list(length=None)
    return [s["site"] for s in sites]

async def remove_global_site(site):
    """Remove global site"""
    result = await global_sites_col.delete_one({"site": site})
    return result.deleted_count > 0

async def save_card_to_db(card_data):
    """Save card result to database"""
    try:
        await cards_col.insert_one({
            **card_data,
            "checked_at": datetime.utcnow()
        })
        return True
    except:
        return False

async def get_total_cards_count():
    """Get total cards checked"""
    return await cards_col.count_documents({})

async def get_charged_count():
    """Get count of charged cards"""
    return await cards_col.count_documents({"status": "Charged"})

async def get_approved_count():
    """Get count of approved cards"""
    return await cards_col.count_documents({"status": "Approved"})

async def get_all_premium_users():
    """Get all premium users"""
    cursor = users_col.find({"plan": {"$ne": "free"}})
    return await cursor.to_list(length=None)

async def get_total_users():
    """Get total number of users"""
    return await users_col.count_documents({})

async def get_premium_count():
    """Get number of premium users"""
    return await users_col.count_documents({"plan": {"$ne": "free"}})

async def get_total_sites_count():
    """Get total number of sites across all users"""
    return await sites_col.count_documents({})

async def get_users_with_sites():
    """Get users who have sites"""
    pipeline = [
        {"$group": {"_id": "$user_id"}},
        {"$count": "count"}
    ]
    result = await sites_col.aggregate(pipeline).to_list(length=1)
    return result[0]["count"] if result else 0

async def get_sites_per_user():
    """Get average sites per user"""
    pipeline = [
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
        {"$group": {"_id": None, "avg": {"$avg": "$count"}}}
    ]
    result = await sites_col.aggregate(pipeline).to_list(length=1)
    return round(result[0]["avg"], 2) if result else 0

async def get_all_sites_detail():
    """Get detailed site statistics"""
    pipeline = [
        {"$group": {"_id": "$site", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20}
    ]
    return await sites_col.aggregate(pipeline).to_list(length=20)

async def create_key(key, plan_type, days):
    """Create a new key (alias for create_plan_key)"""
    return await create_plan_key(key, plan_type, days)

async def get_key_data(key):
    """Get key data"""
    return await keys_col.find_one({"key": key})

async def use_key(user_id, key):
    """Use a key (alias for use_plan_key)"""
    return await use_plan_key(user_id, key)

async def get_all_keys():
    """Get all keys (alias for get_all_plan_keys)"""
    return await get_all_plan_keys()
