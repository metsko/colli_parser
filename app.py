import hashlib
import math
import os
from pathlib import Path
from typing import Dict, List

import polars as pl
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger
from splitwise import Splitwise
from splitwise.expense import Expense
from splitwise.group import Group
from splitwise.user import ExpenseUser
from tabulate import tabulate
from telegram import Bot, Update

from api_client import ChatGPTClient
from config import config
from invoice_parser import InvoiceParser
from utils import get_hash_map

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
SOFIE_MAARTEN_SW_GROUP_NAME = "Anti Hangriness Sofieke"
BLIJDEBERG_SW_GROUP_NAME = "Blijdeberg"


def get_group(group_name: str = SOFIE_MAARTEN_SW_GROUP_NAME) -> Group:
    group = list(filter(lambda g: g.getName() == group_name, s.getGroups()))
    if group != []:
        return group[0]
    else:
        logger.warning(f"Group {SOFIE_MAARTEN_SW_GROUP_NAME} does not exists.")
        create_sw_group()


def create_sw_group():
    logger.info(f"Creating group {SOFIE_MAARTEN_SW_GROUP_NAME}")
    group = group = Group()
    group.setName(SOFIE_MAARTEN_SW_GROUP_NAME)
    sofie = list(filter(lambda f: f.first_name == "Sofie", s.getFriends()))[0]
    group.addMember(sofie)
    s.createGroup(group)


def register_splitwise_expense(
    item_dict: Dict,
    payer_name: str,
    friend_names: List = None,
    maarten_percentage: float = None,
    group_name: str = SOFIE_MAARTEN_SW_GROUP_NAME,
):
    price = item_dict["price"]
    description = item_dict["description"]
    group = get_group(group_name)
    members = group.members
    available_members = [f.first_name for f in members]
    
    # Replace assertion with proper error handling
    if payer_name not in available_members:
        error_msg = (
            f"Invalid payer name '{payer_name}'. "
            f"Please choose from available members: {', '.join(available_members)}"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    if friend_names:
        members = [f for f in members if f.first_name in friend_names] + [current]

    for friend in members:
        if not any(member.id == friend.id for member in group.getMembers()):
            logger.error(
                f"Friend {friend.first_name} is not in the group {group_name}."
            )
            return

    expense = Expense()
    expense.setGroupId(group.id)
    expense.setCost(price)
    expense.setDescription(description)
    maarten_exp = ExpenseUser()
    maarten_exp.setId(current.id)

    assert (not maarten_percentage) or (maarten_percentage <= 1), (
        "Maarten's percentage should be less than 1."
    )
    if maarten_percentage:
        maartens_share = price * maarten_percentage
        maarten_exp.setOwedShare(maartens_share)
        if payer_name == "maarten":
            maarten_exp.setPaidShare(price)
        else:
            maarten_exp.setPaidShare(0)
        # without Maarten
        equal_share = ((1 - maarten_percentage) * price) / (len(members))
    else:
        # with Maarten
        equal_share = math.floor(price * 100 / len(members)) / 100
        maartens_share = equal_share
        maarten_exp.setPaidShare(equal_share)
        maarten_exp.setOwedShare(equal_share)

    expense.addUser(maarten_exp)

    if equal_share > 0:
        total_share = maartens_share
        other_members = list(
            set(filter(lambda f: f.first_name.lower() != "maarten", members))
        )
        for i, friend in enumerate(other_members):
            friend_exp = ExpenseUser()
            friend_exp.setId(friend.id)
            # last
            if i == (len(other_members) - 1):
                remainder = round(price - equal_share - total_share, 2)
                equal_share += remainder
            if friend.first_name == payer_name:
                friend_exp.setPaidShare(price)
            else:
                friend_exp.setPaidShare(0)
            friend_exp.setOwedShare(equal_share)
            expense.addUser(friend_exp)
            total_share += equal_share

    nExpense, errors = s.createExpense(expense)
    if errors:
        logger.error(errors)


def register_splitwise_expenses(
    items: List,
    payer_name: str,
    friend_names: List = None,
    maarten_percentage: float = None,
    group_name: str = SOFIE_MAARTEN_SW_GROUP_NAME,
):
    for item in items:
        register_splitwise_expense(
            item,
            payer_name,
            friend_names,
            maarten_percentage=maarten_percentage,
            group_name=group_name,
        )


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
            pl.lit(local_file_path.as_posix()).alias("path"), pl.lit(file_hash).alias("file_hash")
        )
        df.to_pandas().to_json(output_path, orient="records", mode="a", lines="True")
        return df
    except ValueError as e:
        logger.error(f"Error: {e}")


def filter_items(invoice_items_df: pl.DataFrame, items: List[str]) -> pl.DataFrame:
    output = get_hash_map(invoice_items_df, items).sort(
        "max_similarity_ratio", descending=True
    )

    return output.select("description", "price")


def clean_invoice_df(invoice_items_df: pl.DataFrame) -> pl.DataFrame:
    return (
        invoice_items_df.explode("items")
        .unnest("items")
        .filter(pl.col("description").is_not_null())
        .filter(pl.col("price").is_not_null())
        .filter(pl.col("price").cast(pl.Float32) != 0.0)
        .with_columns(pl.col("description").str.to_lowercase().alias("description"))
        .filter(~pl.col("description").str.contains("korting"))
    )


@app.post("/register_expense")
async def register_expense(item_json: str):
    """
    Parse Maarten's items from the invoice
    """

    return register_splitwise_expense(item_json)


@app.post("/parse_maarten")
async def parse_maarten(local_file_path: str) -> str:
    """
    Parse Maarten's items from the invoice
    """
    invoice_items_df = parse_invoice(local_file_path.as_posix())
    return tabulate(
        filter_items(
            invoice_items_df,
            ["soya", "espresso", "koffie", "graindor", "bananen", "actimel"],
        )
    )


def items_dicts_to_items(items_dicts: List[Dict]) -> List[str]:
    return [items["description"] for items in items_dicts]


@app.post("/process_invoice")
async def process_invoice(local_file_path: str, payer_name:str) -> str:
    invoice_items_df = clean_invoice_df(parse_invoice(local_file_path))
    maartens_items_df = filter_items(
        invoice_items_df,
        [
            "sojadrank",
            "espresso",
            "koffie",
            "graindor",
            "bananen",
            "actimel",
            "san pellegrino clementina",
            "san pellegrino aranciata",
        ],
    )
    maartens_items_descriptions = maartens_items_df["description"].to_list()
    register_splitwise_expenses(
        maartens_items_df.to_dicts(),payer_name=payer_name, friend_names=["Sofie"], maarten_percentage=1
    )

    # ultra normal is maandverband
    sofies_items_df = filter_items(
        invoice_items_df,
        ["raclette", "ultra normal"],
    )
    sofies_items_descriptions = sofies_items_df["description"].to_list()
    register_splitwise_expenses(
        sofies_items_df.to_dicts(), payer_name=payer_name, friend_names=["Sofie"], maarten_percentage=0
    )

    common_items_df = filter_items(
        invoice_items_df,
        ["toiletpapier", "handzeep", "ontstopper", "allesreiniger", "afwasmiddel"],
    )
    common_items_descriptions = common_items_df["description"].to_list()
    # register_splitwise_expenses(common_items_df.to_dicts(), group_name=BLIJDEBERG_SW_GROUP_NAME)

    not_rest_items = (
        common_items_descriptions
        + maartens_items_descriptions
        + sofies_items_descriptions
    )
    rest_items_df = invoice_items_df.filter(pl.col("description").is_not_null()).filter(
        ~pl.col("description").is_in(not_rest_items)
    )
    register_splitwise_expenses(rest_items_df.to_dicts(), payer_name=payer_name)

    answer = f"Registered the Maartens items: \n{tabulate(maartens_items_df.to_pandas())}\n\n"
    answer += (
        f"Registered the Sofies items: \n{tabulate(sofies_items_df.to_pandas())}\n\n"
    )
    answer += (
        f"Registered the common items: \n{tabulate(common_items_df.to_pandas())}\n\n"
    )
    answer += f"Registered the rest items: \n{tabulate(rest_items_df)}\n\n"

    return answer


conversation_state = {}


async def handle_telegram_update(update_data: dict) -> None:
    """
    Main handler for a Telegram update.
    Step 1: Ask "Who paid the invoice?" (store state)
    Step 2: Wait for the user to reply with the payer's name
    Step 3: Ask the user to send a PDF
    Step 4: Parse invoice with the payer's name
    """
    update = Update.de_json(update_data, bot)
    chat_id = update.message.chat.id
    text = update.message.text or ""

    # If we have no state for this chat_id, start by asking who paid
    if chat_id not in conversation_state:
        conversation_state[chat_id] = {"state": "WAIT_FOR_PAYER"}
        await bot.send_message(chat_id=chat_id, text="Who paid the invoice?")
        return

    current_state = conversation_state[chat_id]["state"]

    # If we are waiting for the payer's name text:
    if current_state == "WAIT_FOR_PAYER":
        # Save the payer name from user’s text
        conversation_state[chat_id]["payer_name"] = text.strip().lower()
        # Move to the next state, ask for the PDF
        conversation_state[chat_id]["state"] = "WAIT_FOR_PDF"
        await bot.send_message(
            chat_id=chat_id, text="Please upload the PDF invoice now."
        )
        return

    # If we are waiting for the PDF file:
    if current_state == "WAIT_FOR_PDF":
        if (
            update.message.document
            and update.message.document.mime_type == "application/pdf"
        ):
            try:
                file_id = update.message.document.file_id
                file_info = await bot.get_file(file_id)

                local_file_path = Path("data") / f"{file_id}.pdf"
                await file_info.download_to_drive(local_file_path)

                payer_name = conversation_state[chat_id]["payer_name"]
                answer = await process_invoice(local_file_path, payer_name=payer_name)
                await bot.send_message(chat_id=chat_id, text=answer)
            except ValueError as e:
                await bot.send_message(chat_id=chat_id, text=str(e))
                # Reset state to ask for payer name again
                conversation_state[chat_id] = {"state": "WAIT_FOR_PAYER"}
                await bot.send_message(chat_id=chat_id, text="Who paid the invoice?")
            except Exception as e:
                await bot.send_message(
                    chat_id=chat_id, 
                    text=f"An error occurred while processing the invoice: {str(e)}"
                )
                conversation_state.pop(chat_id, None)
            else:
                conversation_state.pop(chat_id, None)
        else:
            await bot.send_message(chat_id=chat_id, text="Please send a PDF file.")


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
    # logger.info(f"Received Secret Token header: {x_telegram_bot_api_secret_token}")
    # logger.info(f"Expected Secret Token header: {API_TOKEN}")

    if x_telegram_bot_api_secret_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    update_data = await request.json()
    await handle_telegram_update(update_data)  # Call the new main handler

    return JSONResponse(content={"status": "ok"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=6000)
