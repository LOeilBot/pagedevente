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

HOMME_CATALOG_ID = 5

GOOD_CONDITIONS = {"new_with_tags", "new_without_tags", "very_good", "good"}

PREMIUM_BRANDS = [
    "nike", "air jordan", "jordan", "adidas", "yeezy", "puma", "new balance",
    "under armour", "north face", "canada goose", "moncler", "stone island",
    "ralph lauren", "lacoste", "tommy hilfiger", "hugo boss", "calvin klein",
    "gucci", "louis vuitton", "prada", "balenciaga", "off-white", "supreme",
    "palace", "burberry", "versace", "dior", "givenchy", "fendi", "kenzo",
    "armani", "moschino", "valentino", "dsquared", "philipp plein", "carhartt",
    "stussy", "bape", "represent", "ami", "acne studios", "levi", "levis",
    "champion", "polo", "fred perry", "timberland", "vans", "converse", "reebok",
    "asics", "salomon", "columbia", "patagonia",
]

BLACKLIST = [
    # Femme FR
    "femme", "fille", "madame", "dame", "vetements-femmes", "mixte",
    "robe", "jupe", "jupette",
    "soutien-gorge", "soutien gorge", "brassiere", "lingerie",
    "bustier", "corset", "crop top", "croptop", "crop-top", "caraco", "tunique",
    "maternite", "maternité", "grossesse",
    "bikini", "tankini", "monokini",
    "escarpins", "stiletto", "ballerine",
    # Femme EN
    "women", "woman", "girl", "girls", "ladies", "lady",
    "women's", "womens", "dress", "skirt", "bra ", " bra", "maternity", "heels",
    # Femme DE
    "damen", "frau", "frauen", "kleid", "kleider",
    # Femme IT
    "donna", "donne", "ragazza", "vestito", "gonna", "reggiseno",
    # Femme ES/PT
    "mujer", "mujeres", "chica", "vestido", "falda", "mulher", "saia",
    # Sous-vêtements (FR+EN+IT+DE+ES)
    "calecon", "caleçon", "culotte", "string", "shorty", "slip", "brief", "briefs",
    "boxer", "boxers", "underwear", "mutande", "mutandine", "calzoncillo", "unterhose",
    # Chaussettes
    "chaussette", "chaussettes", "socken", "socks",
    # Ceintures
    "ceinture", "belt", "cinturon", "cintura",
    # Montres
    "montre", "watch", "orologio", "uhr", "reloj",
    # Cravates (FR + IT + ES + DE)
    "cravate", "cravatta", "corbata", "krawatte", "tie ", " tie",
    # Lunettes
    "lunette", "lunettes", "glasses", "sunglasses", "occhiali", "brille", "gafas",
    # Bijoux (FR + ES + IT + DE + EN)
    "bijou", "bijoux", "collier", "bracelet", "bague", "boucle d'oreille",
    "jewelry", "necklace", "earring", "ring ", " ring",
    "collar ", " collar", "collana", "colares", "colgante",
    "armband", "silberarmband", "goldarmband", "kette ", " kette", "anhänger",
    "strass", "pendentif", "charm ", " charm",
    # Chapeaux (FR + IT + ES + DE)
    "chapeau", "casquette", "bonnet", "hat ", " hat",
    "cappellino", "cappello", "gorra", "mütze",
    # Sacs (FR + IT + DE)
    "sac ", " sac", "bag ", " bag", "backpack", "pochette",
    "portefeuille", "wallet", "marsupio", "tasche",
    # Parfums / hygiène (FR + IT + ES + DE + EN)
    "parfum", "perfume", "cologne", "fragrance", "eau de toilette", "eau de parfum",
    "edp", "edt", "deodorant", "déodorant", "aftershave", "after-shave",
    "profumo",
    "gel douche", "gel de ducha", "dusche", "duschgel", "shampoo", "shampooing",
    "savon", "soap", "shower", "lotion", "crème", "creme", "soin ",
    # Rasoirs / lames
    "rasoir", "razor", "gillette", "lame ", " lame", "recambio", "recambios",
    # Divers
    "peluche", "jouet", "toy",
]

# Chaussures : bloquées dans #alertes et #bonnes-affaires, autorisées dans #marques-premium
SHOES = [
    "chaussure", "chaussures", "shoe", "shoes",
    "basket", "baskets", "sneaker", "sneakers",
    "crampon", "crampons", "botte", "bottes", "boot", "boots",
    "mocassin", "mocassins", "espadrille", "espadrilles",
    "sandale", "sandales", "sandal", "sandals",
    "tong", "tongs", "infradito", "claquette", "claquettes",
    "scarpa", "scarpe", "schuh", "schuhe", "zapato", "zapatos",
    "loafer", "derby", "oxford",
]

CHANNEL_IDS = [1512096461930627142, 1512096568818270299, 1512096652570267658]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": f"{VINTED_BASE}/",
}


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


def not_femme(item: dict) -> bool:
    text = (
        item.get("title", "") + " " +
        item.get("description", "") + " " +
        item.get("url", "") + " " +
        item.get("brand_title", "") + " " +
        item.get("category_title", "")
    ).lower()
    return not any(w in text for w in BLACKLIST)


def not_shoe(item: dict) -> bool:
    text = (
        item.get("title", "") + " " +
        item.get("url", "") + " " +
        item.get("category_title", "")
    ).lower()
    return not any(w in text for w in SHOES)


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
queues: dict[int, asyncio.Queue] = {cid: asyncio.Queue() for cid in CHANNEL_IDS}
posted: dict[str, set[int]] = {}


class VintedView(discord.ui.View):
    def __init__(self, item_url: str, buy_url: str):
        super().__init__()
        self.add_item(discord.ui.Button(label="👁 Voir l'annonce", style=discord.ButtonStyle.link, url=item_url))


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

    condition_map = {
        "new_with_tags":    "✨ Neuf avec étiquettes",
        "new_without_tags": "✨ Neuf sans étiquettes",
        "very_good":        "👍 Très bon état",
        "good":             "👌 Bon état",
        "satisfactory":     "🔸 État satisfaisant",
    }
    condition_label = condition_map.get(condition, condition)

    raw = get_price(item)
    if is_premium_brand(item):
        multiplier = random.uniform(1.7, 2.2)
    else:
        multiplier = random.uniform(1.4, 1.7)
    resale = round(raw * multiplier - 0.01, 2)
    profit = round(resale - raw, 2)
    margin_pct = round(profit / raw * 100) if raw > 0 else 0
    resale_str = f"{resale:.2f} {currency}"
    profit_str = f"+{profit:.2f} {currency}"

    desc = f"📊  Marge estimée : **+{margin_pct}%**"
    embed = discord.Embed(title=f"**{title}**", description=desc, color=0x00D4FF)

    embed.add_field(name="💰  Prix d'achat",      value=f"```{price} {currency}```", inline=True)
    embed.add_field(name="📈  Revente conseillée", value=f"```{resale_str}```",       inline=True)
    embed.add_field(name="💵  Profit estimé",      value=f"```{profit_str}```",       inline=True)

    embed.add_field(name="📐  Taille", value=size if size else "—",                      inline=True)
    embed.add_field(name="🏷️  Marque", value=f"**{brand}**" if brand else "—",          inline=True)
    embed.add_field(name="✨  État",   value=condition_label if condition_label else "—", inline=True)

    if photo_url:
        embed.set_image(url=photo_url)
    embed.set_footer(
        text=f"Vinted  ·  {brand}" if brand else "Vinted",
        icon_url="https://cdn.discordapp.com/attachments/1511054295452225626/1512185116439347261/FRIPEX_4.png"
    )
    embed.timestamp = datetime.now(timezone.utc)
    return embed


async def get_vinted_session(client: httpx.AsyncClient) -> None:
    try:
        await client.get(f"{VINTED_BASE}/", headers=HEADERS)
    except Exception as e:
        log.warning("Session init failed: %s", e)


async def fetch_items(client: httpx.AsyncClient, extra_params: str = "") -> list[dict]:
    url = f"{VINTED_BASE}/api/v2/catalog/items?order=newest_first&page=1&per_page=96&catalog_ids[]={HOMME_CATALOG_ID}{extra_params}"
    try:
        resp = await client.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 401:
            await get_vinted_session(client)
            resp = await client.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        log.info("Fetched %d items", len(items))
        return items
    except Exception as e:
        log.error("Fetch error: %s", e)
        return []


async def fetch_all_channels(client: httpx.AsyncClient) -> None:
    await get_vinted_session(client)
    fetches = [
        {
            "channel_id": 1512096461930627142,
            "name": "#alertes-vinted",
            "extra": "&price_to=50",
            "filter": lambda item: not_femme(item) and not_shoe(item) and get_price(item) <= 50,
        },
        {
            "channel_id": 1512096568818270299,
            "name": "#bonnes-affaires",
            "extra": "&price_to=30",
            "filter": lambda item: not_femme(item) and not_shoe(item) and get_price(item) <= 30,
        },
        {
            "channel_id": 1512096652570267658,
            "name": "#marques-premium",
            "extra": "&price_to=50",
            "filter": lambda item: not_femme(item) and get_price(item) <= 50 and is_premium_brand(item),
        },
    ]
    for fetch_cfg in fetches:
        try:
            items = await fetch_items(client, fetch_cfg["extra"])
            channel_id = fetch_cfg["channel_id"]
            filter_fn = fetch_cfg["filter"]
            queued = 0
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
                posted.setdefault(item_id, set()).add(channel_id)
                await queues[channel_id].put(item)
                queued += 1
            log.info("  → %s: %d mis en file", fetch_cfg["name"], queued)
        except Exception as e:
            log.error("Fetcher error %s: %s", fetch_cfg["name"], e)
        await asyncio.sleep(random.uniform(8, 15))


async def scanner_loop() -> None:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        while True:
            log.info("=== Scan Vinted ===")
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
        buy_url = item_url + "/buy"
        try:
            await channel.send(embed=build_embed(item), view=VintedView(item_url, buy_url))
            log.info("Posté %s → %d", item_id, channel_id)
        except discord.HTTPException as e:
            log.error("Erreur post: %s", e)
        q.task_done()
        if len(posted) > 10000:
            for k in list(posted.keys())[:len(posted) - 10000]:
                del posted[k]
        await asyncio.sleep(POST_DELAY + random.uniform(0, 1.5))


@bot.event
async def on_ready():
    log.info("Bot prêt : %s", bot.user)
    bot.loop.create_task(scanner_loop())
    for cid in CHANNEL_IDS:
        bot.loop.create_task(poster(cid))


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
