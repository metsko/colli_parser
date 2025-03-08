import os

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app import handle_telegram_update

API_TOKEN = os.getenv("API_TOKEN")

app = FastAPI()


@app.post("/webhook")
async def webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(
        ..., alias="X-Telegram-Bot-Api-Secret-Token"
    ),
):
    """
    Webhook to handle Telegram messages
    """
    if x_telegram_bot_api_secret_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    update_data = await request.json()
    # we run from ./webhook
    await handle_telegram_update(update_data, data_path="../data")
    return JSONResponse(content={"status": "ok"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5000)
