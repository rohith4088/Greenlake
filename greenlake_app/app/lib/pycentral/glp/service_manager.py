# (C) Copyright 2025 Hewlett Packard Enterprise Development LP.
# MIT License

from ..utils import GLP_URLS, generate_url


class ServiceManager(object):
    def get_application_id_and_region(self, conn, application_name, region):
        """Retrieve the application ID and API region name for a specified application and region.


        Args:
            conn (NewCentralBase): pycentral base connection object
            application_name (str): name of the application to search for.
            region (str): The region (UI name) where the application is deployed.

        Returns:
            (dict): Dictionary containing the application ID and API region name if found, otherwise None.
        """
        if not application_name or not region:
            conn.logger.error("Application name or region cannot be empty.")
            return None

        resp = self.get_service_manager_by_region(conn)
        if resp["code"] != 200:
            conn.logger.error(
                f"Error fetching list of service manager(applications) by region: {resp['code']} - {resp['msg']}"
            )
            return None

        region_service_manager_mapping = (
            self._generate_application_region_mapping(resp["msg"]["items"])
        )
        if region not in region_service_manager_mapping.keys():
            conn.logger.error(
                f"Unable to find region with name {region}. \nValid regions are {', '.join(region_service_manager_mapping.keys())}"
            )
            return None
        api_region_name = region_service_manager_mapping[region]["id"]

        region_service_managers = list(
            region_service_manager_mapping[region]["serviceManagers"].keys()
        )
        if application_name not in region_service_managers:
            conn.logger.error(
                f"Unable to find service manager with name {application_name}. \nValid service managers(applications) in region {region} are {', '.join(region_service_managers)}"
            )
            return None
        service_manager_id = region_service_manager_mapping[region][
            "serviceManagers"
        ][application_name]

        resp = self.get_service_manager_provisions(conn)
        if resp["code"] != 200:
            conn.logger.error(
                f"Error fetching list of service manager provisions (installed applications): {resp['code']} - {resp['msg']}"
            )
            return None
        for provisioned_service in resp["msg"]["items"]:
            if (
                service_manager_id
                == provisioned_service["serviceManager"]["id"]
                and provisioned_service["region"] == api_region_name
            ):
                conn.logger.info(
                    f"Successfully verified installation of service manager {application_name} in region {region}."
                )
                return {
                    "id": service_manager_id,
                    "region": api_region_name,
                }

        conn.logger.error(
            f"Unable to find service manager(application) with name {application_name} in region {region}."
        )
        return None

    def get_service_manager_provisions(self, conn, limit=2000, offset=0):
        """Retrieve all provisioned services in GLP workspace.

        Args:
            conn (NewCentralBase): pycentral base connection object
            limit (int, optional): Specify the maximum number of entries per page. Maximum value accepted is 2000.
            offset (int, optional): Specify pagination offset. Defines how many pages to skip before returning results. Default is 0.

        Returns:
            (dict): API response containing provisioned services.
        """
        conn.logger.info("Getting provisioned services in GLP workspace")
        path = generate_url(
            GLP_URLS["SERVICE_MANAGER_PROVISIONS"], category="service_catalog"
        )

        params = {
            "limit": limit,
            "offset": offset,
        }

        resp = conn.command(
            api_method="GET", api_path=path, api_params=params, app_name="glp"
        )
        return resp

    def get_service_manager_by_region(self, conn):
        """Get the region mapping for the service manager.

        Args:
            conn (NewCentralBase): pycentral base connection object

        Returns:
            (dict): API response containing service managers by region.
        """
        conn.logger.info("Getting services managers by region in GLP")
        path = generate_url(
            GLP_URLS["SERVICE_MANAGER_BY_REGION"], category="service_catalog"
        )

        resp = conn.command(api_method="GET", api_path=path, app_name="glp")
        return resp

    def _generate_application_region_mapping(self, service_manager_list):
        """Generate mappings for service managers and regions.

        Args:
            service_manager_list (list): List of dictionaries where each dictionary represents a region
                and contains its name, ID, and associated service managers.

        Returns:
            (dict): Dictionary mapping region names to their IDs and service managers.
        """
        region_map = {}
        for region in service_manager_list:
            region_map[region["regionName"]] = {"id": region["id"]}
            region_map[region["regionName"]]["serviceManagers"] = {
                serviceManager["name"]: serviceManager["id"]
                for serviceManager in region["serviceManagers"]
            }

        return region_map

    def get_service_managers(self, conn, limit=2000, offset=0):
        """Retrieve all available service managers in GLP.

        Args:
            conn (NewCentralBase): pycentral base connection object
           limit (int, optional): Specify the maximum number of entries per page. Maximum value accepted is 2000.
           offset (int, optional): Specify pagination offset. Defines how many pages to skip before returning results.

        Returns:
            (dict): API response containing service managers.
        """
        conn.logger.info("Getting service managers in GLP")
        path = generate_url(
            GLP_URLS["SERVICE_MANAGER"], category="service_catalog"
        )

        params = {
            "limit": limit,
            "offset": offset,
        }

        resp = conn.command(
            api_method="GET", api_path=path, api_params=params, app_name="glp"
        )
        return resp
