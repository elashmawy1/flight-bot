import os
import re
import json
import requests
from flask import Flask, request, jsonify
from serpapi import GoogleSearch

app = Flask(__name__)

# ─── Environment Variables ─────────────────────────────────────────────────────

MESSENGER_TOKEN = os.environ.get("MESSENGER_TOKEN", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "flight_bot_secret")
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")

# ─── Home Route ────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return "Flight Bot is running ✅"

# ─── Messenger Webhook Verification ───────────────────────────────────────────

@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge", ""), 200
    return "Forbidden", 403

# ─── Receive Messages ─────────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)

    if data and data.get("object") == "page":
        for entry in data.get("entry", []):
            for event in entry.get("messaging", []):

                if "message" in event and not event["message"].get("is_echo"):

                    sender_id = event["sender"]["id"]
                    text = event["message"].get("text", "").strip()

                    if text:
                        handle_message(sender_id, text)

    return jsonify({"status": "ok"}), 200

# ─── Main Logic ───────────────────────────────────────────────────────────────

def handle_message(sender_id: str, text: str):

    send_message(sender_id, "🔍 بدور على رحلات ليك، انتظر ثانية...")

    flight_info = extract_flight_info(text)

    if not flight_info:
        send_message(
            sender_id,
            "معلش مش قادر أفهم التفاصيل 😅\n\n"
            "جرب تبعتلي كده:\n"
            "عايز أسافر من القاهرة CAI لـ دبي DXB يوم 2026-06-10 وأرجع 2026-06-17"
        )
        return

    result = search_flights(flight_info)

    send_message(sender_id, result)

# ─── AI: Extract Flight Info ──────────────────────────────────────────────────

def extract_flight_info(text: str):

    user_prompt = f"""
Extract flight details from this message and return ONLY JSON.

Fields:
- departure_id
- arrival_id
- outbound_date
- return_date
- type

Message: {text}
"""

    payload = {
        "messages": [
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        "temperature": 0.1,
        "max_tokens": 256
    }

    headers = {
        "Content-Type": "application/json",
        "x-rapidapi-host": "chatgpt-42.p.rapidapi.com",
        "x-rapidapi-key": RAPIDAPI_KEY,
    }

    try:

        response = requests.post(
            "https://chatgpt-42.p.rapidapi.com/conversationgpt4-2",
            json=payload,
            headers=headers,
            timeout=15
        )

        response.raise_for_status()

        ai_text = response.json().get("result", "")

        match = re.search(r"\{.*\}", ai_text, re.DOTALL)

        if match:
            return json.loads(match.group())

    except Exception as e:
        print(f"[AI Error] {e}")

    return None

# ─── Search Flights ───────────────────────────────────────────────────────────

def search_flights(info: dict):

    params = {
        "engine": "google_flights",
        "departure_id": info.get("departure_id", ""),
        "arrival_id": info.get("arrival_id", ""),
        "outbound_date": info.get("outbound_date", ""),
        "currency": "USD",
        "type": info.get("type", "2"),
        "api_key": SERPAPI_KEY,
        "hl": "en",
    }

    if info.get("return_date"):
        params["return_date"] = info["return_date"]

    try:

        results = GoogleSearch(params).get_dict()

    except Exception as e:
        print(f"[SerpAPI Error] {e}")
        return "❌ حصل خطأ أثناء البحث عن الرحلات."

    best_flights = results.get("best_flights", [])
    other_flights = results.get("other_flights", [])

    flights = (best_flights + other_flights)[:5]

    if not flights:
        return (
            f"😕 مش لاقي رحلات من "
            f"{params['departure_id']} "
            f"لـ {params['arrival_id']}"
        )

    trip_type = "ذهاب وإياب" if params["type"] == "2" else "ذهاب فقط"

    lines = [
        f"✈️ رحلات من {params['departure_id']} → {params['arrival_id']}",
        f"📅 {params['outbound_date']}",
        f"🔄 {trip_type}",
        ""
    ]

    for i, flight in enumerate(flights, 1):

        price = flight.get("price", "?")
        duration = flight.get("total_duration", "?")

        legs = flight.get("flights", [])

        airline = "—"
        stops = 0

        if legs:
            airline = legs[0].get("airline", "—")
            stops = len(legs) - 1

        stop_text = "مباشر" if stops == 0 else f"{stops} توقف"

        lines.append(
            f"{i}. {airline} | 💰 ${price} | ⏱ {duration} دقيقة | {stop_text}"
        )

    lines.append("\n💡 الأسعار من Google Flights")

    return "\n".join(lines)

# ─── Send Messenger Message ───────────────────────────────────────────────────

def send_message(recipient_id: str, text: str):

    chunks = [text[i:i+2000] for i in range(0, len(text), 2000)]

    for chunk in chunks:

        try:

            requests.post(
                "https://graph.facebook.com/v19.0/me/messages",
                params={
                    "access_token": MESSENGER_TOKEN
                },
                json={
                    "recipient": {
                        "id": recipient_id
                    },
                    "message": {
                        "text": chunk
                    }
                },
                timeout=10
            )

        except Exception as e:
            print(f"[Messenger Error] {e}")

# ─── Run App ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port
    )
