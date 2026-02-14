# (C) Copyright 2025 Hewlett Packard Enterprise Development LP.
# MIT License

from typing import Any


class PycentralError(Exception):
    """Base exception class for all pycentral-specific errors.

    This exception serves as the base class for all custom exceptions in the pycentral library.
    It provides common functionality for error handling and message formatting.

    Attributes:
        base_msg (str): The base error message for this exception type.
        message (str): The complete formatted error message.
        response (dict): The API response associated with the error, if applicable.

    Example:
        ```python
        >>> raise PycentralError("An unexpected error occurred")
        PycentralError: 'PYCENTRAL ERROR, An unexpected error occurred'
        ```
    """

    base_msg = "PYCENTRAL ERROR"

    def __init__(self, *args):
        self.message = ", ".join(
            (
                self.base_msg,
                *(str(a) for a in args),
            )
        )
        self.response = None

    def __setattr__(self, name: str, value: Any) -> None:
        return super().__setattr__(name, value)

    def __str__(self):
        return repr(self.message)

    def set_response(self, response):
        self.response = response
