#!/usr/bin/env python3
"""
CryptoGamma ETH Signal Bot
----------------------------------
Раз в N минут (запускается через GitHub Actions cron) скрипт:
  1. Запрашивает JSON-снапшот с https://cryptogamma.io/api/public/snapshot?asset=ETH
  2. Сравнивает текущую цену ETH с уровнями support / resistance / breakout
  3. Если цена близко к уровню (или пробила его) — формирует сигнал
  4. Проверяет state.json, чтобы не слать один и тот же сигнал повторно
  5. Отправляет сообщение в Telegram через Bot API

ВАЖНО: squeeze levels на CryptoGamma — это уровни концентрации опционного
open interest (где дилеры будут хеджироваться), а не классические уровни
технического анализа и не прогноз направления цены. Это не финансовый совет.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

API_URL = "https://cryptogamma.io/api/public/snapshot?asset=ETH"
ASSET = "ETH"

# Насколько близко цена должна быть к support/resistance, чтобы считать
# это "касанием уровня". 0.002 = 0.2%.
PROXIMITY_THRESHOLD = 0.002

# Файл, в котором хранится тип последнего отправленного сигнала,
# чтобы не дублировать сообщения, пока цена держится у того же уровня.
STATE_FILE = Path(__file__).parent.parent / "state.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# ---------------------------------------------------------------------------
# Получение данных
# ---------------------------------------------------------------------------

def fetch_snapshot(url: str) -> dict:
    """Запрашивает JSON-снапшот с CryptoGamma. Бросает исключение при ошибке."""
    req = urllib.request.Request(url, headers={"User-Agent": "cryptogamma-eth-bot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
    except urllib.error.URLError as e:
        raise RuntimeError(f"Не удалось получить данные с {url}: {e}") from e

    data = json.loads(raw)

    # Сервер CryptoGamma иногда отдаёт BTC, даже если параметр ?asset=ETH
    # указан (наблюдалось эмпирически). Поэтому всегда проверяем поле
    # "asset" в ответе, а не доверяем своему собственному query-параметру.
    if data.get("asset") != ASSET:
        raise RuntimeError(
            f"Ожидался asset={ASSET}, но API вернул asset={data.get('asset')!r}. "
            "Пропускаем этот цикл, чтобы не отправить сигнал по неверному активу."
        )

    return data


# ---------------------------------------------------------------------------
# Логика сигнала
# ---------------------------------------------------------------------------

def evaluate_signal(snapshot: dict) -> dict | None:
    """
    Возвращает dict с описанием сигнала, если цена около/за уровнем,
    иначе None.

    Приоритет проверки: breakout > resistance > support.
    Если цена уже выше breakout, это важнее, чем простое касание resistance.
    """
    levels = snapshot["squeezeLevels"]
    price = levels["currentPrice"]
    support = levels["support"]
    resistance = levels["resistance"]
    breakout = levels["breakout"]

    # Пробой breakout — цена выше уровня прорыва
    if price >= breakout:
        return {
            "type": "breakout",
            "direction": "LONG",
            "level": breakout,
            "price": price,
            "message": (
                f"🚀 Пробой breakout-уровня\n"
                f"Цена ETH ${price:,.2f} превысила уровень прорыва ${breakout:,.2f}.\n"
                f"Гамма-экспозиция тонкая выше этой зоны — потенциальное ускорение движения вверх."
            ),
        }

    # Касание resistance (цена подошла к сопротивлению снизу или сверху)
    if abs(price - resistance) / resistance <= PROXIMITY_THRESHOLD:
        return {
            "type": "resistance",
            "direction": "SHORT / наблюдение",
            "level": resistance,
            "price": price,
            "message": (
                f"⚠️ Цена у уровня сопротивления\n"
                f"ETH ${price:,.2f} рядом с resistance ${resistance:,.2f}.\n"
                f"Здесь дилеры хеджируют шорт-коллы — возможно давление продавцов."
            ),
        }

    # Касание support (цена подошла к поддержке)
    if abs(price - support) / support <= PROXIMITY_THRESHOLD:
        return {
            "type": "support",
            "direction": "LONG / наблюдение",
            "level": support,
            "price": price,
            "message": (
                f"🟢 Цена у уровня поддержки\n"
                f"ETH ${price:,.2f} рядом с support ${support:,.2f}.\n"
                f"Здесь дилеры хеджируют лонг-путы — возможна покупательная активность."
            ),
        }

    return None


# ---------------------------------------------------------------------------
# Анти-спам state
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            # Повреждённый файл — не валим скрипт, просто начинаем с чистого состояния
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def should_send(signal: dict, state: dict) -> bool:
    """
    Не отправляем повторно тот же тип сигнала на том же уровне.
    Если уровень изменился (например, support пересчитался дашбордом)
    или сигнал другого типа — отправляем снова.
    """
    last = state.get("last_signal")
    if last is None:
        return True
    return not (last.get("type") == signal["type"] and last.get("level") == signal["level"])


# ---------------------------------------------------------------------------
# Отправка в Telegram
# ---------------------------------------------------------------------------

def send_telegram_message(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram API вернул ошибку {e.code}: {error_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Не удалось связаться с Telegram API: {e}") from e

    result = json.loads(body)
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API ответил ok=false: {result}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(
            "ОШИБКА: переменные окружения TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID не заданы. "
            "Они должны быть добавлены как GitHub Actions secrets.",
            file=sys.stderr,
        )
        return 1

    try:
        snapshot = fetch_snapshot(API_URL)
    except RuntimeError as e:
        print(f"ОШИБКА при получении данных: {e}", file=sys.stderr)
        return 1

    signal = evaluate_signal(snapshot)

    if signal is None:
        price = snapshot["squeezeLevels"]["currentPrice"]
        print(f"Нет сигнала. Текущая цена ETH: ${price:,.2f}. Цикл завершён без отправки.")
        return 0

    state = load_state()

    if not should_send(signal, state):
        print(f"Сигнал типа '{signal['type']}' на уровне {signal['level']} уже был отправлен ранее. Пропускаем.")
        return 0

    full_message = (
        f"<b>ETH Signal — CryptoGamma</b>\n\n"
        f"{signal['message']}\n\n"
        f"Направление: {signal['direction']}\n"
        f"Net Gamma: {snapshot['metrics']['netGamma']:,.0f} ({snapshot['metrics']['bias']})\n"
        f"P/C Ratio: {snapshot['metrics']['putCallRatio']}\n\n"
        f"<i>Это аналитический сигнал на основе опционной гамма-экспозиции, "
        f"а не финансовая рекомендация. Уровни могут не сработать.</i>"
    )

    try:
        send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, full_message)
    except RuntimeError as e:
        print(f"ОШИБКА при отправке в Telegram: {e}", file=sys.stderr)
        return 1

    state["last_signal"] = {"type": signal["type"], "level": signal["level"]}
    save_state(state)

    print(f"Сигнал отправлен: {signal['type']} на уровне {signal['level']} (цена {signal['price']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
