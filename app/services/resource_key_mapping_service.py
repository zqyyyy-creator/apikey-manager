class ResourceKeyMappingService:
    """Maps billing resource_uuid values to managed key_hash_id values.

    The real resource_uuid -> key_hash_id table is not available yet. Until it is
    provided, keep the old identity behavior in one place so the billing service
    can switch to the real mapping without changing its aggregation rules.
    """

    async def get_resource_uuids_for_key(self, key_hash_id: str) -> list[str]:
        return [key_hash_id]

    async def get_resource_uuid_map_for_keys(
        self,
        key_hash_ids: list[str],
    ) -> dict[str, str]:
        return {key_hash_id: key_hash_id for key_hash_id in key_hash_ids}
