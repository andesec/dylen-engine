# Prompt: Implement Secure GCS Image Proxy with CDN Simulation

## Context
We are moving away from Signed URLs to a static URL strategy that leverages Cloud CDN. The backend must validate that a user owns a lesson/section before allowing them to view an image.

## Objective
Configure a Docker-based GCS emulator and implement a backend "Gatekeeper" service that validates access and serves image content from GCS under a consistent URL path.

## Requirements

### 1. Docker & Environment
- Update `docker-compose.yml` to include the `fsouza/fake-gcs-server` (GCS Emulator).
- Map a local volume `./storage_data` to `/data` in the emulator to persist images.
- Set `GCS_STORAGE_HOST=http://gcs-emulator:4443/storage/v1/` for the backend.

### 2. Backend Gatekeeper Logic
Implement an endpoint `GET /media/lessons/{lesson_id}/{image_name}`:
- **Auth Check:** Extract the user identity from the request (JWT/Session).
- **Validation:** Query the DB to ensure this user has access to `{lesson_id}`.
- **Serving:**
    - **Development:** The backend should fetch the bytes from the GCS Emulator and stream them back to the user with the correct `Content-Type: image/webp`.
    - **Production:** To leverage Cloud CDN, the backend should return an `X-Accel-Redirect` or simply stream the file. (Ideally, for your scale, streaming the file from GCS through your backend is the safest way to enforce validation without making the bucket public).
- **Caching Headers:** Ensure the backend sends `Cache-Control: public, max-age=3600` so Cloud CDN knows it is allowed to cache this specific authorized response.

### 3. Connection Manager
- Implement a `StorageClient` that switches between `AnonymousCredentials` (Dev) and standard `google.cloud.storage.Client()` (Prod) based on the presence of the emulator host variable.
