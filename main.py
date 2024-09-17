import asyncio
import argparse
import csv
import os
import random
import re
import logging
from pyppeteer import launch
from contextlib import asynccontextmanager
from utils import get_browser_instance, handle_qr_scan

# Configure logging
logging.basicConfig(
    filename='whatsapp_sender.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def get_browser_and_page():
    """
    Initializes the browser and page, handles QR scan, and ensures proper cleanup.
    """
    try:
        browser = await get_browser_instance()
        page = await browser.newPage()
        await handle_qr_scan(page)
        yield page
    except Exception as e:
        logger.error(f"Error initializing browser and page: {e}")
        raise
    finally:
        try:
            await page.close()
            await browser.close()
            logger.info("Browser and page closed successfully.")
        except Exception as e:
            logger.error(f"Error closing browser/page: {e}")

def append_number_to_file(number, filename, include_reason=False, reason=''):
    """
    Appends a phone number (and optionally a reason) to the specified CSV file.

    :param number: str, phone number to append
    :param filename: str, path to the CSV file
    :param include_reason: bool, whether to include a reason
    :param reason: str, reason for failure or status
    """
    try:
        with open(filename, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            if include_reason:
                writer.writerow([number, reason])
            else:
                writer.writerow([number])
        logger.info(f"Appended number to {filename}: {number}" + (f" - Reason: {reason}" if include_reason else ""))
    except Exception as e:
        logger.error(f"Failed to append number to {filename}: {e}")

def read_phone_numbers_from_csv(file_path):
    """
    Reads phone numbers from a CSV file and cleans them by removing '+' signs.

    :param file_path: str, path to the CSV file
    :return: list of str, cleaned phone numbers
    """
    phone_numbers = []
    try:
        with open(file_path, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.reader(file)
            headers = next(reader, None)  # Skip the header
            for row in reader:
                if row:
                    # Remove any non-digit characters, such as '+' signs
                    clean_number = re.sub(r'\D', '', row[0])
                    phone_numbers.append(clean_number)
        logger.info(f"Read {len(phone_numbers)} phone numbers from {file_path}")
    except Exception as e:
        logger.error(f"Failed to read phone numbers from {file_path}: {e}")
    return phone_numbers

def read_message_from_text(file_path):
    """
    Reads the message text from a file.

    :param file_path: str, path to the text file
    :return: str, message
    """
    try:
        with open(file_path, mode='r', encoding='utf-8') as file:
            message = file.read().strip()
        logger.info(f"Read message from {file_path}")
        return message
    except Exception as e:
        logger.error(f"Failed to read message from {file_path}: {e}")
        return ""

def read_processed_numbers(file_path):
    """
    Reads processed phone numbers from a CSV file and returns a set of successfully processed numbers.

    :param file_path: str, path to the CSV file
    :return: set of str, processed phone numbers
    """
    processed_numbers = set()
    try:
        with open(file_path, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.reader(file)
            next(reader, None)  # Skip the header
            for row in reader:
                if row and row[1] == 'Sent successfully':
                    processed_numbers.add(re.sub(r'\D', '', row[0]))
        logger.info(f"Read {len(processed_numbers)} processed phone numbers from {file_path}")
    except Exception as e:
        logger.error(f"Failed to read processed phone numbers from {file_path}: {e}")
    return processed_numbers

async def send_message(page, phone_number, message, writer):
    """
    Sends a WhatsApp message to a single phone number.

    :param page: pyppeteer page object
    :param phone_number: str, recipient's phone number
    :param message: str, message to send
    :param writer: csv.writer object, to write results
    """
    try:
        logger.info(f"Processing number: {phone_number}")
        chat_url = f'https://web.whatsapp.com/send?phone={phone_number}'
        await page.goto(chat_url, {'waitUntil': 'networkidle0', 'timeout': 30000})  # Wait until network is idle
        await asyncio.sleep(3)  # Wait 3 seconds before sending message

        # Check for invalid number error
        invalid_number_selector = 'div[role="alert"]'
        try:
            invalid_number_element = await page.waitForSelector(invalid_number_selector, timeout=10000)
            if invalid_number_element:
                error_message = await page.evaluate('(element) => element.textContent', invalid_number_element)
                logger.warning(f"Invalid phone number {phone_number}. Skipping. Reason: {error_message}")
                writer.writerow([phone_number, f'Failed - Invalid number: {error_message}'])
                return
        except asyncio.TimeoutError:
            pass  # No invalid number error found, continue

        try:
            message_box = await page.waitForSelector('div[contenteditable="true"][data-tab="10"]', timeout=10000)
        except asyncio.TimeoutError:
            logger.warning(f"Message box not found for {phone_number}. Skipping.")
            writer.writerow([phone_number, 'Failed'])
            return

        # Type and send the message
        for line in message.split('\n'):
            await message_box.type(line)
            await page.keyboard.down('Shift')
            await page.keyboard.press('Enter')
            await page.keyboard.up('Shift')
        await message_box.press('Enter')
        await asyncio.sleep(random.choice([1, 2, 3]))  # Dynamic wait time

        writer.writerow([phone_number, 'Sent successfully'])
        logger.info(f"Message sent successfully to {phone_number}")

    except Exception as e:
        logger.error(f"An error occurred while sending to {phone_number}: {e}")
        writer.writerow([phone_number, f'Failed - {e}'])
        await asyncio.sleep(10)  # Sleep for 10 seconds before retrying the next number

async def send_messages_in_batches(page, phone_numbers, message, writer, batch_size=5):
    """
    Sends WhatsApp messages to phone numbers in batches sequentially to avoid concurrency issues.

    :param page: pyppeteer page object
    :param phone_numbers: list of str, phone numbers to send messages to
    :param message: str, message to send
    :param writer: csv.writer object, to write results
    :param batch_size: int, number of numbers to process in each batch
    """
    total_numbers = len(phone_numbers)
    logger.info(f"Starting to send messages to {total_numbers} numbers.")

    for i in range(0, total_numbers, batch_size):
        batch = phone_numbers[i:i+batch_size]
        logger.info(f"Processing batch {i//batch_size + 1}: {len(batch)} number(s).")

        for phone_number in batch:
            await send_message(page, phone_number, message, writer)
            await asyncio.sleep(1)  # Short pause between messages to mimic human behavior

        logger.info(f"Completed batch {i//batch_size + 1}.")

    logger.info("Completed sending messages to all numbers.")

async def main():
    """
    Main function to parse arguments and initiate message sending.
    """
    parser = argparse.ArgumentParser(description='Send WhatsApp messages to filtered numbers.')
    parser.add_argument('-p', '--phone_csv', default='whatsapp_numbers.csv', help='Path to the filtered WhatsApp numbers CSV file')
    parser.add_argument('-m', '--message_txt', default='message.txt', help='Path to the message text file')
    parser.add_argument('-b', '--batch_size', type=int, default=5, help='Number of numbers to process in each batch')
    args = parser.parse_args()

    input_csv = args.phone_csv
    message_txt = args.message_txt
    batch_size = args.batch_size
    output_csv = 'message_sending_results.csv'

    phone_numbers = read_phone_numbers_from_csv(input_csv)
    message = read_message_from_text(message_txt)

    if not phone_numbers:
        logger.error("No phone numbers to process. Exiting.")
        print("No phone numbers to process. Exiting.")
        return

    # Read processed numbers to skip already successfully sent messages
    processed_numbers = read_processed_numbers(output_csv)
    phone_numbers_to_send = [num for num in phone_numbers if num not in processed_numbers]

    if not phone_numbers_to_send:
        logger.info("All phone numbers have been processed successfully. Exiting.")
        print("All phone numbers have been processed successfully. Exiting.")
        return

    # Initialize or clear the output CSV file with headers if it doesn't exist
    if not os.path.exists(output_csv):
        try:
            with open(output_csv, 'w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow(['Phone Number', 'Status'])
            logger.info(f"Initialized {output_csv} with headers.")
        except Exception as e:
            logger.error(f"Failed to initialize {output_csv}: {e}")
            print(f"Failed to initialize {output_csv}: {e}")
            return

    try:
        with open(output_csv, mode='a', newline='', encoding='utf-8') as result_file:
            writer = csv.writer(result_file)
            async with get_browser_and_page() as page:
                await send_messages_in_batches(page, phone_numbers_to_send, message, writer, batch_size=batch_size)
    except Exception as e:
        logger.critical(f"Unhandled exception during execution: {e}")
        print(f"An error occurred: {e}")
    finally:
        logger.info("Script execution completed.")
        print(f"Message sending results saved to: {output_csv}")
        print(f"Check 'whatsapp_sender.log' for detailed logs.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Unhandled exception in main: {e}")
        print(f"An unhandled exception occurred: {e}")


