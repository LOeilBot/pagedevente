import asyncio
import logging
import os
import random
from datetime import datetime, timezone

import discord
from discord.ext import commands
import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
VINTED_BASE = "https://www.vinted.fr"

POST_DELAY = 3.0
FETCH_INTERVAL = 180
MAX_WOMEN_RATIO = 0.20

GOOD_CONDITIONS = {"new_with_tags", "new_without_tags", "very_good"}

CATALOG_IDS_WOMEN = {1, 2, 3, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30}

PREMIUM_BRANDS = [
    "nike", "air jordan", "jordan", "adidas", "yeezy", "puma", "new balance",
    "under armour", "north face", "canada goose", "moncler", "stone island",
    "ralph lauren", "lacoste", "tommy hilfiger", "hugo boss", "calvin klein",
    "gucci", "louis vuitton", "prada", "balenciaga", "off-white", "supreme",
    "palace", "burberry", "versace", "dior", "givenchy", "fendi", "kenzo",
    "armani", "moschino", "valentino", "dsquared", "philipp plein", "carhartt",
    "stussy", "bape", "represent", "ami", "acne studios",
]


def get_price(item: dict) -> float:
    p = item.get("price", 0)
    if isinstance(p, dict):
        return float(p.get("amount", 0))
    return float(p or 0)


def is_good_condition(item: dict) -> bool:
    return item.get("status", "") in GOOD_CONDITIONS


def is_premium_brand(item: dict) -> bool:
    text = (item.get("title", "") + " " + item.get("brand_title", "")).lower()
    return any(brand in text for brand in PREMIUM_BRANDS)


def is_women_item(item: dict) -> bool:
    return int(item.get("catalog_id") or item.get("category_id") or 0) in CATALOG_IDS_WOMEN


channel_counts: dict[int, dict] = {
    1511054495545557122: {"homme": 0, "femme": 0},
    1511054666593472533: {"homme": 0, "femme": 0},
    1511758434146713892: {"homme": 0, "femme": 0},
}


def can_post_item(channel_id: int, item: dict) -> bool:
    counts = channel_counts[channel_id]
    if not is_women_item(item):
        return True
    total = counts["homme"] + counts["femme"]
    if total == 0:
        return True
    return (counts["femme"] / total) < MAX_WOMEN_RATIO


def record_post(channel_id: int, item: dict) -> None:
    counts = channel_counts[channel_id]
    if is_women_item(item):
        counts["femme"] += 1
    else:
        counts["homme"] += 1


FETCHES = [
    {
        "channel_id": 1511054495545557122,
        "name": "#alertes-vinted",
        "params": {"catalog_ids": [4], "per_page": 48},
        "filter": lambda item: True,
    },
    {
        "channel_id": 1511054495545557122,
        "name": "#alertes-vinted-femme",
        "params": {"catalog_ids": [1], "per_page": 24},
        "filter": lambda item: True,
    },
    {
        "channel_id": 1511054666593472533,
        "name": "#bonnes-affaires-homme",
        "params": {"catalog_ids": [4], "price_to": 30, "per_page": 48},
        "filter": lambda item: get_price(item) <= 30 and is_good_condition(item),
    },
    {
        "channel_id": 1511054666593472533,
        "name": "#bonnes-affaires-femme",
        "params": {"catalog_ids": [1], "price_to": 30, "per_page": 24},
        "filter": lambda item: get_price(item) <= 30 and is_good_condition(item),
    },
    {
        "channel_id": 1511758434146713892,
        "name": "#marques-premium-homme",
        "params": {"catalog_ids": [4], "price_to": 50, "per_page": 48},
        "filter": lambda item: get_price(item) <= 50 and is_premium_brand(item),
    },
    {
        "channel_id": 1511758434146713892,
        "name": "#marques-premium-femme",
        "params": {"catalog_ids": [1], "price_to": 50, "per_page": 24},
        "filter": lambda item: get_price(item) <= 50 and is_premium_brand(item),
    },
]

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

CHANNEL_IDS = [1511054495545557122, 1511054666593472533, 1511758434146713892]
queues: dict[int, asyncio.Queue] = {cid: asyncio.Queue() for cid in CHANNEL_IDS}
posted: dict[str, set[int]] = {}


class VintedView(discord.ui.View):
    def __init__(self, item_url: str, buy_url: str):
        super().__init__()
        self.add_item(discord.ui.Button(label="👁 Voir l'annonce", style=discord.ButtonStyle.link, url=item_url))
        self.add_item(discord.ui.Button(label="🛒 Acheter", style=discord.ButtonStyle.link, url=buy_url))
        self.add_item(discord.ui.Button(label="💬 Faire une offre", style=discord.ButtonStyle.link, url=item_url + "?make_offer=1"))
        self.add_item(discord.ui.Button(label="❤️ Favoris", style=discord.ButtonStyle.link, url=item_url + "?add_to_favourites=1"))


def build_embed(item: dict) -> discord.Embed:
    raw_price = item.get("price", {})
    if isinstance(raw_price, dict):
        price = raw_price.get("amount", "?")
        currency = raw_price.get("currency_code", "€")
    else:
        price = raw_price
        currency = item.get("currency", "€")

    title = item.get("title", "Sans titre")
    brand = item.get("brand_title", "")
    size = item.get("size_title", "")
    condition = item.get("status", "")
    photos = item.get("photos", [])
    photo_url = photos[0].get("url", "") if photos else ""

    conditions = {
        "new_with_tags": "Neuf avec étiquettes",
        "new_without_tags": "Neuf sans étiquettes",
        "very_good": "Très bon état",
        "good": "Bon état",
        "satisfactory": "État satisfaisant",
    }
    condition_label = conditions.get(condition, condition)

    embed = discord.Embed(title=title, color=0x09B1BA)
    embed.add_field(name="💰 Prix", value=f"**{price} {currency}**", inline=True)
    if brand:
        embed.add_field(name="🏷️ Marque", value=brand, inline=True)
    if size:
        embed.add_field(name="📏 Taille", value=size, inline=True)
    if condition_label:
        embed.add_field(name="✨ État", value=condition_label, inline=True)
    if photo_url:
        embed.set_image(url=photo_url)
    embed.set_footer(text="Vinted • Nouvelle annonce")
    embed.timestamp = datetime.now(timezone.utc)
    return embed


async def get_vinted_session(client: httpx.AsyncClient) -> None:
    try:
        await client.get(f"{VINTED_BASE}/", headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
    except Exception as e:
        log.warning("Session init failed: %s", e)


async def fetch_items(client: httpx.AsyncClient, params: dict) -> list[dict]:
    query: dict = {"order": "newest_first", "page": 1}
    catalog_ids = params.pop("catalog_ids", [])
    query.update(params)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer": f"{VINTED_BASE}/",
    }
    param_str = "&".join(f"{k}={v}" for k, v in query.items())
    if catalog_ids:
        param_str += "&" + "&".join(f"catalog_ids[]={cid}" for cid in catalog_ids)
    url = f"{VINTED_BASE}/api/v2/catalog/items?{param_str}"
    try:
        resp = await client.get(url, headers=headers, timeout=15)
        if resp.status_code == 401:
            await get_vinted_session(client)
            resp = await client.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception as e:
        log.error("Fetch error: %s", e)
        return []


async def fetch_all_channels(client: httpx.AsyncClient) -> None:
    await get_vinted_session(client)
    for fetch_cfg in FETCHES:
        try:
            params = dict(fetch_cfg["params"])
            items = await fetch_items(client, params)
            filter_fn = fetch_cfg["filter"]
            channel_id = fetch_cfg["channel_id"]

            for item in reversed(items):
                item_id = str(item.get("id", ""))
                if not item_id:
                    continue
                if channel_id in posted.get(item_id, set()):
                    continue
                if not filter_fn(item):
                    continue
                if not item.get("photos"):
                    continue
                if not can_post_item(channel_id, item):
                    continue
                record_post(channel_id, item)
                posted.setdefault(item_id, set()).add(channel_id)
                await queues[channel_id].put(item)
        except Exception as e:
            log.error("Fetcher error for %s: %s", fetch_cfg["name"], e)
        await asyncio.sleep(random.uniform(8, 15))


async def scanner_loop() -> None:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        while True:
            try:
                await fetch_all_channels(client)
            except Exception as e:
                log.error("Scanner error: %s", e)
            await asyncio.sleep(FETCH_INTERVAL)


async def poster(channel_id: int) -> None:
    q = queues[channel_id]
    while True:
        item = await q.get()
        channel = bot.get_channel(channel_id)
        if channel is None:
            q.task_done()
            continue
        item_id = str(item.get("id", ""))
        item_url = item.get("url", f"{VINTED_BASE}/items/{item_id}")
        buy_url = f"{VINTED_BASE}/items/{item_id}/buy"
        try:
            await channel.send(embed=build_embed(item), view=VintedView(item_url, buy_url))
        except discord.HTTPException as e:
            log.error("Post failed: %s", e)
        q.task_done()
        if len(posted) > 8000:
            overflow = list(posted.keys())[: len(posted) - 8000]
            for k in overflow:
                del posted[k]
        await asyncio.sleep(POST_DELAY + random.uniform(0, 1.5))


@bot.event
async def on_ready():
    log.info("Vinted bot ready as %s", bot.user)
    bot.loop.create_task(scanner_loop())
    for cid in CHANNEL_IDS:
        bot.loop.create_task(poster(cid))


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
