import os
import time
import argparse
import logging
import json
import shutil
import threading
from multiprocessing import Process, Manager
from concurrent.futures import ThreadPoolExecutor
from fake_useragent import UserAgent
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium_stealth import stealth
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import requests


a = r"a"

# Настройка логирования
logging.basicConfig(filename='send_messages.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logging.getLogger('').addHandler(console_handler)

class DriverManager:
    def __init__(self, user_id, extension_path=None):
        self.user_id = user_id
        self.extension_path = extension_path
        self.driver = self.create_driver()

    def create_driver(self):
        options = Options()
        options.add_argument("start-maximized")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_experimental_option('excludeSwitches', ['enable-logging'])

        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_directory = os.path.join(script_dir, 'users')
        a_directory = os.path.join(script_dir, 'a')
        user_directory = os.path.join(base_directory, f'user_{self.user_id}')

        options.add_argument(f'user-data-dir={user_directory}')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-popup-blocking")
        options.add_argument('--no-sandbox')
        options.add_argument('--log-level=3')
        options.add_argument('--ignore-certificate-errors')
        options.add_argument(f'--load-extension={a_directory}')
        
        # options.add_argument("--window-size=700,800")


        if self.extension_path:
            options.add_argument(f'--load-extension={self.extension_path}')

        driver = webdriver.Chrome(options=options)
        ua = UserAgent(browsers='chrome', os='windows', platforms='pc').random
        stealth(driver=driver,
                user_agent=ua,
                languages=["en-EN", "EN"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
                run_on_insecure_origins=True)

        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            'source': '''
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
          '''
        })
        return driver

    def quit(self):
        self.driver.quit()

class ProxyManager:
    @staticmethod
    def read_proxies(file_path):
        with open(file_path, 'r') as file:
            proxies = file.readlines()
        return [proxy.strip() for proxy in proxies]

    @staticmethod
    def check_proxy(proxy):
        try:
            if '@' in proxy:
                auth, address = proxy.split('@')
                username, password = auth.split(':')
                host, port = address.split(':')
            else:
                host, port, username, password = proxy.split(':')
            
            proxies = {
                'http': f'http://{username}:{password}@{host}:{port}',
                'https': f'http://{username}:{password}@{host}:{port}'
            }
            
            response = requests.get('http://httpbin.org/ip', proxies=proxies, timeout=5)
            if response.status_code == 200:
                logging.info(f"Прокси {proxy} работает. IP: {response.json()['origin']}")
                return True
            else:
                logging.warning(f"Прокси {proxy} не работает. Статус: {response.status_code}")
                return False
        except Exception as e:
            logging.error(f"Ошибка при проверке прокси {proxy}: {e}")
            return False

    @staticmethod
    def create_extension(proxy, extension_dir):
        host, port, username, password = proxy.split(':')
        
        background_js = f"""
        var config = {{
            mode: "fixed_servers",
            rules: {{
                singleProxy: {{
                    scheme: "http",
                    host: "{host}",
                    port: {port}
                }},
                bypassList: ["localhost"]
            }}
        }};
        chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});

        function callbackFn(details) {{
            return {{
                authCredentials: {{
                    username: "{username}",
                    password: "{password}"
                }}
            }};
        }}

        chrome.webRequest.onAuthRequired.addListener(
            callbackFn,
            {{urls: ["<all_urls>"]}},
            ['blocking']
        );
        """
        
        manifest_json = {
            "version": "1.0.0",
            "manifest_version": 3,
            "name": "Chrome Proxy Authentication",
            "permissions": ["proxy", "tabs", "unlimitedStorage", "storage", "webRequest", "webRequestAuthProvider"],
            "host_permissions": ["<all_urls>"],
            "background": {
                "service_worker": "background.js"
            },
            "minimum_chrome_version": "108"
        }
        
        os.makedirs(extension_dir, exist_ok=True)
        with open(os.path.join(extension_dir, 'background.js'), 'w') as file:
            file.write(background_js)
        with open(os.path.join(extension_dir, 'manifest.json'), 'w') as file:
            json.dump(manifest_json, file, indent=4)

class CookieManager:
    @staticmethod
    def save_cookies(driver, file_path):
        cookies = driver.get_cookies()
        with open(file_path, 'w') as file:
            json.dump(cookies, file, indent=4)

    @staticmethod
    def load_cookies(driver, file_path):
        try:
            with open(file_path, 'r') as file:
                cookies = json.load(file)
            for cookie in cookies:
                if 'name' in cookie and 'value' in cookie and 'domain' in cookie:
                    driver.add_cookie(cookie)
                else:
                    logging.warning(f"Некорректный формат куки: {cookie}")
        except Exception as e:
            logging.error(f"Ошибка при загрузке кук из файла {file_path}: {e}")

class TikTokBot:
    def __init__(self, user_id, usernames, proxies, max_follows, total_follows_counter, total_follows_lock, no_proxy=False):
        self.user_id = user_id
        self.usernames = usernames
        self.proxies = proxies
        self.max_follows = max_follows
        self.total_follows_counter = total_follows_counter
        self.total_follows_lock = total_follows_lock
        self.no_proxy = no_proxy
        self.captcha_detected = threading.Event()  # Флаг для обнаружения капчи


    def move_cookies_to_bad(self):
        """
        Перемещает файл кук в папку bad.
        """
        script_dir = os.path.dirname(os.path.abspath(__file__))
        cookies_dir = os.path.join(script_dir, 'cookies')
        bad_cookies_dir = os.path.join(cookies_dir, 'bad')
        os.makedirs(bad_cookies_dir, exist_ok=True)

        cookies_files = [f for f in os.listdir(cookies_dir) if f.endswith('.txt')]
        if cookies_files:
            cookies_file_path = os.path.join(cookies_dir, cookies_files[self.user_id % len(cookies_files)])
            shutil.move(cookies_file_path, os.path.join(bad_cookies_dir, os.path.basename(cookies_file_path)))
            logging.info(f"Файл кук {cookies_file_path} перемещен в папку bad.")


    def follow(self, driver):
        max_retries = 3  # Максимальное количество попыток
        retry_count = 0

        while retry_count < max_retries:
            try:
                # Проверяем, есть ли уже подписка (текст "Followed" или "Following")
                followed_button = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'TUXButton-label') and (contains(text(), 'Followed') or contains(text(), 'Following'))]"))
                )
                logging.info('Уже подписан на этот аккаунт')
                return  # Если подписка уже есть, выходим из функции
            except TimeoutException:
                # Если подписки нет, ищем кнопку "Follow"
                try:
                    follow_button = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'TUXButton-label') and contains(text(), 'Follow')]"))
                    )
                    follow_button.click()  # Выполняем подписку

                    # Ожидаем появления текста "Following" после подписки
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'TUXButton-label') and (contains(text(), 'Followed') or contains(text(), 'Following'))]"))
                    )
                    logging.info('Подписался')
                    time.sleep(2)
                    return  # Успешная подписка, выходим из функции
                except TimeoutException:
                    logging.info('Не удалось выполнить подписку')
                    retry_count += 1
                    time.sleep(3)  # Пауза перед повторной попыткой
                except Exception as e:
                    if "element click intercepted" in str(e):

                        login_container = WebDriverWait(driver, 1).until(
                            EC.presence_of_element_located((By.XPATH, "//h2[contains(text(), 'Log in to TikTok'))]"))
                        )
                        if login_container:
                            logging.info("Разлогинило")
                            self.move_cookies_to_bad()
                        
                            return

                        else:    
                            logging.warning("Обнаружена капча. Начинаю решение")
                            time.sleep(10)  # Пауза для решения капчи
                            retry_count += 1
                    else:
                        logging.error(f"Ошибка при подписке: {e}")
                        retry_count += 1

        logging.error("Не удалось выполнить подписку после нескольких попыток.")



    


    def check_login(self, driver):
        """
        Проверяет успешность логина после загрузки кук.
        Возвращает True, если логин успешен, иначе False.
        """
        try:
            driver.get("https://www.tiktok.com/profile")
            time.sleep(5)  # Даем странице время для загрузки

            # Ожидаем появления кнопки "Edit profile"
            edit_profile_button = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'TUXButton-label') and contains(text(), 'Edit profile')]"))
            )

            if edit_profile_button:
                logging.info("Успешный вход в аккаунт")
                return True
            else:
                logging.warning("Обнаружена невалидная сессия")
                return False
        except Exception as e:
            logging.error(f"Ошибка при проверке логина: {e}")
            return False

    def login(self, driver, cookie_name):
        """
        Выполняет вход в аккаунт и сохраняет куки, если вход успешен.
        """
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                driver.get("https://www.tiktok.com/login/phone-or-email/phone-password")
                time.sleep(5)  # Даем странице время для загрузки

                # Ожидаем появления кнопки "Edit profile"
                edit_profile_button = WebDriverWait(driver, 100).until(
                    EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Upload')]"))
                )

                if edit_profile_button:
                    logging.info("Успешный вход в аккаунт")
                    # Сохраняем куки
                    cookies_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies')
                    os.makedirs(cookies_dir, exist_ok=True)
                    cookie_file_path = os.path.join(cookies_dir, f"{cookie_name}.txt")
                    CookieManager.save_cookies(driver, cookie_file_path)
                    logging.info(f"Куки сохранены в файл: {cookie_file_path}")
                    return True
                else:
                    logging.warning("Не удалось войти в аккаунт")
                    return False
            except Exception as e:
                retry_count += 1
                logging.error(f"Ошибка при входе в аккаунт (попытка {retry_count} из {max_retries}): {e}")
                time.sleep(5)  # Ждем перед повторной попыткой

        logging.error("Не удалось войти в аккаунт после нескольких попыток.")
        return False

    def run(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_directory = os.path.join(script_dir, 'users')
        user_directory = os.path.join(base_directory, f'user_{self.user_id}')
        extension_dir = os.path.join(user_directory, 'extension')

        if args.create_cookies:
            cookie_name = input("Введите имя для сохранения кук: ")
            if not self.no_proxy:
                proxy = self.proxies[self.user_id % len(self.proxies)]
                if not ProxyManager.check_proxy(proxy):
                    logging.error(f"Прокси {proxy} не работает. Пропускаем сессию.")
                    return
                ProxyManager.create_extension(proxy, extension_dir)
                driver_manager = DriverManager(self.user_id, extension_dir)
            else:
                driver_manager = DriverManager(self.user_id)

            driver = driver_manager.driver

            if self.login(driver, cookie_name):
                driver_manager.quit()
                shutil.rmtree(user_directory)
                return
            else:
                logging.error("Не удалось сохранить куки. Завершение сессии.")
                driver_manager.quit()
                shutil.rmtree(user_directory)
                return

        if not self.no_proxy:
            proxy = self.proxies[self.user_id % len(self.proxies)]
            if not ProxyManager.check_proxy(proxy):
                logging.error(f"Прокси {proxy} не работает. Пропускаем сессию.")
                return
            ProxyManager.create_extension(proxy, extension_dir)
            driver_manager = DriverManager(self.user_id, extension_dir)
        else:
            driver_manager = DriverManager(self.user_id)

        driver = driver_manager.driver

        driver.get("https://www.tiktok.com")

        cookies_dir = os.path.join(script_dir, 'cookies')
        cookies_files = [f for f in os.listdir(cookies_dir) if f.endswith('.txt')]
        if not cookies_files:
            logging.error("Файлы кук не найдены в папке cookies.")
            driver_manager.quit()
            return

        cookies_file_path = os.path.join(cookies_dir, cookies_files[self.user_id % len(cookies_files)])
        logging.info(f"Сессия {self.user_id}: Загружаем куки из файла: {cookies_file_path}")
        CookieManager.load_cookies(driver, cookies_file_path)

        if not self.check_login(driver):
            logging.warning(f"Сессия {self.user_id}: Невалидная сессия. Перемещаем куки в папку bad.")
            bad_cookies_dir = os.path.join(cookies_dir, 'bad')
            os.makedirs(bad_cookies_dir, exist_ok=True)
            os.rename(cookies_file_path, os.path.join(bad_cookies_dir, os.path.basename(cookies_file_path)))
            driver_manager.quit()
            shutil.rmtree(user_directory)
            return

        session_follows_counter = 0

        for url in [f"https://www.tiktok.com/@{username}" for username in self.usernames]:
            driver.get(url)
            self.follow(driver)
            session_follows_counter += 1
            with self.total_follows_lock:
                self.total_follows_counter.value += 1
            logging.info(f"Подписался на {url}")

            if session_follows_counter >= self.max_follows:
                logging.info(f"Сессия {self.user_id}: Достигнут лимит подписок в сессии ({self.max_follows}).")
                break

        driver_manager.quit()
        shutil.rmtree(user_directory)
        logging.info(f"Сессия {self.user_id}: Папка пользователя {user_directory} удалена.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Подписка на аккаунты TikTok")
    parser.add_argument('--usernames', type=str, required=False, help="Юзернеймы аккаунтов для подписки через запятую (например, user1,user2,user3)")
    parser.add_argument('--follows', type=int, required=False, help="Максимальное количество подписок в сессии (с одного аккаунта)")
    parser.add_argument('--total-follows', type=int, required=False, help="Общее количество подписок на всех пользователей")
    parser.add_argument('--threads', type=int, default=1, help="Количество потоков")
    parser.add_argument('--no-proxy', action='store_true', help="Работать без прокси")
    parser.add_argument('--create-cookies', action='store_true', help="Режим создания кук")
    args = parser.parse_args()

    # Проверяем, активирован ли режим создания кук
    if args.create_cookies:
        # В режиме создания кук нам не нужны usernames, follows и total-follows
        usernames = []
        max_follows = 0
        total_follows = 0
        threads_count = 1
    else:
        # В обычном режиме эти аргументы обязательны
        if not args.usernames or not args.follows or not args.total_follows:
            parser.error("В обычном режиме --usernames, --follows и --total-follows обязательны.")
        usernames = args.usernames.split(',')
        max_follows = args.follows
        total_follows = args.total_follows
        threads_count = args.threads

    proxies = ProxyManager.read_proxies('proxys.txt') if not args.no_proxy else []

    total_follows_counter = Manager().Value('i', 0)
    total_follows_lock = Manager().Lock()

    if args.create_cookies:
        bot = TikTokBot(1, usernames, proxies, max_follows, total_follows_counter, total_follows_lock, args.no_proxy)
        bot.run()
    else:
        with ThreadPoolExecutor(max_workers=threads_count) as executor:
            for user_id in range(1, threads_count + 1):
                bot = TikTokBot(user_id, usernames, proxies, max_follows, total_follows_counter, total_follows_lock, args.no_proxy)
                executor.submit(bot.run)

    logging.info(f"Всего подписок выполнено: {total_follows_counter.value}")
    