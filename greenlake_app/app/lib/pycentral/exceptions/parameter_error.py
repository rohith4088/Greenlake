# (C) Copyright 2025 Hewlett Packard Enterprise Development LP.
# MIT License

from pycentral.exceptions.verification_error import VerificationError


class ParameterError(VerificationError):
    """Exception raised when invalid parameters are passed to functions.

    This exception is a subclass of VerificationError and is used to indicate
    that one or more parameters provided to a function are invalid, missing,
    or do not meet the required constraints.

    Attributes:
        base_msg (str): The base error message for this exception type.

    Example:
        ```python
        >>> raise ParameterError(f"name must be a valid string found {type(name)}")
        ParameterError: "PARAMETER ERROR: name must be a valid string found <class 'int'>"
        ```
    """

    base_msg = "PARAMETER ERROR"
