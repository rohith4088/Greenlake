# (C) Copyright 2025 Hewlett Packard Enterprise Development LP.
# MIT License

from .base_utils import console_logger

import time

DEVICE_LIMIT = 20
SUB_LIMIT = 5

logger = console_logger("RATE LIMIT CHECK")


def rate_limit_check(input_array, input_size_limit, rate_per_minute):
    """Check and handle rate limiting for API requests.

    Splits the input array into smaller chunks and calculates wait time
    to prevent rate limit errors.

    Args:
        input_array (list): Array of items to process.
        input_size_limit (int): Maximum size of each chunk.
        rate_per_minute (int): Maximum number of requests allowed per minute.

    Returns:
        (tuple): A tuple containing:

            - queue (list): List of sub-arrays split by input_size_limit.
            - wait_time (float): Seconds to wait between requests (0 if no wait needed).
    """
    print("Attempting to bypass rate limit")
    queue = []
    wait_time = []

    for i in range(0, len(input_array), input_size_limit):
        sub_array = input_array[i : i + input_size_limit]
        queue.append(sub_array)

    if len(queue) > rate_per_minute:
        wait_time = 60 / rate_per_minute
        print(
            "Array size exceeded,",
            wait_time,
            "second wait timer implemented per request to prevent errors",
        )
        print("Loading ...")
    else:
        wait_time = 0

    return queue, wait_time


def check_progress(conn, id, module_instance, limit=None):
    """Check progress of an async GLP API operation.

    Polls the status of an asynchronous operation until it completes,
    times out, or fails.

    Args:
        conn (NewCentralBase): PyCentral base connection object.
        id (str): Async transaction ID.
        module_instance (object): Instance of the module class (Devices or Subscriptions).
        limit (int, optional): Rate limit for the module. If None, uses default
            based on module type (20 for Devices, 5 for Subscriptions).

    Returns:
        (tuple): A tuple containing:

            - success (bool): True if operation succeeded, False otherwise.
            - status (dict): API response with operation status details.

    Raises:
        ValueError: If module_instance is not an instance of Devices or Subscriptions.
    """
    if limit is None:
        if module_instance.__class__.__name__ == "Devices":
            limit = DEVICE_LIMIT
        elif module_instance.__class__.__name__ == "Subscriptions":
            limit = SUB_LIMIT
        else:
            raise ValueError(
                "module_instance must be an instance of Devices or Subscription"
            )

    updated = False
    while not updated:
        status = module_instance.get_status(conn, id)
        if status["code"] != 200:
            conn.logger.error(
                f"Bad request for get async status with transaction {id}!"
            )
            return (False, status)
        elif status["msg"]["status"] == "SUCCEEDED":
            updated = True
            return (True, status)
        elif status["msg"]["status"] == "TIMEOUT":
            updated = True
            conn.logger.error(
                f"Async operation timed out for transaction {id}!"
            )
            return (False, status)
        elif status["msg"]["status"] == "FAILED":
            updated = True
            conn.logger.error(f"Async operation failed for transaction {id}!")
            return (False, status)
        else:
            # Sleep time calculated by async rate limit.
            sleep_time = 60 / limit
            time.sleep(sleep_time)
