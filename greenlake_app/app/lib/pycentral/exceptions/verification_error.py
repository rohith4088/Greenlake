# (C) Copyright 2025 Hewlett Packard Enterprise Development LP.
# MIT License

from pycentral.exceptions.pycentral_error import PycentralError


class VerificationError(PycentralError):
    """Exception raised when verification checks fail during pycentral operations.

    This exception is raised when verification checks of values fail prior to API execution.
    It serves as a base class for more specific verification-related exceptions.

    Attributes:
        base_msg (str): The base error message for this exception type.
        message (str): Detailed error message describing the verification failure.
        module (str): The module or context where the verification error occurred.

    Example:
        ```python
        >>> raise VerificationError(err_str, " get_resource_str() failed")
        VerificationError: "VERIFICATION ERROR: Missing self.object_data['resource'] attribute DETAIL: get_resource_str() failed"
        ```
    """

    base_msg = "VERIFICATION ERROR"

    def __init__(self, *args):
        self.message = None
        self.module = None
        if args:
            self.module = args[0]
            if len(args) > 1:
                self.message = ", ".join(str(a) for a in args[1:])

    def __str__(self):
        msg_parts = [self.base_msg]
        if self.module:
            if self.message:
                msg_parts.append("{0} DETAIL".format(self.module))
                msg_parts.append(self.message)
            else:
                msg_parts.append(self.module)
        msg = ": ".join(msg_parts)
        return repr(msg)
