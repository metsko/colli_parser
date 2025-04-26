from pathlib import Path

from mistralai import Mistral
from mistralai import TextChunk

from models import Invoice


class MistralAIClient:
    def __init__(self, api_token: str):
        self.client = Mistral(api_key=api_token)

    def get_response(self, file_path: str):
        """
        Sends an image or PDF to the Mistral AI OCR API and returns structured data.
        """
        try:
            file_ext = Path(file_path).suffix.lower()
            if file_ext == '.pdf':
                return self.structured_pdf_ocr(file_path)
            else:
                raise ValueError("Unsupported file type. Only PDF files are supported.")
        except Exception as e:
            raise ValueError(f"Failed to get response from Mistral AI API: {e}")

    def structured_pdf_ocr(self, pdf_path: str) -> Invoice:
        """
        Process a PDF document using OCR and extract structured data.

        Args:
            pdf_path: Path to the PDF file to process

        Returns:
            Invoice object containing the extracted data

        Raises:
            AssertionError: If the PDF file does not exist
        """
        # Validate input file
        pdf_file = Path(pdf_path)
        assert pdf_file.is_file(), "The provided PDF path does not exist."

        # Upload the PDF file to Mistral
        uploaded_pdf = self.client.files.upload(
            file={
                "file_name": pdf_file.name,
                "content": open(pdf_file, "rb"),
            },
            purpose="ocr"
        )

        # Get a signed URL for the uploaded file
        signed_url = self.client.files.get_signed_url(file_id=uploaded_pdf.id)

        # Process the PDF using OCR
        ocr_response = self.client.ocr.process(
            model="mistral-ocr-latest",
            document={"type": "document_url", "document_url": signed_url.url}
        )

        # Extract text from all pages
        all_markdown = "\n\n".join([page.markdown for page in ocr_response.pages])

        # Parse the OCR result into a structured JSON response
        chat_response = self.client.chat.parse(
            model="pixtral-12b-latest",
            messages=[
                {
                    "role": "user",
                    "content": [
                        TextChunk(text=(
                            f"This is the PDF's OCR in markdown:\n{all_markdown}\n.\n"
                            "Convert this into a structured JSON response "
                            "with the OCR contents in a sensible dictionnary."
                        ))
                    ]
                }
            ],
            response_format=Invoice,
            temperature=0
        )

        return chat_response.choices[0].message.parsed

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv("webhook/.env")
    api_client = MistralAIClient(api_token=os.getenv("MISTRAL_API_TOKEN"))
    # api_client.structured_pdf_ocr("data/Kasticket_19022025_17h09_260749292.pdf")
    from invoice_parser import InvoiceParser
    from app import parse_invoice, clean_invoice_df
    invoice_parser = InvoiceParser(api_client)
    local_file_path = "data/Kasticket_19022025_17h09_260749292.pdf"
    invoice_items_df = clean_invoice_df(
            parse_invoice(local_file_path, data_path="data")
        )
    print(invoice_items_df)

