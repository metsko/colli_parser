# Telegram Bot Webhook Setup

This guide explains how to set up a webhook for your Telegram bot to handle PDF files and process them using a Flask application.

## Prerequisites

- Python 3.6 or higher
- `pip` package manager
- `ngrok` for exposing your local server to the internet
- Telegram bot token from BotFather
- API token for securing the endpoint

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/colli_parser.git
   cd colli_parser
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**:
   Create a `.env` file in the project root with:
   ```
   TELEGRAM_TOKEN=your_telegram_bot_token
   API_TOKEN=your_api_token
   CHATGPT_API_TOKEN=your_chatgpt_api_token
   ```

## Running the Application

1. **Start ngrok**:
   ```bash
   ngrok http 5000
   ```
   Copy the HTTPS URL provided by ngrok (e.g., `https://xxxx-xx-xx-xxx-xx.ngrok.io`)

2. **Set up the webhook**:
   Replace `YOUR_NGROK_URL` and `YOUR_API_TOKEN` with your values:
   ```bash
   source .env && curl -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/setWebhook"    -H "Content-Ty
   pe: application/json"    -d '{"url": "'${NGROK_URL}'/webhook", "secret_token": "'${API_TOKEN}'"}'
   ```

3. **Start the Flask application**:
   ```bash
   python app.py
   ```

## Usage

1. Start a chat with your Telegram bot
2. Send a PDF invoice file to the bot
3. The bot will process the invoice and return extracted information

## Security Notes

- Keep your `.env` file secure and never commit it to version control
- Regularly rotate your API tokens
- The webhook endpoint is protected with the API token

## Project Structure

```
colli_parser/
├── app.py              # Main Flask application
├── api_client.py       # ChatGPT API client
├── invoice_parser.py   # PDF parsing logic
├── utils.py           # Utility functions
├── config.py          # Configuration
├── data/              # PDF storage
└── .env               # Environment variables
```