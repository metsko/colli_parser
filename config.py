import os

class Config:
    API_TOKEN = os.environ.get("CHATGPT_API_TOKEN")  # Set your API token as an environment variable
    if not API_TOKEN:
        raise ValueError("No API token found. Please set the CHATGPT_API_TOKEN environment variable.")

config = Config()
