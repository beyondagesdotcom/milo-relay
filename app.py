from flask import Flask, request, jsonify
import requests

app = Flask(__name__)
RELAY_TOKEN = "RELAY_TOKEN_MK2026"

@app.route("/proxy", methods=["POST"])
def proxy():
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {RELAY_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    url = data.get("url")
    method = data.get("method", "GET").upper()
    headers = data.get("headers", {})
    body = data.get("body", None)

    try:
        resp = requests.request(method, url, headers=headers, json=body, timeout=30)
        try:
            resp_body = resp.json()
        except:
            resp_body = resp.text
        return jsonify({"status": resp.status_code, "body": resp_body})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
