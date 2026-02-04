# -*- coding: utf-8 -*-
import os
import json
import hashlib
import time
from urllib.parse import unquote
from flask import Flask, send_file, Response
import requests
from datetime import datetime
import sys

# === Константы ===
CONFIG_FILE = "config.json"
CACHE_DIR = "./cache"
PORT = 4444
CHUTES_IMAGE_ENDPOINT = "https://image.chutes.ai/generate"

# === Функции конфигурации ===

def load_config():
    """Загрузить конфигурацию из config.json"""
    default_config = {
        "api_key": "",
        "model_name": "",
        "provider_type": "unified", # 'unified' (сторонние) или 'chutes' (родные)
        "cache_dir": CACHE_DIR
    }
    if not os.path.exists(CONFIG_FILE):
        return default_config
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            # Дополнить дефолтными значениями если ключей нет
            for k, v in default_config.items():
                if k not in config:
                    config[k] = v
            return config
    except Exception as e:
        print(f"Ошибка чтения конфига: {e}")
        return default_config

def save_config(config):
    """Сохранить конфигурацию в config.json"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Ошибка сохранения конфига: {e}")

def validate_api_key(key):
    """Проверка формата API ключа"""
    return (key.startswith("cpk_") or key.startswith("sk_")) and len(key) >= 20

def mask_api_key(key):
    """Маскировка API ключа для вывода"""
    if not key:
        return "не настроен"
    if len(key) < 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"

def count_cache_files():
    """Подсчет файлов в кэше"""
    if not os.path.exists(CACHE_DIR):
        return 0
    try:
        return len([f for f in os.listdir(CACHE_DIR) if f.endswith('.jpg')])
    except:
        return 0

def configure_api_key(config):
    """Интерактивная настройка API ключа"""
    key = input("Введите API ключ от Chutes AI: ").strip()
    if validate_api_key(key):
        config["api_key"] = key
        print("✓ API ключ сохранён")
    else:
        print("❌ Неверный формат API ключа (должен начинаться с cpk_ или sk_ и быть длиннее 20 символов)")

def configure_model_name(config):
    """Настройка имени модели"""
    print("\n📝 Как найти имя модели:")
    print("1. Откройте страницу публичного chute в браузере")
    print("2. Найдите кнопку 'Copy model name'")
    print("3. Скопируйте имя модели (например: Illustrij, z-image-turbo)")
    print("4. Посмотрите на 'Provider' рядом с именем")
    print()
    
    model_name = input("Введите имя модели: ").strip()
    
    if not model_name:
        print("❌ Имя модели не может быть пустым")
        return

    print("\nЭто 'родная' модель от провайдера Chutes?")
    print("(Обычно это модели вроде z-image-turbo, flux-dev-schnell и т.д.)")
    is_chutes = input("Введите 'y' если провайдер Chutes, или 'n' если другой (Illustrij и др.): ").lower().strip()
    
    config["model_name"] = model_name
    if is_chutes == 'y':
        config["provider_type"] = "chutes"
        print(f"✓ Модель сохранена: {model_name} (Тип: Native Chutes)")
    else:
        config["provider_type"] = "unified"
        print(f"✓ Модель сохранена: {model_name} (Тип: Unified/Third-party)")

def show_settings(config):
    """Показать текущие настройки"""
    print("\nТекущая конфигурация:")
    
    if config.get("api_key"):
        print(f"- API ключ: {mask_api_key(config['api_key'])}")
    else:
        print("- API ключ: не настроен")
    
    if config.get("model_name"):
        p_type = "Native Chutes" if config.get("provider_type") == "chutes" else "Unified"
        print(f"- Модель: {config['model_name']} ({p_type})")
    else:
        print("- Модель: не настроена")
    
    cache_count = count_cache_files()
    print(f"- Папка кэша: {CACHE_DIR} ({cache_count} файлов)")

def show_menu():
    """Главное меню"""
    # Загружаем конфиг внутри цикла, чтобы обновлять статус
    
    while True:
        config = load_config()
        
        print("\n=== Chutes AI Image Proxy ===")
        
        # Статус настройки
        key_status = "✅ Введен" if config.get("api_key") else "❌ Не введен"
        model_status = f"✅ Указана ({config['model_name']})" if config.get("model_name") else "❌ Не указана"
        
        print(f"Ключ: {key_status}")
        print(f"Модель: {model_status}")
        
        # Пример ссылки
        provider = config.get("provider_type", "unified")
        if provider == "chutes":
            link_example = f"http://localhost:{PORT}/prompt/[PROMPT]"
        else:
            link_example = f"http://localhost:{PORT}/prompt/[PROMPT]/[NEGATIVE_PROMPT]/[WIDTH]x[HEIGHT]"
            
        print(f"Ссылка для использования: {link_example}")
        print("-----------------------------")
        
        print("1. Настроить API ключ")
        print("2. Настроить имя модели")
        print("3. Показать подробные настройки")
        print("4. Запустить сервер")
        print("5. Выход")
        
        try:
            choice = input("\nВыберите опцию [1-5]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nВыход...")
            break
        
        if choice == "1":
            configure_api_key(config)
            save_config(config)
        elif choice == "2":
            configure_model_name(config)
            save_config(config)
        elif choice == "3":
            show_settings(config)
        elif choice == "4":
            if not config.get("api_key") or not config.get("model_name"):
                print("❌ Сначала настройте API ключ и имя модели (опции 1 и 2)")
                continue
            start_server(config)
            break
        elif choice == "5":
            print("До свидания!")
            break
        else:
            print("Неверная опция. Выберите от 1 до 5.")

# === HTTP сервер ===

def get_cache_key(prompt, negative_prompt, width, height):
    """Генерация уникального ключа для кэша (БЕЗ модели, общий кэш)"""
    cache_string = f"{prompt}||{negative_prompt}||{width}||{height}"
    hash_obj = hashlib.md5(cache_string.encode('utf-8'))
    return f"{hash_obj.hexdigest()}.jpg"

def check_cache(cache_filename):
    """Проверка наличия файла в кэше"""
    filepath = os.path.join(CACHE_DIR, cache_filename)
    return filepath if os.path.exists(filepath) else None

def save_to_cache(cache_filename, image_data):
    """Сохранение изображения в кэш"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    filepath = os.path.join(CACHE_DIR, cache_filename)
    with open(filepath, 'wb') as f:
        f.write(image_data)
    return filepath

def log_message(message):
    """Логирование с временной меткой"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")
    sys.stdout.flush()

def request_chutes_image(prompt, negative_prompt, width, height, config):
    """Запрос генерации изображения в Chutes AI"""
    
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json"
    }
    
    provider_type = config.get("provider_type", "unified")
    model_name = config["model_name"]
    
    if provider_type == "chutes":
        # Формат для "родных" моделей Chutes (z-image-turbo и т.д.)
        # URL: https://chutes-{MODEL}.chutes.ai/generate
        # Payload: ТОЛЬКО prompt (судя по примерам, они строгие к параметрам)
        url = f"https://chutes-{model_name}.chutes.ai/generate"
        
        payload = {
            "prompt": prompt
        }
        # Если нужно, можно попробовать добавить другие параметры, но пока строго по примеру пользователя
    else:
        # Формат для остальных (Unified endpoint)
        # URL: https://image.chutes.ai/generate
        # Payload: с полем model
        url = CHUTES_IMAGE_ENDPOINT
        
        payload = {
            "model": model_name,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "num_inference_steps": 20,
            "guidance_scale": 7.5
        }
    
    response = requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=60
    )
    
    if response.status_code == 200:
        return response.content
    elif response.status_code == 401:
        raise Exception("Неверный API ключ (401).")
    elif response.status_code == 404:
        raise Exception(f"Модель '{config['model_name']}' не найдена (404).")
    elif response.status_code == 429:
        raise Exception("Достигнут дневной лимит (300 запросов).")
    elif response.status_code == 500:
        raise Exception("Ошибка сервера Chutes (500).")
    else:
        raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")

def start_server(config):
    """Запуск Flask HTTP-сервера"""
    app = Flask(__name__)
    
    # Отключаем стандартный логгер Flask, чтобы не засорять вывод
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    @app.route('/prompt/<path:params>')
    def generate_image(params):
        # Декодировать URL
        params = unquote(params)
        
        # Разделить по "/"
        parts = params.split('/')
        
        # Парсинг параметров
        prompt = parts[0] if len(parts) > 0 else ""
        
        # negative_prompt может быть пропущен или обозначен как '-' или ' '
        negative_prompt = ""
        if len(parts) > 1:
            val = parts[1].strip()
            if val and val not in ['-', '']:
                negative_prompt = parts[1]
        
        # Размеры по умолчанию
        width = 1024
        height = 1024
        
        if len(parts) > 2:
            size_part = parts[2]
            if 'x' in size_part:
                try:
                    w, h = size_part.lower().split('x')
                    width = int(w)
                    height = int(h)
                except:
                    pass  # Оставить дефолтные
        
        # Логирование запроса
        neg_text = f'"{negative_prompt}"' if negative_prompt else '""'
        log_message(f'Запрос: "{prompt}" | Негатив: {neg_text} | Размер: {width}x{height}')
        
        # Проверка кэша (БЕЗ имени модели, общий кэш)
        cache_file = get_cache_key(prompt, negative_prompt, width, height)
        cached = check_cache(cache_file)
        
        if cached:
            log_message(f"Кэш: ПОПАДАНИЕ - возвращаем из кэша")
            return send_file(cached, mimetype='image/jpeg')
        
        # Генерация нового изображения
        log_message("Кэш: ПРОМАХ - генерируем...")
        try:
            start_time = time.time()
            
            image_data = request_chutes_image(prompt, negative_prompt, width, height, config)
            
            elapsed = time.time() - start_time
            log_message(f"Сгенерировано за {elapsed:.1f}с")
            
            # Сохранить в кэш
            save_to_cache(cache_file, image_data)
            log_message(f"Сохранено: {cache_file}")
            
            # Вернуть изображение
            return Response(image_data, mimetype='image/jpeg')
            
        except requests.exceptions.Timeout:
            error_msg = "Таймаут генерации. Попробуйте более простой промпт."
            log_message(f"ОШИБКА: {error_msg}")
            return Response(error_msg, status=504, mimetype='text/plain; charset=utf-8')
        except requests.exceptions.RequestException as e:
            error_msg = "Ошибка сети. Проверьте подключение к интернету."
            log_message(f"ОШИБКА: {str(e)}")
            return Response(error_msg, status=503, mimetype='text/plain; charset=utf-8')
        except Exception as e:
            log_message(f"ОШИБКА: {str(e)}")
            return Response(str(e), status=500, mimetype='text/plain; charset=utf-8')
    
    print(f"\n✓ Сервер запущен на http://localhost:{PORT}")
    print(f"  Используемая модель: {config['model_name']}")
    print("Нажмите Ctrl+C для остановки\n")
    try:
        app.run(host='0.0.0.0', port=PORT, debug=False)
    except Exception as e:
        print(f"Ошибка при запуске сервера: {e}")

# === Точка входа ===

if __name__ == '__main__':
    # Создаем папку кэша сразу при запуске
    os.makedirs(CACHE_DIR, exist_ok=True)
    show_menu()
