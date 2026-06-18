from fastapi import APIRouter

router = APIRouter(prefix="/api/timeline", tags=["timeline"])

# Timeline is currently project-scoped and served from
# GET /api/projects/{project_id}/timeline. This router is reserved for future
# cross-project timeline/calendar endpoints.
