# Backend Spec — Onboarding & Waitlist (FastAPI)

## Purpose
Accept a complete onboarding submission, validate it, store legal consent, and move the user into a PENDING state.

---

## Authentication
- All endpoints require authenticated user
- User identity comes from auth middleware (JWT / session)
- Do NOT trust client-sent user IDs

---

## Database Fields

### User Table
```text
id
email
full_name
age
gender
gender_other
city
country

occupation
topics_of_interest (JSONB)
intended_use
intended_use_other

onboarding_completed (bool)
status (enum)

accepted_terms_at (datetime)
accepted_privacy_at (datetime)
terms_version
privacy_version

created_at
updated_at

Status Enum
	•	APPROVED
	•	PENDING
	•	REJECTED
	•	DISABLED

⸻

API Endpoints

GET /api/me

Returns:
{
  "id": "uuid",
  "email": "user@email.com",
  "status": "PENDING",
  "onboardingCompleted": true
}

Used by frontend to control routing.

⸻

POST /api/onboarding/complete

Request Body

{
  "basic": { ... },
  "personalization": { ... },
  "legal": { ... }
}

Validation Rules
	•	User must be authenticated
	•	onboarding_completed must be false
	•	Legal checkboxes must be true
	•	Age ≥ 13
	•	Topics must not be empty
	•	Email must match auth email

⸻

Backend Logic Flow
	1.	Authenticate user
	2.	Fetch user record
	3.	If onboarding already complete:
	•	Return 409 or existing status
	4.	Validate payload
	5.	Persist:
	•	Profile fields
	•	Personalization fields
	6.	Store legal acceptance:
	•	timestamp
	•	version
	•	optional IP + UA
	7.	Set:

onboarding_completed = true
status = PENDING

8.	Return success

⸻

Example Response
{
  "status": "PENDING",
  "onboardingCompleted": true
}

Security Requirements
	•	Ignore client-provided userId
	•	Prevent overwriting legal acceptance
	•	Reject partial submissions
	•	Enforce auth on all endpoints
	•	Log consent timestamp

⸻

Idempotency

If onboarding already completed:
	•	Return 409 OR
	•	Return current state without modification

No re-writing of consent allowed.

⸻

Optional Enhancements
	•	Store IP address and user agent
	•	Track onboarding analytics
	•	Add admin approval flow later
	•	Email notification on approval

⸻

Acceptance Criteria
	•	Single API call completes onboarding
	•	Legal consent is auditable
	•	User becomes PENDING
	•	Frontend routing works purely via /me
	•	No way to bypass legal agreement

---

## Task Checklist

### Database Migration
- [ ] Update `User` table schema:
    - [ ] Add `gender` (String, nullable)
    - [ ] Add `gender_other` (String, nullable)
    - [ ] Add `occupation` (String, nullable)
    - [ ] Add `topics_of_interest` (JSONB, nullable)
    - [ ] Add `intended_use` (String, nullable)
    - [ ] Add `intended_use_other` (String, nullable)
    - [ ] Add `onboarding_completed` (Boolean, default False, nullable=False)
    - [ ] Add `accepted_terms_at` (DateTime, nullable)
    - [ ] Add `accepted_privacy_at` (DateTime, nullable)
    - [ ] Add `terms_version` (String, nullable)
    - [ ] Add `privacy_version` (String, nullable)
    - [ ] Add `updated_at` (DateTime, server_default=func.now(), onupdate=func.now())
- [ ] Update `UserStatus` enum: add `REJECTED`.
- [ ] Create and run Alembic migration.

### API Implementation
- [ ] Update `GET /api/me`:
    - [ ] Return `id`, `email`, `status`, `onboardingCompleted`.
- [ ] Create `POST /api/onboarding/complete`:
    - [ ] Define Pydantic models for validation.
    - [ ] Implement validation logic (age, empty topics, etc.).
    - [ ] Check if onboarding is already completed (Idempotency).
    - [ ] Update user record in database.
    - [ ] Return success response.

### Tests
- [ ] Test `GET /api/me` returns correct structure.
- [ ] Test `POST /api/onboarding/complete` success path.
- [ ] Test validations (age < 13, empty topics, etc.).
- [ ] Test idempotency (calling complete twice).
