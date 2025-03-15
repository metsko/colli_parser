import base64
from pathlib import Path

from mistralai import Mistral
from mistralai import ImageURLChunk, TextChunk

from models import Invoice


class MistralAIClient:
    def __init__(self, api_token: str):
        self.client = Mistral(api_key=api_token)

    def get_response(self, image_path: str, response_format=Invoice):
        """
        Sends an image to the Mistral AI OCR API and returns structured data.
        """
        try:
            return self.structured_ocr(image_path)
        except Exception as e:
            raise ValueError(f"Failed to get response from Mistral AI API: {e}")

    def structured_ocr(self, image_path: str) -> Invoice:
        """
        Process an image using OCR and extract structured data.

        Args:
            image_path: Path to the image file to process

        Returns:
            Invoice object containing the extracted data

        Raises:
            AssertionError: If the image file does not exist
        """
        # Validate input file
        image_file = Path(image_path)
        assert image_file.is_file(), "The provided image path does not exist."

        # Read and encode the image file
        encoded_image = base64.b64encode(image_file.read_bytes()).decode()
        base64_data_url = f"data:image/jpeg;base64,{encoded_image}"

        # Process the image using OCR
        image_response = self.client.ocr.process(
            document=ImageURLChunk(image_url=base64_data_url),
            model="mistral-ocr-latest"
        )
        image_ocr_markdown = image_response.pages[0].markdown

        # Parse the OCR result into a structured JSON response
        chat_response = self.client.chat.parse(
            model="pixtral-12b-latest",
            messages=[
                {
                    "role": "user",
                    "content": [
                        ImageURLChunk(image_url=base64_data_url),
                        TextChunk(text=(
                            f"This is the image's OCR in markdown:\n{image_ocr_markdown}\n.\n"
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

