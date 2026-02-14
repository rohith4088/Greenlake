import ssl
import time
import websocket
from .events.audit import audit_trail_pb2
from .events.location import location_pb2
from .events.location_analytics import location_analytics_pb2
from .events.geofence import geofence_pb2
from .events.event import event_pb2
from google.protobuf.json_format import MessageToDict
import threading
import signal

# Supported Events and their corresponding endpoints and decoders
SUPPORTED_EVENTS = {
    "audit-trail-events": audit_trail_pb2.AuditTrail,
    "location": location_pb2.StreamLocationMessage,
    "rssi-events": location_analytics_pb2.RssiEvent,
    "geofence": geofence_pb2.StreamGeofenceMessage,
}


class Streaming:
    """
    Minimal WebSocket streaming client for HPE Aruba Networking Central.

    Responsibilities:
        - Build the WSS URL for the selected streaming endpoint.
        - Maintain a single WebSocket connection with optional auto-reconnect.
        - Decode protobuf payloads and deliver them to a user callback.
        - Allow graceful stop and cleanup of the WebSocket connection.

    Args:
        central_conn (NewCentralBase): Central connection object, used for
            tokens, base URL and logging.
        event (str): Streaming event name. Must be one of the keys in
            SUPPORTED_EVENTS (for example, "audit-trail-events").
        reconnect_delay (int, optional): Delay in seconds before attempting
            to reconnect after an unexpected disconnection. Defaults to 5.
        filters (str | list[str], optional): Either a single filter string or a list of filter strings.
            If a list is provided, its elements will be joined with commas to form the header value.

    Raises:
        ValueError: If an unsupported event is provided or filters are of an unexpected type.
    """

    def __init__(self, central_conn, event, reconnect_delay=5, filters=None):
        self.central_conn = central_conn
        if event not in SUPPORTED_EVENTS:
            raise ValueError(
                f"Unsupported event: {event}. Supported events: {list(SUPPORTED_EVENTS.keys())}"
            )
        self.endpoint = event
        self.decoder = SUPPORTED_EVENTS[event]
        self.reconnect_delay = reconnect_delay
        self.logger = central_conn.logger
        self.ws = None
        self.stop_streaming = False
        self.user_callback = None

        self.stop_event = threading.Event()  # Thread-safe stop flag
        self._original_sigint = None

        self.filters = None
        if filters is not None:
            if isinstance(filters, str):
                self.filters = filters
            elif isinstance(filters, list):
                if not all(isinstance(f, str) for f in filters):
                    raise ValueError("All filter values must be strings.")
                self.filters = ",".join(filters)
            else:
                raise ValueError(
                    "Filters must be a string or a list of strings."
                )

    def _on_message(self, ws, message):
        """Handle incoming WebSocket messages.

        The raw message is first parsed as a CloudEvent protobuf and then
        decoded using the event-specific protobuf decoder. The decoded
        message is converted to a dict and passed to the user callback
        if provided, otherwise logged.

        Args:
            ws (websocket.WebSocketApp): WebSocket instance (unused).
            message (bytes): Raw protobuf-encoded message payload.
        """
        event_data = event_pb2.CloudEvent()
        event_data.ParseFromString(message)

        decoded_message = self.decoder()
        decoded_message.ParseFromString(event_data.proto_data.value)
        json_message = MessageToDict(
            decoded_message, preserving_proto_field_name=True
        )
        if self.user_callback:
            try:
                self.user_callback(json_message)
            except Exception as callback_error:
                self.logger.error(
                    f"Callback raised an error: {callback_error}"
                )
        else:
            self.logger.info(f"{decoded_message}")

    def _on_error(self, ws, error):
        """Handle WebSocket errors.

        If a 401-like error is detected, this method attempts to refresh
        the access token via the Central connection. If token refresh
        fails, streaming is stopped.

        Args:
            ws (websocket.WebSocketApp): WebSocket instance (unused).
            error (Exception|str): Error raised by the WebSocket client.
        """
        self.logger.error(f"WebSocket error: {error}")
        if "401" in str(error):
            try:
                self.central_conn.handle_expired_token("new_central")
                self.logger.info("Token refreshed. Will reconnect.")
            except Exception as refresh_error:
                self.logger.error(f"Token refresh failed: {refresh_error}")
                self.stop_streaming = True

    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close events.

        Args:
            ws (websocket.WebSocketApp): WebSocket instance (unused).
            close_status_code (int|None): WebSocket close status code.
            close_msg (str|None): Close reason/message from server.
        """
        self.logger.info(
            f"Disconnected (code: {close_status_code}, msg: {close_msg})"
        )

    def _on_open(self, ws):
        """Handle WebSocket open events.

        Args:
            ws (websocket.WebSocketApp): WebSocket instance.
        """
        self.logger.info(
            f"Connection established. Listening for {self.endpoint}..."
        )
        if self.filters:
            self.logger.info(f"Applied filters: {self.filters}")

    def _get_wss_url(self):
        """Build the WebSocket Secure (WSS) URL for the configured event.

        The URL is constructed using the Central base URL from the
        connection object and the event-specific endpoint.

        Returns:
            str: Fully qualified WSS URL for the streaming endpoint.
        """
        base_url = self.central_conn.token_info["new_central"][
            "base_url"
        ].rstrip("/")
        if base_url.startswith("https://"):
            ws_base = base_url.replace("https://", "wss://")
        else:
            ws_base = f"wss://{base_url}"
        return f"{ws_base}/network-services/v1alpha1/{self.endpoint}"

    def stream(self, callback=None):
        """Start streaming messages for the configured event.

        This method establishes the WebSocket connection, listens for
        messages, and optionally auto-reconnects on unexpected closure
        until `stop()` is called or a fatal error occurs.

        Args:
            callback (callable, optional): Function to be invoked for each
                decoded message. It must accept a single argument
                (dict) representing the decoded protobuf message.
                If not provided, decoded messages are logged.

        Raises:
            KeyboardInterrupt: If interrupted by the user (Ctrl+C) while
                streaming in a foreground loop.
        """
        self.user_callback = callback
        self.stop_event.clear()
        self.stop_streaming = False

        self._setup_signal_handler()

        try:
            while not self.stop_event.is_set():
                try:
                    url = self._get_wss_url()
                    token = self.central_conn.token_info["new_central"][
                        "access_token"
                    ]
                    headers = [f"Authorization: Bearer {token}"]
                    if self.filters:
                        headers.append(f"event-types: {self.filters}")
                    self.ws = websocket.WebSocketApp(
                        url,
                        header=headers,
                        on_open=self._on_open,
                        on_close=self._on_close,
                        on_error=self._on_error,
                        on_message=self._on_message,
                    )

                    self.logger.info(f"Connecting to {url}...")
                    self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

                    if self.stop_event.is_set():
                        break

                    self.logger.info(
                        f"Connection closed. Reconnecting in {self.reconnect_delay}s…"
                    )
                    if self.stop_event.wait(timeout=self.reconnect_delay):
                        break

                except Exception as e:
                    self.logger.error(
                        f"Unexpected error in streaming loop: {e}"
                    )
                    if self.ws:
                        self.ws.close()
                    if self.stop_event.wait(timeout=self.reconnect_delay):
                        break
        finally:
            self._restore_signal_handler()
            self._cleanup()

    def stop(self):
        """Request the streaming loop to stop and close the WebSocket.

        This method can be called from another thread or from within
        the user callback to stop streaming gracefully.
        """
        self.logger.info("Stop requested.")
        self.stop_event.set()
        self.stop_streaming = True
        if self.ws:
            self.ws.close()
        self._cleanup()

    def _cleanup(self):
        """Clean up WebSocket resources after streaming stops.

        Ensures the WebSocket is closed and internal references are
        reset. This method is idempotent.
        """
        if self.ws:
            try:
                self.ws.close()
            finally:
                self.ws = None
        self.logger.info("Cleanup complete.")

    def _setup_signal_handler(self):
        """Set up signal handler for graceful shutdown on Ctrl+C."""

        def signal_handler(signum, frame):
            self.logger.info("Received interrupt signal. Stopping...")
            self.stop()

        self._original_sigint = signal.signal(signal.SIGINT, signal_handler)

    def _restore_signal_handler(self):
        """Restore the original signal handler."""
        if self._original_sigint is not None:
            signal.signal(signal.SIGINT, self._original_sigint)
            self._original_sigint = None
