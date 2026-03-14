---
name: "git-resolve-conflicts"
description: "Step-by-step process for resolving git merge conflicts safely and correctly"
tags: ["git", "merge", "conflicts", "version-control"]
---

## Instructions

Merge conflicts occur when two branches modify the same region of a file. Resolving them correctly requires understanding what both sides intended.

**Step 1: Understand the Conflict Markers**
Git marks conflicting sections like this:
```
<<<<<<< HEAD
your current branch's version
=======
the incoming branch's version
>>>>>>> feature/new-login
```
Everything between `<<<<<<<` and `=======` is your branch. Everything between `=======` and `>>>>>>>` is the incoming change.

**Step 2: Gather Context Before Editing**
- Run `git log --merge` to see the commits that introduced the conflict.
- Use `git diff --diff-filter=U` to list all conflicted files at once.
- Open the file in an IDE merge tool (`git mergetool`) to see a three-panel diff: base, ours, theirs.

**Step 3: Resolve Each Conflict**
For each marked region, choose one of:
- Keep your version (delete the incoming section and markers).
- Keep the incoming version (delete your section and markers).
- Combine both (manually write the correct merged result).
- Rewrite the section entirely if both versions are incompatible.

Remove all `<<<<<<<`, `=======`, and `>>>>>>>` markers before saving.

**Step 4: Verify the Resolution**
1. Build the project and run the full test suite.
2. Stage the resolved file: `git add <file>`.
3. Complete the merge: `git merge --continue` (or `git rebase --continue` if rebasing).
4. Do *not* use `git commit -m` with a forced message — accept the auto-generated merge commit message unless you have a good reason to change it.

**Step 5: Prevent Future Conflicts**
- Merge or rebase from the main branch frequently (at least daily on active teams).
- Keep PRs small and short-lived.
- Communicate with teammates when touching shared files.
