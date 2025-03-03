import json

import azure.functions as func
from app import handle_telegram_update
from config import config

app = func.FunctionApp()


# This decorator defines an HTTP endpoint for the webhook
@app.route(methods=["post"], route="webhook")
async def process_webhook(req: func.HttpRequest) -> func.HttpResponse:
    token = req.headers.get("X-Telegram-Bot-Api-Secret-Token")

    if not token or token != config.API_TOKEN:
        return func.HttpResponse("Unauthorized", status_code=401)
    try:
        update_data = req.get_json()
        await handle_telegram_update(update_data)
        return func.HttpResponse(
            json.dumps({"status": "ok"}), mimetype="application/json"
        )
    except json.JSONDecodeError as e:
        return func.HttpResponse(f"JSON decode error: {str(e)}", status_code=400)
    except Exception as e:
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)
