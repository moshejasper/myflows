from pathlib import Path
from .project import Project

class ProcessLib:

    def __init__(self, project: Project):
        if not getattr(project, "_launched", False):
            raise RuntimeError(
                "Project runtime has not been launched. "
                "Call project.launch() before creating ProcessLib objects."
            )
        self.project = project
        self.logger = project.logger
        self.failer = project.failer

    def acheck(self, *processes, seqname="NA", proc = "NA", abort=True):
        for process in processes:
            if process.returncode != 0:
                self.failer.info(seqname)
                if abort:
                    raise Exception(f"Process {proc} on sequence {seqname} failed!")
                else:
                    return(False)
        return(True)

    def filecheck(self, *paths, base=None):
        base = Path(base) if base is not None else None

        for path in paths:
            path = Path(path)

            if base is not None and not path.is_absolute():
                path = base / path

            if not path.is_file():
                raise FileNotFoundError(f"Cannot find file: {path}")

        return True

    def __repr__(self):
        return f"{type(self).__name__}()"

    def __str__(self):
        helpers = []
        processes = []

        base_methods = {
            name
            for name, value in ProcessLib.__dict__.items()
            if callable(value) and not name.startswith("_")
        }

        for name in dir(self):
            if name.startswith("_"):
                continue

            value = getattr(self, name)

            if not callable(value):
                continue

            if name in base_methods:
                helpers.append(name)
            else:
                processes.append(name)

        lines = [
            type(self).__name__,
            f"  project: {self.project.config_yml}",
        ]

        if processes:
            lines.append("  processes:")
            for name in processes:
                lines.append(f"    - {name}()")

        if helpers:
            lines.append("  helpers:")
            for name in helpers:
                lines.append(f"    - {name}()")

        return "\n".join(lines)