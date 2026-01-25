# **Technical Specification: Subscription Tiers & Usage Guardrails**

## **1\. Overview**

Implement a robust guardrail system to prevent LLM API abuse and manage resource consumption. This involves a static SubscriptionTier table for base limits, a UserUsage table for tracking real-time consumption, and a UserTierOverride table for promotional or custom limits.

## **2\. Database Schema (SQLAlchemy)**

### **2.1. Table: subscription\_tiers (Static Data)**

This table defines the hard limits for each tier.

| Column | Type | Description |
| :---- | :---- | :---- |
| id | Integer | Primary Key |
| name | String | Unique Tier Name (e.g., 'Free', 'Pro', 'Enterprise') |
| max\_file\_upload\_size | Integer | 512, 1024, 2048 (in KB) |
| highest\_lesson\_depth | Enum | 'highlights', 'detailed', 'training' |
| max\_sections\_per\_lesson | Integer | 2, 6, 10 |
| file\_upload\_quota | Integer | 0, 5, 10, 20 (Total allowed) |
| image\_upload\_quota | Integer | 0, 5, 10, 20 (Total allowed) |
| gen\_sections\_quota | Integer | 20, 100, 250 (Total allowed) |
| coach\_mode\_enabled | Boolean | True/False |
| coach\_voice\_tier | String? | 'device' or 'premium' or 'none' |

### **2.2. Table: user\_tier\_overrides (Dynamic Limits)**

Used for promos or custom user agreements. If a record exists for a user and is currently active, these values take precedence over the static tier limits.

| Column | Type | Description |
| :---- | :---- | :---- |
| id | Integer | Primary Key |
| user\_id | String | Foreign Key to User |
| starts\_at | DateTime | Promo start |
| expires\_at | DateTime | Promo end |
| max\_file\_upload\_kb | Integer | Nullable Override |
| file\_upload\_quota | Integer | Nullable Override |
| image\_upload\_quota | Integer | Nullable Override |
| gen\_sections\_quota | Integer | Nullable Override |
| coach\_mode\_enabled | Boolean | Nullable Override |

### **2.3. Table: user\_usage\_metrics (Real-time Tracking)**

Tracks current consumption aggregates.

| Column | Type | Description |
| :---- | :---- | :---- |
| user\_id | String | Primary Key / Foreign Key |
| files\_uploaded\_count | Integer | Default 0 |
| images\_uploaded\_count | Integer | Default 0 |
| sections\_generated\_count | Integer | Default 0 |
| last\_updated | DateTime | Timestamp of last activity |

### **2.4. Table: user\_usage\_logs (Audit Trail)**

Records individual events for debugging and analytics.

| Column | Type | Description |
| :---- | :---- | :---- |
| id | Integer | Primary Key |
| user\_id | String | Foreign Key |
| action\_type | String | e.g., 'FILE\_UPLOAD', 'SECTION\_GEN' |
| quantity | Integer | Amount consumed |
| metadata\_json | JSONB | Details like file name or size |
| created\_at | DateTime | Timestamp of the event |

## **3\. Implementation Details**

### **3.1. SQLAlchemy Models**

from sqlalchemy import Column, Integer, String, Boolean, Enum, DateTime, ForeignKey, JSON, func, and\_  
from sqlalchemy.orm import Session  
from database import Base  
import datetime

class SubscriptionTier(Base):  
    \_\_tablename\_\_ \= "subscription\_tiers"  
    id \= Column(Integer, primary\_key=True)  
    name \= Column(String, unique=True, nullable=False)  
    max\_file\_upload\_kb \= Column(Integer)  
    highest\_lesson\_depth \= Column(Enum('highlights', 'detailed', 'training', name='lesson\_depth'))  
    max\_sections\_per\_lesson \= Column(Integer)  
    file\_upload\_quota \= Column(Integer)  
    image\_upload\_quota \= Column(Integer)  
    gen\_sections\_quota \= Column(Integer)  
    coach\_mode\_enabled \= Column(Boolean, default=False)  
    coach\_voice\_tier \= Column(String)

class UserTierOverride(Base):  
    \_\_tablename\_\_ \= "user\_tier\_overrides"  
    id \= Column(Integer, primary\_key=True)  
    user\_id \= Column(String, index=True, nullable=False)  
    starts\_at \= Column(DateTime, default=datetime.datetime.utcnow)  
    expires\_at \= Column(DateTime, nullable=False)  
    max\_file\_upload\_kb \= Column(Integer, nullable=True)  
    file\_upload\_quota \= Column(Integer, nullable=True)  
    image\_upload\_quota \= Column(Integer, nullable=True)  
    gen\_sections\_quota \= Column(Integer, nullable=True)  
    coach\_mode\_enabled \= Column(Boolean, nullable=True)

class UserUsageMetrics(Base):  
    \_\_tablename\_\_ \= "user\_usage\_metrics"  
    user\_id \= Column(String, primary\_key=True)  
    files\_uploaded\_count \= Column(Integer, default=0)  
    images\_uploaded\_count \= Column(Integer, default=0)  
    sections\_generated\_count \= Column(Integer, default=0)  
    last\_updated \= Column(DateTime, onupdate=datetime.datetime.utcnow)

    @classmethod  
    def get\_remaining\_quota(cls, db: Session, user\_id: str, metric\_column: str):  
        now \= datetime.datetime.utcnow()  
        mapping \= {  
            'files': (SubscriptionTier.file\_upload\_quota, UserTierOverride.file\_upload\_quota, cls.files\_uploaded\_count),  
            'images': (SubscriptionTier.image\_upload\_quota, UserTierOverride.image\_upload\_quota, cls.images\_uploaded\_count),  
            'sections': (SubscriptionTier.gen\_sections\_quota, UserTierOverride.gen\_sections\_quota, cls.sections\_generated\_count)  
        }  
        tier\_col, override\_col, usage\_col \= mapping\[metric\_column\]  
        query \= (  
            db.query((func.coalesce(override\_col, tier\_col) \- usage\_col).label("remaining"))  
            .join(SubscriptionTier, True)  
            .outerjoin(UserTierOverride, and\_(  
                UserTierOverride.user\_id \== user\_id,  
                UserTierOverride.starts\_at \<= now,  
                UserTierOverride.expires\_at \>= now  
            ))  
            .filter(cls.user\_id \== user\_id)  
        )  
        return query.scalar()

class UserUsageLog(Base):  
    \_\_tablename\_\_ \= "user\_usage\_logs"  
    id \= Column(Integer, primary\_key=True)  
    user\_id \= Column(String, ForeignKey("user\_usage\_metrics.user\_id"), index=True)  
    action\_type \= Column(String, nullable=False)  
    quantity \= Column(Integer, default=1)  
    metadata\_json \= Column(JSON)  
    created\_at \= Column(DateTime, default=datetime.datetime.utcnow)


### **3.2. Guardrail Logic**

1. **Resolved Limit Query:** Use the get\_remaining\_quota logic to determine availability in a single SQL operation.  
2. **Evaluate Result:** If result \<= 0, return 403 QUOTA\_EXCEEDED.  
3. **Atomic Update:** On success, wrap the increment of UserUsageMetrics and the insertion into UserUsageLog in a single transaction.

## **4\. Migration Plan**

1. Run Alembic migrations to create tables.  
2. Seed subscription\_tiers (Free, Plus, Pro).  
3. Backfill existing users into user\_usage\_metrics.  
4. Integrate check\_quota utility into existing API endpoints.