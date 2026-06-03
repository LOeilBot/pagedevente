import asyncio
import hashlib
import hmac
import logging
import os

import discord
from discord.ext import commands
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
DISCORD_GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])
DISCORD_ROLE_ID = int(os.environ["DISCORD_ROLE_ID"])
WHOP_WEBHOOK_SECRET = os.environ["WHOP_WEBHOOK_SECRET"]
PORT = int(os.getenv("PORT", "8000"))

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

app = FastAPI()


def verify_whop_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def grant_role(discord_user_id: int) -> str:
    guild = bot.get_guild(DISCORD_GUILD_ID)
    if guild is None:
        return "guild_not_found"
    role = guild.get_role(DISCORD_ROLE_ID)
    if role is None:
        return "role_not_found"
    member = guild.get_member(discord_user_id)
    if member is None:
        try:
            member = await guild.fetch_member(discord_user_id)
        except discord.NotFound:
            return "member_not_found"
    if role in member.roles:
        return "already_has_role"
    await member.add_roles(role, reason="Whop payment validated")
    log.info("Role granted to %s (%d)", member, discord_user_id)
    return "role_granted"


async def revoke_role(discord_user_id: int) -> str:
    guild = bot.get_guild(DISCORD_GUILD_ID)
    if guild is None:
        return "guild_not_found"
    role = guild.get_role(DISCORD_ROLE_ID)
    if role is None:
        return "role_not_found"
    member = guild.get_member(discord_user_id)
    if member is None:
        try:
            member = await guild.fetch_member(discord_user_id)
        except discord.NotFound:
            return "member_not_found"
    if role not in member.roles:
        return "did_not_have_role"
    await member.remove_roles(role, reason="Whop membership expired/cancelled")
    log.info("Role revoked from %s (%d)", member, discord_user_id)
    return "role_revoked"


@app.post("/webhook/whop")
async def whop_webhook(
    request: Request,
    x_whop_signature: str = Header(None, alias="x-whop-signature-256"),
):
    payload = await request.body()
    if x_whop_signature is None:
        raise HTTPException(status_code=400, detail="Missing signature header")
    sig = x_whop_signature.removeprefix("sha256=")
    if not verify_whop_signature(payload, sig, WHOP_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid signature")
    data = await request.json()
    event_type: str = data.get("event", "")
    membership: dict = data.get("data", {})
    log.info("Whop event received: %s", event_type)
    discord_id_raw = (
        membership.get("discord_id")
        or (membership.get("metadata") or {}).get("discord_id")
        or (membership.get("user") or {}).get("discord_id")
    )
    if not discord_id_raw:
        log.warning("No discord_id in payload for event %s", event_type)
        return JSONResponse({"status": "no_discord_id"})
    discord_user_id = int(discord_id_raw)
    if event_type == "membership.went_valid":
        status = await grant_role(discord_user_id)
    elif event_type in ("membership.went_invalid", "membership.deleted"):
        status = await revoke_role(discord_user_id)
    else:
        status = "event_ignored"
    return JSONResponse({"status": status})


@app.get("/health")
async def health():
    return {"status": "ok", "bot_ready": bot.is_ready()}


@bot.event
async def on_ready():
    log.info("Bot ready as %s (guild id: %d)", bot.user, DISCORD_GUILD_ID)


async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await asyncio.gather(
        bot.start(DISCORD_TOKEN),
        server.serve(),
    )


if __name__ == "__main__":
    asyncio.run(main())
