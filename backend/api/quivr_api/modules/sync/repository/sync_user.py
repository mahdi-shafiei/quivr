import json
from typing import List, Literal
from uuid import UUID

from quivr_api.logger import get_logger
from quivr_api.modules.dependencies import get_supabase_client
from quivr_api.modules.sync.dto.inputs import SyncsUserInput, SyncUserUpdateInput
from quivr_api.modules.sync.entity.sync_models import SyncFile, SyncsUser
from quivr_api.modules.sync.service.sync_notion import SyncNotionService
from quivr_api.modules.sync.utils.sync import (
    AzureDriveSync,
    BaseSync,
    DropboxSync,
    GitHubSync,
    GoogleDriveSync,
    NotionSync,
)

logger = get_logger(__name__)


class SyncUserRepository:
    def __init__(self):
        """
        Initialize the Sync class with a Supabase client.
        """
        supabase_client = get_supabase_client()
        self.db = supabase_client  # type: ignore
        logger.debug("Supabase client initialized")

    def create_sync_user(
        self,
        sync_user_input: SyncsUserInput,
    ):
        """
        Create a new sync user in the database.

        Args:
            sync_user_input (SyncsUserInput): The input data for creating a sync user.

        Returns:
            dict or None: The created sync user data or None if creation failed.
        """
        logger.info("Creating sync user with input: %s", sync_user_input)
        response = (
            self.db.from_("syncs_user")
            .insert(sync_user_input.model_dump(exclude_none=True, exclude_unset=True))
            .execute()
        )
        if response.data:
            logger.info("Sync user created successfully: %s", response.data[0])
            return response.data[0]
        logger.warning("Failed to create sync user")

    def get_sync_user_by_id(self, sync_id: int) -> SyncsUser | None:
        """
        Retrieve sync users from the database.
        """
        response = self.db.from_("syncs_user").select("*").eq("id", sync_id).execute()
        if response.data:
            logger.info("Sync user found: %s", response.data[0])
            return SyncsUser.model_validate(response.data[0])
        logger.error("No sync user found for sync_id: %s", sync_id)

    def get_syncs_user(self, user_id: UUID, sync_user_id: int | None = None):
        """
        Retrieve sync users from the database.

        Args:
            user_id (str): The user ID to filter sync users.
            sync_user_id (int, optional): The sync user ID to filter sync users. Defaults to None.

        Returns:
            list: A list of sync users matching the criteria.
        """
        logger.info(
            "Retrieving sync users for user_id: %s, sync_user_id: %s",
            user_id,
            sync_user_id,
        )
        query = self.db.from_("syncs_user").select("*").eq("user_id", user_id)
        if sync_user_id:
            query = query.eq("id", str(sync_user_id))
        response = query.execute()
        if response.data:
            # logger.info("Sync users retrieved successfully: %s", response.data)
            return response.data
        logger.warning(
            "No sync users found for user_id: %s, sync_user_id: %s",
            user_id,
            sync_user_id,
        )
        return []

    def get_sync_user_by_state(self, state: dict) -> SyncsUser | None:
        """
        Retrieve a sync user by their state.

        Args:
            state (dict): The state to filter sync users.

        Returns:
            dict or None: The sync user data matching the state or None if not found.
        """
        logger.info("Getting sync user by state: %s", state)

        state_str = json.dumps(state)
        response = (
            self.db.from_("syncs_user").select("*").eq("state", state_str).execute()
        )
        if response.data and len(response.data) > 0:
            logger.info("Sync user found by state: %s", response.data[0])
            sync_user = SyncsUser.model_validate(response.data[0])
            return sync_user
        logger.error("No sync user found for state: %s", state)
        return None

    def delete_sync_user(self, sync_id: int, user_id: UUID | str):
        """
        Delete a sync user from the database.

        Args:
            provider (str): The provider of the sync user.
            user_id (str): The user ID of the sync user.
        """
        logger.info(
            "Deleting sync user with sync_id: %s, user_id: %s", sync_id, user_id
        )
        self.db.from_("syncs_user").delete().eq("id", sync_id).eq(
            "user_id", user_id
        ).execute()
        logger.info("Sync user deleted successfully")

    def update_sync_user(
        self, sync_user_id: UUID, state: dict, sync_user_input: SyncUserUpdateInput
    ):
        """
        Update a sync user in the database.

        Args:
            sync_user_id (str): The user ID of the sync user.
            state (dict): The state to filter sync users.
            sync_user_input (SyncUserUpdateInput): The input data for updating the sync user.
        """
        logger.info(
            "Updating sync user with user_id: %s, state: %s, input: %s",
            sync_user_id,
            state,
            sync_user_input,
        )

        state_str = json.dumps(state)
        self.db.from_("syncs_user").update(sync_user_input.model_dump()).eq(
            "user_id", str(sync_user_id)
        ).eq("state", state_str).execute()
        logger.info("Sync user updated successfully")

    def get_all_notion_user_syncs(self):
        """
        Retrieve all Notion sync users from the database.

        Returns:
            list: A list of Notion sync users.
        """
        logger.info("Retrieving all Notion sync users")
        response = (
            self.db.from_("syncs_user").select("*").eq("provider", "Notion").execute()
        )
        if response.data:
            logger.info("Notion sync users retrieved successfully")
            return response.data
        logger.warning("No Notion sync users found")
        return []

    async def get_files_folder_user_sync(
        self,
        sync_active_id: int,
        user_id: UUID,
        notion_service: SyncNotionService | None,
        folder_id: str | None = None,
        recursive: bool = False,
    ) -> None | dict[str, List[SyncFile]] | Literal["No sync found"]:
        """
        Retrieve files from a user's sync folder, either from Google Drive or Azure.

        Args:
            sync_active_id (int): The ID of the active sync.
            user_id (str): The user ID associated with the active sync.
            folder_id (str, optional): The folder ID to filter files. Defaults to None.

        Returns:
            dict or str: A dictionary containing the list of files or a string indicating the sync provider.
        """
        logger.info(
            "Retrieving files for user sync with sync_active_id: %s, user_id: %s, folder_id: %s",
            sync_active_id,
            user_id,
            folder_id,
        )
        # Check whether the sync is Google or Azure
        sync_user = self.get_syncs_user(user_id=user_id, sync_user_id=sync_active_id)
        if not sync_user:
            logger.warning(
                "No sync user found for sync_active_id: %s, user_id: %s",
                sync_active_id,
                user_id,
            )
            return None

        sync_user = sync_user[0]
        sync: BaseSync

        provider = sync_user["provider"].lower()
        if provider == "google":
            logger.info("Getting files for Google sync")
            sync = GoogleDriveSync()
            return {"files": sync.get_files(sync_user["credentials"], folder_id)}
        elif provider == "azure":
            logger.info("Getting files for Azure sync")
            sync = AzureDriveSync()
            return {
                "files": sync.get_files(sync_user["credentials"], folder_id, recursive)
            }
        elif provider == "dropbox":
            logger.info("Getting files for Drop Box sync")
            sync = DropboxSync()
            return {
                "files": sync.get_files(
                    sync_user["credentials"], folder_id if folder_id else "", recursive
                )
            }
        elif provider == "notion":
            if notion_service is None:
                raise ValueError("provider notion but notion_service is None")
            logger.info("Getting files for Notion sync")
            sync = NotionSync(notion_service=notion_service)
            return {
                "files": await sync.aget_files(
                    sync_user["credentials"], folder_id if folder_id else "", recursive
                )
            }
        elif provider == "github":
            logger.info("Getting files for GitHub sync")
            sync = GitHubSync()
            return {
                "files": sync.get_files(
                    sync_user["credentials"], folder_id if folder_id else "", recursive
                )
            }

        else:
            logger.warning(
                "No sync found for provider: %s", sync_user["provider"], recursive
            )
            return "No sync found"
