import os
import discord
import stripe
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import asyncio
import threading

load_dotenv()

app = Flask(__name__)

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
STRIPE_WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]
GUILD_ID = 1511049493133529138
ROLE_ID = 1511058215817711748

intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)

loop = asyncio.new_event_loop()

async def attribuer_role(discord_user_id):
    await client.wait_until_ready()
    guild = client.get_guild(GUILD_ID)
    member = await guild.fetch_member(int(discord_user_id))
    role = guild.get_role(ROLE_ID)
    await member.add_roles(role)

@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        return jsonify(error=str(e)), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        fields = session.get("custom_fields", [])
        discord_id = None
        for field in fields:
            if field.get("key") == "iddiscord":
                discord_id = field.get("text", {}).get("value")
        if discord_id:
            asyncio.run_coroutine_threadsafe(
                attribuer_role(discord_id), loop
            )

    return jsonify(success=True), 200

def run_bot():
    loop.run_until_complete(client.start(DISCORD_TOKEN))

threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
