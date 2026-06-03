import asyncio
import logging
import os
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks
import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "30"))
VINTED_BASE = "https://www.vinted.fr"

CATALOG_MEN    = [4]
CATALOG_WOMEN  = [1]
CATALOG_OTHERS = [306, 1906]

PREMIUM_BRANDS = [
    "nike", "air jordan", "jordan", "adidas", "yeezy", "puma", "new balance",
    "under armour", "north face", "canada goose", "moncler", "stone island",
    "ralph lauren", "lacoste", "tommy hilfiger", "hugo boss", "calvin klein",
    "gucci", "louis vuitton", "prada", "balenciaga", "off-white", "supreme",
    "palace", "burberry", "versace", "dior", "givenchy", "fendi", "kenzo",
    "armani", "moschino", "valentino", "dsquared", "philipp plein",
]

CHANNELS = [
    {
        "id": 1511054495545557122,
        "name": "#moins-de-10€",
        "params": {"price_to": 9.99, "order": "newest_first", "per_page": 48},
        "filter": lambda item: float(item.get("price", 999)) < 10,
    },
    {
        "id": 1511054553083154724,
        "name": "#10€-20€",
        "params": {"price_from": 10, "price_to": 20, "order": "newest_first", "per_page": 48},
        "filter": lambda item: 10 <= float(item.get("price", 0)) <= 20,
    },
    {
        "id": 1511054666593472533,
        "name": "#homme-garcon",
        "params": {"catalog_ids": CATALOG_MEN, "order": "newest_first", "per_page": 48},
        "filter": lambda item: True,
    },
    {
        "id": 1511758434146713892,
        "name": "#femme-fille",
        "params": {"catalog_ids": CATALOG_WOMEN, "order": "newest_first", "per_page": 48},
        "filter": lambda item: True,
    },
    {
        "id": 1511758632243691820,
        "name": "#autres",
        "params": {"catalog_ids": CATALOG_OTHERS, "order": "newest_first", "per_page": 48},
        "filter": lambda item: True,
    },
    {
        "id": 1511758714405781744,
        "name": "#marques-premium",
        "params": {"order": "newest_first", "per_page": 96},
        "filter": lambda item: any(
            brand in (item.get("title", "") + " " + item.get("brand_title", "")).lower()
            for brand in PREMIUM_BRANDS
        ),
    },
]

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

posted: dict[str, set[int]] = {}


class VintedView(discord.ui.View):
    def __init__(self, item_url: str, buy_url: str):
        super().__init__()
        self.add_item(discord.ui.Button(
            label="👁 Voir l'annonce",
            style=discord.ButtonStyle.link,
            url=item_url,
        ))
        self.add_item(discord.ui.Button(
            label="🛒 Acheter",
            style=discord.ButtonStyle.link,
            url=buy_url,
        ))
        self.add_item(discord.ui.Button(
            label="💬 Faire une offre",
            style=discord.ButtonStyle.link,
            url=item_url + "?make_offer=1",
        ))
        self.add_item(discord.ui.Button(
            label="❤️ Favoris",
            style=discord.ButtonStyle.link,
            url=item_url + "?add_to_favourites=1",
        ))


def build_embed(item: dict) -> discord.Embed:
    price = item.get("price", "?")
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


async def get_vinted_token(client: httpx.AsyncClient) -> None:
    try:
        await client.get(
            f"{VINTED_BASE}/auth/token_refresh",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
    except Exception as e:
        log.warning("Token refresh failed: %s", e)


async def search_vinted(client: httpx.AsyncClient, params: dict) -> list[dict]:
    query: dict = {"order": "newest_first", "per_page": 48, "page": 1}
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
            await get_vinted_token(client)
            resp = await client.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception as e:
        log.error("Vinted search error: %s", e)
        return []


async def scan_and_post():
    async with httpx.AsyncClient(follow_redirects=True) as client:
        await get_vinted_token(client)

        for ch_cfg in CHANNELS:
            channel_id = ch_cfg["id"]
            params = dict(ch_cfg["params"])
            filter_fn = ch_cfg["filter"]

            items = await search_vinted(client, params)
            channel = bot.get_channel(channel_id)
            if channel is None:
                log.warning("Channel %d not found", channel_id)
                continue

            new_count = 0
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

                item_url = item.get("url", f"{VINTED_BASE}/items/{item_id}")
                buy_url = f"{VINTED_BASE}/items/{item_id}/buy"
                embed = build_embed(item)
                view = VintedView(item_url=item_url, buy_url=buy_url)

                try:
                    await channel.send(embed=embed, view=view)
                    posted.setdefault(item_id, set()).add(channel_id)
                    new_count += 1
                    await asyncio.sleep(0.5)
                except discord.HTTPException as e:
                    log.error("Failed to post item %s to %s: %s", item_id, ch_cfg["name"], e)

            if new_count:
                log.info("Posted %d new items to %s", new_count, ch_cfg["name"])

    if len(posted) > 5000:
        overflow = list(posted.keys())[: len(posted) - 5000]
        for k in overflow:
            del posted[k]


@bot.event
async def on_ready():
    log.info("Vinted bot ready as %s", bot.user)
    scanner.start()


@tasks.loop(seconds=SCAN_INTERVAL)
async def scanner():
    log.info("Scanning Vinted...")
    await scan_and_post()


@scanner.before_loop
async def before_scanner():
    await bot.wait_until_ready()


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
