# The sandbox: a Firecracker microVM runner (QUAR-02, QUAR-05, D-73, D-74).
#
# `docker compose build sandbox` does everything: it downloads the pinned Firecracker
# release and the Linux kernel source (both checked against a sha256 kept in this file),
# builds a lean guest kernel and an ext4 rootfs with ffprobe, and copies the results into
# a small runtime image. Nothing built here is committed to the repo: no kernel, rootfs or
# Firecracker binary lives in git (QUAR-05). The build is the same on WSL2 and on Ubuntu.
#
# The first build compiles a kernel: about 8 minutes on a fast laptop, longer on a small
# mini PC. Docker caches the layer afterwards.

# The versions live here once; each stage that needs one re-declares it without a value.
# Firecracker v1.17.0 was published 2026-09-10. Linux 6.18 is a Firecracker-validated guest
# kernel line.
ARG FIRECRACKER_VERSION=1.17.0
ARG KERNEL_VERSION=6.18.58
ARG ALPINE_VERSION=3.24.3

# --- Stage 1: the Firecracker release binary ------------------------------------------
FROM alpine:3.24.3 AS firecracker
ARG FIRECRACKER_VERSION
# The hash is the one in the release's own firecracker-v1.17.0-x86_64.tgz.sha256.txt; to
# bump the version, copy the new hash from there.
ARG FIRECRACKER_SHA256=06094a1108ae9e82aa4c23a775aa92758f53f1175d422270d9d6162cb9ade558
RUN apk add --no-cache curl ca-certificates
WORKDIR /dl
RUN curl -fsSL -o firecracker.tgz \
      "https://github.com/firecracker-microvm/firecracker/releases/download/v${FIRECRACKER_VERSION}/firecracker-v${FIRECRACKER_VERSION}-x86_64.tgz" \
 && echo "${FIRECRACKER_SHA256}  firecracker.tgz" | sha256sum -c - \
 && tar -xzf firecracker.tgz \
 && mkdir -p /out \
 && install -m 0755 "release-v${FIRECRACKER_VERSION}-x86_64/firecracker-v${FIRECRACKER_VERSION}-x86_64" /out/firecracker

# --- Stage 2: the guest kernel ---------------------------------------------------------
FROM alpine:3.24.3 AS kernel
ARG KERNEL_VERSION
# The hash is the one on kernel.org (cdn.kernel.org/pub/linux/kernel/v6.x/sha256sums.asc).
ARG KERNEL_SHA256=069b19f9032c4dac8149ae4b6520c35debca0f42a9f6d52ee55ba6ca9b818013
RUN apk add --no-cache build-base bc bison flex perl bash diffutils findutils \
      elfutils-dev openssl-dev linux-headers xz curl ca-certificates
WORKDIR /build
RUN curl -fsSL -o linux.tar.xz \
      "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-${KERNEL_VERSION}.tar.xz" \
 && echo "${KERNEL_SHA256}  linux.tar.xz" | sha256sum -c - \
 && tar -xJf linux.tar.xz \
 && mv "linux-${KERNEL_VERSION}" src
COPY guest/kernel.fragment /build/kernel.fragment
# tinyconfig plus the committed fragment: Firecracker's own CI config takes over 20 minutes.
RUN cd src \
 && make tinyconfig \
 && ./scripts/kconfig/merge_config.sh -m .config /build/kernel.fragment \
 && make olddefconfig \
 && make -j"$(nproc)" vmlinux \
 && mkdir -p /out \
 && cp vmlinux /out/vmlinux

# --- Stage 3: the guest root filesystem ------------------------------------------------
FROM alpine:3.24.3 AS rootfs
# ffmpeg (it ships ffprobe) is pinned to the exact Alpine revision. Alpine keeps only the
# current revision of a package, so when it publishes a new one this build fails loudly:
# bump FFMPEG_APK_VERSION (the current value: `apk policy ffmpeg` in alpine:3.24.3).
# apk verifies package signatures against the Alpine keys.
ARG FFMPEG_APK_VERSION=8.1.2-r0
ARG ALPINE_VERSION
ARG FIRECRACKER_VERSION
ARG KERNEL_VERSION
RUN apk add --no-cache e2fsprogs "ffmpeg=${FFMPEG_APK_VERSION}"
RUN apk add --root /rootfs --initdb --no-cache --keys-dir /etc/apk/keys \
      --repositories-file /etc/apk/repositories \
      alpine-baselayout busybox "ffmpeg=${FFMPEG_APK_VERSION}"
COPY guest/init /rootfs/init
# mkfs.ext4 -d builds the image from a directory: no root, no loop mount.
RUN chmod 0755 /rootfs/init \
 && rm -rf /rootfs/var/cache \
 && mkdir -p /out \
 && mkfs.ext4 -q -d /rootfs -L fxprobe -O ^has_journal /out/rootfs.ext4 256M
# A tiny clip for POST /selftest, made by the same ffmpeg that is in the guest.
RUN ffmpeg -v error -f lavfi -i testsrc=duration=5:size=160x120:rate=10 -c:v mpeg4 /out/selftest.mkv
# What GET /health reports (key=value lines); the ffmpeg line is read from the guest's own
# apk database, so it is what is really installed.
RUN FFV="$(awk '/^P:ffmpeg$/ {found=1; next} found && /^V:/ {sub(/^V:/, ""); print; exit}' /rootfs/lib/apk/db/installed)" \
 && test -n "${FFV}" \
 && printf 'firecracker=%s\nkernel=%s\nalpine=%s\nffmpeg=%s\n' \
      "${FIRECRACKER_VERSION}" "${KERNEL_VERSION}" "${ALPINE_VERSION}" "${FFV}" > /out/fx-versions

# --- Stage 4: the runtime image --------------------------------------------------------
FROM python:3.12.15-slim AS runtime
COPY --from=firecracker /out/firecracker /usr/local/bin/firecracker
COPY --from=kernel /out/vmlinux /opt/fx/vmlinux
COPY --from=rootfs /out/rootfs.ext4 /opt/fx/rootfs.ext4
COPY --from=rootfs /out/selftest.mkv /opt/fx/selftest.mkv
COPY --from=rootfs /out/fx-versions /etc/fx-versions
COPY runner/ /opt/runner/runner/
WORKDIR /opt/runner
ENV PYTHONUNBUFFERED=1
# Not root: /dev/kvm comes in through the KVM group that docker-compose.yml adds.
RUN useradd --system --uid 10002 --no-create-home --shell /usr/sbin/nologin fxrunner
USER 10002:10002
# The runner has no authentication: compose attaches it to an internal network only and
# publishes no port.
EXPOSE 8090
CMD ["python", "-m", "runner.server"]
