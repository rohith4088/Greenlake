# (C) Copyright 2025 Hewlett Packard Enterprise Development LP.
# MIT License

from ..utils import SCOPE_URLS, generate_url


class ScopeMaps:
    def __init__(self):
        pass

    # ? Should central_conn be stored in self
    def get(self, central_conn):
        """Perform a GET call to retrieve data for the Global Scope Map.

        Args:
            central_conn (NewCentralBase): Established Central connection object

        Returns:
            (list): List of scope map dictionaries if success, empty list otherwise
        """
        scope_maps_list = []
        api_method = "GET"
        api_path = generate_url(SCOPE_URLS["SCOPE-MAPS"])
        resp = central_conn.command(api_method=api_method, api_path=api_path)
        if resp["code"] == 200:
            for mapping in resp["msg"]["scope-map"]:
                mapping["scope-name"] = int(mapping["scope-name"])
            scope_maps_list = resp["msg"]["scope-map"]
        else:
            central_conn.logger.error(
                f"Unable to fetch scope maps data. Error code - {resp['code']}.\n Error Description - {resp['msg']}"
            )
        return scope_maps_list

    # ? should this return a value or set a value to self?
    def get_scope_assigned_profiles(self, central_conn, scope_id):
        """Performs a GET call to retrieve Global Scope Map then finds matching scope.

        Args:
            central_conn (NewCentralBase): Established Central connection object
            scope_id (int): ID of the scope to be matched on

        Returns:
            (list): List of assigned profile dictionaries for the scope
        """
        assigned_profiles = []
        mappings = self.get(central_conn=central_conn)
        if mappings:
            for mapping in mappings:
                if mapping["scope-name"] == scope_id:
                    assigned_profiles.append(mapping)
        for profile in assigned_profiles:
            profile.pop("scope-name")

    def associate_profile_to_scope(
        self, central_conn, scope_id, profile_name, persona
    ):
        """Performs a POST call to associate a profile with device persona to the provided scope.

        Args:
            central_conn (NewCentralBase): Established Central connection object
            scope_id (int or str): ID of the scope to associate the profile
            profile_name (str): Name of the profile to be assigned
            persona (str or list): Device persona(s) to be associated with the profile.
                Valid values: SERVICE_PERSONA, HYBRID_NAC, CORE_SWITCH, BRIDGE,
                CAMPUS_AP, IOT, MOBILITY_GW, AGG_SWITCH, BRANCH_GW, VPNC,
                ACCESS_SWITCH, MICROBRANCH_AP, or "ALL"

        Returns:
            (dict): JSON Data of returned response from POST call
        """
        api_method = "POST"
        api_path = generate_url(SCOPE_URLS["SCOPE-MAPS"])
        valid_personas = [
            "SERVICE_PERSONA",
            "HYBRID_NAC",
            "CORE_SWITCH",
            "BRIDGE",
            "CAMPUS_AP",
            "IOT",
            "MOBILITY_GW",
            "AGG_SWITCH",
            "BRANCH_GW",
            "VPNC",
            "ACCESS_SWITCH",
            "MICROBRANCH_AP",
        ]
        if isinstance(persona, list) or "ALL" in persona:
            if "ALL" in persona:
                persona = valid_personas
            for p in persona:
                if p not in valid_personas:
                    central_conn.logger.error(
                        f"{p} is not a valid device persona"
                        f"Unable to assign profile {profile_name} to "
                        f"{scope_id}"
                    )
                api_data = {
                    "scope-map": [
                        {
                            "scope-name": str(scope_id),
                            "persona": p,
                            "resource": profile_name,
                        }
                    ]
                }
                resp = central_conn.command(
                    api_method=api_method, api_path=api_path, api_data=api_data
                )
                if resp["code"] == 200:
                    central_conn.logger.info(
                        f"Successfully assigned profile {profile_name} to"
                        f" {scope_id} with {p} device persona"
                    )
        else:
            api_data = {
                "scope-map": [
                    {
                        "scope-name": str(scope_id),
                        "persona": persona,
                        "resource": profile_name,
                    }
                ]
            }

            resp = central_conn.command(
                api_method=api_method, api_path=api_path, api_data=api_data
            )

            if resp["code"] == 200:
                central_conn.logger.info(
                    f"Successfully assigned profile {profile_name} to "
                    f"{scope_id} with {persona} device persona"
                )
        return resp

    def unassociate_profile_from_scope(
        self, central_conn, scope_id, profile_name, persona
    ):
        """Performs a DELETE call to unassign a profile with device persona from the provided scope.

        Args:
            central_conn (NewCentralBase): Established Central connection object
            scope_id (int or str): ID of the scope to unassociate the profile from
            profile_name (str): Name of the profile to be unassigned
            persona (str or list): Device persona(s) to be unassociated from the profile.
                Valid values: SERVICE_PERSONA, HYBRID_NAC, CORE_SWITCH, BRIDGE,
                CAMPUS_AP, IOT, MOBILITY_GW, AGG_SWITCH, BRANCH_GW, VPNC,
                ACCESS_SWITCH, MICROBRANCH_AP, or "ALL"

        Returns:
            (dict): JSON Data of returned response from DELETE call
        """
        api_method = "DELETE"
        api_path = generate_url(SCOPE_URLS["SCOPE-MAPS"])
        valid_personas = [
            "SERVICE_PERSONA",
            "HYBRID_NAC",
            "CORE_SWITCH",
            "BRIDGE",
            "CAMPUS_AP",
            "IOT",
            "MOBILITY_GW",
            "AGG_SWITCH",
            "BRANCH_GW",
            "VPNC",
            "ACCESS_SWITCH",
            "MICROBRANCH_AP",
        ]
        if isinstance(persona, list) or "ALL" in persona:
            if "ALL" in persona:
                persona = valid_personas
            for p in persona:
                if p not in valid_personas:
                    central_conn.logger.error(
                        f"{p} is not a valid device persona"
                        f"Unable to unassign profile {profile_name} from"
                        f" {scope_id}"
                    )
                api_data = {
                    "scope-map": [
                        {
                            "scope-name": str(scope_id),
                            "persona": p,
                            "resource": profile_name,
                        }
                    ]
                }
                resp = central_conn.command(
                    api_method=api_method, api_path=api_path, api_data=api_data
                )

                if resp["code"] == 200:
                    central_conn.logger.info(
                        f"Successfully unassigned profile {profile_name} from"
                        f" {scope_id} with {p} device persona"
                    )
        else:
            api_data = {
                "scope-map": [
                    {
                        "scope-name": str(scope_id),
                        "persona": persona,
                        "resource": profile_name,
                    }
                ]
            }

            resp = central_conn.command(
                api_method=api_method, api_path=api_path, api_data=api_data
            )

            if resp["code"] == 200:
                central_conn.logger.info(
                    f"Successfully unassigned profile {profile_name} from"
                    f" {scope_id} with {persona} device persona"
                )
        return resp
