from pathlib import Path
import logging

def skipmessage(val, lev, logger=None):
    logger.info(f"Skipping {val} as it has progressed beyond level {lev}")

class Logger:
    def __init__(self, logfile, workdir=None, stream=False):
        #logfile =  logname + strftime("_%Y-%m-%d_%H:%M:%S", localtime()) + '.log'
        #logfile = logname + '_dummy' + '.log' # transitioning away from this hopefully... will see if this works or crases ### BUG ALERT HERE... 

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        if logfile is not None:
            f_handler = logging.FileHandler(logfile)
            f_handler.setLevel(logging.INFO)
        # formatters
            f_format = logging.Formatter('%(asctime)s - %(name)s - %(message)s')
            f_handler.setFormatter(f_format)
            self.logger.addHandler(f_handler)
        if stream:
            c_handler = logging.StreamHandler()
            c_handler.setLevel(logging.INFO)
            c_format = logging.Formatter('%(name)s - %(message)s')
            c_handler.setFormatter(c_format)
            self.logger.addHandler(c_handler)

    def info(self, message):
        self.logger.info(message)

class Tracker:
    def __init__(self, trackfile, workdir=None, logger=None):

        #### Set up tracker file
        self.trackfile=Path(trackfile)
        self.tracker = logging.getLogger("tracker")
        self.tracker.setLevel(logging.INFO)
        t_handler = logging.FileHandler(trackfile)
        t_handler.setLevel(logging.INFO)
        t_format = logging.Formatter('%(message)s')
        t_handler.setFormatter(t_format)
        self.tracker.addHandler(t_handler)
        self.tdict = dict()
        self.workdir = self.trackfile.parent if workdir is None else Path(workdir)
        self.logger = logger

    def select(self, names=None, lower=None, upper=None):
        """Select tracked names by inclusive value bounds."""

        self.read()

        if names is None:
            names = self.tdict.keys()

        selected = []

        for name in names:
            if name not in self.tdict:
                continue

            value = self.tdict[name]

            if lower is not None and value < lower:
                continue

            if upper is not None and value > upper:
                continue

            selected.append(name)

        return selected

    def prepare(
        self,
        names,
        value=0,
        *,
        floor=False,
        ceiling=False,
    ):
        """Ensure tracked names exist and optionally constrain their values.

        Missing names are initialized to `value`.

        floor=True
            Raise existing values below `value` to `value`.

        ceiling=True
            Lower existing values above `value` to `value`.

        floor and ceiling are mutually exclusive.
        """

        if floor and ceiling:
            raise ValueError(
                "floor and ceiling cannot both be True"
            )

        self.read()

        changed_downward = False

        for name in names:

            # Missing names
            if name not in self.tdict:
                self.write(name, value)
                continue

            current = self.tdict[name]

            # Raising is compatible with append-only tracker semantics
            if floor and current < value:
                self.write(name, value)

            # Lowering requires rewriting current state
            elif ceiling and current > value:
                self.tdict[name] = value
                changed_downward = True

        if changed_downward:
            self._rewrite()

        return self


    def _rewrite(self):
        """Rewrite the tracker file from current tdict state.

        Not safe while parallel jobs are writing to the tracker.
        """

        with open(self.trackfile, "w") as tfile:
            for name, value in self.tdict.items():
                tfile.write(f"{name}\t{value}\n")

    def write(self, seqname, sval):
        self.tracker.info(f"{seqname}\t{sval}")
        if not seqname in self.tdict.keys():
            self.tdict[seqname] = sval
        elif sval > self.tdict[seqname]:
            self.tdict[seqname] = sval

    def read(self):
        if not self.trackfile.exists():
            return self.tdict

        with open(self.trackfile, "r") as tfile:
            for line in tfile:
                line = line.strip()

                if not line:
                    continue

                rkey, rval = line.split("\t", 1)
                rval = int(rval)

                if rkey not in self.tdict:
                    self.tdict[rkey] = rval
                elif rval > self.tdict[rkey]:
                    self.tdict[rkey] = rval

        return self.tdict

    def update(self, sval, seqnames):
        with open(self.trackfile, "r") as tfile:
            tpairs = tfile.read().strip().split(sep="\n")
            rvals = [x.split(sep="\t")[0] for x in tpairs]
            for seqname in seqnames:
                if not seqname in rvals:
                    self.write(seqname, sval)

    def check(self, seqname, tlev=0, permit=False, mess=True):
        if tlev > self.tdict[seqname]: # if the level we are testing is higher than the current level
            if not permit:
                raise Exception(f"File {seqname} is not sufficiently advanced! Tracked level: {self.tdict[seqname]}: attempted level: {tlev}")
            elif permit:
                return(False) # this file has advanced past the checkpoint
        elif tlev == self.tdict[seqname]: # if we are at the right level
            return(True) # this code could throw too m any errors
        else: # if we are still below the progress level of our actual file
            if mess and self.logger is not None:
                skipmessage(seqname, tlev)
            return(False)
        
    def threshold_upper(self, seqname, tlev=0): # only let in files at a certain level or below (don't launch useless jobs)
        """Don't launch jobs from samples LESS advanced than this. Returns True if sample inside upper threshold"""
        # This function useful in rare circumstances when you want to finish a process that involves only a few files (e.g. a pilot run) and probably assumes a second filter
        if tlev >= self.tdict[seqname]: # if the level we are testing is equal to or LOWER THAN than our threshold
            return(True)
        else:
            return(False)
    
    def threshold_lower(self, seqname, tlev=0): # only let in files at a certain level or above, i.e. kick underdeveloped files (don't launch useless jobs)
        """Don't launch jobs from samples MORE advanced than this. Returns True if sample inside lower threshold"""
        # this function useful in rare circumstances when you want to finish an advanced process that involves only a few files (e.g. a pilot run) and probably assumes 2nd filter
        if tlev <= self.tdict[seqname]: # if the level we are testing is equal or ABOVE our threshold
            return(True)
        else:
            return(False)

    def simplify(self):
        self.read()
        self._rewrite()

    def overwrite(self, seqname, sval): # never use in parallel
        """Force a tracked value exactly. Not safe during parallel writes."""
        self.read()
        self.tdict[seqname] = sval
        self._rewrite()

    def filecheck(self, seqname, tlev=0, pref="", post="", workdir=None): # add workdir reference... 
        workdir = self.workdir if workdir is None else workdir
        if self.check(seqname, tlev, permit=True, mess=False): #TODO switch back... 
            pp = Path(workdir + pref + seqname + post)
            if not pp.is_file():
                print(f"file {seqname} has not ACTUALLY advanced to stage {tlev}!")
                return(False)
            else:
                return(True)
        return(True)

class Failer:
    def __init__(self, failfile):
        #### Set up fail file
        self.failfile = failfile
        self.failer = logging.getLogger("failer")
        self.failer.setLevel(logging.INFO)
        fl_handler = logging.FileHandler(failfile)
        fl_handler.setLevel(logging.INFO)
        fl_format = logging.Formatter('%(message)s\t%(asctime)s')
        fl_handler.setFormatter(fl_format)
        self.failer.addHandler(fl_handler)

    def info(self, message):
        self.failer.info(message)

    def read(self):
        with open(self.failfile, "r") as ffile:
            failures = ffile.read().strip().split(sep="\n")
            return(failures)
