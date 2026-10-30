from pathlib import Path
from time import localtime, strftime
import os

import yaml

from myflows import flowtracker as ftrack


class LinkPath:
    """A path that may be defined relative to another LinkPath.

    Linked descendants automatically update when an upstream path changes.
    """

    def __init__(self, path, parent=None):
        self._children = []
        self._parent = None
        self._linked = False
        self._relpath = Path(path)
        self._path = Path(path)

        if parent is not None:
            if not isinstance(parent, LinkPath):
                raise TypeError("parent must be a LinkPath or None")
            self._parent = parent
            self._linked = True
            self._path = parent.path / self._relpath
            parent._children.append(self)

    # ---- Path-like behaviour ----

    def __fspath__(self):
        return str(self.path)

    def __str__(self):
        return str(self.path)

    def __repr__(self):
        if self.linked:
            return f"LinkPath({str(self.relpath)!r}, parent={str(self.parent)!r})"
        return f"LinkPath({str(self.path)!r})"

    def __getattr__(self, name):
        return getattr(self.path, name)

    def __truediv__(self, other):
        # Ordinary path composition should not alter the dependency graph.
        return self.path / other

    # ---- Properties ----

    @property
    def path(self):
        return self._path

    @path.setter
    def path(self, value):
        value = Path(value)

        if self.linked:
            parent_path = self.parent.path

            if value.is_absolute():
                if value.is_relative_to(parent_path):
                    self._relpath = value.relative_to(parent_path)
                    self._path = value
                else:
                    # An absolute path outside the parent becomes independent.
                    self._unlink()
                    self._relpath = value
                    self._path = value
            else:
                self._relpath = value
                self._path = parent_path / value
        else:
            self._relpath = value
            self._path = value

        self._update_children()

    @property
    def relpath(self):
        return self._relpath

    @property
    def parent(self):
        return self._parent

    @property
    def linked(self):
        return self._linked

    @property
    def children(self):
        return tuple(self._children)

    # ---- Dependency updates ----

    def _unlink(self):
        if self._parent is not None:
            try:
                self._parent._children.remove(self)
            except ValueError:
                pass
        self._parent = None
        self._linked = False

    def _update_from_parent(self):
        if self.linked:
            self._path = self.parent.path / self._relpath
        self._update_children()

    def _update_children(self):
        for child in tuple(self._children):
            child._update_from_parent()


class _PreLinker:
    """Temporary YAML value describing a path and the config key it links to."""

    def __init__(self, path, parent_key):
        self.path = Path(path)
        self.parent_key = parent_key


class ConfigLoader(yaml.SafeLoader):
    pass


def _construct_path(loader, node):
    return Path(loader.construct_scalar(node))


def _construct_root(loader, node):
    return LinkPath(loader.construct_scalar(node))


def _link_constructor(parent_key):
    def constructor(loader, node):
        return _PreLinker(loader.construct_scalar(node), parent_key)
    return constructor


ConfigLoader.add_constructor("!path", _construct_path)
ConfigLoader.add_constructor("!root", _construct_root)
ConfigLoader.add_constructor("!base", _link_constructor("base"))
ConfigLoader.add_constructor("!work", _link_constructor("workdir"))
ConfigLoader.add_constructor("!data", _link_constructor("datadir"))
ConfigLoader.add_constructor("!geno", _link_constructor("genomes"))

def resolve_config(config=None):
    """Resolve the project configuration file.

    Resolution order:
        1. Explicitly supplied path
        2. ./myflows.yml
        3. $MYFLOWS_CONFIG
        4. $XDG_CONFIG_HOME/myflows/config.yml
           or ~/.config/myflows/config.yml
    """

    # Explicit config
    if config is not None:
        path = Path(config).expanduser()

        if not path.is_file():
            raise FileNotFoundError(
                f"Config file does not exist: {path}"
            )

        return path.resolve()

    # Project-local config
    local = Path.cwd() / "myflows.yml"

    if local.is_file():
        return local.resolve()

    # Environment default
    env = os.environ.get("MYFLOWS_CONFIG")

    if env:
        path = Path(env).expanduser()

        if not path.is_file():
            raise FileNotFoundError(
                f"$MYFLOWS_CONFIG points to a missing file: {path}"
            )

        return path.resolve()

    # User default
    config_home = Path(
        os.environ.get(
            "XDG_CONFIG_HOME",
            Path.home() / ".config",
        )
    ).expanduser()

    user_config = config_home / "myflows" / "config.yml"

    if user_config.is_file():
        return user_config.resolve()

    raise FileNotFoundError(
        "No myflows configuration found. Tried:\n"
        f"  {local}\n"
        "  $MYFLOWS_CONFIG\n"
        f"  {user_config}"
    )

class Project:
    """Project configuration loaded from YAML.

    YAML keys become attributes directly. LinkPath attributes retain their
    identity when reassigned, allowing downstream linked paths to update.
    """

    def __init__(self, config_yml=None):
        
        config_yml = resolve_config(config_yml)

        object.__setattr__(self, "config_yml", config_yml)
        object.__setattr__(self, "_ymldict", self._load_yaml(config_yml))
        object.__setattr__(self, "_launched", False)
        self._process_yaml()

    def __setattr__(self, name, value):
        current = self.__dict__.get(name)
        if isinstance(current, LinkPath) and not isinstance(value, LinkPath):
            current.path = value
        else:
            object.__setattr__(self, name, value)

    @staticmethod
    def _load_yaml(fname):
        with open(fname) as fn:
            config = yaml.load(fn, Loader=ConfigLoader)
        return {} if config is None else config

    def _resolve_value(self, value):
        """Recursively resolve YAML values containing linked paths."""

        if isinstance(value, _PreLinker):
            parent = getattr(self, value.parent_key, None)

            if not isinstance(parent, LinkPath):
                return value   # unresolved for now

            return LinkPath(value.path, parent=parent)

        if isinstance(value, dict):
            return {
                key: self._resolve_value(val)
                for key, val in value.items()
            }

        if isinstance(value, list):
            return [
                self._resolve_value(val)
                for val in value
            ]

        if isinstance(value, tuple):
            return tuple(
                self._resolve_value(val)
                for val in value
            )

        return value

    def _process_yaml(self):
        pending = {}

        # First install ordinary top-level values and root LinkPaths.
        for key, value in self._ymldict.items():

            if isinstance(value, _PreLinker):
                pending[key] = value
            else:
                object.__setattr__(self, key, value)

        # Resolve top-level linked paths first.
        while pending:
            resolved = []

            for key, spec in pending.items():
                parent = self.__dict__.get(spec.parent_key)

                if isinstance(parent, LinkPath):
                    object.__setattr__(
                        self,
                        key,
                        LinkPath(spec.path, parent=parent),
                    )
                    resolved.append(key)

            for key in resolved:
                del pending[key]

            if not resolved:
                unresolved = ", ".join(
                    f"{key} -> {spec.parent_key}"
                    for key, spec in pending.items()
                )

                raise ValueError(
                    "Could not resolve linked YAML paths: "
                    + unresolved
                )

        # Now resolve LinkPaths nested inside dicts/lists.
        for key in self._ymldict:
            value = getattr(self, key)
            object.__setattr__(
                self,
                key,
                self._resolve_value(value),
            )

    def launch(self):
        if self._launched:
            return

        self.prepare_dirs()
        self.launch_logging()
        self.launch_tracker()
        self._launched = True

    def prepare_dirs(self):
        for path in (
            self.workdir, 
            self.logfolder, 
            self.exfolder, 
            self.slurm_temp,
        ):
            Path(path).mkdir(parents=True, exist_ok=True)

    def launch_logging(self):
        logpath = self.logfolder / (
            str(self.logname)
            + strftime("_%Y-%m-%d_%H-%M-%S", localtime())
            + ".log"
        )

        self._logger = ftrack.Logger(logpath, stream=True)
        self.logger = self._logger.logger

    def launch_tracker(self):
        if hasattr(self, "trackfile"):
            self.tracker = ftrack.Tracker(
                self.trackfile, 
            )

        if hasattr(self, "failfile"):
            self.failer = ftrack.Failer(self.failfile)

    def update_logname(self, newname):
        self.logname = newname
        logfile = self.logfolder / Path(newname).with_suffix(".log")
        self._logger = ftrack.Logger(logfile)
        self.logger = self._logger.logger

    def __repr__(self):
        return f"{type(self).__name__}(config={self.config_yml!r})"


    def __str__(self):
        lines = [
            f"{type(self).__name__}",
            f"  config: {self.config_yml}",
        ]

        # Path/config values loaded from YAML
        for name in self._ymldict:
            value = getattr(self, name, None)

            if isinstance(value, dict):
                lines.append(f"  {name}:")
                for key, val in value.items():
                    lines.append(f"    {key}: {val}")
            else:
                lines.append(f"  {name}: {value}")

        if getattr(self, "_launched", False):
            lines.append("  runtime: launched")
        else:
            lines.append("  runtime: not launched")

        return "\n".join(lines)

    @classmethod
    def create_config(
        cls,
        path=None,
        *,
        scope="local",
        overwrite=False,
    ):
        if path is None:
            if scope == "local":
                path = Path.cwd() / "myflows.yml"

            elif scope == "user":
                config_home = Path(
                    os.environ.get(
                        "XDG_CONFIG_HOME",
                        Path.home() / ".config",
                    )
                )
                path = config_home / "myflows" / "config.yml"

            else:
                raise ValueError(
                    "scope must be 'local' or 'user'"
                )

        path = Path(path).expanduser()

        if path.exists() and not overwrite:
            raise FileExistsError(
                f"Config already exists: {path}"
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cls.STARTER_CONFIG)

        return path

STARTER_CONFIG = """\
base: !root .
workdir: !base workdir

logfolder: !work logs
exfolder: !work temp_execs
slurm_temp: !work temp_slurm

logname: mylog
trackfile: !work tracker.txt
failfile: !work failures.txt

slurm_settings:
  partitions: [YOUR_PARTITION]
  qos: null
"""