# **Fenster Widget: Engine Specification (FastAPI / PostgreSQL)**

## **1\. Executive Summary**

**Purpose**: To provide a robust, scalable engine infrastructure for "Fenster"—a Just-In-Time (JIT) educational widget system.  
**Intent**: To decouple the generation of AI-driven interactive tools from the main application flow, ensuring lessons remain performant while offering premium, dynamic content.  
**Ideal Result**: A user on a "Pro" plan loads a lesson; the engine checks permissions, retrieves a pre-generated, Brotli-compressed HTML blob (or CDN link) in \<50ms, and serves it securely.  
**Success Criteria**:

* The **Fenster Builder Agent** successfully processes jobs from the shared queue, generates code, compresses payloads, and stores widgets without blocking main threads.  
* API endpoints strictly enforce "Plus" and "Pro" tier access.  
* Database storage is optimized using TOAST and Brotli, keeping row sizes manageable.

## **2\. Architecture & Interfaces**

### **A. Job Creation (Internal Database Operation)**

* **Mechanism**: The Planning Agent utilizes the existing application framework to create jobs directly in the database. There is no internal API call; it is a direct DB transaction within the single service.  
* **Target Routing**: Jobs must be explicitly flagged for the **Fenster Builder Agent** using a dedicated column.  
* **Job Record Schema**:  
  {  
    "job\_id": "uuid",  
    "status": "pending",  
    "target\_agent": "fenster\_builder", // NEW COLUMN  
    "payload": {  
      "lesson\_id": "uuid",  
      "concept\_context": "string",  
      "target\_audience": "string",  
      "technical\_constraints": {  
        "max\_tokens": 4000,  
        "allowed\_libs": \["alpine", "tailwind"\]  
      }  
    },  
    "created\_at": "timestamp"  
  }

### **B. Widget Retrieval from Frontend**

* **Endpoint**: GET /api/v1/fenster/{widget\_id}  
* **Access**: Authenticated Users (Tier Gated).  
* **Response Schema (Success)**:  
  {  
    "fenster\_id": "uuid",  
    "type": "inline\_blob", // or "cdn\_url"  
    "content": "base64\_encoded\_brotli\_string", // null if type is cdn\_url  
    "url": null, // string if type is cdn\_url  
  }

* **Response Schema (Forbidden)**: 403 Forbidden { "error": "UPGRADE\_REQUIRED", "min\_tier": "plus" }

## **3\. Detailed Requirements**

### **Functional Requirements (FR)**

1. **Jobs Table Extension**:  
   * The existing jobs table must be altered to include a target\_agent column (String or Enum).  
   * This column enables multiple agents to share the same job queue framework while filtering for their specific tasks (e.g., planner, fenster\_builder, quiz\_generator).  
2. **The Fenster Builder Agent**: A dedicated autonomous agent must be created to handle the entire build lifecycle.  
   * **Role**: It triggers from the job request when target\_agent \== 'fenster\_builder' and status \== 'pending'. Using the Cloud Task process.  
   * **Lifecycle**: Consumes job \-\> Generates Code (LLM) \-\> Validates \-\> Compresses \-\> Inserts to fenster\_widgets \-\> Updates Job Status to completed.  
3. **Dual-Mode Storage**:  
   * Primary: Store compressed binary data in TEXT column.  
   * Fallback: Ability to store a CDN URL if the content exceeds database row limits.  
4. **Deterministic Retrieval**: The GET endpoint must query the database once. Logic must prefer returning the inline\_blob. If inline\_blob is empty, return cdn\_url.  
5. **Tier Gating**: Middleware must intercept requests to /api/v1/fenster/\* and validate user.subscription\_tier against \['plus', 'pro'\].

### **Non-Functional Requirements (NFR)**

1. **Latency**: Retrieval endpoint p95 latency must be under 100ms.  
2. **Compression**: Inline HTML must be compressed using Brotli (Level 11 preferred for write-once-read-many) before DB insertion.  
3. **Data Integrity**: Stored blobs must be verifiable via hash to ensure no corruption during TOAST storage.

### **Security Design & Guardrails**

1. **Least Privilege**: The Cloud Run service account for the API must have SELECT permissions only on the fenster\_widgets table. Only the **Fenster Builder Agent** logic has INSERT/UPDATE privileges.  
2. **Header Security**: The API response must **NOT** include Content-Type: text/html. It should serve JSON. This prevents the browser from accidentally rendering the payload if the API is accessed directly.

## **4\. Implementation Phases (Coding Agent Tasks)**

### **Phase 1: Database & Core Models**

**Objective**: Establish the storage layer and compression logic.

* **Task**:  
  1. Create FensterWidget SQLAlchemy/Pydantic models.  
  2. Implement a PostgreSQL migration creating the fenster\_widgets table with a BYTEA column for brotli\_content.  
  3. Write utility functions: compress\_html(raw\_html: str) \-\> bytes and decompress\_html(blob: bytes) \-\> str.  
* **Test Criteria**: Unit tests verifying that a 100kb HTML string compresses correctly, stores in DB, retrieves, and decompresses to the exact original string.

### **Phase 2: Asynchronous Worker Pipeline (The Builder Agent)**

**Objective**: Develop and deploy the **Fenster Builder Agent**.

* **Task**:  
  1. **Schema Migration**: Create a migration to add target\_agent column to the jobs table.  
  2. **Planner Logic Update**: update the Planning Agent to insert widget generation jobs with target\_agent='fenster\_builder'.  
  3. **Develop the Fenster Builder Agent**:  
     * Similar to the other agents. Uses Gemini 2.0 Flash model by default but additionally include Gemini 2.5 flash as well, it in both vertex and gemini providers, default to gemini provider.  
     * Implement the prompt engineering logic for generating the HTML/JS.  
     * Wire up the success path: AI \-\> Compress \-\> DB Insert \-\> Update Job Status.  
* **Test Criteria**: Integration test where the Planner inserts a job, the Builder Agent picks it up from the DB, processes it, and a valid row appears in the fenster\_widgets table.

### **Phase 3: Public API & Security Layer**

**Objective**: Serve the content to the frontend securely.

* **Task**:  
  1. Implement GET /api/v1/fenster/{widget\_id}.  
  2. Add TierPermissionDependency: Check user JWT for tier claims.  
  3. Implement the logic to choose between blob vs cdn based on DB columns.  
  4. Serialize response to JSON (Base64 for binary).  
* **Test Criteria**:  
  * Free user receives 403\.  
  * Pro user receives JSON with Base64 payload.  
  * Payload successfully decodes to valid HTML.