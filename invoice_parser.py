import os
import time
from pathlib import Path
from typing import List

import polars as pl
from loguru import logger
from pdf2image import convert_from_path
from tqdm import tqdm

from api_client import ChatGPTClient
from config import config
from models import Invoice


class InvoiceParser:
    def __init__(self, api_client: ChatGPTClient):
        self.api_client = api_client

    def parse_invoice(self, invoice_path: str) -> Invoice:
        """
        Parses the invoice PDF and extracts relevant information by processing each page as an image.
        """
        logger.info(f"Parsing invoice: {invoice_path}")
        start_time = time.time()
        try:
            image_paths = self.pdf_to_image(invoice_path)
        except Exception as e:
            logger.error(f"Failed to convert PDF to images: {e}")
            raise ValueError(f"Failed to convert PDF to images: {e}")

        try:
            jsons = list(map(self.api_client.get_response, image_paths))
            end_time = time.time()
            logger.info(
                f"Successfully parsed invoice: {invoice_path} in {end_time - start_time:.2f} seconds"
            )
            return jsons
        except Exception as e:
            logger.error(f"Failed to parse invoice: {e}")
            raise ValueError(f"Failed to parse invoice: {e}")

    def pdf_to_image(self, pdf_path: str) -> List[str]:
        """
        Converts each page of the PDF to an image and returns a list of image paths.
        """
        images = convert_from_path(pdf_path)
        image_paths = []
        for i, image in enumerate(images):
            image_path = f"data/temp_image_{i}.jpg"
            image.resize((600, 850)).save(image_path, "JPEG")
            image_paths.append(image_path)
        return image_paths

    def to_json(self, invoice: Invoice) -> str:
        """
        Converts the Invoice object to a JSON string.
        """
        return invoice.model_dump_json()


def main():
    files = set(Path("data").rglob("*.pdf"))
    api_client = ChatGPTClient(config.API_TOKEN)
    parser = InvoiceParser(api_client)
    for file in tqdm(files, total=len(files)):
        try:
            invoice_jsons = parser.parse_invoice(file)
            json_outputs = list(map(parser.to_json, invoice_jsons))
            df = pl.DataFrame(json_outputs)
            df = df.select(pl.col('column_0').str.json_decode().alias('page_struct')).unnest('page_struct')
            df.with_columns(pl.lit(file.as_posix()).alias("path")).write_ndjson('data/output.ndjson')
        except ValueError as e:
            print(f"Error: {e}")
            logger.error(f"Error: {e}")
        finally:
            # Clean up temporary image files
            for i in range(10):  # Assuming a maximum of 10 pages for simplicity
                image_path = f"data/temp_image_{i}.jpg"
                if os.path.exists(image_path):
                    os.remove(image_path)


if __name__ == "__main__":
    # Create a dummy pdf file for testing
    # from reportlab.pdfgen import canvas
    # c = canvas.Canvas("example_invoice.pdf")
    # c.drawString(100, 750, "Invoice Date: 2024-05-03")
    # c.drawString(100, 730, "Item 1: Apple - 2 units @ $1.00/unit")
    # c.drawString(100, 710, "Item 2: Banana - 3 units @ $0.50/unit")
    # c.drawString(100, 690, "Total: $3.50")
    # c.save()
    main()
