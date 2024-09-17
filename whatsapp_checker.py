import asyncio
import csv
import os
import re
import logging
from pyppeteer import launch
from utils import find_chrome_executable, get_browser_instance, handle_qr_scan
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(
    filename='whatsapp_checker.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

@asynccontextmanager
async def get_browser_and_page():
    """
    Initializes the browser and page, handles QR scan, and ensures proper cleanup.
    """
    browser = await get_browser_instance()
    page = await browser.newPage()
    await handle_qr_scan(page)
    try:
        yield page
    except Exception as e:
        logging.error(f"Error within browser context: {e}")
        raise
    finally:
        try:
            await page.close()
            await browser.close()
        except Exception as e:
            logging.error(f"Error closing browser/page: {e}")

def append_number_to_file(number, filename, include_reason=False, reason=''):
    """
    Appends a phone number (and optionally a reason) to the specified CSV file.
    """
    try:
        with open(filename, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            if include_reason:
                writer.writerow([number, reason])
            else:
                writer.writerow([number])
    except Exception as e:
        logging.error(f"Failed to append number to {filename}: {e}")

def read_existing_numbers(filename):
    """
    Reads existing numbers from a CSV file to avoid reprocessing.
    """
    if not os.path.exists(filename):
        return set()
    try:
        with open(filename, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.reader(file)
            headers = next(reader, None)  # Skip header
            return {row[0] for row in reader if row}
    except Exception as e:
        logging.error(f"Failed to read numbers from {filename}: {e}")
        return set()

async def is_number_on_whatsapp(page, phone_number, max_retries=3):
    """
    Checks if a given phone number is registered on WhatsApp.

    :param page: pyppeteer page object
    :param phone_number: str, phone number to check
    :param max_retries: int, number of retries for transient errors
    :return: tuple (bool, str), (True if the number is on WhatsApp, error message if any)
    """
    for attempt in range(1, max_retries + 1):
        try:
            cleaned_number = re.sub(r'\D', '', phone_number)
            chat_url = f'https://web.whatsapp.com/send?phone={cleaned_number}'
            await page.goto(chat_url, {'waitUntil': 'networkidle0', 'timeout': 90000})  # Increased timeout
            await asyncio.sleep(5)  # Adjusted wait time

            # Check for chat input
            chat_input = await page.querySelector('div[contenteditable="true"][data-tab="10"]')
            if chat_input:
                return True, ""
            
            # Check for invalid number message
            invalid_number_selector = 'div._3J6wB'
            invalid_number_element = await page.querySelector(invalid_number_selector)
            if invalid_number_element:
                error_text = await page.evaluate('(element) => element.textContent', invalid_number_element)
                return False, error_text.strip()

            # Check for general error message
            error_selector = 'div[data-animate-modal-body="true"]'
            error_element = await page.querySelector(error_selector)
            if error_element:
                error_text = await page.evaluate('(element) => element.textContent', error_element)
                return False, error_text.strip()

            # If no chat input or error message is found, assume it's not on WhatsApp
            return False, "Number not found on WhatsApp"

        except Exception as e:
            logging.warning(f"Attempt {attempt} failed for {phone_number}: {e}")
            if attempt == max_retries:
                return False, str(e)
            await asyncio.sleep(2)  # Wait before retrying

async def check_numbers_on_whatsapp(phone_numbers, whatsapp_csv, non_whatsapp_csv, batch_size=5):
    """
    Processes phone numbers in batches to check their WhatsApp registration status.

    :param phone_numbers: list of phone numbers to check
    :param whatsapp_csv: path to save WhatsApp-registered numbers
    :param non_whatsapp_csv: path to save non-WhatsApp numbers with reasons
    :param batch_size: number of numbers to process in each batch
    """
    existing_whatsapp_numbers = read_existing_numbers(whatsapp_csv)
    existing_non_whatsapp_numbers = read_existing_numbers(non_whatsapp_csv)
    processed_numbers = existing_whatsapp_numbers.union(existing_non_whatsapp_numbers)

    phone_numbers_to_check = [num for num in phone_numbers if num not in processed_numbers]
    total_numbers = len(phone_numbers_to_check)
    logging.info(f"Starting to check {total_numbers} numbers.")

    async with get_browser_and_page() as page:
        for i in range(0, total_numbers, batch_size):
            batch = phone_numbers_to_check[i:i+batch_size]
            logging.info(f"Processing batch {i//batch_size + 1}: {len(batch)} numbers.")
            for phone_number in batch:
                is_on_whatsapp, error_message = await is_number_on_whatsapp(page, phone_number)
                if is_on_whatsapp:
                    logging.info(f"{phone_number} is on WhatsApp.")
                    append_number_to_file(phone_number, whatsapp_csv)
                else:
                    logging.info(f"{phone_number} is not on WhatsApp. Reason: {error_message}")
                    append_number_to_file(phone_number, non_whatsapp_csv, include_reason=True, reason=error_message)
                
                await asyncio.sleep(1)  # Rate limiting

    logging.info("Completed checking all numbers.")

def save_numbers_to_file(numbers, filename, include_reason=False):
    """
    Saves a list of numbers (and optionally reasons) to a CSV file.

    :param numbers: list of tuples or single values
    :param filename: path to the CSV file
    :param include_reason: bool, whether to include reasons
    """
    try:
        with open(filename, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            if include_reason:
                writer.writerow(['Phone Number', 'Reason'])
                for number, reason in numbers:
                    writer.writerow([number, reason])
            else:
                writer.writerow(['Phone Number'])
                for number in numbers:
                    writer.writerow([number])
    except Exception as e:
        logging.error(f"Failed to save numbers to {filename}: {e}")

def read_phone_numbers_from_csv(file_path):
    """
    Reads phone numbers from a CSV file.

    :param file_path: path to the CSV file
    :return: list of phone numbers
    """
    phone_numbers = []
    try:
        with open(file_path, mode='r') as file:
            reader = csv.reader(file)
            headers = next(reader, None)  # Skip the header
            for row in reader:
                if row:
                    phone_numbers.append(row[0])
    except Exception as e:
        logging.error(f"Failed to read phone numbers from {file_path}: {e}")
    return phone_numbers

async def main():
    import argparse

    parser = argparse.ArgumentParser(description='Check and filter WhatsApp numbers.')
    parser.add_argument('-p', '--phone_csv', default='phone_numbers.csv', help='Path to the phone numbers CSV file')
    args = parser.parse_args()

    input_csv = args.phone_csv
    whatsapp_csv = 'whatsapp_numbers.csv'
    non_whatsapp_csv = 'non_whatsapp_numbers.csv'

    phone_numbers = read_phone_numbers_from_csv(input_csv)
    if not phone_numbers:
        logging.error("No phone numbers to process. Exiting.")
        return

    # Initialize or clear the output files with headers
    for filename, headers in [
        (whatsapp_csv, ['Phone Number']),
        (non_whatsapp_csv, ['Phone Number', 'Reason'])
    ]:
        if not os.path.exists(filename):
            try:
                with open(filename, 'w', newline='', encoding='utf-8') as file:
                    writer = csv.writer(file)
                    writer.writerow(headers)
            except Exception as e:
                logging.error(f"Failed to initialize {filename}: {e}")

    await check_numbers_on_whatsapp(phone_numbers, whatsapp_csv, non_whatsapp_csv)

    print(f"WhatsApp numbers saved to: {whatsapp_csv}")
    print(f"Non-WhatsApp numbers with reasons saved to: {non_whatsapp_csv}")
    logging.info("Script execution completed.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.critical(f"Unhandled exception: {e}")