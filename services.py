#!/usr/bin/env python3

import argparse
import glob
import logging
import os
import subprocess
import sys
import tempfile

import aws_encryption_sdk as awscrypt
import jinja2
import yaml

_CONTAINER_LINK_DIR = "~/.config/containers/systemd"
"""Quadlet directory."""
_SECRET_CFG = "secrets.yml"
"""Primary source for secrets, passwords, API keys, etc."""
_SERVICE_CFG = "services.yml"
"""Service configuration."""
_STATE_CFG = ".state.yml"
"""Service state tracking file."""

_verbose = False
"""Verbose flag; display extra logging and debug information if True."""
_logger = logging.getLogger(__name__)
"""Logger instance."""


class Service:
    """Representation of a configured service."""

    def __init__(self, name: str, properties: dict, deployed: bool):
        """Instantiate a service representation.

        Args:
            name (str): Service name.
            properties (dict): Service properties loaded from YAML file.
            deployed (bool): True if the service has been deployed (quadlets and crontab installed).
        """
        self.name = name
        self.start = properties.get("start", [])
        self.stop = properties.get("stop", [])
        self.quadlets = properties.get("quadlets", [])
        self.crontab = properties.get("crontab", "")
        self.backups = properties.get("backups", [])
        self.secret_files = properties.get("secretfiles", [])
        self.deployed = deployed
        self.selected = False


def write_state(args: argparse.Namespace) -> None:
    """Store the service state to the state tracking file.

    Args:
        args (argparse.Namespace): Arguments containing service states.
    """
    state = {"deployed": {s.name: s.deployed for s in args.services}}
    with open(_STATE_CFG, mode="w") as cfg:
        yaml.safe_dump(state, cfg)
    _logger.debug(f"Wrote {_STATE_CFG}")


def run(cmd: list[str], checked: bool = True, env: dict = None) -> bool:
    """Run an executable.

    Args:
        cmd (list[str]): Command and parameters to execute.
        checked (bool, optional): Check for success (return code of 0). Defaults to True.
        env (dict, optional): Extra environment variables to merge into the process's environment. Defaults to None.

    Returns:
        bool: True if the command suceeded (returned 0), False otherwise.
    """
    _logger.debug(f"Command: {' '.join(cmd)}")
    fullenv = None
    if env:
        fullenv = dict(os.environ)
        fullenv.update(env)

    if _verbose:
        result = subprocess.run(cmd, env=fullenv)
    else:
        result = subprocess.run(cmd, env=fullenv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    _logger.debug(f"Result: {result.returncode}")
    if checked:
        result.check_returncode()
    return result.returncode == 0


def systemctl(*args, checked=True) -> bool:
    """Execute a systemd command.

    Args:
        args: The systemctl command to execute.
        checked (bool, optional): Check for success. Defaults to True.

    Returns:
        bool: True of the command suceeded, False otherwise.
    """
    cmd = ["systemctl", "--user"] + [*args]
    return run(cmd, checked=checked)


def reload(args: argparse.Namespace) -> None:
    """Reload systemd configuration.

    Args:
        args (argparse.Namespace): Command line parameters and services list.
    """
    _logger.info("Reloading service configuration")
    systemctl("daemon-reload")


def start(args: argparse.Namespace) -> None:
    """Start the selected services.

    Args:
        args (argparse.Namespace): Command line parameters and services list.
    """
    for service in args.services:
        if service.selected and service.start:
            _logger.info(f"Starting {service.name}")
            systemctl("start", *service.start)


def stop(args: argparse.Namespace) -> None:
    """Stop the selected services

    Args:
        args (argparse.Namespace): Command line parameters and services list.
    """
    for service in args.services:
        if service.selected and service.stop:
            _logger.info(f"Stopping {service.name}")
            systemctl("stop", *service.stop)


def restart(args: argparse.Namespace) -> None:
    """Restart the selected services.

    Args:
        args (argparse.Namespace): Command line parameters and services list.
    """
    stop(args)
    start(args)


def deploy(args: argparse.Namespace) -> None:
    """Deploy the selected services by linking quadlets into the container directory and generating crontab and secrets.

    Args:
        args (argparse.Namespace): Command line parameters and services list.
    """
    linkdir = os.path.expanduser(_CONTAINER_LINK_DIR)

    for service in args.services:
        if service.selected and not service.deployed:
            _logger.info(f"Deploying {service.name}")
            for quadlet in service.quadlets:
                source = os.path.abspath(quadlet)
                filename = os.path.basename(quadlet)
                destination = os.path.join(linkdir, filename)
                os.symlink(fullpath, dst)
            service.deployed = True

    crontab(args)
    secrets(args)
    write_state(args)
    reload(args)


def undeploy(args: argparse.Namespace) -> None:
    """Disable and remove the selected services by removing quadlet links and crontab entries.

    Args:
        args (argparse.Namespace): Command line parameters and services list.
    """
    stop(args)

    linkdir = os.path.expanduser(_CONTAINER_LINK_DIR)
    for service in args.services:
        if service.selected and service.deployed:
            _logger.info(f"Undeploying {service.name}")
            for quadlet in service.quadlets:
                filename = os.path.basename(quadlet)
                destination = os.path.join(linkdir, filename)
                try:
                    os.remove(destination)
                except FileNotFoundError:
                    pass
            service.deployed = False

    crontab(args)
    write_state(args)
    reload(args)


def status(args: argparse.Namespace) -> None:
    """Display status of all configured services.

    Args:
        args (argparse.Namespace): Command line parameters and services list.
    """
    _logger.debug("Displaying service status")

    statuses = []
    longest = 0
    for service in args.services:
        status = {"name": service.name, "deployed": "no", "running": "no"}
        if service.deployed:
            status["deployed"] = "yes"
            if service.start:
                status["running"] = "yes" if systemctl("is-active", *service.start, checked=False) else "no"
            else:
                status["running"] = "yes"
        statuses.append(status)
        if len(service.name) > longest:
            longest = len(service.name)

    print(f"{'SERVICE':<{longest}} DEPLOYED RUNNING")
    for row in statuses:
        print(f"{row["name"]:<{longest}} {row["deployed"]:<{len('DEPLOYED')}} {row["running"]}")


def crontab(args: argparse.Namespace) -> None:
    """Regenerate the crontab for all deployed services.

    Args:
        args (argparse.Namespace): Command line parameters and services list.
    """
    _logger.info("Refreshing crontab")
    with tempfile.NamedTemporaryFile(mode="w") as tmpcrontab:
        for service in args.services:
            if service.deployed and service.crontab:
                tmpcrontab.write(service.crontab)
        tmpcrontab.flush()

        cmd = ["crontab", "-n", tmpcrontab.name]
        run(cmd)
        cmd = ["crontab", tmpcrontab.name]
        run(cmd)


def xcrypt(
    crypto: awscrypt.EncryptionSDKClient,
    key: awscrypt.StrictAwsKmsMasterKeyProvider,
    encrypt: bool,
    source: str,
    dest: str,
) -> None:
    """Encrypt or decrypt a file using an AWS KMS key.

    Args:
        crypto (awscrypt.EncryptionSDKClient): AWS client side encryption instance.
        key (awscrypt.StrictAwsKmsMasterKeyProvider): AWS key provider instance.
        encrypt (bool): True to encrypt source to destination, False to decrypt source to destination.
        source (str): File to read from.
        dest (str): File to write to.
    """
    _logger.debug(f"{'En' if encrypt else 'De'}crypting {source} to {dest}")

    with open(source, mode="rb") as instream, open(dest, mode="wb") as outstream:
        with crypto.stream(mode="e" if encrypt else "d", source=instream, key_provider=key) as cryptor:
            for chunk in cryptor:
                outstream.write(chunk)


def mount_bucket(bucket: str, region: str) -> str:
    """Mount an S3 bucket as a directory.

    Args:
        bucket (str): Bucket name.
        region (str): AWS region name.

    Returns:
        str: Name of the mount point.
    """
    _logger.debug("Mounting S3 bucket")
    mountpoint = tempfile.mkdtemp()

    cmd = ["s3fs", "-o", "use_sse", "-o", f"endpoint={region}", "-o", f"url=https://s3.{region}.amazonaws.com"]
    if _verbose:
        cmd += ["-o", "dbglevel=info", "-o", "curldbg"]
    cmd += [bucket, mountpoint]
    run(cmd)

    _logger.debug(f"Mounted {mountpoint}")
    return mountpoint


def unmount_bucket(mountpoint: str) -> None:
    """Unmount a previously mounted S3 bucket.

    Args:
        mountpoint (str): The mount point path.
    """
    _logger.debug("Unmounting S3 bucket")
    cmd = ["fusermount", "-u", mountpoint]
    run(cmd)
    os.rmdir(mountpoint)


def backup(args: argparse.Namespace) -> None:
    """Collect up all configured backup files, encrypt them, and sync them to an S3 bucket.

    Args:
        args (argparse.Namespace): Command line parameters and services list.
    """
    secrets = load_secrets()

    os.environ["AWS_ACCESS_KEY_ID"] = secrets["apis"]["aws"]["key"]
    os.environ["AWS_SECRET_ACCESS_KEY"] = secrets["apis"]["aws"]["secret"]

    crypto = awscrypt.EncryptionSDKClient()
    key = awscrypt.StrictAwsKmsMasterKeyProvider(key_ids=[secrets["services"]["backup"]["key_arn"]])
    mountpoint = mount_bucket(secrets["services"]["backup"]["bucket"], secrets["services"]["backup"]["region"])

    for service in args.services:
        if service.deployed and service.backups:
            with tempfile.TemporaryDirectory() as tmpdir:
                for pattern in service.backups:
                    for source in glob.iglob(pattern):
                        dest = os.path.join(tmpdir, os.path.basename(source))
                        xcrypt(crypto, key, True, source, dest)

                cmd = ["rsync", "--recursive", "--delete-during", "--whole-file", "--fsync"]
                if _verbose:
                    cmd.append("--verbose")
                cmd += [tmpdir + "/", os.path.join(mountpoint, service.name)]
                run(cmd)

    unmount_bucket(mountpoint)

    del os.environ["AWS_ACCESS_KEY_ID"]
    del os.environ["AWS_SECRET_ACCESS_KEY"]


def secrets(args: argparse.Namespace) -> None:
    """Regenerate individual secrets files from the primary source.

    Args:
        args (argparse.Namespace): Command line parameters and services list.
    """
    secrets = load_secrets()
    templates = load_templates(args)

    for name, template in templates.items():
        with open(name, mode="w") as target:
            _logger.debug(f"Generating {name}")
            template.stream(secrets=secrets).dump(target)
    del secrets


def fetch(args: argparse.Namespace) -> None:
    """Download and decrypt a stored backup file.

    Args:
        args (argparse.Namespace): Command line parameters and services list.
    """
    secrets = load_secrets()

    os.environ["AWS_ACCESS_KEY_ID"] = secrets["apis"]["aws"]["key"]
    os.environ["AWS_SECRET_ACCESS_KEY"] = secrets["apis"]["aws"]["secret"]

    crypto = awscrypt.EncryptionSDKClient()
    key = awscrypt.StrictAwsKmsMasterKeyProvider(key_ids=[secrets["services"]["backup"]["key_arn"]])
    mountpoint = mount_bucket(secrets["services"]["backup"]["bucket"], secrets["services"]["backup"]["region"])

    for service in args.services:
        if service.selected:
            source = os.path.join(mountpoint, service.name, args.file)
            dest = args.file
            xcrypt(crypto, key, False, source, dest)

    unmount_bucket(mountpoint)

    del os.environ["AWS_ACCESS_KEY_ID"]
    del os.environ["AWS_SECRET_ACCESS_KEY"]


def load_templates(args: argparse.Namespace) -> dict[str, jinja2.Template]:
    """Load the secret file templates for deployed services.

    Args:
        args (argparse.Namespace): Command line parameters and services list.

    Returns:
        dict[str, jinja2.Template]: Instantiated Jinja2 templates for each file.
    """
    _logger.debug("Loading templates")
    templates = {}
    for service in args.services:
        if service.deployed:
            for path in service.secret_files:
                template_path = path + ".jinja"
                with open(template_path, mode="r") as template:
                    templates[path] = template.read()

    loader = jinja2.DictLoader(templates)
    autoescape = jinja2.select_autoescape(disabled_extensions=("txt", "sh"))
    env = jinja2.Environment(loader=loader, keep_trailing_newline=True, autoescape=autoescape)
    return {name: env.get_template(name) for name in templates}


def load_secrets() -> dict:
    """Load secrets from the primary file.

    Returns:
        dict: Tree of secrets.
    """
    _logger.info("Loading secrets")
    with open(_SECRET_CFG, mode="r") as cfg:
        secret_entries = yaml.safe_load(cfg)
    return secret_entries["secrets"]


def load_services() -> list[Service]:
    """Load services configuration and state, and render as Service instances.

    Returns:
        list[Service]: List of configured services.
    """
    _logger.info("Loading service configuration")
    with open(_SERVICE_CFG, mode="r") as cfg:
        service_entries = yaml.safe_load(cfg)
    services = service_entries.get("services", {})

    state = {}
    try:
        with open(_STATE_CFG, mode="r") as cfg:
            state = yaml.safe_load(cfg)
    except FileNotFoundError:
        pass
    deployed = state.get("deployed", {})

    return [Service(s, services[s], deployed.get(s, False)) for s in services]


def make_argparser(services: list[Service]) -> argparse.ArgumentParser:
    """Assemble the parser for all command line parameters.

    Args:
        services (list[Service]): List of services.

    Returns:
        argparse.ArgumentParser: Argument parser instance, ready for use.
    """

    def add_service_param(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("service", help="service(s)", nargs="+", choices=[s.name for s in services])

    parser = argparse.ArgumentParser(description="Vairë service management tool")
    parser.add_argument("-v", "--verbose", help="turn on verbose output", action="store_true")
    subparsers = parser.add_subparsers(required=True)

    parser_reload = subparsers.add_parser("reload", help="reload services daemon")
    parser_reload.set_defaults(func=reload, services=services, service=[])

    parser_status = subparsers.add_parser("status", help="display service status")
    parser_status.set_defaults(func=status, services=services, service=[])

    parser_start = subparsers.add_parser("start", help="start service(s)")
    add_service_param(parser_start)
    parser_start.set_defaults(func=start, services=services)

    parser_stop = subparsers.add_parser("stop", help="stop service(s)")
    add_service_param(parser_stop)
    parser_stop.set_defaults(func=stop, services=services)

    parser_restart = subparsers.add_parser("restart", help="restart service(s)")
    add_service_param(parser_restart)
    parser_restart.set_defaults(func=restart, services=services)

    parser_deploy = subparsers.add_parser("deploy", help="deploy/install service(s)")
    add_service_param(parser_deploy)
    parser_deploy.set_defaults(func=deploy, services=services)

    parser_undeploy = subparsers.add_parser("undeploy", help="undeploy/uninstall service(s)")
    add_service_param(parser_undeploy)
    parser_undeploy.set_defaults(func=undeploy, services=services)

    parser_crontab = subparsers.add_parser("crontab", help="(re)install the crontab for deployed services")
    parser_crontab.set_defaults(func=crontab, services=services, service=[])

    parser_backup = subparsers.add_parser("backup", help="collect service backups and sync to S3")
    parser_backup.set_defaults(func=backup, services=services, service=[])

    parser_secrets = subparsers.add_parser("secrets", help="(re)generate secrets files for deployed services")
    parser_secrets.set_defaults(func=secrets, services=services, service=[])

    parser_fetch = subparsers.add_parser(
        "fetch", help="fetch a stored backup file and place the decrypted version in the CWD"
    )
    parser_fetch.add_argument("service", help="service", choices=[s.name for s in services])
    parser_fetch.add_argument("file", help="backup file to retrieve from S3")
    parser_fetch.set_defaults(func=fetch, services=services)

    return parser


def parse_arguments(parser: argparse.ArgumentParser) -> argparse.Namespace:
    """Parse the command line parameters to the script.

    Args:
        parser (argparse.ArgumentParser): Argument parser instance.

    Returns:
        argparse.Namespace: Parsed arguments.
    """
    global _verbose

    args = parser.parse_args()

    _verbose = args.verbose
    if _verbose:
        _logger.setLevel(logging.DEBUG)

    for service in args.services:
        if isinstance(args.service, str) and service.name == args.service:
            service.selected = True
        elif isinstance(args.service, list) and service.name in args.service:
            service.selected = True

    return args


def main() -> None:
    """Script entry point."""
    logging.basicConfig(level=logging.INFO, style="{", format="{levelname}:{lineno}:{message}")

    services = load_services()
    parser = make_argparser(services)
    args = parse_arguments(parser)

    args.func(args)
    sys.exit(0)


if __name__ == "__main__":
    main()
