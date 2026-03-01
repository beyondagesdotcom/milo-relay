# Milo API Relay

Forwards API requests from the Mac mini through a clean cloud IP.

## Deploy to Render.com

1. Push this repo to GitHub
2. Go to render.com → New → Web Service
3. Connect your GitHub repo
4. Use free tier
5. Deploy

## Usage

POST /proxy
Authorization: Bearer RELAY_TOKEN_MK2026
{"url": "https://...", "method": "GET", "headers": {...}, "body": {...}}
