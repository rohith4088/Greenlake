# (C) Copyright 2025 Hewlett Packard Enterprise Development LP.
# MIT License

from pycentral.exceptions.pycentral_error import PycentralError


class ResponseError(PycentralError):
    """Exception raised when an API response indicates an error.

    This exception is raised when the API returns an error response, such as
    HTTP error codes (4xx, 5xx) or when the response content indicates a failure.

    Attributes:
        base_msg (str): The base error message for this exception type.
        message (str): Detailed error message describing the response failure.
        response (dict): The API response object containing error details.

    Example:
        ```python
        >>> raise ResponseError({"code": 404, "msg": "Not found"}, "Resource does not exist")
        ResponseError: 'RESPONSE ERROR: Resource does not exist: Response: {"code": 404, "msg": "Not found"}'
        ```
    """

    base_msg = "RESPONSE ERROR"

    def __init__(self, *args):
        self.message = None
        self.response = None
        if args:
            self.response = args[0]
            if len(args) > 1:
                self.message = ", ".join(str(a) for a in args[1:])
        else:
            self.message = None

    def __str__(self):
        msg_parts = [self.base_msg]
        if self.message:
            msg_parts.append(str(self.message))
        if self.response:
            msg_parts.append("Response")
            msg_parts.append(str(self.response))
        msg = ": ".join(msg_parts)
        return repr(msg)
