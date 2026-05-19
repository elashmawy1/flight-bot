import os
import re
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify
from serpapi import GoogleSearch

app = Flask(__name__)

MESSENGER_TOKEN = os.environ.get("MESSENGER_TOKEN", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "flight_bot_secret")
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")

sessions = {}

EGYPT_DESTINATIONS = """
مدن مصر المتاحة:
1. القاهرة
2. الإسكندرية
3. شرم الشيخ
4. الغردقة
5. الأقصر
6. أسوان
7. مرسى علم
"""

@app.route("/")
def home():
    return "Flight Bot is running ✅"

@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge", ""), 200
    return "Forbidden", 403

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

def handle_message(sender_id: str, text: str):
    send_message(sender_id, "تمام ✈️ بثواني أراجع تفاصيل الرحلة")

    old_info = sessions.get(sender_id, {})
    flight_info = extract_flight_info(text, old_info)

    if not flight_info:
        send_message(sender_id, "معلش مش قادر أفهم الرسالة. ممكن توضحلي أكتر؟")
        return

    merged_info = merge_info(old_info, flight_info)
    sessions[sender_id] = merged_info

    missing = get_missing_fields(merged_info)
    departure = merged_info.get("departure_id")

    if "arrival_id" in missing:
        if departure and departure != "CAI":
            send_message(
                sender_id,
                "تمام ✈️\n"
                "تحب توصل لأنهي مدينة في مصر؟\n\n"
                f"{EGYPT_DESTINATIONS}"
            )
        else:
            send_message(sender_id, "تمام ✈️\nتحب تسافر لأي مدينة؟")
        return

    if "outbound_date" in missing:
        send_message(sender_id, "تمام ✈️\nتحب تسافر يوم كام؟")
        return

    result = search_flights(merged_info)
    send_message(sender_id, result)

    sessions.pop(sender_id, None)

def merge_info(old: dict, new: dict):
    merged = old.copy()

    for key in [
        "departure_id",
        "arrival_id",
        "outbound_date",
        "return_date",
        "type"
    ]:
        value = new.get(key)
        if value not in [None, "", "null"]:
            merged[key] = value

    if not merged.get("departure_id"):
        merged["departure_id"] = "CAI"

    if not merged.get("return_date"):
        merged["return_date"] = None

    if merged.get("return_date"):
        merged["type"] = "2"
    else:
        merged["type"] = "1"

    return merged

def get_missing_fields(info: dict):
    missing = []

    if not info.get("arrival_id"):
        missing.append("arrival_id")

    if not info.get("outbound_date"):
        missing.append("outbound_date")

    return missing

def extract_flight_info(text: str, old_info: dict):
    today = datetime.now(ZoneInfo("Africa/Cairo")).strftime("%Y-%m-%d")

    user_prompt = f"""
You are an Arabic travel assistant.

Today's date is: {today}

Previous known flight info:
{json.dumps(old_info, ensure_ascii=False)}

User message:
{text}

Rules:
1. Understand Arabic natural language.
2. Do not ask the user for airport codes.
3. Convert cities to IATA codes.
4. If departure city is missing, assume Cairo = CAI.
5. If user says only "يوم 22":
   - Use current month if day 22 has not passed.
   - If day 22 already passed, use next month.
6. If user says "22 يونيو" without year:
   - Use nearest future date.
7. If user gives return day like "وارجع 5":
   - If return day is after outbound day, same month.
   - If return day is before outbound day, next month.
8. If departure is Milan, Milano, or Italy and arrival is missing:
   - Leave arrival_id as null.
   - The bot will offer Egyptian cities.
9. If user says Egypt, مصر, القاهرة, اسكندرية, شرم الشيخ, الغردقة, الأقصر, أسوان, or مرسى علم as destination:
   - Convert it to the correct IATA code.
10. If user says مصر as destination and no city:
   - Leave arrival_id as null.
11. If return date is missing:
   - return_date = null
   - type = "1"
12. If return date exists:
   - type = "2"
13. Return ONLY valid JSON.

IATA hints:
- Cairo / القاهرة = CAI
- Alexandria / الإسكندرية / اسكندرية = HBE
- Sharm El Sheikh / شرم الشيخ = SSH
- Hurghada / الغردقة = HRG
- Luxor / الأقصر = LXR
- Aswan / أسوان = ASW
- Marsa Alam / مرسى علم = RMF
- Dubai / دبي = DXB
- Milan / Milano / ميلان = MIL

Required JSON format:
{{
  "departure_id": "CAI",
  "arrival_id": "DXB",
  "outbound_date": "YYYY-MM-DD",
  "return_date": null,
  "type": "1"
}}
"""

    payload = {
        "messages": [
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        "temperature": 0.1,
        "max_tokens": 300
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
            timeout=20
        )

        response.raise_for_status()

        ai_text = response.json().get("result", "")
        match = re.search(r"\{.*\}", ai_text, re.DOTALL)

        if match:
            return json.loads(match.group())

    except Exception as e:
        print(f"[AI Error] {e}")

    return None

def search_flights(info: dict):
    params = {
        "engine": "google_flights",
        "departure_id": info.get("departure_id"),
        "arrival_id": info.get("arrival_id"),
        "outbound_date": info.get("outbound_date"),
        "currency": "USD",
        "type": info.get("type", "1"),
        "api_key": SERPAPI_KEY,
        "hl": "en",
    }

    if info.get("return_date"):
        params["return_date"] = info["return_date"]

    try:
        results = GoogleSearch(params).get_dict()
    except Exception as e:
        print(f"[SerpAPI Error] {e}")
        return "❌ حصل خطأ أثناء البحث عن الرحلات. جرب تاني بعد لحظات."

    flights = (
        results.get("best_flights", []) +
        results.get("other_flights", [])
    )[:5]

    if not flights:
        return "😕 مش لاقي رحلات مناسبة للتفاصيل دي."

    trip_type = "ذهاب وعودة" if params["type"] == "2" else "ذهاب فقط"

    lines = [
        f"✈️ الرحلة: {params['departure_id']} → {params['arrival_id']}",
        f"📅 السفر: {params['outbound_date']}",
    ]

    if params.get("return_date"):
        lines.append(f"↩️ العودة: {params['return_date']}")

    lines.append(f"🔄 النوع: {trip_type}")
    lines.append("")

    for i, flight in enumerate(flights, 1):
        price = flight.get("price", "?")
        duration = flight.get("total_duration", "?")
        legs = flight.get("flights", [])

        airline = legs[0].get("airline", "—") if legs else "—"
        stops = len(legs) - 1 if legs else 0
        stop_text = "مباشر" if stops == 0 else f"{stops} توقف"

        lines.append(
            f"{i}. {airline} | 💰 ${price} | ⏱ {duration} دقيقة | {stop_text}"
        )

    lines.append("\n💡 الأسعار من Google Flights وقد تتغير وقت الحجز")

    return "\n".join(lines)

def send_message(recipient_id: str, text: str):
    chunks = [text[i:i+2000] for i in range(0, len(text), 2000)]

    for chunk in chunks:
        try:
            requests.post(
                "https://graph.facebook.com/v19.0/me/messages",
                params={"access_token": MESSENGER_TOKEN},
                json={
                    "recipient": {"id": recipient_id},
                    "message": {"text": chunk}
                },
                timeout=10
            )
        except Exception as e:
            print(f"[Messenger Error] {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
