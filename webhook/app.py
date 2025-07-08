import difflib
import hashlib
import io
import math
import os
from pathlib import Path
from typing import Dict, List

import numpy as np
import polars as pl
from dotenv import load_dotenv
from loguru import logger
from splitwise import Splitwise
from splitwise.expense import Expense
from splitwise.group import Group
from splitwise.user import ExpenseUser
from tabulate import tabulate
from telegram import Bot, Update

from api_client import MistralAIClient
# from blob_utils import async_azure_upload_ndjson, get_async_container_client

from azure.storage.blob import BlobServiceClient, ContainerClient
from invoice_parser import InvoiceParser
from utils import get_hash_map

env_path = ".env"
if load_dotenv(env_path):
    logger.info(f"Loaded env variables from {env_path}.")

# Your bot token from BotFather
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
# Your API token for securing the endpoint
API_TOKEN = os.getenv("API_TOKEN")
CHATGPT_API_TOKEN = os.getenv("CHATGPT_API_TOKEN")

bot = Bot(token=BOT_TOKEN)
# api_client = ChatGPTClient(CHATGPT_API_TOKEN)
api_client = MistralAIClient(os.getenv("MISTRAL_API_TOKEN"))
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

data_path = Path("../data")
data_path.mkdir(exist_ok=True)
data_path = data_path.as_posix()


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
    maartens_owe_percentage: float = None,
    sofies_pct: float = 0,
    group_name: str = SOFIE_MAARTEN_SW_GROUP_NAME,
):
    price = item_dict["adjusted_amount"]
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
    expense.setDate(item_dict.get("date", None))
    maarten_exp = ExpenseUser()
    maarten_exp.setId(current.id)

    assert (not maartens_owe_percentage) or (maartens_owe_percentage <= 1), (
        "Maarten's percentage should be less than or equal to 1."
    )
    if payer_name == "maarten":
        maartens_paid_share = price * (1 - sofies_pct / 100)
        maarten_exp.setPaidShare(maartens_paid_share)
    else:
        maarten_exp.setPaidShare(0)

    if maartens_owe_percentage is not None:
        maartens_share = price * maartens_owe_percentage
        # without Maarten
        equal_share = ((1 - maartens_owe_percentage) * price) / (len(members) - 1)
    else:
        # with Maarten
        equal_share = math.floor(price * 100 / len(members)) / 100
        maartens_share = equal_share

    maarten_exp.setOwedShare(maartens_share)
    expense.addUser(maarten_exp)
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
        friends_name = friend.first_name.lower().strip()
        payer_name = payer_name.lower().strip()
        if friends_name == "sofie":
            friend_exp.setPaidShare(price * sofies_pct / 100)
        elif friends_name == payer_name:
            friend_exp.setPaidShare(price * (1 - sofies_pct / 100))
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
    maartens_owe_percentage: float = None,
    group_name: str = SOFIE_MAARTEN_SW_GROUP_NAME,
    sofies_pct: float = None,
):
    for item in items:
        register_splitwise_expense(
            item,
            payer_name,
            friend_names,
            maartens_owe_percentage=maartens_owe_percentage,
            group_name=group_name,
            sofies_pct=sofies_pct,
        )


def calculate_file_hash(file_path: str) -> str:
    """Calculate SHA-256 hash of a file"""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        buf = f.read()
        hasher.update(buf)
    return hasher.hexdigest()

def get_container_client(container_name: str) -> ContainerClient:
    """Get a synchronous container client"""
    connection_string = os.getenv("AzureWebJobsStorage")
    if not connection_string:
        raise ValueError("No Azure Storage connection string found in environment variables")
    
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    return blob_service_client.get_container_client(container_name)

def azure_upload_ndjson(df: pl.DataFrame, blob_name: str):
    """Synchronous upload of DataFrame as NDJSON to blob storage"""
    container_name = "function"
    container_client = get_container_client(container_name)
    
    # Convert DataFrame to NDJSON
    ndjson_data = io.BytesIO()
    df.write_ndjson(ndjson_data)
    ndjson_data.seek(0)
    
    # Upload to blob storage
    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(ndjson_data, overwrite=True)

def local_save_ndjson(df: pl.DataFrame, file_name: str, data_path: str = data_path) -> None:
    """Save DataFrame as NDJSON to local file system"""
    # Ensure the output directory exists
    output_dir = Path(data_path) / "output"
    output_dir.mkdir(exist_ok=True)
    
    # Save the DataFrame to NDJSON file
    output_path = output_dir / file_name
    df.write_ndjson(output_path)
    logger.info(f"Saved DataFrame to {output_path}")

def parse_invoice(local_file_path: str, data_path=data_path) -> pl.DataFrame:
    """Parse an invoice using local file operations"""
    parser = InvoiceParser(api_client, output_path=data_path)
    file_hash = calculate_file_hash(local_file_path)
    
    # Ensure local storage directories exist
    output_dir = Path(data_path) / "output"
    invoices_dir = Path(data_path) / "invoices"
    output_dir.mkdir(exist_ok=True)
    invoices_dir.mkdir(exist_ok=True)
    
    # Output file paths
    df_output_file = output_dir / "output.ndjson"
    invoice_file = invoices_dir / f"{file_hash}.pdf"

    # Convert Path to string if needed
    if isinstance(local_file_path, Path):
        local_file_path_str = str(local_file_path)
    else:
        local_file_path_str = local_file_path

    try:
        # Check if invoice file already exists
        if invoice_file.exists():
            logger.info(f"Invoice file {invoice_file} already exists.")
            
            # Check if output file exists and contains this invoice data
            if df_output_file.exists():
                try:
                    # Read existing data
                    df_existing = pl.read_ndjson(df_output_file)
                    
                    if file_hash in df_existing["file_hash"].to_list():
                        logger.info(f"File hash {file_hash} already exists. Reading from local storage.")
                        return df_existing.filter(pl.col("file_hash") == file_hash)
                    else:
                        logger.info(f"File hash {file_hash} not found in existing output. Continuing with parse.")
                except Exception as e:
                    logger.warning(f"Failed to read output data: {str(e)}")
        else:
            logger.info(f"Invoice file {invoice_file} not found, copying file.")
            
            # Copy the invoice file to the invoices directory
            try:
                import shutil
                shutil.copy2(local_file_path_str, invoice_file)
            except Exception as e:
                logger.warning(f"Error copying invoice file: {str(e)}")
    
    except Exception as e:
        logger.warning(f"Error with file operations: {str(e)}")

    # Process the invoice
    try:
        invoice_result = parser.parse_invoice(local_file_path_str)

        # Handle both single invoice and list of invoices
        if hasattr(invoice_result, "model_dump_json"):
            invoice_json = invoice_result.model_dump_json()
            df = pl.DataFrame([invoice_json])
        else:
            # Assuming list of Invoice objects
            invoice_jsons = [inv.model_dump_json() for inv in invoice_result]
            df = pl.DataFrame(invoice_jsons)

        df = df.select(
            pl.col("column_0").str.json_decode().alias("page_struct")
        ).unnest("page_struct")

        df = df.with_columns(
            pl.lit(local_file_path_str).alias("path"),
            pl.lit(file_hash).alias("file_hash"),
        )

        # Save result to local file system
        local_save_ndjson(df, "output.ndjson", data_path)
        
        return df
    except ValueError as e:
        logger.error(f"Error: {e}")
        raise


def filter_items(invoice_items_df: pl.DataFrame, items: List[str]) -> pl.DataFrame:
    output = get_hash_map(invoice_items_df, items).sort(
        "max_similarity_ratio", descending=True
    )

    # Make sure to preserve the date field if it exists in the dataframe
    columns_to_select = ["description", "adjusted_amount"]
    if "date" in invoice_items_df.columns:
        columns_to_select.append("date")

    return output.select(columns_to_select)


def group_waarborg_fields(invoice_items_df: pl.DataFrame) -> pl.DataFrame:
    waarborg_filter = pl.col("description").str.contains("waarborg")
    waarborg_df = invoice_items_df.filter(waarborg_filter)

    if waarborg_df.is_empty():
        return invoice_items_df

    return pl.concat(
        [
            invoice_items_df.filter(~waarborg_filter),
            waarborg_df.group_by(pl.lit(1))
            .agg(
                pl.exclude(["adjusted_amount"]).first(),
                pl.sum("adjusted_amount").alias("adjusted_amount"),
            )
            .select(invoice_items_df.columns)
            .with_columns(pl.lit("waarborg net").alias("description")),
        ]
    )


def clean_invoice_df(invoice_items_df: pl.DataFrame) -> pl.DataFrame:
    total_amount_filter = pl.col("description").str.contains(
        "total payment|total amount"
    )

    adjusted_discount = (
        pl.when(
            pl.col("next_description").str.to_lowercase().str.starts_with("korting")
        )
        .then(pl.col("next_discount"))
        .otherwise(
            # pl.when(pl.col("description").str.contains("korting"))
            # .then(pl.col("discount"))
            # .otherwise(pl.lit(0.0))
            pl.col("discount")
        )
        .alias("discount")
    )

    # First extract the total amount from any row with korting/total payment/total amount due
    invoice_items_df = (
        invoice_items_df.explode("items")
        .unnest("items")
        .filter(pl.col("description").is_not_null())
        .with_columns(
            (pl.col("quantity") * pl.col("unit_price")).round(2).alias("price")
        )
        .with_columns(pl.col("description").str.to_lowercase().alias("description"))
        .with_columns(
            [
                pl.col("discount").shift(-1).alias("next_discount"),
                pl.col("description").shift(-1).alias("next_description"),
            ]
        )
        .with_columns(
            pl.when(
                pl.col("next_description").str.to_lowercase().str.starts_with("korting")
            )
            .then((pl.col("description") + " " + pl.col("next_description")))
            .otherwise(pl.col("description"))
            .alias("description")
        )
        .with_columns(adjusted_discount)
    )

    # Get total amount if available (use first match if multiple rows)
    total_amount_df = invoice_items_df.filter(total_amount_filter)
    total_amount = (
        total_amount_df["total_amount_invoice"][0]
        if not total_amount_df.is_empty()
        else None
    )

    # apple due to xtra sign similar to an apple
    not_a_product_filter = pl.col("description").str.contains(
        "total payment|total amount|apple|maestro"
    )
    cleaned_df = (
        invoice_items_df.filter(~not_a_product_filter)
        # Adjust price by discount
        .with_columns(
            (pl.col("price") * (1 - (pl.col("discount") / 100)))
            .round(2)
            .alias("adjusted_amount")
        )
    )

    # Add total_amount as a column and check for discrepancy
    sum_price = cleaned_df["adjusted_amount"].sum()
    if total_amount is not None and abs(sum_price - total_amount) > 0.01:
        print(f"Sum of items ({sum_price}) differs from total amount ({total_amount})")

    # Add date back to each row if we had captured it earlier
    cleaned_df_with_total = cleaned_df.with_columns(
        pl.lit(total_amount).alias("total_amount")
    )
    # Add date column if it exists in the original data
    if "invoice_date" in invoice_items_df.columns:
        invoice_date = invoice_items_df["invoice_date"].first()
        cleaned_df_with_total = cleaned_df_with_total.with_columns(
            pl.lit(invoice_date).alias("date")
        )

    return group_waarborg_fields(cleaned_df_with_total)


def items_dicts_to_items(items_dicts: List[Dict]) -> List[str]:
    return [items["description"] for items in items_dicts]


async def process_invoice(
    local_file_path: str, payer_name: str, sofies_amount: float, data_path: str
) -> str:
    # Get the invoice data without await
    invoice_df = parse_invoice(local_file_path, data_path=data_path)
    invoice_items_df = clean_invoice_df(invoice_df)
    total_price = invoice_items_df["adjusted_amount"].sum()
    sofies_pct = (
        sofies_amount / total_price * 100 if payer_name.lower() != "sofie" else 100
    )
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
            "roomijs vanille",
            "côte d'or",
            "pizza Hawaii",
            "pizza barbecue",
        ],
    )

    maartens_items_descriptions = maartens_items_df["description"].to_list()
    register_splitwise_expenses(
        maartens_items_df.to_dicts(),
        payer_name=payer_name,
        friend_names=["Sofie"],
        maartens_owe_percentage=1,
        sofies_pct=sofies_pct,
    )

    sofies_items_df = filter_items(
        invoice_items_df,
        ["raclette", "maandverband"],
    )
    sofies_items_descriptions = sofies_items_df["description"].to_list()
    register_splitwise_expenses(
        sofies_items_df.to_dicts(),
        payer_name=payer_name,
        friend_names=["Sofie"],
        maartens_owe_percentage=0,
        sofies_pct=sofies_pct,
    )

    common_items_df = filter_items(
        invoice_items_df,
        ["toiletpapier", "handzeep", "ontstopper", "allesreiniger", "afwasmiddel"],
    )
    common_items_descriptions = common_items_df["description"].to_list()
    # register_splitwise_expenses(common_items_df.to_dicts(), group_name=BLIJDEBERG_SW_GROUP_NAME, sofies_pct=sofies_pct)

    not_rest_items = (
        common_items_descriptions
        + maartens_items_descriptions
        + sofies_items_descriptions
    )
    rest_items_df = invoice_items_df.filter(pl.col("description").is_not_null()).filter(
        ~pl.col("description").is_in(not_rest_items)
    )
    register_splitwise_expenses(
        rest_items_df.to_dicts(), payer_name=payer_name, sofies_pct=sofies_pct
    )

    answer = f"Registered the Maartens items: \n{tabulate(maartens_items_df.to_pandas())}\n\n"
    answer += (
        f"Registered the Sofies items: \n{tabulate(sofies_items_df.to_pandas())}\n\n"
    )
    answer += (
        f"Registered the common items: \n{tabulate(common_items_df.to_pandas())}\n\n"
    )
    answer += f"Registered the rest items: \n{tabulate(rest_items_df.select('description', 'adjusted_amount').to_pandas())}\n\n"

    return answer


conversation_state = {}

# Add new states for our conversation flow
CONVERSATION_STATES = {
    "WAIT_FOR_GROUP": "Which group is this expense for? (Anti Hangriness Sofieke/Blijdeberg)",
    "WAIT_FOR_PAYER": "Who paid the invoice?",
    "WAIT_FOR_PDF": "Send me an invoice PDF file, please.",
}


def get_available_members(group_name: str) -> List[str]:
    group = get_group(group_name)
    if group:
        return [f.first_name for f in group.members]
    return []


async def handle_telegram_update(update_data: dict, data_path=data_path) -> None:
    update = Update.de_json(update_data, bot)
    chat_id = update.message.chat.id
    text = update.message.text or ""

    # Initialize new conversation
    if chat_id not in conversation_state:
        conversation_state[chat_id] = {"state": "WAIT_FOR_GROUP"}
        await bot.send_message(
            chat_id=chat_id, text=CONVERSATION_STATES["WAIT_FOR_GROUP"]
        )
        return

    current_state = conversation_state[chat_id]["state"]

    def longest_common_subsequence(str1, str2):
        sequence_matcher = difflib.SequenceMatcher(None, str1, str2)
        match = sequence_matcher.find_longest_match(0, len(str1), 0, len(str2))
        return {"lcs": str1[match.a : match.a + match.size]}

    def fuzzy_match(target: str, options: List[str]) -> str:
        lcses = [longest_common_subsequence(target, option) for option in options]
        return options[np.argmax([len(lcs["lcs"]) for lcs in lcses])]

    # Reset conversation if user types "reset"
    if text.strip().lower() == "reset":
        conversation_state[chat_id] = {"state": "WAIT_FOR_GROUP"}
        await bot.send_message(
            chat_id=chat_id,
            text="Conversation reset. " + CONVERSATION_STATES["WAIT_FOR_GROUP"],
        )
        return

    # Handle group selection
    if current_state == "WAIT_FOR_GROUP":
        group_name = text.strip().lower()
        if group_name in ["1", "2"]:
            group_name = int(group_name)
            group_name -= 1
            group_name = [SOFIE_MAARTEN_SW_GROUP_NAME, BLIJDEBERG_SW_GROUP_NAME][
                group_name
            ]
        else:
            group_name = fuzzy_match(
                group_name, [SOFIE_MAARTEN_SW_GROUP_NAME, BLIJDEBERG_SW_GROUP_NAME]
            )
        if group_name is None:
            await bot.send_message(
                chat_id=chat_id,
                text=f"Invalid group. Please choose from: {SOFIE_MAARTEN_SW_GROUP_NAME} or {BLIJDEBERG_SW_GROUP_NAME}",
            )
            return
        conversation_state[chat_id].update(
            {"state": "WAIT_FOR_PAYER", "group_name": group_name}
        )
        message = (
            f"Group selected: {group_name}. {CONVERSATION_STATES['WAIT_FOR_PAYER']}"
        )
        await bot.send_message(chat_id=chat_id, text=message)
        return

        # Handle payer name
    if current_state == "WAIT_FOR_PAYER":
        payer_name = text.strip().lower()
        group_name = conversation_state[chat_id]["group_name"]
        available_members = get_available_members(group_name)
        payer_name = fuzzy_match(payer_name, available_members)

        if not payer_name:
            await bot.send_message(
                chat_id=chat_id,
                text=f"Invalid payer name '{payer_name}'. Please choose from: {', '.join(available_members)}",
            )
            return

        conversation_state[chat_id].update(
            {"state": "WAIT_FOR_PDF", "payer_name": payer_name}
        )

        if payer_name.lower() == "sofie":
            conversation_state[chat_id]["sofies_pct"] = 1
            message = CONVERSATION_STATES["WAIT_FOR_PDF"]
        else:
            message = f"Payer selected: {payer_name}. How much did Sofie pay?"
            conversation_state[chat_id]["state"] = "WAIT_FOR_SOFIE_AMOUNT"
            conversation_state[chat_id]["sofies_pct"] = 0

        await bot.send_message(chat_id=chat_id, text=message)
        return

    # Handle Sofie's amount
    if current_state == "WAIT_FOR_SOFIE_AMOUNT":
        try:
            sofie_amount = float(text.strip())
            conversation_state[chat_id].update(
                {"state": "WAIT_FOR_PDF", "sofie_amount": sofie_amount}
            )
            message = (
                f"Sofie's amount: {sofie_amount}. {CONVERSATION_STATES['WAIT_FOR_PDF']}"
            )
            await bot.send_message(chat_id=chat_id, text=message)
        except ValueError:
            await bot.send_message(chat_id=chat_id, text="Please enter a valid amount.")
        return

    # Handle PDF upload
    if current_state == "WAIT_FOR_PDF":
        if not (
            update.message.document
            and update.message.document.mime_type == "application/pdf"
        ):
            await bot.send_message(chat_id=chat_id, text="Please send a PDF file.")
            return

    try:
        file_id = update.message.document.file_id
        file_info = await bot.get_file(file_id)
        local_file_path = Path(data_path) / f"{file_id}.pdf"
        await file_info.download_to_drive(local_file_path)

        payer_name = conversation_state[chat_id]["payer_name"]
        group_name = conversation_state[chat_id]["group_name"]
        sofies_amount = conversation_state[chat_id].get("sofie_amount", 0)

        # Convert Path to string for process_invoice
        local_file_path_str = str(local_file_path)
        answer = await process_invoice(
            local_file_path_str,
            payer_name=payer_name,
            sofies_amount=sofies_amount,
            data_path=data_path,
        )
        logger.info(answer)
        await bot.send_message(chat_id=chat_id, text=answer)
        conversation_state.pop(chat_id, None)

    except ValueError as e:
        await bot.send_message(chat_id=chat_id, text=str(e))
        # Reset to group selection
        conversation_state[chat_id] = {"state": "WAIT_FOR_GROUP"}
        await bot.send_message(
            chat_id=chat_id, text=CONVERSATION_STATES["WAIT_FOR_GROUP"]
        )
    except Exception as e:
        await bot.send_message(
            chat_id=chat_id,
            text=f"An error occurred while processing the invoice: {str(e)}",
        )
        conversation_state.pop(chat_id, None)
