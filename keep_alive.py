import os
from flask import Flask
from threading import Thread

app = Flask("")


@app.route("/")
def home():
    return "Le bot Site-42 est en ligne."


def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    """Lance le serveur web dans un thread séparé, en parallèle du bot Discord."""
    t = Thread(target=run)
    t.start()
