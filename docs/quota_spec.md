# **Technical Specification: Subscription Tiers & Usage Guardrails**

## **1\. Overview**

Implement a robust guardrail system to prevent LLM API abuse and manage resource consumption. This involves a static SubscriptionTier table for base limits, a UserUsage table for tracking real-time consumption, and a UserTierOverride table for promotional or custom limits.

## **2\. Database Schema (SQLAlchemy)**

### **2.1. Table: subscription_tiers (Static Data)**

This table defines the hard limits for each tier.

| Column | Type | Description |
| :---- | :---- | :---- |
| id | Integer | Primary Key |
| name | String | Unique Tier Name (e.g., 'Free', 'Pro', 'Enterprise') |
| max_file_upload_kb | Integer | 512, 1024, 2048 (in KB) |
| highest_lesson_depth | Enum | 'highlights', 'detailed', 'training' |
| max_sections_per_lesson | Integer | 2, 6, 10 |
| file_upload_quota | Integer | 0, 5, 10, 20 (Total allowed) |
| image_upload_quota | Integer | 0, 5, 10, 20 (Total allowed) |
| gen_sections_quota | Integer | 20, 100, 250 (Total allowed) |
| coach_mode_enabled | Boolean | True/False |
| coach_voice_tier | String? | 'device' or 'premium' or 'none' |

### **2.2. Table: user_tier_overrides (Dynamic Limits)**

Used for promos or custom user agreements. If a record exists for a user and is currently active, these values take precedence over the static tier limits.

| Column | Type | Description |
| :---- | :---- | :---- |
| id | Integer | Primary Key |
| user_id | UUID | Foreign Key to User |
| starts_at | DateTime | Promo start |
| expires_at | DateTime | Promo end |
| max_file_upload_kb | Integer | Nullable Override |
| file_upload_quota | Integer | Nullable Override |
| image_upload_quota | Integer | Nullable Override |
| gen_sections_quota | Integer | Nullable Override |
| coach_mode_enabled | Boolean | Nullable Override |

### **2.3. Table: user_usage_metrics (Real-time Tracking)**

Tracks current consumption aggregates.

| Column | Type | Description |
| :---- | :---- | :---- |
| user_id | UUID | Primary Key / Foreign Key |
| subscription_tier_id | Integer | Foreign Key to SubscriptionTier |
| files_uploaded_count | Integer | Default 0 |
| images_uploaded_count | Integer | Default 0 |
| sections_generated_count | Integer | Default 0 |
| last_updated | DateTime | Timestamp of last activity |

### **2.4. Table: user_usage_logs (Audit Trail)**

Records individual events for debugging and analytics.

| Column | Type | Description |
| :---- | :---- | :---- |
| id | Integer | Primary Key |
| user_id | UUID | Foreign Key |
| action_type | String | e.g., 'FILE_UPLOAD', 'SECTION_GEN' |
| quantity | Integer | Amount consumed |
| metadata_json | JSONB | Details like file name or size |
| created_at | DateTime | Timestamp of the event |

## **3\. Implementation Details**

### **3.1. SQLAlchemy Models**

See `app/schema/quotas.py` for the definitive source of truth.

```python
class SubscriptionTier(Base):
  __tablename__ = "subscription_tiers"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
  max_file_upload_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
  highest_lesson_depth: Mapped[str | None] = mapped_column(Enum("highlights", "detailed", "training", name="lesson_depth"), nullable=True)
  max_sections_per_lesson: Mapped[int | None] = mapped_column(Integer, nullable=True)
  file_upload_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
  image_upload_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
  gen_sections_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
  coach_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
  coach_voice_tier: Mapped[str | None] = mapped_column(String, nullable=True)


class UserTierOverride(Base):
  __tablename__ = "user_tier_overrides"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False)
  starts_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), default=func.now(), nullable=False)
  expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
  max_file_upload_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
  file_upload_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
  image_upload_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
  gen_sections_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
  coach_mode_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class UserUsageMetrics(Base):
  __tablename__ = "user_usage_metrics"

  user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
  subscription_tier_id: Mapped[int] = mapped_column(ForeignKey("subscription_tiers.id"), nullable=False)
  files_uploaded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
  images_uploaded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
  sections_generated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
  last_updated: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UserUsageLog(Base):
  __tablename__ = "user_usage_logs"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False)
  action_type: Mapped[str] = mapped_column(String, nullable=False)
  quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
  metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

### **3.2. Guardrail Logic**

1. **Resolved Limit Query:** Use the get\_remaining\_quota logic to determine availability in a single SQL operation.  
2. **Evaluate Result:** If result \<= 0, return 403 QUOTA\_EXCEEDED.  
3. **Atomic Update:** On success, wrap the increment of UserUsageMetrics and the insertion into UserUsageLog in a single transaction.

## **4\. Migration Plan**

1. Run Alembic migrations to create tables.  
2. Seed subscription\_tiers (Free, Plus, Pro).  
3. Backfill existing users into user\_usage\_metrics.  
4. Integrate check\_quota utility into existing API endpoints.