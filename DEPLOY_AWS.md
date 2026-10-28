# Deploying to AWS EC2 (web console only, no local Docker or AWS CLI)

Both services run on **one EC2 instance** with Docker Compose, from the same image (`Dockerfile`):

| Container | What runs | Public URL |
|---|---|---|
| `api` | FastAPI (`app.py`) | `http://<EC2_PUBLIC_IP>:8000` |
| `ui`  | Streamlit (`streamlit_app.py`) | `http://<EC2_PUBLIC_IP>/` |

The UI talks to the API over Docker's internal network (`API_URL=http://api:8080`).

**Time needed:** about 30–40 minutes, including a 10–20 minute first build on the server.
**Cost:** EC2 is covered by the AWS Free Tier (see [Cost](#cost)). App Runner and ECS Fargate are **not** free,
so this guide uses plain EC2.

---

## Files this relies on (already in the repo)

| File | Purpose |
|---|---|
| `Dockerfile` | Python 3.12 slim image with CPU-only torch and the embedding model baked in. `SERVICE=api` or `SERVICE=ui` picks what it runs. |
| `docker-compose.yml` | Starts `api` (port 8000) and `ui` (port 80), with a health check, auto-restart and log rotation. The UI waits until the API is healthy. |
| `deploy/setup_ec2.sh` | One-time server setup: 2 GB swap, Docker, clone repo, ask for the Groq key, write `.env`, build and start. |
| `deploy/update.sh` | Pull the latest code and redeploy. |
| `.dockerignore` | Keeps `.env`, `.venv`, `.git` and screenshots out of the image. **Your API key never goes into the image.** |

---

## Step 0: Push the code to GitHub

The server clones the repo from GitHub:

```
git add -A
git commit -m "Deploy to AWS EC2 with Docker Compose"
git push origin main
```

- Check on github.com that `docker-compose.yml`, `deploy/` and `knowledge_base.txt` are there and that `.env` is **not**.
- **Private repo?** The server can't clone it without credentials. Either make the repo public, or create a GitHub
  personal access token (Settings → Developer settings → Fine-grained tokens, read-only *Contents* on this repo) and
  use `https://<TOKEN>@github.com/<user>/<repo>.git` as the repo URL in Step 4.

Keep your Groq API key handy (https://console.groq.com/keys).

---

## Step 1: AWS account and a spending alert

1. Sign in at https://console.aws.amazon.com (create an account if needed; a card is required for verification).
2. Top right, pick a region near you, e.g. **Asia Pacific (Mumbai) ap-south-1**. Use the same region for everything.
3. Set a budget alert **before** creating anything:
   1. Search **Budgets** → **Create budget**.
   2. Choose **Use a template** → **Zero spend budget**.
   3. Enter your email → **Create budget**.

   You'll get an email as soon as anything costs even $0.01. Alerts only notify you; they don't stop charges.

---

## Step 2: Launch the EC2 instance

Search **EC2** → **Launch instance** and fill in:

| Field | Value |
|---|---|
| Name | `rag-assistant` |
| Application and OS Images | **Ubuntu** → **Ubuntu Server 24.04 LTS** (tagged *Free tier eligible*), architecture **64-bit (x86)** |
| Instance type | One tagged **Free tier eligible**. Prefer **t3.small** (2 GB RAM) if it has the tag; otherwise **t3.micro** or **t2.micro** (1 GB; works thanks to swap, just slower) |
| Key pair | **Proceed without a key pair** (you'll connect from the browser). Create one only if you want SSH from your PC. |
| Network settings → Edit | Auto-assign public IP: **Enable** |
| Firewall (security groups) | **Create security group**, then add rules (below) |
| Configure storage | **20 GiB gp3** (free tier allows up to 30 GiB) |

Security group inbound rules:

| Type | Port | Source | Why |
|---|---|---|---|
| SSH | 22 | Anywhere `0.0.0.0/0` | Browser-based *EC2 Instance Connect* needs it |
| HTTP | 80 | Anywhere `0.0.0.0/0` | Streamlit UI |
| Custom TCP | 8000 | Anywhere `0.0.0.0/0` | FastAPI (`/docs`, `/health`, `/ask`) |

Click **Launch instance**, then **View all instances**. Wait until **Instance state = Running** and
**Status check = 2/2 checks passed** (about 2 minutes). Copy the **Public IPv4 address**.

---

## Step 3: Connect from the browser

1. Select the instance → **Connect** (top right).
2. Tab **EC2 Instance Connect** → Username `ubuntu` → **Connect**.

A terminal opens in a new browser tab.

> If it fails to connect, check that the security group has the SSH (22) rule from `0.0.0.0/0`.

---

## Step 4: Run the setup script

In the browser terminal (replace the URL with your repo if it differs):

```bash
git clone https://github.com/traveller318/temp.git ~/app
bash ~/app/deploy/setup_ec2.sh https://github.com/traveller318/temp.git
```

It will:
1. Add 2 GB of swap.
2. Install Docker, Docker Compose and git.
3. Ask for your Groq key (typing is hidden; paste and press Enter) and write it to `~/app/.env` with `chmod 600`.
4. Build the image and start both containers.

The first build takes **10–20 minutes** (torch + embedding model download). Leave the tab open. If the tab
disconnects, reconnect and run `cd ~/app && sudo docker compose up -d --build` again; it continues from cache.

When it finishes it prints your URLs.

---

## Step 5: Check that it works

On the server:

```bash
cd ~/app
sudo docker compose ps        # both should be "Up", api should be "(healthy)" after ~1 minute
sudo docker compose logs -f api   # look for "startup finished"; Ctrl+C to stop following
```

In your browser:

- `http://<EC2_PUBLIC_IP>:8000/health` should show `{"status":"ok","rag_loaded":true,"indexed_chunks":92,"provider":"groq"}`
- `http://<EC2_PUBLIC_IP>:8000/docs` shows Swagger UI. Try `POST /ask` with `{"question": "How can I track my shipment?"}`.
- `http://<EC2_PUBLIC_IP>/` opens the Streamlit UI. The sidebar should show **Backend: 🟢 online**.
  - Ask **"How can I track my shipment?"**: green grounded answer with sources.
  - Ask **"Do you sell home insurance?"**: yellow fallback reply.

Use `http://`, not `https://`. Browsers sometimes auto-switch to https, which won't load.

**You're deployed.** 🎉 The containers restart automatically if they crash or the instance reboots.

---

## Updating after code changes

Push to GitHub from your PC, then in the EC2 browser terminal:

```bash
bash ~/app/deploy/update.sh
```

Change the Groq key: `nano ~/app/.env`, save, then `cd ~/app && sudo docker compose up -d`.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Page never loads / times out | Port not open, or using https | Security group must allow 80 and 8000 from `0.0.0.0/0`. Use `http://`. |
| `git clone` asks for username/password | Repo is private | Make it public, or use the token URL from Step 0. |
| Build stops with `Killed` | Out of memory | Check swap with `free -h` (should show 2.0G swap). Re-run `sudo docker compose up -d --build`. |
| `no space left on device` | Disk too small | EC2 → Volumes → select the volume → **Modify** → 30 GiB, then reboot the instance. Also run `sudo docker system prune -af`. |
| UI shows 🔴 offline | API still loading or crashed | `sudo docker compose logs api`. Wait about a minute after start. |
| `/ask` returns 503 | Groq key missing or wrong | Fix `~/app/.env`, then `sudo docker compose up -d`. |
| Public IP changed | Instance was stopped and started | Normal. Use the new IP, or allocate an **Elastic IP** and associate it (free while attached to a running instance). |
| `permission denied ... docker.sock` | Group change not active yet | Use `sudo docker ...`, or reconnect the terminal. |

---

## Cost

- **Accounts created on or after 15 July 2025:** the **Free plan** gives up to $200 in credits for 6 months.
  You aren't charged unless you upgrade to a paid plan. Instance types marked *Free tier eligible* include
  t3.micro and t3.small.
- **Older accounts:** 750 hours/month of t2.micro or t3.micro (one instance running 24/7) and 30 GiB of EBS
  for the first 12 months. The public IPv4 address is free for 750 hours/month during those 12 months.
- After the free period: a t3.micro plus disk plus public IP costs about **$10–12/month** if left running.

To keep it at zero:
- **Stop** the instance when you aren't using it (EC2 → Instances → Instance state → **Stop**). Stopped instances
  aren't billed for compute; the 20 GiB disk is still covered by the free tier.
- When you're done for good: **Terminate** the instance (this deletes its disk), and release any Elastic IP you allocated.
  An Elastic IP that isn't attached to a running instance is billed.
