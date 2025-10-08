import os
import json
import logging

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# ЛОГИ
# =========================
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO
)
logger = logging.getLogger("pletushiy_konez")

# =========================
# .ENV
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN не задан в .env")

PORTAL_CHAT_ID_RAW = os.getenv("PORTAL_CHAT_ID", "").strip()
PORTAL_CHAT_ID = int(PORTAL_CHAT_ID_RAW) if PORTAL_CHAT_ID_RAW else None

OWNER_IDS = [
    int(x) for x in os.getenv("OWNER_IDS", "").replace(" ", "").split(",") if x.isdigit()
]

STATE_FILE = os.getenv("STATE_FILE", "game_state.json").strip()
INTRO_IMAGE_PATH = os.getenv("INTRO_IMAGE_PATH", "intro.jpg").strip()

# =========================
# Глобальное состояние
# =========================
games = {}  # chat_id -> state

# Параметры боя (примеры — легко менять под баланс)
BOSS_MAX_HP = 100
PLAYERS_MAX_HP = 100
BOSS_NORMAL_DAMAGE = 10
BOSS_SPECIAL_DAMAGE = 20
PLAYER_NORMAL_DAMAGE = 10
FLAME_DAMAGE = 30
LIGHTNING_DAMAGE = 15
SHIELD_GAIN = 2  # прибавка «простых» щитов

# =========================
# УТИЛИТЫ
# =========================
def is_owner(user_id: int) -> bool:
    return (not OWNER_IDS) or (user_id in OWNER_IDS)

def in_portal_chat(chat_id: int) -> bool:
    return (PORTAL_CHAT_ID is None) or (chat_id == PORTAL_CHAT_ID)

def init_game_state(chat_id: int):
    """Инициализировать/сбросить бой в чате."""
    games[chat_id] = {
        "active": True,
        "boss_hp": BOSS_MAX_HP,
        "boss_max_hp": BOSS_MAX_HP,
        "players_hp": PLAYERS_MAX_HP,
        "players_max_hp": PLAYERS_MAX_HP,
        "shields": 0,
        "players_attack_count": 0,
        "special_charges": 0,
        "boss_actions_count": 0,
        "boss_skip": False,
        "damage_by_user": {},
        "user_names": {},
    }

def load_state_from_disk():
    global games
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            games = {int(k): v for k, v in data.items()}
            logger.info("✅ Состояние боя загружено из файла.")
        except Exception as e:
            logger.error(f"Ошибка загрузки состояния: {e}")

async def save_state():
    try:
        data = {str(k): v for k, v in games.items()}
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Ошибка сохранения состояния: {e}")

# =========================
# ХЕНДЛЕРЫ КОМАНД
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Старт/перезапуск боя. Разрешено только в портальном чате; при желании — только для владельцев."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not in_portal_chat(chat_id):
        await update.message.reply_text("Эта команда доступна только в чате портала.")
        return

    # Если хочешь ограничить запуск только для админов — раскомментируй:
    # if not is_owner(user_id):
    #     await update.message.reply_text("Только админы могут запускать бой.")
    #     return

    init_game_state(chat_id)
    await save_state()

    intro_text = (
        "🕷️ В пещере появляется гигантский Паук по имени *Плетущий Конец*!\n"
        "Он угрожает уничтожить всё вокруг. Объединитесь, чтобы сразить его!\n\n"
        "⚔️ Команды:\n"
        "💥 /attack – обычная атака\n"
        "🔥 /flame – огненная атака (спец)\n"
        "⚡ /lightning – атака молнией (спец)\n"
        "🛡 /shield – защитный щит (спец)\n\n"
        "ℹ️ Накопите 3 обычных атаки командой, чтобы открыть спец-атаку.\n"
        "У команды общие здоровье и щиты. Удачи!"
    )

    if os.path.exists(INTRO_IMAGE_PATH):
        try:
            with open(INTRO_IMAGE_PATH, "rb") as img:
                await update.message.reply_photo(
                    photo=img, caption=intro_text, parse_mode=ParseMode.MARKDOWN
                )
        except Exception as e:
            logger.warning(f"Не удалось отправить картинку интро: {e}")
            await update.message.reply_text(intro_text, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(intro_text, parse_mode=ParseMode.MARKDOWN)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = games.get(chat_id)
    if not state or not state.get("active"):
        await update.message.reply_text("Сейчас нет активного боя. Введите /start, чтобы начать битву.")
        return
    lines = [
        f"❤️ HP Паук: {state['boss_hp']}/{state['boss_max_hp']}",
        f"❤️ HP Команда: {state['players_hp']}/{state['players_max_hp']}",
        f"🛡 Щиты: {state['shields']}",
    ]
    if state["special_charges"] > 0:
        lines.append(f"✨ Спец-атак готово: {state['special_charges']}")
    else:
        lines.append(f"⚔️ Энергия для спец-атаки: {state['players_attack_count']}/3")
    await update.message.reply_text("\n".join(lines))

# ==========
# Игрок: обычная атака
# ==========
async def handle_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = games.get(chat_id)
    if not state or not state.get("active"):
        await update.message.reply_text("Битва ещё не началась. Введите /start, чтобы вызвать босса!")
        return

    user = update.effective_user
    user_name = user.first_name or "Игрок"

    # Урон боссу
    damage = PLAYER_NORMAL_DAMAGE
    state["boss_hp"] = max(0, state["boss_hp"] - damage)

    # Учёт урона
    state["damage_by_user"][user.id] = state["damage_by_user"].get(user.id, 0) + damage
    state["user_names"][user.id] = user_name

    # Заряд спец-атаки
    state["players_attack_count"] += 1
    special_unlocked = False
    if state["players_attack_count"] >= 3:
        state["players_attack_count"] -= 3
        state["special_charges"] += 1
        special_unlocked = True

    text_lines = [f"💥 *{user_name}* атакует Паука, нанося {damage} урона."]

    # Победа?
    if state["boss_hp"] <= 0:
        await announce_victory(update, state, text_lines)
        await save_state()
        return

    if special_unlocked:
        text_lines.append("✨ Спец-энергия накоплена! Доступны /flame, /lightning или /shield.")

    # Ход босса
    await boss_turn(state, text_lines)

    # Проигрыш?
    if state["players_hp"] <= 0:
        state["players_hp"] = 0
        state["active"] = False
        text_lines.append("❌ Команда пала в бою... Паук победил. Введите /start для реванша.")
        await update.message.reply_text("\n".join(text_lines), parse_mode=ParseMode.MARKDOWN)
        await save_state()
        return

    # Статус
    text_lines.append(
        f"❤️ Паук: {state['boss_hp']}/{state['boss_max_hp']} | "
        f"❤️ Команда: {state['players_hp']}/{state['players_max_hp']} | "
        f"🛡 Щиты: {state['shields']}"
    )
    await update.message.reply_text("\n".join(text_lines), parse_mode=ParseMode.MARKDOWN)
    await save_state()

# ==========
# Игрок: 🔥 Пламя
# ==========
async def handle_flame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = games.get(chat_id)
    if not state or not state.get("active"):
        await update.message.reply_text("Бой ещё не начат. Используйте /start, чтобы начать сражение.")
        return
    if state["special_charges"] <= 0:
        await update.message.reply_text("Спец-атака ещё не готова!")
        return

    user = update.effective_user
    user_name = user.first_name or "Игрок"
    state["special_charges"] -= 1

    damage = FLAME_DAMAGE
    state["boss_hp"] = max(0, state["boss_hp"] - damage)

    state["damage_by_user"][user.id] = state["damage_by_user"].get(user.id, 0) + damage
    state["user_names"][user.id] = user_name

    text_lines = [f"🔥 *{user_name}* выпускает пламя и наносит {damage} урона Пауку!"]

    if state["boss_hp"] <= 0:
        await announce_victory(update, state, text_lines)
        await save_state()
        return

    await boss_turn(state, text_lines)

    if state["players_hp"] <= 0:
        state["players_hp"] = 0
        state["active"] = False
        text_lines.append("❌ Команда пала... Паук одержал победу. Используйте /start для реванша.")
        await update.message.reply_text("\n".join(text_lines), parse_mode=ParseMode.MARKDOWN)
        await save_state()
        return

    text_lines.append(
        f"❤️ Паук: {state['boss_hp']}/{state['boss_max_hp']} | "
        f"❤️ Команда: {state['players_hp']}/{state['players_max_hp']} | "
        f"🛡 Щиты: {state['shields']}"
    )
    await update.message.reply_text("\n".join(text_lines), parse_mode=ParseMode.MARKDOWN)
    await save_state()

# ==========
# Игрок: ⚡ Молния (оглушение)
# ==========
async def handle_lightning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = games.get(chat_id)
    if not state or not state.get("active"):
        await update.message.reply_text("Бой ещё не начался. Используйте /start, чтобы начать сражение.")
        return
    if state["special_charges"] <= 0:
        await update.message.reply_text("Спец-атака ещё не готова!")
        return

    user = update.effective_user
    user_name = user.first_name or "Игрок"
    state["special_charges"] -= 1

    damage = LIGHTNING_DAMAGE
    state["boss_hp"] = max(0, state["boss_hp"] - damage)

    state["damage_by_user"][user.id] = state["damage_by_user"].get(user.id, 0) + damage
    state["user_names"][user.id] = user_name

    # оглушение на один ход
    state["boss_skip"] = True

    text_lines = [f"⚡ *{user_name}* поражает молнией: {damage} урона и оглушение!"]

    if state["boss_hp"] <= 0:
        await announce_victory(update, state, text_lines)
        await save_state()
        return

    text_lines.append("😵 Паук оглушен и пропускает свой ход!")
    text_lines.append(
        f"❤️ Паук: {state['boss_hp']}/{state['boss_max_hp']} | "
        f"❤️ Команда: {state['players_hp']}/{state['players_max_hp']} | "
        f"🛡 Щиты: {state['shields']}"
    )
    await update.message.reply_text("\n".join(text_lines), parse_mode=ParseMode.MARKDOWN)
    await save_state()

# ==========
# Игрок: 🛡 Щит (накапливаем простые щиты)
# ==========
async def handle_shield(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = games.get(chat_id)
    if not state or not state.get("active"):
        await update.message.reply_text("Бой ещё не начался. Введите /start для начала.")
        return
    if state["special_charges"] <= 0:
        await update.message.reply_text("Спец-атака ещё не готова!")
        return

    user = update.effective_user
    user_name = user.first_name or "Игрок"
    state["special_charges"] -= 1

    state["shields"] += SHIELD_GAIN
    text_lines = [f"🛡 *{user_name}* призывает щит! Щиты +{SHIELD_GAIN} (итого: {state['shields']})."]

    await boss_turn(state, text_lines)

    if state["players_hp"] <= 0:
        state["players_hp"] = 0
        state["active"] = False
        text_lines.append("❌ Команда пала... Паук одержал победу. Введите /start, чтобы попробовать снова.")
        await update.message.reply_text("\n".join(text_lines), parse_mode=ParseMode.MARKDOWN)
        await save_state()
        return

    text_lines.append(
        f"❤️ Паук: {state['boss_hp']}/{state['boss_max_hp']} | "
        f"❤️ Команда: {state['players_hp']}/{state['players_max_hp']} | "
        f"🛡 Щиты: {state['shields']}"
    )
    await update.message.reply_text("\n".join(text_lines), parse_mode=ParseMode.MARKDOWN)
    await save_state()

# =========================
# ВСПОМОГАТЕЛЬНЫЕ ДЕЙСТВИЯ
# =========================
async def announce_victory(update: Update, state: dict, text_lines: list[str]):
    """Сообщить о победе, MVP и завершить бой."""
    text_lines[-1] += " Паук повержен!"
    state["active"] = False

    if state["damage_by_user"]:
        mvp_id = max(state["damage_by_user"], key=lambda uid: state["damage_by_user"][uid])
        mvp_damage = state["damage_by_user"][mvp_id]
        mvp_name = state["user_names"].get(mvp_id, "Игрок")
    else:
        mvp_id = None
        mvp_damage = 0
        mvp_name = ""

    reward_text = "🎃 +50, 🍬 +25"
    text_lines.append(f"🏆 *Победа!* Награда: {reward_text}.")
    if mvp_id:
        text_lines.append(f"⭐ Больше всего урона нанёс *{mvp_name}* — {mvp_damage}.")

    await update.message.reply_text("\n".join(text_lines), parse_mode=ParseMode.MARKDOWN)

async def boss_turn(state: dict, text_lines: list[str]):
    """Ход босса: обычная/спец атака, влияние щитов/оглушения."""
    if state.get("boss_skip"):
        text_lines.append("😵 Паук оглушен и пропускает свою атаку!")
        state["boss_skip"] = False
        return

    state["boss_actions_count"] += 1
    if state["boss_actions_count"] % 4 == 0:
        # спец-атака босса
        damage_to_players = BOSS_SPECIAL_DAMAGE
        desc = "🕷️ Паук применяет *ядовитый укус*!"
        if state["shields"] > 0:
            damage_to_players //= 2
            desc += " Щиты частично поглощают урон, но рассыпались!"
            state["shields"] = 0
        else:
            desc += f" Команда получает {damage_to_players} урона."
        state["players_hp"] = max(0, state["players_hp"] - damage_to_players)
        text_lines.append(desc)
    else:
        # обычная атака босса
        damage_to_players = BOSS_NORMAL_DAMAGE
        desc = "🕷️ Паук атакует команду."
        if state["shields"] > 0:
            state["shields"] -= 1
            desc += " Щит блокирует удар!"
            if state["shields"] > 0:
                desc += f" (Щитов осталось: {state['shields']})"
            else:
                desc += " (Щитов больше нет)"
            damage_to_players = 0
        else:
            desc += f" Команда получает {damage_to_players} урона."
        if damage_to_players > 0:
            state["players_hp"] = max(0, state["players_hp"] - damage_to_players)
        text_lines.append(desc)

# =========================
# MAIN
# =========================
def main():
    load_state_from_disk()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("attack", handle_attack))
    app.add_handler(CommandHandler("flame", handle_flame))
    app.add_handler(CommandHandler("lightning", handle_lightning))
    app.add_handler(CommandHandler("shield", handle_shield))

    # Эмодзи-триггеры
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^💥$"), handle_attack))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^🔥$"), handle_flame))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^⚡$"), handle_lightning))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^🛡$"), handle_shield))

    logger.info("🤖 Бот запущен. Готов к рейду!")
    app.run_polling()

if __name__ == "__main__":
    main()
