import json
import os

import azure.functions as func
from app import handle_telegram_update
import logging

logging.basicConfig(level=logging.DEBUG)

async def main(webhook: func.HttpRequest) -> func.HttpResponse:
    token = webhook.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not token or token != os.getenv("API_TOKEN"):
        return func.HttpResponse("Unauthorized", status_code=401)
    try:
        update_data = webhook.get_json()
        await handle_telegram_update(update_data)
        return func.HttpResponse(
            
            json.dumps({"status": "ok"}), mimetype="application/json"
        )
    except json.JSONDecodeError as e:
        return func.HttpResponse(f"JSON decode error: {str(e)}", status_code=400)
    except Exception as e:
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)
