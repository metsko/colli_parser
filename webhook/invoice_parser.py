import os
import time
from pathlib import Path
from typing import List, Union

import polars as pl
from loguru import logger
from tqdm import tqdm

from api_client import MistralAIClient
from models import Invoice
import fitz
import pymupdf
from azure.storage.blob import BlobServiceClient


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
        if invoice_path.lower().endswith('.pdf'):
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
                logger.warning(f"Direct PDF OCR failed, falling back to image-based method: {e}")
                # Fall back to image-based method
                pass
        
        # Traditional image-based method as fallback
        try:
            image_paths = self.pdf_to_image(invoice_path)
        except Exception as e:
            logger.error(f"Failed to convert PDF to images: {e}")
            raise ValueError(f"Failed to convert PDF to images: {e}")

        try:
            jsons = list(map(self.api_client.get_response, image_paths))
            end_time = time.time()
            logger.info(
                f"Successfully parsed invoice using images: {invoice_path} in {end_time - start_time:.2f} seconds"
            )
            return jsons
        except Exception as e:
            logger.error(f"Failed to parse invoice: {e}")
            raise ValueError(f"Failed to parse invoice: {e}")

    def pdf_to_image(self, pdf_path: str) -> List[str]:
        """
        Converts each page of the PDF to an image and returns a list of image paths.
        """

        doc = fitz.open(pdf_path)
        image_paths = []
        for i in range(len(doc)):
            page = doc.load_page(i)
            zoom_x = 4.0  # horizontal zoom
            zoom_y = 4.0  # vertical zoom
            mat = pymupdf.Matrix(zoom_x, zoom_y)  # zoom factor 2 in each dimension
            
            # Create two pixmaps: top half (A) and bottom half (B)
            # Get page rectangle and middle point
            rect = page.rect  # the page rectangle
            mid_y = (rect.y0 + rect.y1) / 2  # y-coordinate of the middle point
            
            # Top half (A) - from top to middle height
            clip_a = pymupdf.Rect(rect.x0, rect.y0, rect.x1, mid_y)
            pix_a = page.get_pixmap(matrix=mat, clip=clip_a)
            image_path_a = Path(self.output_path)/f"temp_image_{i}_A.jpg"
            pix_a.save(image_path_a)
            # Only upload to Azure if connection string is available
            if os.getenv("AzureWebJobsStorage"):
                azure_upload_file(str(image_path_a), f"images/temp_image_{i}_A.jpg")
            image_paths.append(str(image_path_a))
            
            # Bottom half (B) - from middle height to bottom
            clip_b = pymupdf.Rect(rect.x0, mid_y, rect.x1, rect.y1)
            pix_b = page.get_pixmap(matrix=mat, clip=clip_b)
            image_path_b = Path(self.output_path)/f"temp_image_{i}_B.jpg"
            pix_b.save(image_path_b)
            # Only upload to Azure if connection string is available
            if os.getenv("AzureWebJobsStorage"):
                azure_upload_file(str(image_path_b), f"images/temp_image_{i}_B.jpg")
            image_paths.append(str(image_path_b))
        doc.close()
        return image_paths

    def to_json(self, invoice: Invoice) -> str:
        """
        Converts the Invoice object to a JSON string.
        """
        return invoice.model_dump_json()


def azure_upload_file(local_file_path: str, azure_filename: str):
    connect_str = os.getenv("AzureWebJobsStorage")
    if not connect_str:
        logger.error("AzureWebJobsStorage is not set.")
        return
    blob_service_client = BlobServiceClient.from_connection_string(connect_str)
    container_client = blob_service_client.get_container_client("function")
    if not container_client.exists():
        container_client.create_container()
    with open(local_file_path, "rb") as f:
        blob_client = container_client.get_blob_client(azure_filename)
        blob_client.upload_blob(f, overwrite=True)
    logger.info(f"Uploaded file to Azure container 'function' as {azure_filename}.")


def azure_upload_ndjson(df: pl.DataFrame, file_name: str):
    connect_str = os.getenv("AzureWebJobsStorage")
    if not connect_str:
        logger.error("AzureWebJobsStorage is not set.")
        return
    blob_service_client = BlobServiceClient.from_connection_string(connect_str)
    container_client = blob_service_client.get_container_client("function")
    if not container_client.exists():
        container_client.create_container()
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
                df = df.select(pl.col('column_0').str.json_decode().alias('page_struct')).unnest('page_struct')
            else:
                # Single Invoice from direct PDF OCR
                json_output = parser.to_json(invoice_result)
                df = pl.DataFrame([json_output])
                df = df.select(pl.col('column_0').str.json_decode().alias('page_struct')).unnest('page_struct')
                
            df = df.with_columns(pl.lit(file.as_posix()).alias("path"))
            # Remove local file save:
            # df.write_ndjson(f'{output_path}/output.ndjson')
            azure_upload_ndjson(df, "output.ndjson")
        except Exception as e:
            logger.error(f"Failed to parse invoice: {e}")
            raise ValueError(f"Failed to parse invoice: {e}")


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
