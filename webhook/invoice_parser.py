import os
import time
from pathlib import Path
from typing import List, Union

import polars as pl
from azure.storage.blob import BlobServiceClient, ContainerClient
from loguru import logger
from tqdm import tqdm

from api_client import MistralAIClient
from models import Invoice


class InvoiceParser:
    def __init__(self, api_client: MistralAIClient = None, output_path: str = "data"):
        self.api_client = api_client
        self.output_path = output_path

    def parse_invoice(self, invoice_path: str) -> Union[Invoice, List[Invoice]]:
        """
        Parses the invoice PDF and extracts relevant information.
        Uses direct PDF OCR if possible, otherwise falls back to image-based OCR.
        """
        logger.info(f"Parsing invoice: {invoice_path}")
        start_time = time.time()

        # Check if the file is a PDF
        if invoice_path.lower().endswith(".pdf"):
            try:
                # Try direct PDF OCR processing first
                logger.info(f"Using direct PDF OCR for: {invoice_path}")
                result = self.api_client.get_response(invoice_path)
                end_time = time.time()
                logger.info(
                    f"Successfully parsed PDF directly: {invoice_path} in {end_time - start_time:.2f} seconds"
                )
                return result
            except Exception as e:
                logger.error(f"Direct PDF OCR failed: {e}")
                pass


def get_container_client(name: str) -> ContainerClient:
    connect_str = os.getenv("AzureWebJobsStorage")
    if not connect_str:
        logger.error("AzureWebJobsStorage is not set.")
        return None
    blob_service_client = BlobServiceClient.from_connection_string(connect_str)
    container_client = blob_service_client.get_container_client(name)
    if not container_client.exists():
        container_client.create_container()
    return container_client


def azure_upload_file(local_file_path: str, azure_filename: str):
    container_client = get_container_client("function")
    if not container_client.exists():
        container_client.create_container()
    with open(local_file_path, "rb") as f:
        blob_client = container_client.get_blob_client(azure_filename)
        blob_client.upload_blob(f, overwrite=True)
    logger.info(f"Uploaded file to Azure container 'function' as {azure_filename}.")


def azure_upload_ndjson(df: pl.DataFrame, file_name: str):
    container_client = get_container_client("function")
    ndjson_content = df.to_pandas().to_json(orient="records", lines=True)
    blob_client = container_client.get_blob_client(file_name)
    blob_client.upload_blob(ndjson_content, overwrite=True)
    logger.info(f"Uploaded NDJSON to Azure container 'function' as {file_name}.")


def main():
    files = set(Path("data").rglob("*.pdf"))
    api_client = MistralAIClient(os.getenv("MISTRAL_API_TOKEN"))
    parser = InvoiceParser(api_client)
    output_path = "../data"
    for file in tqdm(files, total=len(files)):
        try:
            invoice_result = parser.parse_invoice(file)

            # Handle both single Invoice and list of Invoices
            if isinstance(invoice_result, list):
                json_outputs = list(map(parser.to_json, invoice_result))
                df = pl.DataFrame(json_outputs)
                df = df.select(
                    pl.col("column_0").str.json_decode().alias("page_struct")
                ).unnest("page_struct")
            else:
                # Single Invoice from direct PDF OCR
                json_output = parser.to_json(invoice_result)
                df = pl.DataFrame([json_output])
                df = df.select(
                    pl.col("column_0").str.json_decode().alias("page_struct")
                ).unnest("page_struct")

            df = df.with_columns(pl.lit(file.as_posix()).alias("path"))
            # Remove local file save:
            # df.write_ndjson(f'{output_path}/output.ndjson')
            azure_upload_ndjson(df, "output.ndjson")
        except Exception as e:
            logger.error(f"Failed to parse invoice: {e}")
            raise ValueError(f"Failed to parse invoice: {e}")


if __name__ == "__main__":
    main()
