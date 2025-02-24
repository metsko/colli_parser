import base64
import json

import openai

from models import Invoice


class ChatGPTClient:
    def __init__(self, api_token: str):
        self.client = openai.OpenAI(api_key=api_token)

    def get_response(self, image_path: str, response_format=Invoice):
        """
        Sends a prompt to the ChatGPT API and returns the response.
        """
        try:
            completion = self.client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                max_tokens=5000,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Extract the invoice info",
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{self.encode_image(image_path)}"
                                },
                            },
                        ],
                    }
                ],
                response_format=response_format,
            )
            return completion.choices[0].message.parsed
        except Exception as e:
            raise ValueError(f"Failed to get response from ChatGPT API: {e}")

    @staticmethod
    def encode_image(image_path):
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def parse_invoice_data(self, invoice_data: str) -> Invoice:
        """
        Parses the invoice data from the OpenAI API response and returns an Invoice object.
        """
        try:
            # Assuming the invoice data is a JSON string
            data = json.loads(invoice_data)
            invoice = Invoice(**data)
            return invoice
        except Exception as e:
            raise ValueError(f"Failed to parse invoice data: {e}")
