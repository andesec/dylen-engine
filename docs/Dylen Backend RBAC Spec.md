# **Specification: Dylen Backend RBAC Implementation (FastAPI \+ PostgreSQL)**

## **1\. Overview**

This document outlines the requirements for implementing Role-Based Access Control (RBAC) in the Dylen backend using **Python FastAPI** and **PostgreSQL**. The system supports a multi-tenant architecture with a "Super Admin" layer, handling both Firebase Google SSO and future native user accounts.

## **2\. Technology Stack**

* **Framework:** Python FastAPI  
* **Database:** PostgreSQL (SQLAlchemy or Tortoise ORM)  
* **Identity & Auth:** Firebase Authentication (Custom Claims \+ JWT Verification)  
* **Environment:** Python 3.10+

## **3\. Database Schema (New Tables)**

*Note: For all tables, the name or slug fields are intended to be user-friendly for display in the UI, while the id (UUID) must be used for all backend comparisons, logic, and calculations.*

### **3.1 roles**

Defines the available roles in the system.

* id: UUID (Primary Key) \- Used for logic and foreign keys.  
* name: String (e.g., Super Admin, Org Admin) \- User-friendly display name.  
* level: Enum (GLOBAL, TENANT)  
* description: Text

### **3.2 permissions**

Granular actions allowed within the system.

* id: UUID (Primary Key) \- Used for logic and assignment.  
* slug: String (Unique, e.g., lesson:generate, user:approve) \- Machine name for code checks.  
* display\_name: String \- User-friendly label for the UI.  
* description: Text

### **3.3 role\_permissions**

Many-to-Many mapping between roles and permissions.

* role\_id: UUID (FK to roles)  
* permission\_id: UUID (FK to permissions)

### **3.4 users (Updated)**

Must sync with Firebase UID and support status logic.

* id: UUID (Primary Key)  
* firebase\_uid: String (Unique, Indexed) \- Maps to Google SSO or Native Firebase ID  
* email: String (Unique)  
* role\_id: UUID (FK to roles)  
* org\_id: UUID (FK to organizations, nullable for global roles)  
* status: Enum (PENDING, APPROVED, DISABLED)  
* auth\_method: Enum (GOOGLE\_SSO, NATIVE)  
* created\_at: Timestamp

## **4\. Implementation Strategy**

### **4.1 Hybrid RBAC (Claims \+ DB)**

* **JWT Claims:** The backend must inject the role, orgId, and status into Firebase Custom Claims. This allows for rapid middleware-level checks without hitting the DB on every request.  
* **DB Verification:** Sensitive administrative actions must still verify against the PostgreSQL state to ensure consistency if a user's status was revoked recently.

### **4.2 Middleware Logic**

* **Authentication:** Verify the Firebase ID Token (JWT).  
* **Status Guard:** If status \!= APPROVED, block all routes except /purgatory or public endpoints.  
* **Role Guard:** Custom FastAPI Dependencies (Security) to check if token.role matches the required access level.

## **5\. API Requirements for Admins**

### **5.1 RBAC Management (Super Admin Only)**

* POST /admin/roles: Create new roles.  
* PUT /admin/roles/{id}/permissions: Batch assign permissions to a role.

### **5.2 User Management (Super/Org Admin)**

* GET /admin/users: List users. Filter by org\_id if requester is org\_admin.  
* PATCH /admin/users/{uid}/status: Update status to approved or disabled.  
* PATCH /admin/users/{uid}/role: Change a user's role.  
* POST /admin/users/invite: (Future) Create a native user stub in Firebase and DB, sending an invite email.

## **6\. Security & Multi-tenancy**

* **Organization Isolation:** Every query involving org\_user or org\_consumer must include a WHERE org\_id \= :request\_org\_id clause derived from the authenticated user's token.  
* **Native User Support:** The system must treat the firebase\_uid as the primary identifier regardless of whether the user signed in via Google or Email/Password.

## **7\. Sync & Onboarding Logic**

* POST /auth/signup: This endpoint is called by the frontend after a user completes the signup form (post-Google SSO or post-Native registration). It inserts the user information into the PostgreSQL users table with a default status of PENDING. This ensures that even after a successful authentication, the user remains in "purgatory" until an admin manually approves the record created during this sync process.