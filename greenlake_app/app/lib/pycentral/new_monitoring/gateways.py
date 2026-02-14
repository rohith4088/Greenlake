from ..utils.monitoring_utils import (
    execute_get,
    generate_timestamp_str,
    clean_raw_trend_data,
    merged_dict_to_sorted_list,
)
from ..exceptions import ParameterError
from concurrent.futures import ThreadPoolExecutor, as_completed

GATEWAY_LIMIT = 100
MONITOR_TYPE = "gateways"


class MonitoringGateways:
    @staticmethod
    def get_all_gateways(central_conn, filter_str=None, sort=None):
        """
        Retrieve all gateways, handling pagination.

        Args:
            central_conn (NewCentralBase): Central connection object.
            filter_str (str, optional): Optional filter expression (supported fields documented in API Reference Guide).
            sort (str, optional): Optional sort parameter (supported fields documented in API Reference Guide).

        Returns:
            (list[dict]): List of gateway items.
        """
        gateways = []
        total_gateways = None
        limit = GATEWAY_LIMIT
        next = 1
        # Loop to get all gateways with pagination
        while True:
            response = MonitoringGateways.get_gateways(
                central_conn, limit=limit, next=next
            )
            if total_gateways is None:
                total_gateways = response.get("total", 0)
            gateways.extend(response.get("items", []))
            if len(gateways) >= total_gateways:
                break
            next += 1

        return gateways

    @staticmethod
    def get_gateways(
        central_conn, filter_str=None, sort=None, limit=GATEWAY_LIMIT, next=1
    ):
        """
        Retrieve a single page of gateways, including optional filtering and sorting as supported by the API.

        This method makes an API call to the following endpoint - `GET network-monitoring/v1alpha1/gateways`

        Args:
            central_conn (NewCentralBase): Central connection object.
            filter_str (str, optional): Optional filter expression (supported fields documented in API Reference Guide).
            sort (str, optional): Optional sort parameter (supported fields documented in API Reference Guide).
            limit (int, optional): Number of entries to return (default is 100).
            next (int, optional): Pagination cursor/index for next page (default is 1).

        Returns:
            (dict):  API response containing keys like 'items', 'total', and 'next'.
        """
        params = {
            "limit": limit,
            "next": next,
            "filter": filter_str,
            "sort": sort,
        }

        path = MONITOR_TYPE
        return execute_get(central_conn, endpoint=path, params=params)

    @staticmethod
    def get_cluster_leader_details(central_conn, cluster_name):
        """
        Get details for the leader of a gateway cluster.

        This method makes an API call to the following endpoint - `GET network-monitoring/v1alpha1/clusters/{cluster_name}/leader`

        Args:
            central_conn (NewCentralBase): Central connection object.
            cluster_name (str): Name of the cluster.

        Returns:
            (dict): API response for the cluster leader.

        Raises:
            ParameterError: If cluster_name is missing or not a string.
        """
        if not cluster_name or not isinstance(cluster_name, str):
            raise ParameterError(
                "cluster_name is required and must be a string"
            )
        path = f"clusters/{cluster_name}/leader"

        return execute_get(central_conn, endpoint=path)

    @staticmethod
    def get_gateway_details(central_conn, serial_number):
        """
        Get details for a specific gateway.

        This method makes an API call to the following endpoint - `GET network-monitoring/v1alpha1/gateways/{serial_number}`

        Args:
            central_conn (NewCentralBase): Central connection object.
            serial_number (str): Serial number of the gateway.

        Returns:
            (dict): API response with gateway details.

        Raises:
            ParameterError: If central_conn is None or serial_number is missing/invalid.
        """
        MonitoringGateways._validate_central_conn_and_serial(
            central_conn, serial_number
        )
        path = f"{MONITOR_TYPE}/{serial_number}"
        return execute_get(central_conn, endpoint=path)

    @staticmethod
    def get_gateway_interfaces(
        central_conn,
        serial_number,
        filter_str=None,
        sort=None,
        limit=GATEWAY_LIMIT,
        next=1,
    ):
        """
        Retrieve port/interface details for a gateway.

        This method makes an API call to the following endpoint - `GET network-monitoring/v1alpha1/gateways/{serial_number}/ports`

        Args:
            central_conn (NewCentralBase): Central connection object.
            serial_number (str): Serial number of the gateway.
            filter_str (str, optional): Optional filter expression (supported fields documented in API Reference Guide).
            sort (str, optional): Optional sort parameter (supported fields documented in API Reference Guide).
            limit (int, optional): Number of entries to return (default is 100).
            next (int, optional): Pagination cursor/index for next page (default is 1).

        Returns:
            (dict): API response for the ports endpoint.

        Raises:
            ParameterError: If central_conn is None or serial_number is missing/invalid.
        """
        MonitoringGateways._validate_central_conn_and_serial(
            central_conn, serial_number
        )
        params = {
            "limit": limit,
            "next": next,
            "filter": filter_str,
            "sort": sort,
        }
        path = f"{MONITOR_TYPE}/{serial_number}/ports"
        return execute_get(central_conn, endpoint=path, params=params)

    @staticmethod
    def get_gateway_lan_tunnels(
        central_conn,
        serial_number,
        filter_str=None,
        sort=None,
        limit=GATEWAY_LIMIT,
        next=1,
    ):
        """
        Retrieve LAN tunnel details for a gateway.

        This method makes an API call to the following endpoint - `GET network-monitoring/v1alpha1/gateways/{serial_number}/lan-tunnels`

        Args:
            central_conn (NewCentralBase): Central connection object.
            serial_number (str): Serial number of the gateway.
            filter_str (str, optional): Optional filter expression (supported fields documented in API Reference Guide).
            sort (str, optional): Optional sort parameter (supported fields documented in API Reference Guide).
            limit (int, optional): Number of entries to return (default is 100).
            next (int, optional): Pagination cursor/index for next page (default is 1).

        Returns:
            (dict): API response for the lan-tunnels endpoint.

        Raises:
            ParameterError: If central_conn is None or serial_number is missing/invalid.
        """
        MonitoringGateways._validate_central_conn_and_serial(
            central_conn, serial_number
        )
        params = {
            "limit": limit,
            "next": next,
            "filter": filter_str,
            "sort": sort,
        }
        path = f"{MONITOR_TYPE}/{serial_number}/lan-tunnels"
        return execute_get(central_conn, endpoint=path, params=params)

    @staticmethod
    def get_gateway_stats(
        central_conn,
        serial_number,
        start_time=None,
        end_time=None,
        duration=None,
        return_raw_response=False,
    ):
        """
        Collect multiple statistics (like CPU, memory, WAN availability) for a gateway for the specified time range. Default is to return sorted trend statistics for last 3 hours.

        Args:
            central_conn (NewCentralBase): Central connection object.
            serial_number (str): Serial number of the gateway.
            start_time (int, optional): Start time (epoch seconds) for range queries.
            end_time (int, optional): End time (epoch seconds) for range queries.
            duration (str|int, optional): Duration string (e.g. '5m') or seconds for relative queries.
            return_raw_response (bool, optional): If True, return raw per-metric API responses.

        Returns:
            (list|dict): If return_raw_response is True returns raw list of responses; otherwise returns merged, sorted trend statistics for the gateway.

        Raises:
            ParameterError: If central_conn is None or serial_number is missing/invalid.
            RuntimeError: If any of the parallel metric requests fail.
        """
        MonitoringGateways._validate_central_conn_and_serial(
            central_conn, serial_number
        )

        # dispatch the three metric calls in parallel; helper methods handle timestamp logic
        funcs = [
            MonitoringGateways.get_gateway_cpu_utilization,
            MonitoringGateways.get_gateway_memory_utilization,
            MonitoringGateways.get_gateway_wan_availability,
        ]

        raw_results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_map = {
                executor.submit(
                    func,
                    central_conn,
                    serial_number,
                    start_time,
                    end_time,
                    duration,
                ): func
                for func in funcs
            }
            for fut in as_completed(future_map):
                func = future_map[fut]
                try:
                    resp = fut.result()
                    if isinstance(resp, list) is True and len(resp) == 1:
                        resp = resp[0]
                    raw_results.append(resp)
                except Exception as e:
                    # propagate the error for the caller to handle, but include which call failed
                    raise RuntimeError(
                        f"{func.__name__} metrics request failed: {e}"
                    ) from e

        if return_raw_response:
            return raw_results

        data = {}
        for resp in raw_results:
            if not isinstance(resp, dict):
                continue
            data = clean_raw_trend_data(resp, data=data)
        data = merged_dict_to_sorted_list(data)
        return data

    def get_latest_gateway_stats(
        central_conn,
        serial_number,
    ):
        """
        Get the latest gateway statistics (like CPU, memory, WAN availability)

        Args:
            central_conn (NewCentralBase): Central connection object.
            serial_number (str): Serial number of the gateway.

        Returns:
            (dict): Latest statistics for the gateway, or empty dict if none exist.

        Raises:
            ParameterError: If central_conn is None or serial_number is missing/invalid.
        """
        MonitoringGateways._validate_central_conn_and_serial(
            central_conn, serial_number
        )
        stats = MonitoringGateways.get_gateway_stats(
            central_conn, serial_number, duration="5m"
        )
        if stats and isinstance(stats, list) and len(stats) > 0:
            return stats[-1]
        else:
            return {}

    @staticmethod
    def get_gateway_cpu_utilization(
        central_conn,
        serial_number,
        start_time=None,
        end_time=None,
        duration=None,
    ):
        """
        Retrieve CPU utilization trends for a gateway.

        This method makes an API call to the following endpoint - `GET network-monitoring/v1alpha1/gateways/{serial_number}/cpu-utilization-trends`

        Args:
            central_conn (NewCentralBase): Central connection object.
            serial_number (str): Serial number of the gateway.
            start_time (int, optional): Start time (epoch seconds) for range queries.
            end_time (int, optional): End time (epoch seconds) for range queries.
            duration (str|int, optional): Duration string or seconds for relative queries.

        Returns:
            (dict|list): API response for cpu-utilization-trends.

        Raises:
            ParameterError: If central_conn is None or serial_number is missing/invalid.
        """
        MonitoringGateways._validate_central_conn_and_serial(
            central_conn, serial_number
        )
        if start_time is None and end_time is None and duration is None:
            return execute_get(
                central_conn,
                endpoint=f"{MONITOR_TYPE}/{serial_number}/cpu-utilization-trends",
            )

        return execute_get(
            central_conn,
            endpoint=f"{MONITOR_TYPE}/{serial_number}/cpu-utilization-trends",
            params={
                "filter": generate_timestamp_str(
                    start_time=start_time, end_time=end_time, duration=duration
                )
            },
        )

    @staticmethod
    def get_gateway_memory_utilization(
        central_conn,
        serial_number,
        start_time=None,
        end_time=None,
        duration=None,
    ):
        """
        Retrieve memory utilization trends for a gateway.

        This method makes an API call to the following endpoint - `GET network-monitoring/v1alpha1/gateways/{serial_number}/memory-utilization-trends`

        Args:
            central_conn (NewCentralBase): Central connection object.
            serial_number (str): Serial number of the gateway.
            start_time (int, optional): Start time (epoch seconds) for range queries.
            end_time (int, optional): End time (epoch seconds) for range queries.
            duration (str|int, optional): Duration string or seconds for relative queries.

        Returns:
            (dict|list): API response for memory-utilization-trends.

        Raises:
            ParameterError: If central_conn is None or serial_number is missing/invalid.
        """
        MonitoringGateways._validate_central_conn_and_serial(
            central_conn, serial_number
        )
        if start_time is None and end_time is None and duration is None:
            return execute_get(
                central_conn,
                endpoint=f"{MONITOR_TYPE}/{serial_number}/memory-utilization-trends",
            )

        return execute_get(
            central_conn,
            endpoint=f"{MONITOR_TYPE}/{serial_number}/memory-utilization-trends",
            params={
                "filter": generate_timestamp_str(
                    start_time=start_time, end_time=end_time, duration=duration
                )
            },
        )

    @staticmethod
    def get_gateway_wan_availability(
        central_conn,
        serial_number,
        start_time=None,
        end_time=None,
        duration=None,
    ):
        """
        Retrieve WAN availability trends for a gateway.

        This method makes an API call to the following endpoint - `GET network-monitoring/v1alpha1/gateways/{serial_number}/wan-availability-trends`

        Args:
            central_conn (NewCentralBase): Central connection object.
            serial_number (str): Serial number of the gateway.
            start_time (int, optional): Start time (epoch seconds) for range queries.
            end_time (int, optional): End time (epoch seconds) for range queries.
            duration (str|int, optional): Duration string or seconds for relative queries.

        Returns:
            (dict|list): API response for wan-availability-trends.

        Raises:
            ParameterError: If central_conn is None or serial_number is missing/invalid.
        """
        MonitoringGateways._validate_central_conn_and_serial(
            central_conn, serial_number
        )
        if start_time is None and end_time is None and duration is None:
            return execute_get(
                central_conn,
                endpoint=f"{MONITOR_TYPE}/{serial_number}/wan-availability-trends",
            )

        return execute_get(
            central_conn,
            endpoint=f"{MONITOR_TYPE}/{serial_number}/wan-availability-trends",
            params={
                "filter": generate_timestamp_str(
                    start_time=start_time, end_time=end_time, duration=duration
                )
            },
        )

    @staticmethod
    def get_tunnel_health_summary(central_conn, serial_number):
        """
        Retrieve LAN tunnels health summary for a gateway.

        This method makes an API call to the following endpoint - `GET network-monitoring/v1alpha1/gateways/{serial_number}/lan-tunnels-health-summary`

        Args:
            central_conn (NewCentralBase): Central connection object.
            serial_number (str): Serial number of the gateway.

        Returns:
            (dict): API response for lan-tunnels-health-summary.

        Raises:
            ParameterError: If central_conn is None or serial_number is missing/invalid.
        """
        MonitoringGateways._validate_central_conn_and_serial(
            central_conn, serial_number
        )
        path = f"{MONITOR_TYPE}/{serial_number}/lan-tunnels-health-summary"
        return execute_get(central_conn, endpoint=path)

    def _validate_central_conn_and_serial(central_conn, serial_number):
        """
        Validate central_conn and serial_number.

        Args:
            central_conn: Central connection object (required).
            serial_number (str): Device serial number (required).

        Raises:
            ParameterError: If central_conn is None or serial_number is missing/invalid.

        Note:
            Internal SDK function
        """
        if central_conn is None:
            raise ParameterError("central_conn is required")
        # Optionally, check for expected type of central_conn here if needed
        if not isinstance(serial_number, str) or not serial_number:
            raise ParameterError(
                "serial_number is required and must be a string"
            )
