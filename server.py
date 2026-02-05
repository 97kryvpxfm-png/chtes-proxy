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
import re

# === Константы ===
CONFIG_FILE = "config.json"
CACHE_DIR = "./cache"
PORT = 4444

# База знаний о моделях (на основе запросы.txt)
KNOWN_MODELS = {
    # Unified models (image.chutes.ai + standard params)
    "qwen-image": {"type": "unified"},
    "JuggernautXL-Ragnarok": {"type": "unified"},
    "FLUX.1-schnell": {"type": "unified"},
    "HassakuXL": {"type": "unified"},
    "Illustrij": {"type": "unified"},
    "stabilityai/stable-diffusion-xl-base-1.0": {"type": "unified"},
    "diagonalge/Booba": {"type": "unified"},
    "NovaFurryXL": {"type": "unified"},
    "iLustMix": {"type": "unified"},
    "Animij": {"type": "unified"},
    "Lykon/dreamshaper-xl-1-0": {"type": "unified"},
    "JuggernautXL": {"type": "unified"},
    "chroma": {"type": "unified"},
    
    # Native models (Specific URL patterns)
    "z-image-turbo": {
        "type": "native",
        "url_template": "https://chutes-{model}.chutes.ai/generate",
        "supports_negative": False,
        "resolution_format": "none"
    },
    "hunyuan-image-3": {
        "type": "native",
        "url_template": "https://chutes-{model}.chutes.ai/generate",
        "supports_negative": False,
        "resolution_format": "none"
    },
    "hidream": {
        "type": "native",
        "url_template": "https://chutes-{model}.chutes.ai/generate",
        "supports_negative": False,
        "resolution_format": "string" # resolution: "1024x1024"
    }
}

# === Функции конфигурации ===

def load_config():
    """Загрузить конфигурацию из config.json"""
    default_config = {
        "api_key": "", 
        "model_name": "", 
        "custom_models": {}, # Для новых моделей, которым научили скрипт
        "link_settings": { # Настройки ссылки (что включать)
            "include_negative": True,
            "include_resolution": True
        },
        "cache_dir": CACHE_DIR
    }
    if not os.path.exists(CONFIG_FILE):
        return default_config
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            # Дополнить дефолтными значениями
            for k, v in default_config.items():
                if k not in config:
                    config[k] = v
            # Рекурсивный мердж для link_settings
            if "link_settings" not in config:
                 config["link_settings"] = default_config["link_settings"]
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

def get_model_info(model_name, config):
    """Получить метаданные модели (из базы или custom_models)"""
    if not model_name:
        return None
    
    # 1. Проверяем в известных (точное совпадение)
    if model_name in KNOWN_MODELS:
        return KNOWN_MODELS[model_name]

    # 1.1 Проверяем в известных (без учета регистра)
    for k, v in KNOWN_MODELS.items():
        if k.lower() == model_name.lower():
            return v
    
    # 2. Проверяем в пользовательских
    if model_name in config.get("custom_models", {}):
        return config["custom_models"][model_name]
    
    return None

def parse_curl_request(model_name, curl_text):
    """Анализ curl запроса для определения возможностей модели"""
    info = {
        "type": "unknown",
        "supports_negative": False,
        "resolution_format": "none",
        "url_template": ""
    }
    
    # 1. Определяем URL и тип
    if "image.chutes.ai/generate" in curl_text:
        info["type"] = "unified"
    elif ".chutes.ai/generate" in curl_text:
        info["type"] = "native"
        # Пытаемся извлечь шаблон URL. Обычно https://chutes-{NAME}.chutes.ai
        # Но сохраним просто как есть, с заменой имени на плейсхолдер если получится, или хардкод
        # Проще: извлечь полный URL из curl
        match = re.search(r'https://[\w\-\.]+\.chutes\.ai/generate', curl_text)
        if match:
            url = match.group(0)
            # Если URL содержит имя модели, заменим его на {model} для универсальности, 
            # но для custom лучше сохранить конкретный URL
            info["url_template"] = url
    
    # 2. Определяем параметры (ищем ключи в JSON)
    if "negative_prompt" in curl_text:
        info["supports_negative"] = True
    
    if "resolution" in curl_text and "x" in curl_text: # "resolution": "1024x1024"
        info["resolution_format"] = "string"
    elif "width" in curl_text and "height" in curl_text:
        info["resolution_format"] = "standard"
    
    # Для Unified моделей обычно все стандартно
    if info["type"] == "unified":
        info["resolution_format"] = "standard"
        info["supports_negative"] = True
        
    return info

def configure_model_name(config):
    """Настройка имени модели с обучением"""
    print("\n📝 Введите имя модели (как на сайте Chutes):")
    model_name = input("> ").strip()
    
    if not model_name:
        print("❌ Имя модели не может быть пустым")
        return

    info = get_model_info(model_name, config)
    
    if info:
        print(f"✓ Модель '{model_name}' найдена в базе.")
        config["model_name"] = model_name
    else:
        print(f"\n⚠️ Модель '{model_name}' не известна скрипту.")
        print("Для настройки, пожалуйста, вставьте пример CURL запроса для этой модели.")
        print("(Скопируйте его на сайте Chutes и вставьте сюда. Нажмите Enter, затем Ctrl+D (или Ctrl+Z в Win) для завершения ввода):")
        
        lines = []
        try:
            while True:
                line = input()
                lines.append(line)
        except EOFError:
            pass
        
        curl_text = "\n".join(lines)
        print("\nАнализирую...")
        
        new_info = parse_curl_request(model_name, curl_text)
        print(f"Результат анализа: Тип={new_info['type']}, Негатив={new_info['supports_negative']}, Разрешение={new_info['resolution_format']}")
        
        config["custom_models"][model_name] = new_info
        config["model_name"] = model_name
        print(f"✓ Модель '{model_name}' сохранена и добавлена в базу.")

def configure_link_settings(config):
    """Настройка параметров ссылки"""
    model_name = config.get("model_name")
    if not model_name:
        print("❌ Сначала выберите модель")
        return
        
    info = get_model_info(model_name, config)
    if not info:
        print("❌ Ошибка данных модели")
        return

    # Проверка поддержки
    supports_neg = info.get("supports_negative", True) if info["type"] == "unified" else info.get("supports_negative", False)
    supports_res = info.get("resolution_format", "standard") != "none"

    print("\n🔗 Настройка параметров ссылки:")
    
    if supports_neg:
        cur = "ВКЛ" if config["link_settings"]["include_negative"] else "ВЫКЛ"
        ans = input(f"Включать негативный промпт в ссылку? (Сейчас {cur}) [y/n]: ").strip().lower()
        if ans == 'y': config["link_settings"]["include_negative"] = True
        elif ans == 'n': config["link_settings"]["include_negative"] = False
    else:
        print("- Негативный промпт: Не поддерживается моделью")
        config["link_settings"]["include_negative"] = False
        
    if supports_res:
        cur = "ВКЛ" if config["link_settings"]["include_resolution"] else "ВЫКЛ"
        ans = input(f"Включать разрешение в ссылку? (Сейчас {cur}) [y/n]: ").strip().lower()
        if ans == 'y': config["link_settings"]["include_resolution"] = True
        elif ans == 'n': config["link_settings"]["include_resolution"] = False
    else:
        print("- Разрешение: Не поддерживается моделью")
        config["link_settings"]["include_resolution"] = False

    print("✓ Настройки ссылки обновлены")

# ... функции API key, cache, etc остаются ...

def validate_api_key(key):
    return (key.startswith("cpk_") or key.startswith("sk_")) and len(key) >= 20

def mask_api_key(key):
    if not key: return "не настроен"
    if len(key) < 8: return "****"
    return f"{key[:4]}****{key[-4:]}"

def count_cache_files():
    if not os.path.exists(CACHE_DIR): return 0
    try: return len([f for f in os.listdir(CACHE_DIR) if f.endswith('.jpg')])
    except: return 0

def configure_api_key(config):
    key = input("Введите API ключ от Chutes AI: ").strip()
    if validate_api_key(key):
        config["api_key"] = key
        print("✓ API ключ сохранён")
    else:
        print("❌ Неверный формат API ключа")

def show_settings(config):
    print("\nТекущая конфигурация:")
    if config.get("api_key"): print(f"- API ключ: {mask_api_key(config['api_key'])}")
    else: print("- API ключ: не настроен")
    
    if config.get("model_name"):
        info = get_model_info(config["model_name"], config)
        print(f"- Модель: {config['model_name']} ({info.get('type', 'unknown')})")
    else:
        print("- Модель: не настроена")
    
    cache_count = count_cache_files()
    print(f"- Папка кэша: {CACHE_DIR} ({cache_count} файлов)")

def show_menu():
    """Главное меню"""
    while True:
        config = load_config() # Перезагрузка конфига
        
        print("\n=== Chutes AI Image Proxy ===")
        
        key_status = "✅ Введен" if config.get("api_key") else "❌ Не введен"
        model_status = f"✅ Указана ({config['model_name']})" if config.get("model_name") else "❌ Не указана"
        
        print(f"Ключ: {key_status}")
        print(f"Модель: {model_status}")
        
        # Генерация примера ссылки
        link_parts = ["http://localhost:4444/prompt/[PROMPT]"]
        if config["link_settings"].get("include_negative"):
            link_parts.append("[NEGATIVE_PROMPT]")
        if config["link_settings"].get("include_resolution"):
            link_parts.append("[WIDTH]x[HEIGHT]")
            
        print(f"Ссылка: {'/'.join(link_parts)}")
        print("-----------------------------")
        
        print("1. Настроить API ключ")
        print("2. Настроить имя модели")
        print("3. Настроить формат ссылки")
        print("4. Показать подробные настройки")
        print("5. Запустить сервер")
        print("6. Выход")
        
        try:
            choice = input("\nВыберите опцию [1-6]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nВыход...")
            break
        
        if choice == "1":
            configure_api_key(config)
            save_config(config)
        elif choice == "2":
            configure_model_name(config)
            # При смене модели сбрасываем настройки ссылки на дефолт модели?
            # Или проверяем их валидность. configure_link_settings делает это при вызове, 
            # но лучше бы авто-апдейтнуть. Пока оставим как есть.
            save_config(config)
        elif choice == "3":
            configure_link_settings(config)
            save_config(config)
        elif choice == "4":
            show_settings(config)
        elif choice == "5":
            if not config.get("api_key") or not config.get("model_name"):
                print("❌ Сначала настройте API ключ и имя модели")
                continue
            start_server(config)
            break
        elif choice == "6":
            print("До свидания!")
            break
        else:
            print("Неверная опция.")

# === HTTP сервер ===

def get_cache_key(prompt, negative_prompt, width, height):
    """Генерация уникального ключа для кэша (общий кэш)"""
    cache_string = f"{prompt}||{negative_prompt}||{width}||{height}"
    hash_obj = hashlib.md5(cache_string.encode('utf-8'))
    return f"{hash_obj.hexdigest()}.jpg"

def check_cache(cache_filename):
    filepath = os.path.join(CACHE_DIR, cache_filename)
    return filepath if os.path.exists(filepath) else None

def save_to_cache(cache_filename, image_data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    filepath = os.path.join(CACHE_DIR, cache_filename)
    with open(filepath, 'wb') as f: f.write(image_data)
    return filepath

def log_message(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")
    sys.stdout.flush()

def request_chutes_image(prompt, negative_prompt, width, height, config):
    """Запрос генерации изображения"""
    
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json"
    }
    
    model_name = config["model_name"]
    info = get_model_info(model_name, config)
    
    if not info:
        raise Exception(f"Нет метаданных для модели {model_name}")
    
    # 1. URL
    if info["type"] == "unified":
        url = "https://image.chutes.ai/generate"
    else:
        # Native
        if "{model}" in info["url_template"]:
            url = info["url_template"].format(model=model_name)
        else:
            url = info["url_template"]

    # 2. Payload
    payload = {"prompt": prompt}
    
    # Unified models требуют параметр model
    if info["type"] == "unified":
        payload["model"] = model_name

    # Добавляем negative_prompt если поддерживается
    # Unified поддерживает всегда (по дефолту в базе KNOWN_MODELS)
    # Native поддерживает если info['supports_negative'] is True
    
    supports_neg = info.get("supports_negative", True) if info["type"] == "unified" else info.get("supports_negative", False)
    
    if supports_neg and negative_prompt:
        payload["negative_prompt"] = negative_prompt

    # Добавляем разрешение
    res_format = info.get("resolution_format", "standard") # standard, string, none
    
    if res_format == "standard":
        payload["width"] = width
        payload["height"] = height
    elif res_format == "string":
        payload["resolution"] = f"{width}x{height}"
    
    # Стандартные параметры (можно добавить проверку, но обычно они ок)
    payload["num_inference_steps"] = 20
    payload["guidance_scale"] = 7.5

    response = requests.post(url, json=payload, headers=headers, timeout=60)
    
    if response.status_code == 200:
        return response.content
    elif response.status_code == 400:
         raise Exception(f"Ошибка 400 (Bad Request): {response.text[:200]}")
    elif response.status_code == 401:
        raise Exception("Неверный API ключ (401).")
    elif response.status_code == 404:
        raise Exception(f"Модель/URL не найден (404).")
    elif response.status_code == 429:
        raise Exception("Достигнут дневной лимит (429).")
    elif response.status_code == 500:
        raise Exception("Ошибка сервера Chutes (500).")
    else:
        raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")

def start_server(config):
    app = Flask(__name__)
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    @app.route('/prompt/<path:params>')
    def generate_image(params):
        params = unquote(params)
        parts = params.split('/')
        
        # Парсинг URL с учетом настроек ссылки (какие части ожидать)
        # Но сервер должен быть гибким: если части есть - берем, нет - дефолт
        
        prompt = parts[0] if len(parts) > 0 else ""
        negative_prompt = ""
        width = 1024
        height = 1024
        
        # Попробуем умный парсинг оставшихся частей
        remaining = parts[1:]
        
        for part in remaining:
            part = part.strip()
            if not part or part == '-': continue
            
            # Если похоже на разрешение (1024x1024)
            if 'x' in part and part.replace('x','').isdigit():
                try:
                    w, h = part.lower().split('x')
                    width = int(w)
                    height = int(h)
                    continue
                except:
                    pass
            
            # Если не разрешение, считаем это негативным промптом
            # (Если негативный промпт еще не был установлен)
            if not negative_prompt:
                negative_prompt = part
        
        neg_text = f'"{negative_prompt}"' if negative_prompt else '""'
        log_message(f'Запрос: "{prompt}" | Негатив: {neg_text} | Размер: {width}x{height}')
        
        cache_file = get_cache_key(prompt, negative_prompt, width, height)
        cached = check_cache(cache_file)
        
        if cached:
            log_message(f"Кэш: ПОПАДАНИЕ")
            return send_file(cached, mimetype='image/jpeg')
        
        log_message("Кэш: ПРОМАХ - генерируем...")
        try:
            start_time = time.time()
            image_data = request_chutes_image(prompt, negative_prompt, width, height, config)
            elapsed = time.time() - start_time
            log_message(f"Сгенерировано за {elapsed:.1f}с")
            save_to_cache(cache_file, image_data)
            return Response(image_data, mimetype='image/jpeg')
        except Exception as e:
            log_message(f"ОШИБКА: {str(e)}")
            return Response(str(e), status=500, mimetype='text/plain; charset=utf-8')
    
    print(f"\n✓ Сервер запущен на http://localhost:{PORT}")
    print("Нажмите Ctrl+C для остановки\n")
    try:
        app.run(host='0.0.0.0', port=PORT, debug=False)
    except Exception as e:
        print(f"Ошибка при запуске сервера: {e}")

if __name__ == '__main__':
    os.makedirs(CACHE_DIR, exist_ok=True)
    show_menu()
