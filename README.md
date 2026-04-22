# An Interactive Tool for Data Service Identification in Cyber-Physical Production Networks

🎥 Video showcasing the prototype available at [this link](https://drive.google.com/file/d/1R0FD7hHdYefOWkMR6An5ptcw7Tm6Jzzz/view)
---

Web application based on **Django**:
[https://www.djangoproject.com/](https://www.djangoproject.com/)
---

## Running the Application with Docker

This project is fully containerized. You do not need to:

- Create a virtual environment
- Install Python manually
- Install MongoDB locally

Everything runs inside Docker.

---

## Requirements

Install:

- [Docker](https://www.docker.com/)
- Docker Compose (included in modern Docker versions)

Verify installation:

```bash
docker --version
docker compose version
```

---

## 🐳 Start the Docker Daemon

Before running the application, make sure the Docker daemon is running.

**Linux:**
```bash
sudo systemctl start docker
```

**macOS / Windows:**
Open the **Docker Desktop** application and wait until the engine is started.

Verify that Docker is running:
```bash
docker info
```

---

## Quick Start

### 1️⃣ Clone the repository

```bash
git clone https://github.com/UnderReviewPapers/2026_COMPSAC_SI.git
cd webapp-files/ds-designer
```

<!--

### 2️⃣ (Optional) Create `.env` file for OpenAI

If you want to enable AI features (Project Generation and AI Chat), create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-your-secret-key
```

If you do not need AI features, skip this step.
-->

### 2️⃣ Start the containers

```bash
docker compose up --build
```

Or run in background:

```bash
docker compose up -d --build
```

---

## 🌐 Access the Application

Open your browser and go to:

```
http://localhost:8000
```

If a custom port is configured (`APP_PORT`):

```
http://localhost:<APP_PORT>
```

---

## 🔄 Change the Port (Optional)

You can run the app on a different port:

```bash
APP_PORT=9000 docker compose up
```

Then open:

```
http://localhost:9000
```

---

## 🛑 Stop the Application

```bash
docker compose down
```

---

## 🗄 Database

- MongoDB runs automatically in a Docker container
- No local MongoDB installation required
- Data is stored in a persistent Docker volume

---

## ⚙️ Environment Variables

The application supports the following environment variables:

| Variable        | Default                          | Description            |
|-----------------|----------------------------------|------------------------|
| `MONGO_HOST`    | `mongo` (Docker) / `localhost` (local) | MongoDB host    |
| `MONGO_PORT`    | `27017`                          | MongoDB port           |
| `APP_PORT`      | `8000`                           | Application port       |
