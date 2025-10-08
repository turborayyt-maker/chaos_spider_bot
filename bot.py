import os
import json
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global state
games = {}
STATE_FILE = "game_state.json"

# Game parameters
BOSS_MAX_HP = 100
PLAYERS_MAX_HP = 100
BOSS_NORMAL_DAMAGE = 10
BOSS_SPECIAL_DAMAGE = 20
PLAYER_NORMAL_DAMAGE = 10
FLAME_DAMAGE = 30
LIGHTNING_DAMAGE = 15
SHIELD_GAIN = 2

# Load state from file if exists
if os.path.exists(STATE_FILE):
    try:
        with open(STATE_FILE, 'r') as f:
            data = json.load(f)
            games = {int(k): v for k, v in data.items()}
            logger.info("Loaded game state from file.")
    except Exception as e:
        logger.error(f"Error loading state: {e}")

async def save_state():
    """Save games state to JSON file."""
    try:
        data = {str(k): v for k, v in games.items()}
        with open(STATE_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Error saving state: {e}")

def init_game_state(chat_id: int):
    """Initialize game state for a new battle in the chat."""
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
        "user_names": {}
    }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command: start a new boss fight."""
    chat_id = update.effective_chat.id
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
    # Send intro with image if available
    intro_image_path = "intro.jpg"
    if os.path.exists(intro_image_path):
        try:
            with open(intro_image_path, 'rb') as img:
                await update.message.reply_photo(photo=img, caption=intro_text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send intro image: {e}")
            await update.message.reply_text(intro_text, parse_mode="Markdown")
    else:
        await update.message.reply_text(intro_text, parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command: show current HP and shields."""
    chat_id = update.effective_chat.id
    state = games.get(chat_id)
    if not state or not state.get("active"):
        await update.message.reply_text("Сейчас нет активного боя. Введите /start, чтобы начать новую битву.")
        return
    boss_hp = state["boss_hp"]
    players_hp = state["players_hp"]
    shields = state["shields"]
    lines = [
        f"❤️ HP Паук: {boss_hp}/{state['boss_max_hp']}",
        f"❤️ HP Команда: {players_hp}/{state['players_max_hp']}",
        f"🛡 Щиты: {shields}"
    ]
    if state["special_charges"] > 0:
        if state["special_charges"] == 1:
            lines.append("✨ Спец-атака готова!")
        else:
            lines.append(f"✨ Спец-атак готово: {state['special_charges']}")
    else:
        count = state["players_attack_count"]
        lines.append(f"⚔️ Энергия для спец-атаки: {count}/3")
    await update.message.reply_text("\n".join(lines))

async def handle_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle a normal attack action (💥 or /attack)."""
    chat_id = update.effective_chat.id
    state = games.get(chat_id)
    if not state or not state.get("active"):
        await update.message.reply_text("Битва ещё не началась. Введите /start, чтобы вызвать босса!")
        return
    user = update.effective_user
    user_name = user.first_name or "Игрок"
    # Player uses normal attack
    damage = PLAYER_NORMAL_DAMAGE
    state["boss_hp"] -= damage
    if state["boss_hp"] < 0:
        state["boss_hp"] = 0
    # Track damage by user
    state["damage_by_user"][user.id] = state["damage_by_user"].get(user.id, 0) + damage
    state["user_names"][user.id] = user_name
    # Increase special meter
    state["players_attack_count"] += 1
    special_unlocked = False
    if state["players_attack_count"] >= 3:
        state["players_attack_count"] -= 3
        state["special_charges"] += 1
        special_unlocked = True
    # Prepare result message for this action
    text_lines = []
    text_lines.append(f"💥 *{user_name}* атакует Паука, нанося {damage} урона.")
    # Check boss defeat
    if state["boss_hp"] <= 0:
        text_lines[-1] += " Паук повержен!"
        # Boss defeated, prepare end of fight summary
        state["active"] = False
        # Determine top damage dealer
        if state["damage_by_user"]:
            mvp_id = max(state["damage_by_user"], key=lambda uid: state["damage_by_user"][uid])
            mvp_damage = state["damage_by_user"][mvp_id]
            mvp_name = state["user_names"].get(mvp_id, "Игрок")
        else:
            mvp_id = None
            mvp_damage = 0
            mvp_name = ""
        # Reward text (could be customized or randomized)
        reward_text = "100 золотых монет и 50 XP"
        text_lines.append(f"🏆 *Победа!* Паук {chr(0x1F577)} повержен. Награда: {reward_text}.")
        if mvp_id:
            text_lines.append(f"⭐ Больше всего урона нанёс *{mvp_name}* — {mvp_damage}.")
        # Send the messages
        await update.message.reply_text("\n".join(text_lines), parse_mode="Markdown")
        await save_state()
        return
    # Boss still alive, possibly announce special unlocked
    if special_unlocked:
        text_lines.append("✨ Энергия для спец-атаки накоплена! Теперь доступны команды /flame, /lightning или /shield.")
    # Boss's turn to attack (if not stunned by a prior lightning)
    if state.get("boss_skip"):
        # Boss skips this turn
        text_lines.append("😵 Паук оглушен и пропускает свою атаку!")
        state["boss_skip"] = False
    else:
        # Determine boss attack type (special or normal)
        state["boss_actions_count"] += 1
        if state["boss_actions_count"] % 4 == 0:
            # Boss uses special attack
            damage_to_players = BOSS_SPECIAL_DAMAGE
            boss_action_desc = "🕷️ Паук применяет *ядовитый укус*!"
            if state["shields"] > 0:
                # Shields absorb half damage but are destroyed
                damage_to_players = BOSS_SPECIAL_DAMAGE // 2
                boss_action_desc += " Щиты частично поглощают урон, но все щиты уничтожены!"
                state["shields"] = 0
            else:
                boss_action_desc += f" Команда получает {damage_to_players} урона."
            state["players_hp"] -= damage_to_players
            if state["players_hp"] < 0:
                state["players_hp"] = 0
            text_lines.append(boss_action_desc)
        else:
            # Boss uses normal attack
            damage_to_players = BOSS_NORMAL_DAMAGE
            boss_action_desc = "🕷️ Паук атакует команду."
            if state["shields"] > 0:
                state["shields"] -= 1
                if state["shields"] < 0:
                    state["shields"] = 0
                boss_action_desc += " Щит блокирует удар!"
                if state["shields"] > 0:
                    boss_action_desc += f" (Щитов осталось: {state['shields']})"
                else:
                    boss_action_desc += " (Щитов больше нет)"
                damage_to_players = 0
            else:
                boss_action_desc += f" Команда получает {damage_to_players} урона."
            if damage_to_players > 0:
                state["players_hp"] -= damage_to_players
                if state["players_hp"] < 0:
                    state["players_hp"] = 0
            text_lines.append(boss_action_desc)
    # Check defeat of players
    if state["players_hp"] <= 0:
        state["players_hp"] = 0
        state["active"] = False
        text_lines.append("❌ Команда пала в бою... Паук победил. Введите /start, чтобы попробовать снова.")
        await update.message.reply_text("\n".join(text_lines), parse_mode="Markdown")
        await save_state()
        return
    # If battle continues, append current HP status
    text_lines.append(f"❤️ HP Паук: {state['boss_hp']}/{state['boss_max_hp']} | ❤️ HP Команда: {state['players_hp']}/{state['players_max_hp']} | 🛡 Щиты: {state['shields']}")
    # Send the message
    await update.message.reply_text("\n".join(text_lines), parse_mode="Markdown")
    # Save state to file
    await save_state()

async def handle_flame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle flame special attack (🔥 or /flame)."""
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
    # Use a special charge
    state["special_charges"] -= 1
    # Player uses flame attack
    damage = FLAME_DAMAGE
    state["boss_hp"] -= damage
    if state["boss_hp"] < 0:
        state["boss_hp"] = 0
    # Track damage
    state["damage_by_user"][user.id] = state["damage_by_user"].get(user.id, 0) + damage
    state["user_names"][user.id] = user_name
    # Prepare message
    text_lines = []
    text_lines.append(f"🔥 *{user_name}* выпускает столб пламени и наносит {damage} урона Пауку!")
    # Check boss defeat
    if state["boss_hp"] <= 0:
        text_lines[-1] += " Паук повержен!"
        state["active"] = False
        # Top damage dealer
        if state["damage_by_user"]:
            mvp_id = max(state["damage_by_user"], key=lambda uid: state["damage_by_user"][uid])
            mvp_damage = state["damage_by_user"][mvp_id]
            mvp_name = state["user_names"].get(mvp_id, "Игрок")
        else:
            mvp_id = None
            mvp_damage = 0
            mvp_name = ""
        reward_text = "100 золотых монет и 50 XP"
        text_lines.append(f"🏆 *Победа!* Паук повержен. Награда: {reward_text}.")
        if mvp_id:
            text_lines.append(f"⭐ Больше всего урона нанёс *{mvp_name}* — {mvp_damage}.")
        await update.message.reply_text("\n".join(text_lines), parse_mode="Markdown")
        await save_state()
        return
    # Boss is still alive. Special attack used does not skip boss turn (no stun effect here).
    # Boss attacks after player's action (flame has no stun)
    if state.get("boss_skip"):
        text_lines.append("😵 Паук оглушен и пропускает свою атаку!")
        state["boss_skip"] = False
    else:
        state["boss_actions_count"] += 1
        if state["boss_actions_count"] % 4 == 0:
            # Boss special
            damage_to_players = BOSS_SPECIAL_DAMAGE
            boss_action_desc = "🕷️ Паук применяет *ядовитый укус*!"
            if state["shields"] > 0:
                damage_to_players = BOSS_SPECIAL_DAMAGE // 2
                boss_action_desc += " Щиты частично поглощают урон, но все щиты уничтожены!"
                state["shields"] = 0
            else:
                boss_action_desc += f" Команда получает {damage_to_players} урона."
            state["players_hp"] -= damage_to_players
            if state["players_hp"] < 0:
                state["players_hp"] = 0
            text_lines.append(boss_action_desc)
        else:
            damage_to_players = BOSS_NORMAL_DAMAGE
            boss_action_desc = "🕷️ Паук атакует команду."
            if state["shields"] > 0:
                state["shields"] -= 1
                if state["shields"] < 0:
                    state["shields"] = 0
                boss_action_desc += " Щит блокирует удар!"
                if state["shields"] > 0:
                    boss_action_desc += f" (Щитов осталось: {state['shields']})"
                else:
                    boss_action_desc += " (Щитов больше нет)"
                damage_to_players = 0
            else:
                boss_action_desc += f" Команда получает {damage_to_players} урона."
            if damage_to_players > 0:
                state["players_hp"] -= damage_to_players
                if state["players_hp"] < 0:
                    state["players_hp"] = 0
            text_lines.append(boss_action_desc)
    # Check players defeat
    if state["players_hp"] <= 0:
        state["players_hp"] = 0
        state["active"] = False
        text_lines.append("❌ Команда пала в бою... Паук одержал победу. Используйте /start для реванша.")
        await update.message.reply_text("\n".join(text_lines), parse_mode="Markdown")
        await save_state()
        return
    # If battle continues, add status
    text_lines.append(f"❤️ HP Паук: {state['boss_hp']}/{state['boss_max_hp']} | ❤️ HP Команда: {state['players_hp']}/{state['players_max_hp']} | 🛡 Щиты: {state['shields']}")
    await update.message.reply_text("\n".join(text_lines), parse_mode="Markdown")
    await save_state()

async def handle_lightning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle lightning special attack (⚡ or /lightning)."""
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
    # Use special charge
    state["special_charges"] -= 1
    # Player uses lightning attack
    damage = LIGHTNING_DAMAGE
    state["boss_hp"] -= damage
    if state["boss_hp"] < 0:
        state["boss_hp"] = 0
    state["damage_by_user"][user.id] = state["damage_by_user"].get(user.id, 0) + damage
    state["user_names"][user.id] = user_name
    # Lightning stuns the boss (boss_skip set to True)
    state["boss_skip"] = True
    text_lines = []
    text_lines.append(f"⚡ *{user_name}* поражает Паука молнией, нанося {damage} урона и оглушая врага!")
    if state["boss_hp"] <= 0:
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
        reward_text = "100 золотых монет и 50 XP"
        text_lines.append(f"🏆 *Победа!* Паук повержен. Награда: {reward_text}.")
        if mvp_id:
            text_lines.append(f"⭐ Больше всего урона нанёс *{mvp_name}* — {mvp_damage}.")
        await update.message.reply_text("\n".join(text_lines), parse_mode="Markdown")
        await save_state()
        return
    # Boss is alive but stunned, so he skips attacking this turn
    text_lines.append("😵 Паук оглушен и не может атаковать в ответ!")
    # (boss_skip True means we skip boss attack this turn)
    # Note: We do not increment boss_actions_count because boss missed this action.
    # Append status
    text_lines.append(f"❤️ HP Паук: {state['boss_hp']}/{state['boss_max_hp']} | ❤️ HP Команда: {state['players_hp']}/{state['players_max_hp']} | 🛡 Щиты: {state['shields']}")
    await update.message.reply_text("\n".join(text_lines), parse_mode="Markdown")
    await save_state()

async def handle_shield(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle shield special (🛡 or /shield): increase team's shields."""
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
    # Use special charge
    state["special_charges"] -= 1
    # Increase shields
    state["shields"] += SHIELD_GAIN
    text_lines = []
    text_lines.append(f"🛡 *{user_name}* призывает магический щит! Щиты +{SHIELD_GAIN} (итого: {state['shields']}).")
    # Shield special does not deal damage, so boss not hurt.
    # Boss will attack as usual (shield does not stun).
    if state.get("boss_skip"):
        text_lines.append("😵 Паук оглушен и пропускает свою атаку!")
        state["boss_skip"] = False
    else:
        state["boss_actions_count"] += 1
        if state["boss_actions_count"] % 4 == 0:
            damage_to_players = BOSS_SPECIAL_DAMAGE
            boss_action_desc = "🕷️ Паук применяет *ядовитый укус*!"
            if state["shields"] > 0:
                damage_to_players = BOSS_SPECIAL_DAMAGE // 2
                boss_action_desc += " Щиты частично поглощают урон, но все щиты уничтожены!"
                state["shields"] = 0
            else:
                boss_action_desc += f" Команда получает {damage_to_players} урона."
            state["players_hp"] -= damage_to_players
            if state["players_hp"] < 0:
                state["players_hp"] = 0
            text_lines.append(boss_action_desc)
        else:
            damage_to_players = BOSS_NORMAL_DAMAGE
            boss_action_desc = "🕷️ Паук атакует команду."
            if state["shields"] > 0:
                state["shields"] -= 1
                if state["shields"] < 0:
                    state["shields"] = 0
                boss_action_desc += " Щит блокирует удар!"
                if state["shields"] > 0:
                    boss_action_desc += f" (Щитов осталось: {state['shields']})"
                else:
                    boss_action_desc += " (Щитов больше нет)"
                damage_to_players = 0
            else:
                boss_action_desc += f" Команда получает {damage_to_players} урона."
            if damage_to_players > 0:
                state["players_hp"] -= damage_to_players
                if state["players_hp"] < 0:
                    state["players_hp"] = 0
            text_lines.append(boss_action_desc)
    # Check players defeat
    if state["players_hp"] <= 0:
        state["players_hp"] = 0
        state["active"] = False
        text_lines.append("❌ Команда пала в бою... Паук одержал победу. Введите /start, чтобы попробовать снова.")
        await update.message.reply_text("\n".join(text_lines), parse_mode="Markdown")
        await save_state()
        return
    # Continue fight: show status
    text_lines.append(f"❤️ HP Паук: {state['boss_hp']}/{state['boss_max_hp']} | ❤️ HP Команда: {state['players_hp']}/{state['players_max_hp']} | 🛡 Щиты: {state['shields']}")
    await update.message.reply_text("\n".join(text_lines), parse_mode="Markdown")
    await save_state()

def main():
    # Retrieve bot token from environment
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set. Please set the BOT_TOKEN environment variable.")
        return
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    # Register handlers for commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("attack", handle_attack))
    application.add_handler(CommandHandler("flame", handle_flame))
    application.add_handler(CommandHandler("lightning", handle_lightning))
    application.add_handler(CommandHandler("shield", handle_shield))
    # Register handlers for emoji as messages
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^💥$'), handle_attack))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^🔥$'), handle_flame))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^⚡$'), handle_lightning))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^🛡$'), handle_shield))
    # Run the bot
    application.run_polling()

if __name__ == "__main__":
    main()

