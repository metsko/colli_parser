import hashlib
import json
import os
from pathlib import Path

import polars as pl
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger
from telegram import Bot, Update

from api_client import ChatGPTClient
from config import config
from invoice_parser import InvoiceParser
from utils import get_hash_map
from splitwise import Splitwise
from splitwise.expense import Expense
from splitwise.user import Friend, ExpenseUser
from splitwise.group import Group
from typing import Dict

env_path = ".env"
if load_dotenv(env_path):
    logger.info(f"Loaded env variables from {env_path}.")

app = FastAPI()

# Your bot token from BotFather
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
# Your API token for securing the endpoint
API_TOKEN = os.getenv("API_TOKEN")

bot = Bot(token=BOT_TOKEN)
api_client = ChatGPTClient(config.API_TOKEN)
parser = InvoiceParser(api_client)

# SPLITWISE_GROUP=
s = Splitwise(
    os.getenv("SPLITWISE_CONSUMER_KEY"),
    os.getenv("SPLITWISE_CONSUMER_SECRET"),
    api_key=os.getenv("SPLITWISE_API_KEY"),
)
current = s.getCurrentUser()
group = s.getGroup()
SW_GROUP_NAME = "Anti Hangriness Sofieke"
sofie = list(filter(lambda f: f.first_name == "Sofie", s.getFriends()))[0]


def get_group():
    group = list(filter(lambda g: g.getName() == SW_GROUP_NAME, s.getGroups()))
    if group != []:
        return group[0]
    else:
        logger.warning(f"Group {SW_GROUP_NAME} does not exists.")
        create_sw_group()


def create_sw_group():
    logger.info(f"Creating group {SW_GROUP_NAME}")
    group = group = Group()
    group.setName(SW_GROUP_NAME)
    group.addMember(sofie)
    s.createGroup(group)


def register_splitwise_expense(item_dict: Dict, sofie: Friend = sofie):
    group = get_group()
    expense = Expense()
    expense.setGroupId(group.id)
    expense.setCost(item_dict["price"])
    expense.setDescription(item_dict["description"])
    maarten_exp = ExpenseUser()
    maarten_exp.setId(current.id)
    maarten_exp.setPaidShare(1 * item_dict["price"])
    maarten_exp.setOwedShare(1 * item_dict["price"])
    sofie_exp = ExpenseUser()
    sofie_exp.setId(sofie.id)
    sofie_exp.setPaidShare(0 * item_dict["price"])
    sofie_exp.setOwedShare(0 * item_dict["price"])
    expense.addUser(maarten_exp)
    expense.addUser(sofie_exp)
    nExpense, errors = s.createExpense(expense)
    if errors:
        logger.error(errors)


def calculate_file_hash(file_path: str) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        buf = f.read()
        hasher.update(buf)
    return hasher.hexdigest()


def parse_invoice(local_file_path: str, parser=parser) -> pl.DataFrame:
    file_hash = calculate_file_hash(local_file_path)
    output_path = Path("data/output.ndjson")

    if output_path.exists():
        df_existing = pl.read_ndjson(output_path)
        if file_hash in df_existing["file_hash"].to_list():
            logger.info(
                f"File hash {file_hash} already exists. Reading from output.ndjson."
            )
            return df_existing.filter(pl.col("file_hash") == file_hash)

    try:
        invoice_jsons = parser.parse_invoice(local_file_path)
        json_outputs = list(map(parser.to_json, invoice_jsons))
        df = pl.DataFrame(json_outputs)
        df = df.select(
            pl.col("column_0").str.json_decode().alias("page_struct")
        ).unnest("page_struct")
        df = df.with_columns(
            pl.lit(local_file_path).alias("path"), pl.lit(file_hash).alias("file_hash")
        )
        df.to_pandas().to_json(output_path, orient="records", mode="a", lines="True")
        return df
    except ValueError as e:
        logger.error(f"Error: {e}")


def parse_maartens_items(local_file_path: Path):
    # Parse the invoice
    df = parse_invoice(local_file_path.as_posix())

    return json.dumps(
        get_hash_map(
            df.explode("items")
            .unnest("items")
            .filter(pl.col("description").is_not_null()),
            ["soya", "espresso", "koffie", "graindor", "bananen", "actimel"],
        )
        .sort("max_similarity_ratio", descending=True)
        .select("description", "price")
        .to_dicts()
    )


@app.post("/register_expense")
async def register_expense(item_json: str):
    """
    Parse Maarten's items from the invoice
    """

    return register_splitwise_expense(item_json)


@app.post("/parse_maarten")
async def parse_maarten(local_file_path: str):
    """
    Parse Maarten's items from the invoice
    """
    return parse_maartens_items(Path(local_file_path))


@app.post("/webhook")
async def webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(...)):
    """
    Webhook to handle Telegram messages
    """
    logger.info(f"Received Secret Token header: {x_telegram_bot_api_secret_token}")
    logger.info(f"Expected Secret Token header: {API_TOKEN}")

    if x_telegram_bot_api_secret_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    update_data = await request.json()
    update = Update.de_json(update_data, bot)
    chat_id = update.message.chat.id

    if (
        update.message.document
        and update.message.document.mime_type == "application/pdf"
    ):
        file_id = update.message.document.file_id
        file_info = await bot.get_file(file_id)

        # Download the PDF file
        local_file_path = Path("data") / f"{file_id}.pdf"
        await file_info.download_to_drive(local_file_path)

        answer = parse_maartens_items(local_file_path)
        list(map(lambda item: register_splitwise_expense(item), json.loads(answer)))
        await bot.send_message(chat_id=chat_id, text=answer)
    else:
        await bot.send_message(chat_id=chat_id, text="Please send a PDF file.")

    return JSONResponse(content={"status": "ok"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=6000)
