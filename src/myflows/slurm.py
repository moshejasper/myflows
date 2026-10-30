"""Generic SLURM job rendering and submission."""

from collections.abc import Mapping
from pathlib import Path
import argparse
import inspect
import random
import shlex
import subprocess
import textwrap
import uuid

def quickparse(*args):
    """Quickly parse positional arguments by name.

    Arguments may be supplied as:
        "name"
    for automatic int/float/string conversion, or:
        ("name", type)
    for explicit conversion.
    """

    def auto_type(value):
        try:
            return int(value)
        except ValueError:
            pass

        try:
            return float(value)
        except ValueError:
            return value

    parser = argparse.ArgumentParser()
    converters = {}

    for arg in args:
        if isinstance(arg, str):
            name = arg
            converters[name] = auto_type

        else:
            name, converter = arg
            converters[name] = converter

        parser.add_argument(name)

    parsed = parser.parse_args()

    for name, converter in converters.items():
        setattr(
            parsed,
            name,
            converter(getattr(parsed, name)),
        )

    return parsed


class SlurmJobRun:
    """One rendered sbatch script."""

    def __init__(self, script):
        self.script = script

    @property
    def slurmstring(self):
        return self.script

    def submit(self):
        return self._submit(["sbatch", "--parsable"])

    def submit_conditional(self, jobids, afterany=True):
        if isinstance(jobids, (str, int)):
            jobids = [jobids]
        else:
            jobids = list(jobids)
        if not jobids:
            return self.submit()

        mode = "afterany" if afterany else "afterok"
        dependency = f"{mode}:" + ":".join(str(x).strip() for x in jobids)
        return self._submit(["sbatch", "--parsable", "--dependency", dependency])

    def _submit(self, command):
        result = subprocess.run(
            command,
            input=self.script,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def __str__(self):
        return self.script


class SlurmJob:
    """SLURM job template using explicit arguments, project YAML, then defaults."""

    DEFAULTS = {
        "threads": 1,
        "threadmem": 10,
        "jobtime": "00-12:00:00",
        "jobname": "default",
        "nodes": 1,
        "ntasks": 1,
        "tmp_mem": 0,
        "modules": [],
        "condamodule": None,
        "conda_path": None,
        "conda_env": None,
        "account": None,
        "partitions": None,
        "qos": None,
        "partitiondict": {},
        "extra_directives": {},
        "postscript": None,
    }

    YAML_ALIASES = {
        "thr_mem": "threadmem",
        "mem_per_cpu": "threadmem",
        "job_time": "jobtime",
        "time": "jobtime",
        "conda_module": "condamodule",
        "partition_qos": "partitiondict",
    }

    def __init__(
        self,
        project=None,
        pyfile=None,
        *,
        snapshot=False,
        threads=None,
        threadmem=None,
        jobtime=None,
        jobname=None,
        nodes=None,
        ntasks=None,
        tmp_mem=None,
        modules=None,
        condamodule=None,
        conda_path=None,
        conda_env=None,
        account=None,
        partitions=None,
        qos=None,
        partitiondict=None,
        extra_directives=None,
        postscript=None,
        runblock=None,
        slurmdir=None,
    ):
        self.project = project
        self.settings = self._get_project_settings()

        caller_file = inspect.stack()[1].filename
        self.source_file = Path(pyfile or caller_file).resolve()
        # update convenience
        self.snapshot = snapshot
        self._runblock_explicit = runblock is not None
        if snapshot:
            self.pyfile = self._snapshot_script(self.source_file)
        else:
            self.pyfile = self.source_file

        if runblock is not None:
            self.runblock = runblock
        elif pyfile is None:
            self.runblock = "__slurm__"
        else:
            self.runblock = "__main__"

        supplied = locals()
        for key in self.DEFAULTS:
            self.__dict__[key] = self._get_setting(key, supplied.get(key))

        self.modules = self._as_list(self.modules)
        self.partitiondict = dict(self.partitiondict or {})
        self.extra_directives = dict(self.extra_directives or {})
        self.partitions = self._normalise_partitions(self.partitions)
        if not self.partitions:
            raise ValueError("SLURM partitions must be configured")

        self.slurmdir = self._get_slurmdir(slurmdir)
        self.conda_path = self._get_conda_path(conda_path)
        self.job_run = self.render_slurm()

    # ---------- configuration ----------

    def _get_project_settings(self):
        if self.project is None:
            return {}
        settings = getattr(self.project, "slurm_settings", {}) or {}
        if not isinstance(settings, Mapping):
            raise TypeError("project.slurm_settings must be a mapping")

        settings = dict(settings)
        for old, new in self.YAML_ALIASES.items():
            if old in settings and new not in settings:
                settings[new] = settings[old]
        return settings

    def _get_setting(self, key, explicit):
        if explicit is not None:
            return explicit
        if key in self.settings:
            return self.settings[key]
        default = self.DEFAULTS[key]
        return default.copy() if isinstance(default, (list, dict)) else default

    @staticmethod
    def _as_list(value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value else []
        return list(value)

    def _normalise_partitions(self, value):
        if isinstance(value, Mapping):
            for partition, qos in value.items():
                if qos is not None:
                    self.partitiondict.setdefault(str(partition), qos)
            return [str(x) for x in value]
        if isinstance(value, str):
            return [x.strip() for x in value.split(",") if x.strip()]
        return [] if value is None else [str(x) for x in value]

    def _get_slurmdir(self, explicit):
        if explicit is not None:
            return Path(explicit)
        if self.project is not None:
            for name in ("slurm_dir", "slurm_temp"):
                value = getattr(self.project, name, None)
                if value is not None:
                    return Path(value)
        value = self.settings.get("slurmdir")
        return None if value is None else Path(value)

    def _get_conda_path(self, explicit):
        if explicit is not None:
            return Path(explicit)
        if self.project is not None:
            for name in ("conda_path"):
                value = getattr(self.project, name, None)
                if value is not None:
                    return Path(value)
        value = self.settings.get("conda_path")
        return None if value is None else Path(value)

    def _choose_partition(self):
        partition = random.choice(self.partitions)
        return partition, self.partitiondict.get(partition, self.qos)

    # ---------- rendering ----------

    @staticmethod
    def _directive(name, value):
        if value is None or value is False:
            return None
        if value is True:
            return f"#SBATCH --{name}"
        return f"#SBATCH --{name}={value}"

    def _render_directives(self, threads, threadmem, jobtime, jobname, slurmdir):
        partition, qos = self._choose_partition()
        values = {
            "partition": partition,
            "qos": qos,
            "nodes": self.nodes,
            "ntasks": self.ntasks,
            "cpus-per-task": threads,
            "mem-per-cpu": f"{threadmem}G",
            "time": jobtime,
            "job-name": jobname,
            "account": self.account,
            "tmp": f"{self.tmp_mem}GB" if self.tmp_mem else None,
            "output": Path(slurmdir) / "slurm-%j.out" if slurmdir else None,
        }
        values.update({str(k).replace("_", "-"): v for k, v in self.extra_directives.items()})
        return "\n".join(
            line for key, value in values.items()
            if (line := self._directive(key, value)) is not None
        )

    def _render_environment(self, conda_env):
        lines = []
        if self.condamodule:
            lines.append(f"module load {shlex.quote(str(self.condamodule))}")
        if self.modules:
            lines.append("module load " + " ".join(shlex.quote(str(x)) for x in self.modules))
        if conda_env:
            lines.append('eval "$(conda shell.bash hook)"')
            env = Path(self.conda_path) / conda_env if self.conda_path else conda_env
            lines.append(f"conda activate {shlex.quote(str(env))}")
        return "\n".join(lines)

    def render_slurm(
        self,
        threads=None,
        threadmem=None,
        jobtime=None,
        jobname=None,
        conda_env=None,
        argstring=None,
        runblock=None,
        slurmdir=None,
    ):
        """Render one run; supplied values override this template without changing it."""
        threads = self.threads if threads is None else threads
        threadmem = self.threadmem if threadmem is None else threadmem
        jobtime = self.jobtime if jobtime is None else jobtime
        jobname = self.jobname if jobname is None else jobname
        conda_env = self.conda_env if conda_env is None else conda_env
        runblock = self.runblock if runblock is None else runblock
        slurmdir = self.slurmdir if slurmdir is None else Path(slurmdir)

        directives = self._render_directives(threads, threadmem, jobtime, jobname, slurmdir)
        environment = self._render_environment(conda_env)
        code = f"import runpy; runpy.run_path({str(self.pyfile)!r}, run_name={runblock!r})"
        command = f"python -c {shlex.quote(code)}"
        if argstring:
            command += " " + str(argstring).strip()

        sections = ["#!/bin/bash", directives]
        if environment:
            sections.append(environment)
        sections.append(command)
        if self.postscript:
            sections.append(str(self.postscript))
        return SlurmJobRun("\n\n".join(sections) + "\n")

    def render_many(
        self,
        items,
        *,
        argfunc=str,
        **render_kwargs,
    ):
        """Render one SlurmJobRun per item without submitting."""

        return [
            self.render_slurm(
                argstring=argfunc(item),
                **render_kwargs,
            )
            for item in items
        ]

    def update_slurmstring(self, **kwargs):
        self.job_run = self.render_slurm(**kwargs)
        return self.job_run

    @property
    def slurmstring(self):
        return self.job_run

    def _snapshot_script(self, source):
        if self.project is None:
            raise ValueError("snapshot=True requires a project")

        exfolder = Path(self.project.exfolder)
        exfolder.mkdir(parents=True, exist_ok=True)

        name = f"{uuid.uuid4().hex[:8]}_{source.name}"
        target = exfolder / name

        target.write_bytes(source.read_bytes())
        return target

    # ---------- submission / querying ----------

    def submit_slurm(self, **kwargs):
        return self.render_slurm(**kwargs).submit()


    def submit_slurm_conditional(self, jobids, afterany=True, **kwargs):
        return self.render_slurm(**kwargs).submit_conditional(jobids, afterany)


    def submit_runs(self, runs, bandwidth=None):
        """Submit already-rendered jobs.

        Parameters
        ----------
        runs
            Iterable of SlurmJobRun objects.
        bandwidth
            Maximum number of independent dependency lanes. If None, every
            job is submitted independently. If an integer, later jobs are
            chained to earlier jobs with ``afterany`` dependencies so that
            at most ``bandwidth`` jobs from this batch can run concurrently.

        Returns
        -------
        list
            SLURM job IDs in the same order as ``runs``.

        Notes
        -----
        The returned IDs can be passed directly to
        ``SlurmJobRun.submit_conditional(jobids)`` when a later job must wait
        for every job in this batch.
        """

        runs = list(runs)

        if bandwidth is None:
            return [run.submit() for run in runs]

        if not isinstance(bandwidth, int) or isinstance(bandwidth, bool):
            raise TypeError("bandwidth must be an integer or None")
        if bandwidth < 1:
            raise ValueError("bandwidth must be >= 1")

        # Each entry stores the most recently submitted job ID in one lane.
        lanes = {}
        jobids = []

        for i, run in enumerate(runs):
            lane = i % bandwidth
            previous = lanes.get(lane)

            if previous is None:
                jobid = run.submit()
            else:
                # Keep the original workflow behaviour: a lane continues
                # regardless of whether the previous job succeeded.
                jobid = run.submit_conditional(previous, afterany=True)

            lanes[lane] = jobid
            jobids.append(jobid)

        return jobids

    def submit_many(
        self,
        items,
        *,
        argfunc=str,
        bandwidth=None,
        **render_kwargs,
    ):
        """Render and submit one job per item.

        ``bandwidth`` optionally limits concurrent execution using afterany
        dependency lanes. Returns only the ordered list of submitted job IDs.
        """

        runs = self.render_many(
            items,
            argfunc=argfunc,
            **render_kwargs,
        )

        return self.submit_runs(runs, bandwidth=bandwidth)

    @property
    def pyfile(self):
        return self._pyfile

    @pyfile.setter
    def pyfile(self, value):
        source = Path(value).resolve()

        self.source_file = source

        if self.snapshot:
            self._pyfile = self._snapshot_script(source)
        else:
            self._pyfile = source

        if not self._runblock_explicit:
            self.runblock = "__main__"

    def get_jobids(self, jobname=None, user=None, partition=None):
        cmd = ["squeue", "--noheader", "--format=%i|%P|%j"]
        cmd += ["--me"] if user is None else ["--user", str(user)]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        partitions = {partition} if isinstance(partition, str) else (
            None if partition is None else set(partition)
        )
        jobids = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            jobid, job_partition, queued_name = line.split("|", 2)
            if jobname is not None and queued_name != jobname:
                continue
            if partitions is not None and job_partition not in partitions:
                continue
            jobids.append(jobid)
        return jobids

    def quicksubmit(self, trigger="__main__", term=True):
        frame = inspect.stack()[1].frame
        if frame.f_globals.get("__name__") != trigger:
            return None
        result = self.submit_slurm()
        if term:
            raise SystemExit(f"Submitted slurmjob {result}")
        return result

    def __str__(self):
        return textwrap.dedent(f"""
            SLURM SUBMIT OBJECT
            -------------------
            Source script: {self.source_file}
            Run script:    {self.pyfile}
            Job name:      {self.jobname}
            Time:          {self.jobtime}
            Threads:       {self.threads}
            Mem / CPU:     {self.threadmem} GB
            Partitions:    {', '.join(self.partitions)}
            Temp:          {self.tmp_mem} GB
        """).strip()