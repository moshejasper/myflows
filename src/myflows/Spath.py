from pathlib import Path

# --- Mpath definition ---
class Mpath(type(Path())):
    @property
    def bare_stem(self):
        """
        Return the filename with all suffixes removed.
        E.g. for 'file.s1.s2' returns 'file'.
        """
        if not self.suffixes:
            return self.name
        total_suffix_len = sum(len(s) for s in self.suffixes)
        return self.name[:-total_suffix_len]

    @property
    def suffs(self):
        """
        Return all suffixes concatenated as one string.
        E.g. for 'file.s1.s2' returns '.s1.s2'.
        """
        return ''.join(self.suffixes)

    def with_bare(self, new_stem):
        """
        Return a new path with the bare stem replaced by new_stem,
        while keeping all suffixes intact.
        E.g. 'file.s1.s2'.with_bare("newfile") -> 'newfile.s1.s2'
        """
        new_name = new_stem + self.suffs
        return self.with_name(new_name)

    def with_suffixes(self, new_suffix):
        """
        Return a new path with all existing suffixes replaced by new_suffix.
        new_suffix must be empty or begin with a dot.
        E.g. 'file.s1.s2'.with_suffixes(".s3.s4") -> 'file.s3.s4'
        """
        if new_suffix and not new_suffix.startswith('.'):
            raise ValueError("Suffix must be empty or start with a dot.")
        new_name = self.bare_stem + new_suffix
        return self.with_name(new_name)

    # --- Override joining behavior for cases when the right-hand side is a Spath ---
    def __truediv__(self, other):
        """
        When joining via "/" and self is a plain Mpath:

        If 'other' is a Spath, return a Spath carrying its semantic element.
        Otherwise, perform a normal join.
        """
        if isinstance(other, Spath):
            new_path = super().__truediv__(str(other))
            return Spath(str(new_path), sem=other._sem)
        return super().__truediv__(other)

    def joinpath(self, *others):
        """
        Override joinpath so that if any component is a Spath (and self is not a Spath),
        the result is wrapped as a Spath carrying the semantic element from that component.
        
        If more than one Spath is present or if self is already a Spath, raise an error.
        """
        spath_args = [o for o in others if isinstance(o, Spath)]
        if spath_args:
            if len(spath_args) > 1 or isinstance(self, Spath):
                raise TypeError("Cannot join two Spath objects")
            new_path = super().joinpath(*(str(o) for o in others))
            return Spath(str(new_path), sem=spath_args[0]._sem)
        return super().joinpath(*others)

# --- Spath definition (semantic path) ---
class Spath(Mpath):
    def __new__(cls, *args, sem):
        """
        Create a new Spath instance.

        The file name (without its extensions) is expected to have
        an underscore-delimited format that includes the semantic element.
        The semantic element (string) is provided via the keyword argument 'sem'
        and must appear as one of the segments.
        """
        instance = super().__new__(cls, *args)
        instance._sem = sem  # store the semantic element
        return instance

    @property
    def _segments(self):
        """Return a list of segments from the name split by '_'."""
        if self.name.startswith(self._sem):
            seg_start = None
            seg_end = [self.name.split(self._sem)[1]]
        elif self.name.endswith(self._sem):
            seg_start = [self.name.split(self._sem)[0]]
            seg_end = None
        else:
            seg_start, seg_end = self.name.split(self._sem)
        segments = []
        if seg_start is not None:
            seg_start = seg_start.strip('_').split('_')
            seg_start = seg_start if isinstance(seg_start, list) else [seg_start]
            segments += seg_start
        segments += [self._sem]
        if seg_end is not None:
            seg_end = seg_end.split('.')[0].strip('_').split('_')
            seg_end = seg_end if isinstance(seg_end, list) else [seg_end]
            segments += seg_end

        return segments

    @property
    def _sem_index(self):
        """Return the index of the semantic element in the segments."""
        segments = self._segments
        if self._sem not in segments:
            raise ValueError(f"Semantic element '{self._sem}' not found in {self.bare_stem}")
        return segments.index(self._sem)

    @property
    def pres(self):
        """Return the pre-label segments as a list."""
        return self._segments[:self._sem_index]

    @property
    def pre(self):
        """Return the pre-label segments joined by underscores."""
        return '_'.join(self.pres)

    @property
    def posts(self):
        """Return the post-label segments as a list."""
        return self._segments[self._sem_index + 1:]

    @property
    def post(self):
        """Return the post-label segments joined by underscores."""
        return '_'.join(self.posts)
    
    @property
    def suffs(self):
        """Return the full suffix as string (including multiple . markers)"""
        return self.name.split(self.bare_stem)[-1]
    
    @property
    def suffixes(self):
        """Returns list of all suffixes occurning after semname"""
        """Return the full suffix as string (including multiple . markers)"""
        return ['.' + str(x) for x in self.name.split(self.bare_stem)[-1].strip('.').split('.')]

    @property
    def semname(self):
        """Return the semantic element as a string."""
        return self._sem
    
    @property
    def bare_stem(self):
        """Return bare stem without suffixes"""
        return "_".join(self._segments)

    def _make_bare(self, pre, sem, post):
        """
        Helper to construct a bare stem from the given parts.
        Only non-empty parts are joined with underscores.
        """
        parts = []
        if pre:
            parts.append(pre)
        if sem:
            parts.append(sem)
        if post:
            parts.append(post)
        return '_'.join(parts)

    # --- Override built-in with-methods so that semantic field is preserved ---
    def with_name(self, name):
        """
        Return a new Spath with the name replaced.
        """
        new_path = super().with_name(name)
        return Spath(str(new_path), sem=self._sem)

    def with_suffix(self, suffix):
        """
        Return a new Spath with the suffix replaced.
        """
        new_path = super().with_suffix(suffix)
        return Spath(str(new_path), sem=self._sem)

    # --- Override our custom with-methods to ensure semantic field is carried over ---
    def with_bare(self, new_stem):
        """
        Return a new Spath with the bare stem replaced by new_stem,
        preserving the semantic element.
        """
        return self.parent / (new_stem + self.suffs)

    def with_suffixes(self, new_suffix):
        """
        Return a new Spath with all existing suffixes replaced by new_suffix,
        preserving the semantic element.
        """
        if new_suffix and not new_suffix.startswith('.'):
            raise ValueError("Suffix must be empty or start with a dot.")
        return self.parent / (self.bare_stem + new_suffix)

    def with_pre(self, new_pre):
        """
        Return a new Spath with the pre-label portion replaced.
        new_pre can be provided as a list (e.g. ['a', 'b', 'c']) or a string ('a_b_c').
        """
        if isinstance(new_pre, list):
            new_pre_str = '_'.join(new_pre)
        elif isinstance(new_pre, str):
            new_pre_str = new_pre.strip('_')
        else:
            raise TypeError("new_pre must be a list or string")
        new_bare = self._make_bare(new_pre_str, self._sem, self.post)
        return self.parent / (new_bare + self.suffs)

    def with_post(self, new_post):
        """
        Return a new Spath with the post-label portion replaced.
        new_post can be provided as a list (e.g. ['d', 'e']) or a string ('d_e').
        """
        if isinstance(new_post, list):
            new_post_str = '_'.join(new_post)
        elif isinstance(new_post, str):
            new_post_str = new_post.strip('_')
        else:
            raise TypeError("new_post must be a list or string")
        new_bare = self._make_bare(self.pre, self._sem, new_post_str)
        return self.parent / (new_bare + self.suffs)

    def with_semname(self, new_sem):
        """
        Return a new Spath with the semantic element replaced by new_sem.
        """
        new_bare = self._make_bare(self.pre, new_sem, self.post)
        new_full = self.parent / (new_bare + self.suffs)
        return Spath(str(new_full), sem=new_sem)

    def with_stem(self, new_stem):
        """
        Return a new Spath with the stem replaced by new_stem.
        This is equivalent to with_bare(new_stem) and preserves the semantic element.
        """
        return self.with_bare(new_stem)

    # --- Override PurePath.with_segments to preserve semantic information ---
    def with_segments(self, *pathsegments):
        """
        Create a new Spath object by combining the given path segments.
        The returned object preserves the semantic element.
        """
        return type(self)(*pathsegments, sem=self._sem)

    # --- Overriding joining behavior when Spath is the left-hand side ---
    def __truediv__(self, other):
        """
        When Spath is the left operand:
        
        If 'other' is a Spath, raise an error.
        Otherwise, join as usual and return a Spath preserving the stored semantic element.
        """
        if isinstance(other, Spath):
            raise TypeError("Cannot join two Spath objects")
        new_path = super().__truediv__(other)
        return Spath(str(new_path), sem=self._sem)

    def joinpath(self, *others):
        """
        When Spath is the left operand:
        
        If any component in 'others' is a Spath, raise an error.
        Otherwise, join and wrap the result as a Spath.
        """
        for o in others:
            if isinstance(o, Spath):
                raise TypeError("Cannot join two Spath objects")
        new_path = super().joinpath(*others)
        return Spath(str(new_path), sem=self._sem)

    def as_path(self):
        """
        Convert this Spath instance to a plain pathlib.Path,
        dropping the stored semantic information.
        """
        return Path(str(self))

    def rename(self, target):
        """
        Rename the file represented by this Spath.

        If the target is a Spath, perform the rename and update the semantic field
        to the semantic value of the target Spath. Otherwise, preserve the current semantic field.
        """
        if isinstance(target, Spath):
            new_target = target.as_path()
            new_file = super().rename(new_target)
            return Spath(str(new_file), sem=target._sem)
        else:
            new_file = super().rename(target)
            return Spath(str(new_file), sem=self._sem)

# --- Example usage ---
if __name__ == '__main__':
    # Create a Spath instance from a file name and specify the semantic element.
    s = Spath("a_b_c_semantic_d_e.ex1.ex2", sem="semantic")
    print("Original Spath:", s)
    print("Semantic element:", s.semname)  # "semantic"

    # Demonstrate built-in with-methods are updated:
    s_name = s.with_name("newname.ex1.ex2")
    print("with_name:", s_name, "; semantic =", s_name.semname)

    s_suffix = s.with_suffix(".s3.s4")
    print("with_suffix:", s_suffix, "; semantic =", s_suffix.semname)

    # Demonstrate custom with-methods:
    s_bare = s.with_bare("newfile")
    print("with_bare:", s_bare, "; semantic =", s_bare.semname)

    s_suffixes = s.with_suffixes(".s3.s4")
    print("with_suffixes:", s_suffixes, "; semantic =", s_suffixes.semname)

    s_pre = s.with_pre(["x", "y"])
    print("with_pre:", s_pre, "; semantic =", s_pre.semname)

    s_post = s.with_post("u_v")
    print("with_post:", s_post, "; semantic =", s_post.semname)

    s_sem = s.with_semname("foo")
    print("with_semname:", s_sem, "; semantic =", s_sem.semname)

    s_stem = s.with_stem("anotherfile")
    print("with_stem:", s_stem, "; semantic =", s_stem.semname)

    # Demonstrate with_segments:
    # Using multiple path segments (e.g. as when a derivative path is created)
    new_path = s.with_segments("alpha", "beta", "gamma.ex1.ex2")
    print("with_segments:", new_path, "; semantic =", new_path.semname)

    # Rename demonstration:
    # Rename s to a new location using a plain Path (semantic field remains unchanged)
    new_location = "renamed_file.ex1.ex2"
    s_renamed = s.rename(new_location)
    print("Renamed Spath (plain target):", s_renamed, "; semantic =", s_renamed.semname)

    # Rename s to a new location using a Spath target (semantic field updates)
    target = Spath("new_prefix_semantic_updated.ex1.ex2", sem="updated")
    s_renamed2 = s.rename(target)
    print("Renamed Spath (Spath target):", s_renamed2, "; semantic =", s_renamed2.semname)
