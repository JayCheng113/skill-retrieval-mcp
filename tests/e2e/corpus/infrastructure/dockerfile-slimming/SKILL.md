---
name: dockerfile-slimming
description: Reduce container image size and build time with multi-stage builds and ordered layer caching.
category: infrastructure
tags: [docker, containers, build, caching]
---

# Making container images small and builds fast

Order instructions from least to most frequently changing. Copying the whole
source tree before installing dependencies invalidates the dependency layer on
every source edit, which is why a one-line change can trigger a full reinstall.
Copy the manifest, install, then copy the source.

Use a multi-stage build so compilers, headers and package caches stay in the build
stage and never reach the final image. Copy only the produced artefact across.

Deleting files in a later layer does not shrink the image, because the earlier
layer still carries them. Whatever you want gone must never be written in the
layer that ships.

Pin the base image by digest. A floating tag makes builds unreproducible and is
the usual explanation for an image that built fine last week and fails today.
