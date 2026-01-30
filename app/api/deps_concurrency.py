import time
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.schema.jobs import Job
from app.schema.quotas import SubscriptionTier, UserTierOverride
from app.schema.sql import User
from app.services.users import get_user_subscription_tier

FeatureType = Literal["lesson", "research", "writing", "coach"]


async def check_concurrency_limit(feature: FeatureType, user: User, db: AsyncSession) -> None:
  """
  Check if the user has reached the concurrency limit for the given feature.
  Raises HTTPException(429) if limit is reached.
  """
  # 1. Get User's Tier ID
  tier_id, _ = await get_user_subscription_tier(db, user.id)

  # 2. Get Limit from Tier or Override
  stmt = select(UserTierOverride).where(and_(UserTierOverride.user_id == user.id, UserTierOverride.expires_at > func.now())).order_by(UserTierOverride.id.desc()).limit(1)
  result = await db.execute(stmt)
  override = result.scalar_one_or_none()

  limit = 1  # Default fallback
  limit_field = f"concurrent_{feature}_limit"

  if override and getattr(override, limit_field) is not None:
    limit = getattr(override, limit_field)
  else:
    tier_stmt = select(SubscriptionTier).where(SubscriptionTier.id == tier_id)
    tier_result = await db.execute(tier_stmt)
    tier = tier_result.scalar_one_or_none()
    if tier:
      val = getattr(tier, limit_field, None)
      if val is not None:
        limit = val

  # 3. Count Active Jobs
  active_statuses = ["queued", "processing", "in_progress"]
  current_time = int(time.time())

  query = select(func.count(Job.job_id)).where(Job.user_id == str(user.id), Job.status.in_(active_statuses), or_(Job.ttl.is_(None), Job.ttl > current_time))

  if feature == "lesson":
    # Include NULL for legacy support, but new writing/research jobs MUST set target_agent.
    query = query.where(or_(Job.target_agent.is_(None), Job.target_agent.in_(["lesson", "planner", "orchestrator", "lesson_orchestrator"])))
  elif feature == "research":
    query = query.where(Job.target_agent == "research")
  elif feature == "writing":
    query = query.where(Job.target_agent == "writing")
  elif feature == "coach":
    query = query.where(Job.target_agent == "coach")

  count_result = await db.execute(query)
  active_count = count_result.scalar_one()

  if active_count >= limit:
    raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=f"Concurrency limit reached for {feature}. Limit: {limit}, Active: {active_count}. Please wait for your current request to complete.")


def verify_concurrency(feature: FeatureType):
  async def _dependency(user: Annotated[User, Depends(get_current_active_user)], db: Annotated[AsyncSession, Depends(get_db)]):
    await check_concurrency_limit(feature, user, db)

  return _dependency
