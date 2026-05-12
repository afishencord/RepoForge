FROM registry.fedoraproject.org/fedora:44

RUN dnf -y update && \
    dnf -y install \
      python3 \
      python3-pip \
      dnf-plugins-core \
      dnf-utils \
      createrepo_c \
      rpm \
      rpm-build \
      gnupg2 \
      openssl \
      xorriso \
      genisoimage \
      findutils \
      util-linux \
      shadow-utils && \
    dnf clean all

WORKDIR /app

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p storage/uploads storage/workspaces storage/artifacts storage/keys storage/tls

EXPOSE 80 443
CMD ["python3", "-m", "app.cli", "serve"]
