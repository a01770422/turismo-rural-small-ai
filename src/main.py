"""Ejecutar desde la raíz del proyecto:  python -m src.main"""
import os

import uvicorn
from dotenv import load_dotenv

if __name__ == "__main__":
    load_dotenv()
    # HOST=0.0.0.0 en .env: los visitantes en la misma wifi pueden abrir el chat (http://IP-de-este-equipo:8000/chat)
    uvicorn.run("src.api:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
