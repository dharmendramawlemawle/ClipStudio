from fastapi import APIRouter, Depends, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import EntityNotFoundException
from app.database import get_db
from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceCreate, WorkspaceRead

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    data: WorkspaceCreate,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceRead:
    """Creates a new workspace domain entity."""
    workspace = Workspace(
        name=data.name,
        description=data.description,
        local_storage_path=data.local_storage_path,
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return WorkspaceRead.model_validate(workspace)


@router.get("", response_model=list[WorkspaceRead])
async def list_workspaces(db: AsyncSession = Depends(get_db)) -> list[WorkspaceRead]:
    """Lists all configured workspaces."""
    stmt = select(Workspace).order_by(desc(Workspace.created_at))
    result = await db.execute(stmt)
    workspaces = result.scalars().all()
    return [WorkspaceRead.model_validate(w) for w in workspaces]


@router.get("/{workspace_id}", response_model=WorkspaceRead)
async def get_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceRead:
    """Fetches workspace details by ID."""
    workspace = await db.get(Workspace, workspace_id)
    if not workspace:
        raise EntityNotFoundException("Workspace", workspace_id)
    return WorkspaceRead.model_validate(workspace)
