import threading
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Optional
import requests
from dataclasses import dataclass
import logging
from ton_address_converter import batch_convert_to_friendly
from datetime import datetime
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import os

app = FastAPI()

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def read_index():
    return FileResponse(os.path.join("static", "index.html"))

# Логирование
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Конфигурация
API_BASE_URL = "https://tonapi.io/v2/blockchain"
ADDRESS = "0:532305126dcb5cd0863f164c0a3f135b926f5e7106e9e487ab93cd798c300c6a"
TARGET_SOURCE = "0:8b0fb7cc97e577e010946bcd0a5a7d20d866b7a8826ebb65ae5f327edbb82b27"
START_TIMESTAMP = 1749646340
SPECIAL_SENDER = "0:c9959a997e1d4e4383d8db37b86d2101ce78dcf1f1b3904d9888fe572ef0efd4"

headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "X-Tonapi-Client": "tonapi.io"
}


# Модели данных
class WoofTransferResponse(BaseModel):
    sender: str
    amount: float
    timestamp: int
    tx_hash: str
    comment: str

class SummaryResponse(BaseModel):
    ticket_transfers: List[WoofTransferResponse]
    hodl_addresses: List[str]
    hodl_tickets: Dict[str, int]
    total_tickets: float
    total_hodl_tickets: int

@dataclass
class WoofTransfer:
    sender: str
    amount: float
    timestamp: int
    tx_hash: str
    comment: str


CACHE = {
    "summary": None,
    "timestamp": None
}

REFRESH_INTERVAL_SECONDS = 300  # 5 минут

def refresh_cache():
    global CACHE

    print("🔁 Обновляем кэш...")
    try:
        txs = fetch_transactions(ADDRESS)
        ticket_transfers, hodl_addresses = extract_woof_transfers(txs)
        hodl_tickets = check_hodl_addresses_tickets_v2(hodl_addresses)

        total_tickets = sum(t.amount for t in ticket_transfers)
        total_hodl_tickets = sum(hodl_tickets.values())

        response = SummaryResponse(
            ticket_transfers=[
                WoofTransferResponse(
                    sender=t.sender,
                    amount=t.amount,
                    timestamp=t.timestamp,
                    tx_hash=t.tx_hash,
                    comment=t.comment
                ) for t in ticket_transfers
            ],
            hodl_addresses=list(hodl_addresses),
            hodl_tickets=hodl_tickets,
            total_tickets=total_tickets,
            total_hodl_tickets=total_hodl_tickets
        )

        CACHE["summary"] = response
        CACHE["timestamp"] = datetime.utcnow()
        print(f"✅ Кэш обновлён: {CACHE['timestamp']}")

    except Exception as e:
        print(f"❌ Ошибка при обновлении кэша: {e}")

    # Планируем следующее обновление
    threading.Timer(REFRESH_INTERVAL_SECONDS, refresh_cache).start()


@app.on_event("startup")
def startup_event():
    print("🚀 Запуск FastAPI + планировщик кэша")
    refresh_cache()  # запускаем первое обновление сразу


@app.get("/api/summary", response_model=SummaryResponse)
async def get_summary():
    if not CACHE["summary"]:
        raise HTTPException(status_code=503, detail="Данные ещё не готовы. Попробуйте позже.")
    return CACHE["summary"]


# Вспомогательные функции (остаются без изменений)
def fetch_transactions(address):
    url = f"{API_BASE_URL}/accounts/{address}/transactions"
    params = {"limit": 100}
    all_transactions = []

    while True:
        try:
            logging.info(f"Requesting transactions for: {address}")
            res = requests.get(url, params=params, headers=headers, timeout=30)

            if res.status_code != 200:
                logging.error(f"API error {res.status_code}: {res.text}")
                break

            data = res.json().get("transactions", [])
            if not data:
                logging.info("No transactions received.")
                break

            all_transactions += [tx for tx in data if tx.get("utime", 0) >= START_TIMESTAMP]
            logging.info(f"Fetched total: {len(all_transactions)}")

            if any(tx.get("utime", 0) < START_TIMESTAMP for tx in data):
                break

            params["before_lt"] = data[-1]["lt"]
        except Exception as e:
            logging.error(f"Fetch error: {e}")
            break

    return all_transactions

def extract_woof_transfers(transactions):
    ticket_transfers = []
    hodl_addresses = set()

    for tx in transactions:
        if not tx.get("in_msg"):
            continue

        in_msg = tx["in_msg"]
        source_addr = in_msg.get("source", {}).get("address", "")
        decoded = in_msg.get("decoded_body", {})
        sender = decoded.get("sender", None)

        if not sender or source_addr != TARGET_SOURCE:
            continue

        comment = decoded.get("forward_payload", {}).get("value", {}).get("value", {}).get("text", "")
        amount = int(decoded.get("amount", "0"))
        amount_woof = amount / 1e9

        try:
            friendly_sender = batch_convert_to_friendly([sender], bounceable=True)[0]
        except Exception as e:
            logging.warning(f"Ошибка конвертации адреса {sender}: {e}")
            continue

        if comment.strip().lower() == "hodl":
            hodl_addresses.add(friendly_sender)

        if amount_woof < 10000:
            continue

        ticket_transfers.append(WoofTransfer(
            sender=friendly_sender,
            amount=amount_woof // 10000,
            timestamp=tx["utime"],
            tx_hash=tx["hash"],
            comment=comment
        ))

    return ticket_transfers, hodl_addresses

def check_hodl_addresses_tickets_v2(hodl_addresses):
    BITGET_ADDRESS = "0:c9959a997e1d4e4383d8db37b86d2101ce78dcf1f1b3904d9888fe572ef0efd4"
    WOOF_SYMBOL = "WOOF"
    QUEST_CONTRACT = "0:72d403954b90270af65f49cd0a133695c2052d23a243c099ea20e91b905a5cfc"
    EARN = "0:dc20ce5b35de0ee6c8aa41d28c3ee29df2baa56bb7202374a43d8b1d45bf8cbf"

    result = {}

    for addr in hodl_addresses:
        url = f"https://tonapi.io/v2/accounts/{addr}/events"
        params = {"limit": 100, "initiator": "false"}
        all_events = []

        while True:
            try:
                retry_delay = 5  # секунд
                max_retries = 5
                retries = 0

                while retries < max_retries:
                    try:
                        res = requests.get(url, headers=headers, params=params)
                        if res.status_code == 429:
                            logging.warning(f"429 Too Many Requests for {addr}. Retrying in {retry_delay}s...")
                            time.sleep(retry_delay)
                            retries += 1
                            continue
                        res.raise_for_status()
                        break
                    except Exception as e:
                        logging.error(f"Ошибка при запросе событий для {addr}: {e}")
                        time.sleep(retry_delay)
                        retries += 1
                else:
                    logging.error(f"Превышено количество попыток запроса для адреса {addr}")
                    break

                data = res.json()
                events = data.get("events", [])

                if not events:
                    break

                events_before_period = [e for e in events if e.get("timestamp", 0) < START_TIMESTAMP]
                all_events += [e for e in events if e.get("timestamp", 0) >= START_TIMESTAMP]

                if events_before_period or len(events) < params["limit"]:
                    break

                params["before_lt"] = events[-1]["lt"]

            except Exception as e:
                logging.error(f"Ошибка при проверке адреса {addr}: {e}")
                break

        tickets = 0

        for event in all_events:
            if event.get("timestamp", 0) < START_TIMESTAMP:
                continue
            for action in event.get("actions", []):
                t = action.get("type")

                if t == "JettonTransfer":
                    jt = action.get("JettonTransfer", {})
                    if (
                            jt.get("sender", {}).get("address") == BITGET_ADDRESS and
                            jt.get("jetton", {}).get("symbol", "").upper() == WOOF_SYMBOL
                    ):
                        amount = int(jt.get("amount", "0"))
                        tickets += amount // 50000000000000

                    if (
                            jt.get("sender", {}).get("address") == EARN and
                            jt.get("jetton", {}).get("symbol", "").upper() == WOOF_SYMBOL
                    ):
                        amount = int(jt.get("amount", "0"))
                        tickets += amount // 50000000000000
                        print(amount // 10**9)

                    if (
                            jt.get("sender", {}).get("address") == QUEST_CONTRACT
                    ):
                        tickets += 1

        if tickets > 0:
            result[addr] = tickets

    return result