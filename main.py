import asyncio
import os
from dotenv import load_dotenv
# from telethon import TelegramClient # <-- Убираем из глобальной области
from telethon import TelegramClient # <-- Но импортируем всё равно
from telethon.tl.types import Message
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI # <-- Импортируем OpenAI

# Загружаем переменные окружения
load_dotenv()

# Настройки Telegram API (для бота и для пользователя telethon)
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')
phone = os.getenv('PHONE')
bot_token = os.getenv('BOT_TOKEN')

# Настройки OpenAI-совместимого API
cloud_api_key = os.getenv('CLOUD_API_KEY')
cloud_api_base_url = os.getenv('CLOUD_API_BASE_URL')
cloud_model_name = "openai/gpt-oss-120b" # Укажите модель, которую вы хотите использовать

# Проверяем, что ключ и URL загружены
if not cloud_api_key or not cloud_api_base_url:
    raise ValueError("❌ API-ключ или URL для облачной модели не найдены в .env файле.")

# Создаем клиента OpenAI с вашими настройками
client_openai = OpenAI(
    api_key=cloud_api_key,
    base_url=cloud_api_base_url
)

# --- УБРАЛИ ГЛОБАЛЬНЫЙ КЛИЕНТ ---
# client = TelegramClient('session_name', api_id, api_hash)

async def get_top_posts(channel_username, limit=50):
    """Получает топ-10 постов по реакциям из канала"""
    client_temp = None
    try:
        # Создаем временный клиент для каждого запроса
        client_temp = TelegramClient('temp_session', api_id, api_hash)
        await client_temp.start(phone)

        posts = []
        print(f"Получаем посты из канала: {channel_username}")

        # Получаем посты
        async for message in client_temp.iter_messages(channel_username, limit=limit):
            if isinstance(message, Message) and message.text:
                # Считаем реакции
                total_reacts = 0
                if message.reactions:
                    total_reacts = sum(r.count for r in message.reactions.results)

                # --- ИЗМЕНЕНО: Добавляем message.id ---
                posts.append({
                    'id': message.id,
                    'text': message.text[:500],  # Ограничиваем длину текста
                    'reactions': total_reacts,
                    'date': message.date.isoformat() if message.date else None
                })

        # Закрываем временный клиент
        await client_temp.disconnect()

        # Сортируем по реакциям и берем топ-15
        top_posts = sorted(posts, key=lambda x: x['reactions'], reverse=True)[:15]
        print(f"Найдено {len(top_posts)} постов для анализа")
        return top_posts

    except Exception as e:
        print(f"Ошибка при получении постов: {e}")
        import traceback
        traceback.print_exc()
        # Закрываем клиент если была ошибка
        if client_temp:
            try:
                await client_temp.disconnect()
            except:
                pass
        return []

# --- НОВАЯ ФУНКЦИЯ АНАЛИЗА С ИСПОЛЬЗОВАНИЕМ OpenAI-СОВМЕСТИМОГО API ---
from openai import APIError # <-- Импортируем конкретное исключение

# --- НОВАЯ ФУНКЦИЯ АНАЛИЗА С ИСПОЛЬЗОВАНИЕМ OpenAI-СОВМЕСТИМОГО API ---
async def analyze_with_openai_compatible(posts):
    """Анализирует посты с помощью удаленной модели через OpenAI-совместимый API"""
    try:
        combined_text = "\n\n".join([
            f"Пост {i+1} (реакции: {post['reactions']}):\n{post['text']}"
            for i, post in enumerate(posts)
        ])

        prompt = f"""
        Проанализируй следующие 15 популярных постов из Telegram-канала.
        Ответь на русском языке кратко и по делу:

        1. О чём эти посты в целом?
        2. Какие основные темы и идеи?
        3. Какой общий тон и настроение?

        {combined_text}
        """

        # Вызов OpenAI-совместимого API
        response = client_openai.chat.completions.create(
            model=cloud_model_name, # Используем указанную модель
            max_tokens=800, # Ограничиваем длину ответа
            temperature=0.7, # Температура генерации
            # presence_penalty=0, # Можно добавить, если поддерживается
            # top_p=0.95, # Можно добавить, если поддерживается
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        # Возвращаем сгенерированный текст
        return response.choices[0].message.content

    except APIError as e: # <-- Ловим APIError
        error_message = f"❌ Ошибка API при анализе: {e.message} (Код: {e.code if hasattr(e, 'code') else 'N/A'})"
        print(error_message)
        return error_message
    except Exception as e: # <-- Ловим остальные исключения
        error_message = f"❌ Ошибка при анализе с помощью облачной модели: {str(e)}"
        print(error_message)
        return error_message

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        "🤖 Привет! Я PostInsight Bot!\n\n"
        "Я анализирую популярные посты из Telegram-каналов с помощью облачной модели.\n"
        "Отправь мне название канала (например: @telegram)\n\n"
        "📝 Примеры:\n"
        "@telegram\n"
        "@breakingnews\n"
        "@habr"
    )

async def handle_channel_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ввода названия канала"""
    channel_input = update.message.text.strip()

    # Форматируем название канала
    if not channel_input.startswith('@') and not channel_input.startswith('https://t.me/'):
        channel_username = '@' + channel_input
    else:
        channel_username = channel_input

    # Отправляем сообщение о начале анализа
    processing_message = await update.message.reply_text(
        f"🔍 Анализирую канал: {channel_username}\n"
        f"🕐 Это может занять 1-2 минуты..."
    )

    try:
        # Получаем топ постов (теперь с ID)
        top_posts = await get_top_posts(channel_username)

        if not top_posts:
            await processing_message.edit_text(
                f"❌ Не удалось получить посты из канала {channel_username}.\n\n"
                "Проверьте:\n"
                "• Правильность названия канала\n"
                "• Доступность канала (публичный ли он?)\n"
                "• Не заблокирован ли канал?"
            )
            return

        # Обновляем сообщение
        await processing_message.edit_text(
            f"✅ Найдено {len(top_posts)} постов для анализа.\n"
            f"🧠 Начинаю анализ с помощью облачной модели ({cloud_model_name})..."
        )

        # --- ИЗМЕНЕНО: Проверка на None ---
        analysis_result = await analyze_with_openai_compatible(top_posts)
        if analysis_result is None:
            analysis_result = "❌ Не удалось получить ответ от облачной модели. Проверьте настройки API или логи."

        # --- Формируем части результата ---
        # Заголовок
        header_message = f"📊 <b>Анализ канала {channel_username}</b>\n\n📈 <b>Топ-10 постов по реакциям:</b>\n"

        # Извлекаем юзернейм (без @)
        username_for_link = channel_username.lstrip('@')

        # Формируем список постов
        posts_message = ""
        for i, post in enumerate(top_posts, 1):
            # Обрезаем текст поста для отображения (например, первые 200 символов)
            preview_text = post['text'][:200].replace('\n', ' ') # <-- Изменено на 200
            if len(post['text']) > 200:
                 preview_text += "..."
            # Формируем ссылку на сообщение используя юзернейм
            post_link = f"https://t.me/{username_for_link}/{post['id']}"
            posts_message += f"{i}. <a href='{post_link}'>Реакции: {post['reactions']}</a> - {preview_text}\n"

        # Общий анализ (уже проверен на None)
        analysis_header = f"\n🧠 <b>Общий анализ содержания 10 постов:</b>\n"
        # full_analysis_message больше не используется как отдельная переменная перед отправкой
        # analysis_full_text = analysis_header + analysis_result # <-- Убрано, используется напрямую

        # Полное сообщение (для проверки длины)
        full_result_message = header_message + posts_message + analysis_header + analysis_result

        # --- Проверяем длину и отправляем соответствующим образом ---
        if len(full_result_message) <= 4096:
            # Если всё помещается в одно сообщение
            await update.message.reply_text(
                full_result_message,
                parse_mode='HTML'
            )
        else:
            # Если не помещается, отправляем части отдельно
            # 1. Отправляем заголовок и список постов
            message_part_1 = header_message + posts_message
            if len(message_part_1) > 4096:
                 # На всякий случай, если даже список постов слишком длинный
                 # Разбиваем его на более мелкие части
                 # Это редкий случай, но на всякий пожарный
                 chunks = []
                 current_chunk = message_part_1
                 while len(current_chunk) > 4096:
                     # Находим последнюю новую строку перед лимитом
                     split_at = current_chunk.rfind('\n', 0, 4096)
                     if split_at == -1: # Не нашли новую строку, разбиваем как есть (может испортить формат)
                         split_at = 4096
                     chunks.append(current_chunk[:split_at])
                     current_chunk = current_chunk[split_at:] # Остаток строки
                 if current_chunk: # Добавляем оставшуюся часть
                     chunks.append(current_chunk)

                 for chunk in chunks:
                     await update.message.reply_text(chunk, parse_mode='HTML')

            else:
                 # Отправляем заголовок и список постов как одно сообщение
                 await update.message.reply_text(message_part_1, parse_mode='HTML')

            # 2. Отправляем общий анализ отдельно
            # Проверяем, нужно ли разбивать анализ
            analysis_full_text = analysis_header + analysis_result # <-- Теперь используется здесь
            if len(analysis_full_text) > 4096:
                # Разбиваем анализ на части
                analysis_chunks = []
                current_text = analysis_full_text
                while len(current_text) > 4096:
                    split_at = current_text.rfind('\n', 0, 4096) # Пытаемся разбить по строкам
                    if split_at == -1:
                        split_at = 4096 # Если нет новой строки, разбиваем как есть
                    analysis_chunks.append(current_text[:split_at])
                    current_text = current_text[split_at:]
                if current_text: # Добавляем оставшуюся часть
                    analysis_chunks.append(current_text)

                for chunk in analysis_chunks:
                    await update.message.reply_text(chunk, parse_mode='HTML')
            else:
                # Отправляем анализ как одно сообщение
                await update.message.reply_text(analysis_full_text, parse_mode='HTML')


    except Exception as e:
        await processing_message.edit_text(f"❌ Произошла ошибка: {str(e)}")
        print(f"Ошибка в handle_channel_input: {e}")
        import traceback
        traceback.print_exc()


# --- УБРАЛИ ФУНКЦИЮ ИНИЦИАЛИЗАЦИИ ---
# async def initialize_client():
#     ...

# --- УБРАЛИ ФУНКЦИЮ НАСТРОЙКИ КЛИЕНТА ---
# def setup_cloud_api():
#     ...

# --- ОСНОВНАЯ ФУНКЦИЯ main ТЕПЕРЬ СИНХРОННАЯ ---
def main():
    """Синхронная точка входа для запуска бота."""
    print("🚀 Запуск PostInsight Bot с облачной моделью...")

    # Проверяем настройки облачного API
    if not os.getenv('CLOUD_API_KEY') or not os.getenv('CLOUD_API_BASE_URL'):
         print("❌ API-ключ или URL для облачной модели не найдены в .env файле.")
         return
    print(f"✅ Используется облачная модель: {cloud_model_name}")
    print(f"✅ URL API: {cloud_api_base_url}")

    # Создаем Telegram бота
    application = Application.builder().token(bot_token).build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_channel_input))

    print("✅ Telegram бот запущен (облачная модель)")
    print("📱 Откройте Telegram и начните диалог с вашим ботом")
    print("🛑 Нажмите Ctrl+C для остановки")

    # Запускаем бота НАПРЯМУЮ - это ключевой момент!
    # python-telegram-bot сам управляет циклом событий
    application.run_polling()

# Запуск приложения
if __name__ == '__main__':
    main() # <-- Вызываем синхронную main функцию