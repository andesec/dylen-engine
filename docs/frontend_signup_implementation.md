# Frontend Implementation Brief: Signup Flow

## Overview
The authentication flow has been updated to require explicit user registration. The `POST /login` endpoint no longer automatically creates accounts for new users. Instead, it returns a `404 Not Found` error, which the frontend must handle by redirecting the user to a signup form.

## API Reference

### 1. Login
To log in an existing user.
- **Endpoint**: `POST /api/auth/login`
- **Payload**:
  ```json
  {
    "idToken": "<FIREBASE_ID_TOKEN>"
  }
  ```
- **Responses**:
  - `200 OK`: Login successful. Session cookie set.
  - `404 Not Found`: **User does not exist.** -> **Redirect to Signup Form.**
  - `403 Forbidden`: User exists but is not approved. Show "Pending Approval" message.

### 2. Signup
To register a new user.
- **Endpoint**: `POST /api/auth/signup`
- **Payload**:
  ```json
  {
    "idToken": "<FIREBASE_ID_TOKEN>",
    "fullName": "John Doe",
    "email": "john@example.com",  // Optional, backend prefers ID Token email
    "profession": "Software Engineer",
    "city": "New York",
    "country": "USA",
    "age": 30,
    "photoUrl": "https://example.com/photo.jpg"
  }
  ```
- **Responses**:
  - `200 OK`: Signup successful. Session cookie set.
  - `409 Conflict`: User already exists.
  - `400 Bad Request`: Validation error.

### 3. Check Status (Get Profile)
 To poll for account approval.
- **Endpoint**: `GET /api/user/me`
- **Headers**: Cookie `session=...` (Automatically sent by browser after login)
- **Response**:
  ```json
  {
    "id": "...",
    "email": "user@example.com",
    "full_name": "...",
    "photo_url": "...",
    "is_approved": false,
    "is_admin": false
  }
  ```

## Frontend Requirements

### Signup Flow
...

### Logic Flow
1. **User clicks "Login with Google"**.
2. **Frontend gets ID Token** from Firebase.
3. **Frontend calls `POST /login`**.
4. **If 404**:
   - Hide login spinner.
   - Show **Signup Form**.
   - Pre-fill fields where possible (Name, Photo).
5. **User submits Signup Form**:
   - **Frontend calls `POST /signup`** with form data and ID Token.
   - **If 200**:
     - Redirect to "Pending Approval" page.

6. **Pending Approval Page** (or Dashboard with overlay):
   - **Poll `GET /api/user/me`** every 5-10 seconds.
   - **If response.is_approved is true**:
     - Enable full dashboard functionality.
