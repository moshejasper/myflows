import subprocess
from pathlib import Path
from .Spath import Spath, Mpath
from .process import ProcessLib


class FileFlux(ProcessLib):

    def destroy_file(self, seqname, datadir=None, extn=""):
        datadir = self.config.datadir if datadir is None else Path(datadir)
        self.logger.info(f"Sestroying file {seqname}{extn}")
        lfile = Path(datadir / (seqname + extn))
        if lfile.exists() and lfile.is_file():
            lfile.unlink()

    def summon_file(self, seqname, datadir=None, subfolder = "", extn=""):
        datadir = self.config.datadir if datadir is None else Path(datadir)

        self.logger.info(f"Summoning file from subfolder {subfolder}")
        dest_fold = Mpath(datadir)
        source_fold = dest_fold / subfolder
        fname = Spath(seqname + extn, sem=seqname) # first implementation of semantics... 
        sourceloc = source_fold / fname
        if sourceloc.exists() and sourceloc.is_file():
            sourceloc.rename(dest_fold / fname)
        else:
            self.failer.info(seqname)
            exit(f"Sequence {seqname}{extn} was not available from subfolder {subfolder}!")

    def dispatch_file(self, seqname, datadir=None, subfolder = "", extn="", makedir=False):
        datadir = self.config.datadir if datadir is None else Path(datadir)
        self.logger.info(f"Dispatching file to subfolder {subfolder}")
        source_fold = Mpath(datadir)
        dest_fold = source_fold / subfolder
        fname = Spath(seqname + extn, sem=seqname)
        sourceloc = source_fold / fname
        if sourceloc.exists():
            if dest_fold.exists() and dest_fold.is_dir():
                sourceloc.rename(dest_fold / fname)
            else:
                if makedir:
                    self.logger.info(f"Making directory at {subfolder}")
                    dest_fold.mkdir()
                    sourceloc.rename(dest_fold / fname)
                else:
                    self.failer.info(seqname)
                    exit(f"Sequence {seqname}{extn} coul not be transferred to subfolder {subfolder}: issue with subfolder")
        else:
            self.failer.info(seqname)
            exit(f"Sequence {seqname}{extn} was not found in main folder!")


