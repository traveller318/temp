# Deploying to Google Cloud Run (web console only, no CLI)

This guide deploys two Cloud Run services from the **same Docker image** (`Dockerfile` in this repo):

| Service | What runs | Env var that picks it | Memory |
|---|---|---|---|
| `rag-api` | FastAPI (`app.py`) | `SERVICE=api` | 2 GiB |
| `rag-ui`  | Streamlit (`streamlit_app.py`) | `SERVICE=ui` | 512 MiB |

Google builds the image for you with **Cloud Build** straight from your GitHub repo. You don't need Docker
or the gcloud CLI on your computer. Every push to `main` rebuilds and redeploys automatically.

**Time needed:** about 30 minutes, including two builds of about 5–10 minutes each.
**Cost:** inside the free tier for demo use (see [Cost](#cost)).

---

## Files this relies on (already in the repo)

| File | Purpose |
|---|---|
| `Dockerfile` | Python 3.12 slim image with CPU-only torch and the embedding model baked in. It starts the API or the UI depending on `SERVICE`, listening on `$PORT` (Cloud Run sets `8080`). |
| `.dockerignore` | Keeps `.env`, `.venv`, `.git` and screenshots out of the image. **Your API key never goes into the image.** |
| `requirements.txt` | Pinned Python dependencies. |
| `knowledge_base.txt` | FAQ content indexed into FAISS at startup. It must be committed. |

> Tested locally: the image builds, the API starts in about 10 seconds with 92 chunks indexed, `/ask` returns
> a Groq answer, and the API uses about 560 MiB of RAM.

---

## Step 0: Push the code to GitHub

Cloud Build pulls from GitHub, so the deployment files must be committed and pushed:

```
git add Dockerfile .dockerignore DEPLOY_GCP.md
git commit -m "Add Cloud Run deployment"
git push origin main
```

Check on github.com that `Dockerfile` and `knowledge_base.txt` are in the repo and that `.env` is **not**.

Keep your Groq API key handy (from https://console.groq.com/keys). You'll paste it in Step 3.

---

## Step 1: Create a project and turn on billing

1. Open https://console.cloud.google.com and sign in.
2. Click the **project picker** at the top left, then **New Project**.
   - Project name: `rag-support-assistant` (any name works)
   - Click **Create**, then select the new project in the project picker.
3. Open the menu (☰), then **Billing**, then **Link a billing account**.
   - New accounts: start the **free trial**. You get $300 of credit for 90 days. A card is needed for
     verification, but you are not charged unless you manually upgrade.
   - Cloud Run will not deploy without billing linked, even if usage stays free.

---

## Step 2: Enable the APIs

In the top search bar, search for each of these, open it and click **Enable**:

1. **Cloud Run Admin API**
2. **Cloud Build API**
3. **Artifact Registry API**
4. **Secret Manager API**

Each takes about 30 seconds.

---

## Step 3: Store the Groq key in Secret Manager

1. Search for **Secret Manager** and click **+ Create Secret**.
2. Name: `groq-api-key`
3. Secret value: paste your Groq key. Check that there are no spaces or newlines.
4. Leave everything else as is and click **Create Secret**.

---

## Step 4: Let Cloud Run read the secret

1. Menu (☰), then **IAM & Admin**, then **IAM**.
2. Find the principal named **Default compute service account**
   (`<PROJECT_NUMBER>-compute@developer.gserviceaccount.com`).
   - Can't see it? Tick **Include Google-provided role grants** at the top right of the table.
3. Click the **pencil** (Edit principal) on that row, then **+ Add another role**.
4. Pick **Secret Manager Secret Accessor**, then **Save**.

---

## Step 5: Deploy the API (`rag-api`)

1. Search for **Cloud Run** and click **Deploy container**, then **Service**.
2. Choose **Continuously deploy from a repository (source or function)**, then click **Set up with Cloud Build**.
   1. Repository provider: **GitHub**, then **Authenticate** and sign in to GitHub.
   2. If your repo isn't listed, click **Manage connected repositories** / **Install Google Cloud Build**,
      give it access to the repo, and come back.
   3. Select the repo, tick the agreement box, and click **Next**.
   4. Branch: `^main$`
   5. Build Type: **Dockerfile**, with Source location `/Dockerfile`
   6. Click **Save**.
3. Fill in the service settings:

   | Field | Value |
   |---|---|
   | Service name | `rag-api` |
   | Region | `asia-south1 (Mumbai)`, or one near you |
   | Authentication | **Allow unauthenticated invocations** (public access) |
   | Billing | **Request-based**. This is what keeps it free when idle. |
   | Minimum number of instances | `0` |
   | Maximum number of instances | `2`. This caps cost. |
   | Ingress | **All** |

4. Expand **Containers, Volumes, Networking, Security**. On the **Container(s)** tab:
   - **Settings** sub-tab:
     - Container port: `8080`
     - Memory: **2 GiB**
     - CPU: **1**
     - Request timeout: `300`
   - **Variables & Secrets** sub-tab:
     - **+ Add variable** for each of these:

       | Name | Value |
       |---|---|
       | `SERVICE` | `api` |
       | `LLM_PROVIDER` | `groq` |
       | `GROQ_MODEL` | `openai/gpt-oss-20b` |

     - **+ Reference a secret**:
       - Name: `GROQ_API_KEY`
       - Secret: `groq-api-key`
       - Reference method: **Exposed as environment variable**
       - Version: **latest**
       - If a warning says the service account lacks access, click **Grant**. Step 4 normally covers this.
5. Click **Create**.
6. Watch the build. Click the build link on the service page, or go to **Cloud Build**, then **History**.
   The first build takes about 5–10 minutes (torch download plus model download). When it goes green, the service deploys.
7. At the top of the service page, copy the **URL**, for example `https://rag-api-xxxxxxxxxx.asia-south1.run.app`.

### Check the API

Open these in your browser:

- `<API_URL>/health` should show `{"status":"ok","rag_loaded":true,"indexed_chunks":92,"provider":"groq"}`
- `<API_URL>/docs` should show Swagger UI. Try `POST /ask` with `{"question": "How can I track my shipment?"}`.

The first request after idle can take 10–30 seconds (cold start). That's normal.

---

## Step 6: Deploy the UI (`rag-ui`)

Repeat Step 5 with the same repo, branch and Dockerfile, but change these values:

| Field | Value |
|---|---|
| Service name | `rag-ui` |
| Region | same as the API |
| Authentication | **Allow unauthenticated invocations** |
| Billing | Request-based |
| Min / Max instances | `0` / `2` |
| Container port | `8080` |
| Memory | **512 MiB** |
| CPU | 1 |
| Variables | `SERVICE` = `ui` and `API_URL` = the API URL from Step 5 (**no trailing slash**) |
| Secrets | none (the UI doesn't need the Groq key) |

Then, on the **Networking** tab, tick **Session affinity**. This keeps a user's Streamlit websocket on the same instance.

Click **Create** and wait for the build. Then copy the `rag-ui` URL.

---

## Step 7: Check that it works

1. Open the `rag-ui` URL.
2. The sidebar should show **Backend: 🟢 online**.
   - If it shows 🔴 offline on the very first load, the API is still cold-starting. Wait about 30 seconds
     and refresh the page.
3. Click a sample question such as **"How can I track my shipment?"**, then **Get answer**.
   You should see a green answer, latency, intent and sources.
4. Try **"Do you sell home insurance?"**. You should get the yellow fallback reply, which proves the safe path works.

**You're deployed.** 🎉 Future `git push origin main` commits rebuild and redeploy both services automatically.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Build fails with `PERMISSION_DENIED` / "does not have permission" | The build service account is missing roles | IAM: give **Default compute service account** the roles **Cloud Build Service Account**, **Artifact Registry Writer**, **Logs Writer** and **Cloud Run Admin**, then rerun from Cloud Build, then **History**, then **Retry**. |
| Build fails with `timeout` | Slow pip download | Cloud Build, then **Triggers**, then edit the trigger, then set the timeout to `1800s`, then **Run**. |
| Revision fails with "container failed to start and listen on PORT" | Usually out of memory, or a missing variable | Check the logs (service, then **Logs** tab). Confirm memory is **2 GiB** and `SERVICE=api`. |
| `/ask` returns 503 / "LLM service unavailable" | Groq key missing or wrong | Secret Manager: check that the `groq-api-key` value is correct. Check that the service references it as `GROQ_API_KEY` and that Step 4 is done. Then **Edit & deploy new revision**. |
| UI shows 🔴 offline and stays that way | `API_URL` is wrong | Edit `rag-ui`, set `API_URL` to the exact API URL (`https://...run.app`, no trailing `/`), and deploy a new revision. |
| UI page loads forever / "Connection error" | Websocket dropped | Make sure **Session affinity** is on for `rag-ui`. |
| `403 Forbidden` when opening a URL | Service is not public | Service, then **Security** tab, then **Allow unauthenticated invocations**, then Save. |

---

## Cost

With **request-based billing** and **min instances = 0**, you pay only while a request is being served:

- Cloud Run free tier is 2M requests, 360k GiB-seconds and 180k vCPU-seconds per month. That's about 50 hours
  of active API time, which is plenty for a demo.
- Cloud Build gives 2,500 free build-minutes per month. Each push uses about 10 minutes (two services).
- Artifact Registry gives 0.5 GB free. The images are about 2 GB each, so expect **about $0.10–0.30/month**,
  paid from the $300 trial credit.

To keep it near zero:
- Artifact Registry, then `cloud-run-source-deploy`: delete old image versions now and then.
- When you're done: IAM & Admin, then **Settings**, then **Shut down** the project. This deletes everything
  and stops all billing.
