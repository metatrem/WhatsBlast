import asyncio
import argparse
import csv
import os
import random
from pyppeteer import connect, launch
import shutil
import re

def find_chrome_executable():
    if os.name == 'nt':  # Windows
        paths = [
            os.path.join(os.getenv('LOCALAPPDATA'), 'Google', 'Chrome', 'Application', 'chrome.exe'),
            os.path.join(os.getenv('PROGRAMFILES'), 'Google', 'Chrome', 'Application', 'chrome.exe'),
            os.path.join(os.getenv('PROGRAMFILES(X86)'), 'Google', 'Chrome', 'Application', 'chrome.exe')
        ]
    elif os.name == 'posix':  # macOS and Linux
        paths = [
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',  # macOS
            '/usr/bin/google-chrome',  # Linux
            '/usr/local/bin/google-chrome',  # Linux
            shutil.which('google-chrome'),  # Linux
            shutil.which('chrome')  # Linux
        ]
    else:
        return None

    for path in paths:
        if path and os.path.exists(path):
            return path
    return None

CHROME_EXECUTABLE_PATH = find_chrome_executable()

if not CHROME_EXECUTABLE_PATH:
    raise FileNotFoundError("Chrome executable not found. Please install Google Chrome or specify the path manually.")

browser_instance = None

async def get_browser_instance():
    global browser_instance
    if browser_instance is None:
        browser_instance = await launch(headless=False, executablePath=CHROME_EXECUTABLE_PATH)  # Launch a new browser instance
    return browser_instance

async def handle_qr_scan(page):
    """
    Handles the QR code scanning process for WhatsApp Web.

    :param page: pyppeteer page object
    """
    await page.goto('https://web.whatsapp.com')
    print("Please scan the QR code to log in to WhatsApp Web.")
    await page.waitForSelector('div[contenteditable="true"][data-tab="3"]', timeout=60000)  # Wait up to 60 seconds for QR scan

async def send_messages_to_multiple_numbers(phone_numbers, message, writer):
    """
    Sends a WhatsApp message to a list of phone numbers one by one.

    :param phone_numbers: list of str, recipient's phone numbers in the format '+1234567890'
    :param message: str, the message to be sent
    :param writer: csv.writer object, to write results incrementally
    """
    browser = await get_browser_instance()
    page = await browser.newPage()
    await handle_qr_scan(page)

    for phone_number in phone_numbers:
        try:
            chat_url = f'https://web.whatsapp.com/send?phone={phone_number}'
            await page.goto(chat_url)
            await asyncio.sleep(5)  # Wait for the chat to load

            message_box = await page.waitForSelector('div[contenteditable="true"][data-tab="10"]', timeout=60000)
            for line in message.split('\n'):
                await message_box.type(line)
                await page.keyboard.down('Shift')
                await message_box.press('Enter')
                await page.keyboard.up('Shift')
            await message_box.press('Enter')
            await asyncio.sleep(random.choice([1, 2, 3]))  # Dynamic wait time

            writer.writerow([phone_number, 'Sent successfully'])
        except Exception as e:
            print(f"An error occurred while sending to {phone_number}: {e}")
            writer.writerow([phone_number, 'Failed'])
            await asyncio.sleep(10)  # Sleep for 10 seconds before retrying the next number

    await page.close()

def read_phone_numbers_from_csv(file_path):
    phone_numbers = []
    with open(file_path, mode='r') as file:
        reader = csv.reader(file)
        next(reader)  # Skip the header
        for row in reader:
            phone_numbers.append(row[0])
    return phone_numbers

def read_message_from_text(file_path):
    with open(file_path, mode='r') as file:
        message = file.read().strip()
    return message

async def close_browser():
    global browser_instance
    if browser_instance:
        await browser_instance.close()
        browser_instance = None
        
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Send WhatsApp messages to filtered numbers.')
    parser.add_argument('-p', '--phone_csv', default='whatsapp_numbers.csv', help='Path to the filtered WhatsApp numbers CSV file')
    parser.add_argument('-m', '--message_txt', default='message.txt', help='Path to the message text file')
    args = parser.parse_args()

    input_csv = args.phone_csv
    message_txt = args.message_txt
    output_csv = 'message_sending_results.csv'

    phone_numbers = read_phone_numbers_from_csv(input_csv)
    message = read_message_from_text(message_txt)

    loop = asyncio.get_event_loop()
    try:
        with open(output_csv, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['Phone Number', 'Status'])
            loop.run_until_complete(send_messages_to_multiple_numbers(phone_numbers, message, writer))

        print(f"Message sending results saved to: {output_csv}")
    finally:
        loop.run_until_complete(close_browser())
        loop.close()


