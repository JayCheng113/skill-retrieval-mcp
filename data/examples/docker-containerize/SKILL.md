---
name: "docker-containerize"
description: "Containerize an application with Docker following production-ready best practices"
tags: ["devops", "docker", "containers", "deployment"]
---

## Instructions

Containerizing an application makes it portable, reproducible, and easier to deploy. Follow these practices to produce lean, secure images.

**Writing an Effective Dockerfile**

Use a multi-stage build to separate build-time dependencies from the runtime image:
```dockerfile
# Stage 1: build
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production

# Stage 2: runtime
FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/node_modules ./node_modules
COPY . .
USER node
EXPOSE 3000
CMD ["node", "server.js"]
```

**Key Principles**
1. **Pin base image versions**: Use `node:20.11-alpine3.19`, not `node:latest`, to ensure reproducible builds.
2. **Order layers for cache efficiency**: Copy dependency manifests (`package.json`, `requirements.txt`) and install dependencies *before* copying source code. Source changes will not bust the dependency cache.
3. **Minimize image size**: Use slim or Alpine variants. Remove build tools, caches, and temporary files in the same `RUN` layer they are created.
4. **Run as a non-root user**: Always switch to a non-root user before the `CMD` instruction to limit blast radius if the container is compromised.
5. **One process per container**: Do not run a database and an app in the same container. Use Docker Compose or Kubernetes pods for multi-process scenarios.
6. **Use `.dockerignore`**: Exclude `node_modules`, `.git`, test files, and local environment files to keep the build context small and avoid leaking secrets.

**Health Checks**
Add a `HEALTHCHECK` instruction so orchestrators know when the container is ready:
```dockerfile
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:3000/health || exit 1
```

**Secrets**
Never bake secrets into the image. Use environment variables at runtime, Docker secrets (Swarm), or Kubernetes Secrets.
