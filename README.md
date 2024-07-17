# Vairë Container Definitions

Home network container definitions and reverse proxy configuration, using rootless [Podman](https://podman.io) Quadlets.

## Services

* [Part-DB](https://docs.part-db.de/): Electronics and hardware component inventory tracking.
* [Snipe-IT](https://snipeitapp.com/): Asset management and tracking.
* [Traefik](https://traefik.io/): Application proxy.

## Installation

_The assumed platform here is an Ubuntu 24.04 VM._

* Install required system packages:
  ```bash
  sudo apt install podman pipx s3fs
  ```

* Allow the services to access privileged ports by adding the following in `/etc/sysctl.d/user_priv_ports.conf`:
  ```
  net.ipv4.ip_unprivileged_port_start=80
  ```
* Do the same for the active session by running:
  ```bash
  sudo sysctl net.ipv4.ip_unprivileged_port_start=80
  ```
  **TODO:** Revise this to instead use forwarding rules in the firewall and restore the privileged port threshold to
  1024.

* Ensure the services run even when the owner is not logged in by running
  ```bash
  loginctl enable-linger
  ```

* Install Python dependencies:
  ```bash
  pipx ensurepath
  pipx install poetry
  # ...restart session here...
  poetry install
  ```

* Create a `secrets.yml` based off the example and populate it with real values.  Save it with permissions of `0600`.

* Install services:
  ```bash
  poetry run ./services.py deploy partdb snipe traefik backup
  ```

* Start services:
  ```bash
  poetry run ./services.py start partdb snipe traefik
  ```
